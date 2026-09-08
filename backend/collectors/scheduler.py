"""定时采集调度器（编排器）
- 仅保留：APScheduler 实例、start_scheduler() 注册逻辑、共享 helper、启动线程
- 所有 scheduled_* 业务函数已拆分到 collectors/scheduler_jobs.py
- 公共 helper (_is_intraday_trading_hours / _is_trading_day / _has_today_data 等)
  在 scheduler_jobs.py 也保留一份以避免循环依赖；scheduler.py 仅导出对外需要的接口
"""
import asyncio
import logging
import sys
import os
import threading
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors import scheduler_jobs as jobs
from services.alert_service import check_realtime_data_gap

logger = logging.getLogger(__name__)


# 回马枪 v1.1.5 当天实时筛选：直接调用服务层触发（绕过 HTTP API key）。
# 交易日 09:35 首扫；失败时仅自动补扫一次（由 10:05 刷新或 10:30 兜底触发），
# 避免 iFinD 瞬时故障造成全天反复请求。盘中每 30 分钟刷新当天任务的实时行情。
def _horseback_scan_job(retry: bool = False):
    try:
        from zoneinfo import ZoneInfo
        from horseback.service import (
            ACTIVE_STATUSES,
            ActiveRunError,
            get_latest_run,
            get_today_run_attempt_count,
            recover_orphaned_runs,
            start_run,
        )
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        if not jobs._is_trading_day(now.strftime('%Y-%m-%d')):
            return
        recover_orphaned_runs()  # 清理进程重启残留的 ACTIVE 僵尸任务，避免永久阻塞
        latest = get_latest_run(include_results=False)
        if latest and latest.get("status") in ACTIVE_STATUSES:
            logger.info("[horseback] 已有实时任务运行中，跳过定时触发")
            return
        if retry and latest and latest.get("requested_end_date") == now.date().isoformat() and latest.get("status") == "COMPLETED":
            return  # 当天已成功，兜底无需再跑
        if retry and get_today_run_attempt_count(now.date()) >= 2:
            logger.info("[horseback] 当天自动扫描已达到两次上限，跳过补扫")
            return
        run = start_run(
            requested_end_date=None,
            min_consolidation_days=3,
            max_consolidation_days=12,
            min_limit_count=1,
            max_limit_count=3,
            min_score=75,
            max_candidates=100,
        )
        logger.info("[horseback] 定时实时扫描已触发 run=%s", run.get("id"))
    except ActiveRunError as exc:
        logger.info("[horseback] 已有实时任务运行，跳过：%s", exc)
    except FileNotFoundError:
        logger.warning("[horseback] iFinD 密钥未配置，跳过定时扫描")
    except Exception:
        logger.exception("[horseback] 定时扫描触发失败")


def _horseback_refresh_job():
    try:
        from zoneinfo import ZoneInfo
        from horseback.service import ACTIVE_STATUSES, ActiveRunError, get_latest_run, refresh_quotes, recover_orphaned_runs
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        if not jobs._is_trading_day(now.strftime('%Y-%m-%d')):
            return
        recover_orphaned_runs()  # 清理进程重启残留的 ACTIVE 僵尸任务，避免永久阻塞
        latest = get_latest_run(include_results=False)
        today_iso = now.date().isoformat()
        has_today_run = latest and latest.get("requested_end_date") == today_iso
        if not has_today_run:
            # 当天还没跑过（后端盘中才启动等场景）→ 兜底补扫一次
            _horseback_scan_job()
            return
        if latest.get("status") in ACTIVE_STATUSES or latest.get("status") == "CANCELLED":
            return
        if latest.get("status") == "FAILED":
            _horseback_scan_job(retry=True)
            return
        if latest.get("status") != "COMPLETED":
            return  # 其他终态不刷新，避免无结果可刷的报错刷屏
        refresh_quotes(latest["id"])
        logger.info("[horseback] 定时刷新实时行情已触发 run=%s", latest.get("id"))
    except ActiveRunError:
        pass  # 页面手动触发中，下一轮再刷
    except FileNotFoundError:
        pass
    except Exception:
        logger.exception("[horseback] 定时刷新实时行情失败")


def _horseback_track_job():
    """盘后同步最新回马枪样本，并用已落库日线推进历史跟踪。"""
    try:
        from zoneinfo import ZoneInfo
        from horseback.tracking import (
            TrackingRunNotFound,
            TrackingRunUnsupported,
            daily_update,
            sync_completed_run,
        )

        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        if not jobs._is_trading_day(now.strftime('%Y-%m-%d')):
            return
        try:
            synced = sync_completed_run()
        except (TrackingRunNotFound, TrackingRunUnsupported) as exc:
            synced = {"skipped": True, "reason": str(exc), "total_added": 0}
            logger.info("[horseback-track] 本轮无新池可同步：%s", exc)
        updated = daily_update()
        logger.info(
            "[horseback-track] 同步完成 run=%s added=%s updated=%s completed=%s",
            synced.get("run_id"),
            synced.get("total_added"),
            updated.get("total_updated"),
            updated.get("total_completed"),
        )
        return {"synced": synced, "updated": updated}
    except Exception:
        logger.exception("[horseback-track] 盘后跟踪更新失败")
        return None


# 横盘蓄势策略：盘后自动扫描（18:15 由 start_scheduler 注册）
def _horizontal_scan_job():
    from services.job_alert import notify_failure
    from strategies.horizontal.runner import run_scan
    try:
        logger.info("[horizontal] 横盘扫描开始")
        r = run_scan()
        if not r.get("ok"):
            notify_failure("横盘蓄势", "盘后扫描返回失败", str(r.get("error") or r)[:180], key="horizontal:scan")
        logger.info("[horizontal] 扫描完成: %s", r.get("stats"))
    except Exception:
        logger.exception("[horizontal] 横盘扫描失败")
        notify_failure("横盘蓄势", "盘后扫描异常", "详见后端日志", key="horizontal:scan")
    try:
        # 扫描后同步更新信号后走势跟踪（每日增量评估胜率/盈亏比）
        from strategies.horizontal.tracker import backfill_all_track
        tr = backfill_all_track(signal_codes=["A", "B", "C", "D"])
        logger.info("[horizontal] 走势跟踪更新: %s", tr)
    except Exception:
        logger.exception("[horizontal] 走势跟踪更新失败")
        notify_failure("横盘蓄势", "走势跟踪更新失败", "详见后端日志", key="horizontal:track")


# 波浪分析（四大指数波段研判）：盘后自动触发采集脚本并入库。
# 复用 API 入口 run_wave_analysis（线程内执行脚本，幂等，_run_lock 防并发），
# 避免与手动运行冲突；脚本失败仅记录日志，不影响调度器。
def _wave_analysis_job():
    try:
        from api.wave_analysis import run_wave_analysis
        logger.info("[wave-analysis] 定时触发波浪分析")
        r = run_wave_analysis()
        logger.info("[wave-analysis] 触发结果: %s", r)
    except Exception:
        logger.exception("[wave-analysis] 定时触发失败")


# V2 因子与信号快照：盘后自动持久化，供 V2 页（dashboard/candidates/sectors…）读取。
# 复用本地 v2_app.service.V2Service.snapshot(persist=True)；save_run 按 trade_date 幂等覆盖。
def _v2_snapshot_job():
    try:
        from v2_app.service import V2Service
        r = V2Service().snapshot(persist=True)
        logger.info(
            "[v2] V2 快照已持久化: date=%s universe=%s score_mode=%s",
            r.get("trade_date"), r.get("universe_count"), r.get("score_mode"),
        )
    except Exception:
        logger.exception("[v2] V2 快照持久化失败")


def _industry_stage_job(refresh_classification: bool = False):
    """独立行业阶段池：外采落库后离线评分，不接入旧轮动逻辑。"""
    try:
        from industry_stage.pipeline import run_pipeline

        result = run_pipeline(
            refresh_classification=refresh_classification,
            backfill_days=10,
        )
        logger.info("[industry-stage] 定时任务完成: %s", result)
    except Exception:
        logger.exception("[industry-stage] 定时任务失败")


def _industry_stage_realtime_job():
    """阶段池盘中行情：独立外采并落库，页面接口只读快照。"""
    try:
        from industry_stage.realtime import collect_realtime_snapshot

        result = collect_realtime_snapshot()
        if result.get("status") in {"FAILED", "MISSING"}:
            logger.warning("[industry-stage] 实时采集状态: %s", result)
    except Exception:
        logger.exception("[industry-stage] 实时采集失败")

# 实时数据断层检测上一次运行时间（避免每5秒重复记录）
_last_gap_check_time = 0

# misfire_grace_time=3600: 任务在计划时间后 1 小时内仍可补执行
# coalesce=True: 多次错过的任务只执行一次
scheduler = AsyncIOScheduler(misfire_grace_time=3600, coalesce=True, timezone='Asia/Shanghai')


# 全局兜底：任何调度任务抛出未捕获异常（回马枪/横盘之外的所有任务）都立刻通知
def _on_job_error(event) -> None:
    try:
        from services.job_alert import notify_failure
        job_id = getattr(event.job, "id", "unknown") if getattr(event, "job", None) else "unknown"
        exc = getattr(event, "exception", None)
        notify_failure("定时任务", f"{job_id} 执行异常", f"{exc}"[:180] if exc else "详见后端日志", key=f"sched:{job_id}")
    except Exception:  # noqa: BLE001 — 监听器自身绝不能抛
        pass


try:
    from apscheduler.events import EVENT_JOB_ERROR
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
except Exception:  # noqa: BLE001
    logger.exception("[scheduler] 注册全局任务错误监听失败")
_daily_pipeline_lock = threading.Lock()


# ============================================================
# 对外暴露的 helper（保持原导入路径可用）
# ============================================================

def _is_trading_day(date_str):
    return jobs._is_trading_day(date_str)


def _is_intraday_trading_hours():
    """判断当前是否在盘中交易时段（9:25-11:30, 13:00-15:00）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return (925 <= t <= 1130) or (1300 <= t <= 1500)


def _has_today_data():
    return jobs._has_today_data()


def _to_ts_code(code):
    return jobs._to_ts_code(code)


# ============================================================
# 启动时后台线程：补采 / 游资补跑 / 概念板块同步
# ============================================================

def _collect_and_analyze():
    """采集 + 分析一条龙；日线未齐时不启动高成本分析。"""
    if not _daily_pipeline_lock.acquire(blocking=False):
        logger.info('[scheduler] Daily pipeline already running; skipping overlapping trigger')
        return False

    try:
        return _collect_and_analyze_locked()
    finally:
        _daily_pipeline_lock.release()


def _collect_and_analyze_locked():
    """在单实例锁内执行日线补采和盘后分析。"""
    today = datetime.now().strftime('%Y-%m-%d')
    date_no_dash = datetime.now().strftime('%Y%m%d')

    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, skipping')
        return False

    if _has_today_data():
        from collectors.tdx_collector import aggregate_stock_sector_flows
        aggregate_stock_sector_flows(today, force=False)
        logger.info(f'[scheduler] {today} data already exists, skipping collection')
        return True

    logger.info(f'[scheduler] Collecting data for {today}')
    try:
        if jobs._has_today_flow_data():
            # 资金流已齐时，不重复抓取全市场资金流/概念定义，只重试缺失的日线。
            from collectors.tdx_collector import _batch_collect_kline, synchronize_stock_flow_prices_from_kline
            logger.info('[scheduler] Daily flows are ready; retrying K-line only')
            _batch_collect_kline(date_no_dash)
            synchronize_stock_flow_prices_from_kline(today)
        else:
            from collectors.tdx_collector import collect_daily_data
            collect_daily_data(date_no_dash)
    except Exception as e:
        logger.error(f'[scheduler] Collect error: {e}')
        return False

    if not _has_today_data():
        logger.info('[scheduler] Daily data is incomplete; defer analysis until K-line data is ready')
        return False

    from collectors.tdx_collector import aggregate_stock_sector_flows, synchronize_stock_flow_prices_from_kline
    synchronize_stock_flow_prices_from_kline(today)
    aggregate_stock_sector_flows(today, force=True)

    logger.info(f'[scheduler] Analyzing for {today}')
    try:
        from analyzers.heat_score import calculate_heat_scores
        from analyzers.lifecycle import update_lifecycle
        from analyzers.rotation import calculate_rotation
        from analyzers.money_flow import calculate_money_flow_path
        calculate_heat_scores(today)
        update_lifecycle(today)
        calculate_rotation(today)
        calculate_money_flow_path(today)
    except Exception as e:
        logger.error(f'[scheduler] Analyze error: {e}')

    return True


def _schedule_research_backfill_if_needed():
    """启动/补采后：若当日 AI 研究层为空，调度一次研究采集补采"""
    try:
        from db.session import get_db_session
        from db.models import AIAnalysisCache
        from collectors.research_collector import run_research_collection
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        with get_db_session() as db:
            ai_today = db.query(AIAnalysisCache).filter(
                AIAnalysisCache.created_at >= today_start).count()
        if ai_today == 0:
            def _sync_run_research():
                asyncio.run(run_research_collection())
            scheduler.add_job(
                _sync_run_research, 'date',
                run_date=datetime.now() + timedelta(minutes=3),
                id='startup_research_backfill', replace_existing=True,
            )
            logger.info('[scheduler] 已调度启动研究补采')
        else:
            logger.info(f'[scheduler] 当日研究层已存在 {ai_today} 条，跳过启动补采')
    except Exception as e:
        logger.warning(f'[scheduler] 启动研究补采检查失败: {e}')


def _startup_backfill():
    """启动时后台线程：检查今天数据是否缺失，缺失则补采；未成功则每小时重试"""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    import time
    time.sleep(5)

    today = datetime.now().strftime('%Y-%m-%d')
    now_hour = datetime.now().hour

    # 当天日线在收盘前并不完整；此时启动全市场补采既拿不到最终数据，
    # 也会和实时行情、网页请求争抢数据库与网络。盘后计划任务会补齐。
    # 启动补采只负责“已完成”的日线。15:10-15:30 之间上游、归档和盘后
    # 策略仍在交接，抢跑会造成重复写入和数据库连接耗尽；交给 15:30 后的
    # 正常盘后链路或下一次启动补齐即可。
    if jobs._is_before_a_share_postmarket_ready():
        logger.info('[scheduler] A-share daily startup backfill deferred until post-market data is ready')
        return

    if now_hour < 7:
        logger.info(f'[scheduler] Too early for backfill (hour={now_hour})')
        return
    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, no backfill needed')
        return

    success = _collect_and_analyze()
    if success:
        logger.info(f'[scheduler] Backfill succeeded for {today}')
        _schedule_research_backfill_if_needed()
        return

    now = datetime.now()
    if now.hour < 19 or (now.hour == 19 and now.minute < 45):
        logger.info('[scheduler] Backfill incomplete; recurring post-market job will retry lightweight K-line collection')
        return

    logger.error(f'[scheduler] Backfill failed for {today}, will retry every hour')

    def retry_job():
        if _has_today_data():
            logger.info(f'[scheduler] {today} data already collected, removing retry job')
            scheduler.remove_job('backfill_retry')
            return
        success = _collect_and_analyze()
        if success:
            logger.info(f'[scheduler] Retry succeeded for {today}, removing retry job')
            scheduler.remove_job('backfill_retry')
            _schedule_research_backfill_if_needed()

    scheduler.add_job(
        retry_job, 'interval', hours=1, id='backfill_retry',
        next_run_time=datetime.now() + timedelta(hours=1),
    )


def _postmarket_daily_pipeline():
    """盘后补齐日线后再分析；未齐时仅在后续轮次重试日线。"""
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    if not _is_trading_day(today) or jobs._is_before_a_share_postmarket_ready(now):
        return

    if _collect_and_analyze():
        logger.info('[scheduler] Post-market daily pipeline complete for %s', today)


def _startup_lifecycle_catchup():
    """启动时检查游资20天跟踪是否落后于信号表，落后则自动补跑"""
    import time
    time.sleep(15)

    try:
        from db.session import get_db_session
        from db.models import YuziLifecycleTracker, YuziQuantSignal
        from sqlalchemy import func
        from collectors.lifecycle_tracker import trigger_d1, update_lifecycle

        with get_db_session() as db:
            latest_sig = db.query(func.max(YuziQuantSignal.trade_date)).scalar()
            latest_track = db.query(func.max(YuziLifecycleTracker.trigger_date)).scalar()

        if not latest_sig:
            logger.info('[scheduler] No yuzi signals, skipping lifecycle catchup')
            return
        if latest_track and latest_track >= latest_sig:
            logger.info(f'[scheduler] Lifecycle tracker up to date ({latest_track})')
            return

        logger.info(f'[scheduler] Lifecycle tracker behind: signal={latest_sig}, tracker={latest_track}, catching up...')
        from datetime import datetime as _dt, timedelta as _td
        sd = _dt.strptime(latest_track or latest_sig, '%Y%m%d') + _td(days=1)
        ed = _dt.strptime(latest_sig, '%Y%m%d')
        cur = sd
        while cur <= ed:
            d = cur.strftime('%Y%m%d')
            try:
                ins = trigger_d1(d)
                upd = update_lifecycle(d)
                logger.info(f'[scheduler] Lifecycle catchup {d}: D1={ins}, update={upd}')
            except Exception as e:
                logger.error(f'[scheduler] Lifecycle catchup {d} error: {e}')
            cur += _td(days=1)
        logger.info('[scheduler] Lifecycle catchup done')
    except Exception as e:
        logger.error(f'[scheduler] Lifecycle catchup error: {e}', exc_info=True)


# ============================================================
# Sync wrappers for async scheduled jobs
# AsyncIOScheduler 的 async 任务在后台线程中可能没有 event loop，
# 用 asyncio.run() 包装确保每个 async 任务有自己的专用 event loop。
# ============================================================

def _sync_wrapper_scheduled_watchlist_sync():
    asyncio.run(jobs.scheduled_watchlist_sync())

def _sync_wrapper_scheduled_auto_trade():
    asyncio.run(jobs.scheduled_auto_trade())

def _sync_wrapper_scheduled_bs_strategy_precompute():
    asyncio.run(jobs.scheduled_bs_strategy_precompute())

def _sync_wrapper_scheduled_market_state_update():
    asyncio.run(jobs.scheduled_market_state_update())

def _sync_wrapper_scheduled_research_collection():
    asyncio.run(jobs.scheduled_research_collection())

def _sync_wrapper_scheduled_daily_report():
    asyncio.run(jobs.scheduled_daily_report())

def _sync_wrapper_scheduled_portfolio_refresh():
    asyncio.run(jobs.scheduled_portfolio_refresh())

def _scheduled_us_market_pipeline():
    jobs.scheduled_market_pipeline('US')

def _scheduled_hk_market_pipeline():
    jobs.scheduled_market_pipeline('HK')

def _scheduled_us_market_research():
    jobs.scheduled_market_research('US')

def _scheduled_hk_market_research():
    jobs.scheduled_market_research('HK')


def _cleanup_realtime_after_close():
    """清理实时明细；保守保留 60 天，失败不影响其他调度任务。"""
    try:
        from collectors.realtime_aggregator import cleanup_realtime_after_close
        cleanup_realtime_after_close(retention_days=60)
    except Exception as e:
        logger.error('[realtime_cleanup] failed: %s', e, exc_info=True)


# ============================================================
# 实时聚合器（5 秒轮询，跨模块通用）
# ============================================================

def _safe_realtime_aggregator():
    """5 秒轮询的安全包装：仅交易时段执行，避免盘前/盘后污染数据"""
    global _last_gap_check_time
    from datetime import time as dtime
    now_dt = datetime.now()
    now = now_dt.time()
    is_trading = (
        dtime(9, 30) <= now <= dtime(11, 30)
    ) or (
        dtime(13, 0) <= now <= dtime(15, 0)
    )
    is_weekday = now_dt.weekday() < 5
    if not (is_trading and is_weekday):
        return
    try:
        from collectors.realtime_aggregator import collect_realtime_snapshot
        collect_realtime_snapshot()
    except Exception as e:
        logger.error(f'[realtime_aggregator] error: {e}', exc_info=True)
        from services.alert_service import record_alert
        record_alert(
            level='warning', category='source_failure',
            message=f'实时聚合器(5s)异常: {str(e)[:120]}',
            trade_date=now_dt.date(),
        )

    try:
        if now_dt.timestamp() - _last_gap_check_time > 60:
            _last_gap_check_time = now_dt.timestamp()
            check_realtime_data_gap(trade_date=now_dt.date())
    except Exception as e:
        logger.error(f'[realtime_aggregator] check gap error: {e}', exc_info=True)


# ============================================================
# 注册所有定时任务
# ============================================================

def start_scheduler():
    """启动定时采集调度器"""
    # === 盘中实时资金流采集 ===
    scheduler.add_job(jobs.scheduled_emdatah5_fund_flow, 'cron',
                      hour='9-11,13-14', minute='*/5', id='emdatah5_fund_flow_intraday',
                      misfire_grace_time=120, max_instances=1)
    scheduler.add_job(jobs.scheduled_emdatah5_fund_flow, 'cron',
                      hour='15', minute='0', id='emdatah5_fund_flow_close',
                      misfire_grace_time=120, max_instances=1)

    # === 盘中实时快照 ===
    realtime_snapshot_kwargs = {'misfire_grace_time': 120, 'max_instances': 1}
    scheduler.add_job(jobs.scheduled_realtime_snapshot, 'cron',
                      hour='9-11,13-14', minute='*', id='realtime_snapshot_intraday',
                      **realtime_snapshot_kwargs)
    scheduler.add_job(jobs.scheduled_realtime_snapshot, 'cron',
                      hour='15', minute='0', id='realtime_snapshot_close',
                      **realtime_snapshot_kwargs)

    # === 中转层资金流向 ===
    scheduler.add_job(jobs._collect_money_flow_concept, 'cron',
                      hour='9-11,13-14', minute='*/5', id='money_flow_concept')
    scheduler.add_job(jobs._collect_money_flow_industry, 'cron',
                      hour='9-11,13-14', minute='*/5', id='money_flow_industry')

    # === 收盘归档（15:05）===
    scheduler.add_job(jobs.scheduled_archive, 'cron', hour='15', minute='5', id='archive')

    # === 盘后分析（15:30）===
    scheduler.add_job(jobs.scheduled_analyze, 'cron', hour='15', minute='30', id='analyze')

    # === 盘后数据补齐（15:30-19:45）===
    # 资金流已存在时仅重试日线，避免数据源尚未发布时反复刷新全市场数据。
    scheduler.add_job(_postmarket_daily_pipeline, 'cron', hour='15-19', minute='*/15',
                      id='postmarket_daily_pipeline', misfire_grace_time=300,
                      max_instances=1, coalesce=True)

    # === 龙虎榜采集（18:00 首次，18:30 兜底）===
    # Tushare 实测：18:00 左右开始发布当日龙虎榜数据，比原定的 18:30 提前 30 分钟
    scheduler.add_job(jobs.scheduled_dragon_tiger, 'cron', hour='18', minute='5', id='dragon_tiger_evening')
    scheduler.add_job(jobs.scheduled_dragon_tiger, 'cron', hour='18', minute='30', id='dragon_tiger_fallback')

    # === 4档资金流采集（17:30）===
    scheduler.add_job(jobs.scheduled_moneyflow_detail, 'cron', hour='17', minute='30', id='moneyflow_detail')

    # === 市场状态更新（16:00）===
    scheduler.add_job(_sync_wrapper_scheduled_market_state_update, 'cron', hour='16', minute='0', id='market_state')

    # === 指数日表维护（18:10，盘后 stock_flow 有真实涨跌后）===
    scheduler.add_job(jobs.scheduled_index_daily_update, 'cron', hour='18', minute='10', id='index_daily',
                      misfire_grace_time=600, max_instances=1, coalesce=True)
    scheduler.add_job(jobs.scheduled_index_daily_update, 'cron', hour='19', minute='20', id='index_daily_retry',
                      misfire_grace_time=600, max_instances=1, coalesce=True)

    # === 策略扫描（15:30-19:00）===
    scheduler.add_job(jobs.scheduled_strategy_scan, 'cron', hour='15', minute='30,45', id='strategy_scan_15')
    scheduler.add_job(jobs.scheduled_strategy_scan, 'cron', hour='16-18', minute='*/15', id='strategy_scan_16_18')
    scheduler.add_job(jobs.scheduled_strategy_scan, 'cron', hour='19', minute='0', id='strategy_scan_19')
    scheduler.add_job(jobs.scheduled_leader_snapshot, 'cron', hour='16-19', minute='10,40',
                      id='leader_snapshot', misfire_grace_time=600,
                      max_instances=1, coalesce=True)
    # 妙想持仓缓存：交易时段每10分钟自动刷新（用户要求，原仅手动同步才更新）
    scheduler.add_job(_sync_wrapper_scheduled_portfolio_refresh, 'cron',
                      hour='9-15', minute='*/10', id='portfolio_refresh_intraday')

    # === 热点缓存定时刷新 ===
    scheduler.add_job(jobs.scheduled_refresh_caches, 'cron', hour='15-22', minute='*/30', id='refresh_caches_post')
    scheduler.add_job(jobs.scheduled_refresh_caches, 'cron', hour='9-14', minute='*/10', id='refresh_caches_intraday')

    # Google Sheets 同步：完成 OAuth 后自动生效；未授权时任务只做本地状态判断并跳过。
    scheduler.add_job(jobs.scheduled_google_sheets_sync, 'interval', minutes=15,
                      id='google_sheets_sync', max_instances=1, misfire_grace_time=300)

    # === 个股信号预计算 ===
    scheduler.add_job(jobs.scheduled_watchlist_signal_compute, 'cron', hour='16-18', minute='*/15', id='watchlist_signal_compute')
    scheduler.add_job(jobs.scheduled_watchlist_signal_compute, 'cron', hour='19', minute='0', id='watchlist_signal_compute_19')

    # === 横盘蓄势策略扫描（18:15，盘后数据齐全后自动圈股）===
    scheduler.add_job(_horizontal_scan_job, 'cron', hour='18', minute='15', id='horizontal_scan',
                      misfire_grace_time=3600, max_instances=1)

    # === 回马枪 v1.1.5 当天实时筛选（交易日 09:35 首扫，10:30 兜底）===
    scheduler.add_job(_horseback_scan_job, 'cron', hour='9', minute='35', id='horseback_scan',
                      misfire_grace_time=1800, max_instances=1, coalesce=True)
    scheduler.add_job(_horseback_scan_job, 'cron', hour='10', minute='30', id='horseback_scan_retry',
                      misfire_grace_time=1800, max_instances=1, coalesce=True, kwargs={'retry': True})
    # 盘中每 30 分钟 + 尾盘 14:55 刷新当天任务的实时行情
    scheduler.add_job(_horseback_refresh_job, 'cron', hour='10-11,13-14', minute='5,35', id='horseback_refresh',
                      misfire_grace_time=300, max_instances=1, coalesce=True)
    scheduler.add_job(_horseback_refresh_job, 'cron', hour='14', minute='55', id='horseback_refresh_tail',
                      args=(), misfire_grace_time=1800, replace_existing=True)
    # 16:00 收盘行情快照：沿用盘中任务的日线结构基准，仅固化收盘价和收盘量。
    scheduler.add_job(_horseback_refresh_job, 'cron', hour='16', minute='0', id='horseback_close_final',
                      misfire_grace_time=300, max_instances=1, coalesce=True)
    # 18:20 主更新，20:20 幂等兜底；只读本地日线，不触发交易。
    scheduler.add_job(_horseback_track_job, 'cron', hour='18,20', minute='20', id='horseback_track_20d',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)

    # === 波浪分析（四大指数波段研判，盘后 17:45 首次，18:45 兜底重试）===
    # 依赖 StockDailyKline 当日数据就绪（15:30 后），脚本异步执行，_run_lock 防并发
    scheduler.add_job(_wave_analysis_job, 'cron', hour='17', minute='45', id='wave_analysis_17_45',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    scheduler.add_job(_wave_analysis_job, 'cron', hour='18', minute='45', id='wave_analysis_18_45',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)

    # === V2 因子与信号快照（盘后 16:45 自动持久化；失败 18:30 兜底重试）===
    scheduler.add_job(_v2_snapshot_job, 'cron', hour='16', minute='45', id='v2_snapshot_persist',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    scheduler.add_job(_v2_snapshot_job, 'cron', hour='18', minute='30', id='v2_snapshot_persist_retry',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)

    # === 独立行业阶段强势池（申万 2021；页面 GET 只读本地快照）===
    scheduler.add_job(_industry_stage_job, 'cron', day_of_week='mon-fri', hour='19', minute='25',
                      id='industry_stage_daily', misfire_grace_time=3600,
                      max_instances=1, coalesce=True)
    scheduler.add_job(_industry_stage_job, 'cron', day_of_week='sun', hour='6', minute='30',
                      id='industry_stage_taxonomy_weekly', kwargs={'refresh_classification': True},
                      misfire_grace_time=7200, max_instances=1, coalesce=True)
    scheduler.add_job(_industry_stage_realtime_job, 'interval', seconds=10,
                      id='industry_stage_realtime_10s', misfire_grace_time=20,
                      max_instances=1, coalesce=True)

    # === BS策略预扫描 ===
    scheduler.add_job(_sync_wrapper_scheduled_bs_strategy_precompute, 'cron', hour='16-18', minute='*/30', id='bs_strategy_precompute')
    scheduler.add_job(_sync_wrapper_scheduled_bs_strategy_precompute, 'cron', hour='19', minute='0', id='bs_strategy_precompute_19')

    # === 4.0 交易信号预计算 ===
    scheduler.add_job(jobs.scheduled_trading_system_compute, 'cron', hour='16-18', minute='*/15', id='trading_system_compute')
    scheduler.add_job(jobs.scheduled_trading_system_compute, 'cron', hour='19', minute='0', id='trading_system_compute_19')

    # === 中线纸面策略快照（盘后数据与短线预计算完成后）===
    scheduler.add_job(jobs.scheduled_medium_term_snapshot, 'cron', hour='19', minute='10', id='medium_term_snapshot')

    # === 盘后研究采集（19:30）===
    scheduler.add_job(_sync_wrapper_scheduled_research_collection, 'cron',
                      hour='19', minute='30', id='research_collection')

    # === 盘后综合日报（20:00）===
    scheduler.add_job(_sync_wrapper_scheduled_daily_report, 'cron',
                      hour='20', minute='0', id='daily_report')

    # === 自选股全量同步（交易时段每小时；手动按钮仍可立即同步）===
    scheduler.add_job(_sync_wrapper_scheduled_watchlist_sync, 'cron',
                      hour='10-11,13-15', minute='0', id='watchlist_sync')

    # === 盈立自选同步（美股收盘后 8:30 / 港股收盘后 16:30；客户端需在线）===
    scheduler.add_job(jobs.scheduled_usmart_watchlist_sync, 'cron',
                      hour='8', minute='30', id='usmart_watchlist_sync_0830')
    scheduler.add_job(jobs.scheduled_usmart_watchlist_sync, 'cron',
                      hour='16', minute='30', id='usmart_watchlist_sync_1630')

    # === 盈立真实持仓同步已下线：持仓改为内置手动管理（api/us_positions.py），
    # 不再依赖盈立客户端 CDP，避免断断续续的同步覆盖手动持仓 ===

    # === Tiger Trade 自选同步（美股 → US_WATCHLIST，与盈立共享同一池）===
    scheduler.add_job(jobs.scheduled_tiger_watchlist_sync, 'cron',
                      hour='8', minute='27', id='tiger_watchlist_sync_0827')
    scheduler.add_job(jobs.scheduled_tiger_watchlist_sync, 'cron',
                      hour='16', minute='27', id='tiger_watchlist_sync_1627')

    # === 自动化交易（盘中每5分钟）===
    # 注意：job 需精确到 9:30-15:00，且仅一个 job，避免多个 cron 时段重叠
    # 导致同一信号在 11:00-11:30 / 13:00-14:00 被双触发重复下单。
    # max_instances=1 + coalesce=True：即使上一轮未跑完，也绝不并发执行。
    scheduler.add_job(_sync_wrapper_scheduled_auto_trade, 'cron',
                      hour='9-14', minute='*/5', id='auto_trade',
                      max_instances=1, coalesce=True)

    # === 数据维护（每日凌晨清理 730 天前数据）===
    scheduler.add_job(jobs.cleanup_old_data, 'cron', hour='6', minute='0', id='cleanup')
    scheduler.add_job(_cleanup_realtime_after_close, 'cron', hour='15', minute='40',
                      id='cleanup_realtime_details', misfire_grace_time=3600,
                      max_instances=1)

    # === 每日新鲜度自检（早 7:30）===
    scheduler.add_job(jobs.scheduled_freshness_check, 'cron', hour='7', minute='30', id='freshness_check')

    # === 外部数据采集（两波）===
    scheduler.add_job(jobs.scheduled_external_wave1, 'cron', hour='16', minute='0', id='ext_wave1')
    scheduler.add_job(jobs.scheduled_external_wave2, 'cron', hour='9', minute='30', id='ext_wave2')

    # === 盘后复盘报告（16:30）===
    scheduler.add_job(jobs.scheduled_generate_recap, 'cron', hour='16', minute='30', id='market_recap')

    # === 盘后 F10 增量预拉（19:10）===
    scheduler.add_job(jobs.scheduled_f10_backfill, 'cron', hour='19', minute='10', id='f10_backfill')

    # === 盘中五档盘口采集（关键池、每10秒）===
    # 盘口只服务短周期观察；日线、因子、策略和分钟快照仍按原链路完整入库。
    scheduler.add_job(jobs.scheduled_orderbook_snapshot, 'interval',
                      seconds=10, id='orderbook_snapshot_10s',
                      misfire_grace_time=30, max_instances=1)

    # === 盘中实时聚合（5秒轮询）===
    scheduler.add_job(_safe_realtime_aggregator, 'interval',
                      seconds=5, id='realtime_aggregator_5s',
                      misfire_grace_time=30, max_instances=1)

    # === 美股日K线+因子采集（兼容夏令/冬令时，收盘后多次幂等重试）===
    scheduler.add_job(jobs.scheduled_us_quant_collect, 'cron',
                      hour='4-6', minute='20', id='us_quant_collect',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    # 服务若在凌晨采集窗口之后、A股盘后就绪之前启动，启动补采会主动让路；
    # 15:35 再按数据库最新交易日做一次幂等补偿，避免整天停留在旧日线。
    scheduler.add_job(jobs.scheduled_us_quant_catchup, 'cron',
                      hour='15', minute='35', id='us_quant_catchup_15_35',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)

    # === 美股强 B/S 盘后快照（因子入库后执行）===
    scheduler.add_job(jobs.scheduled_us_bs_snapshot, 'cron',
                      hour='5-8', minute='35', id='us_bs_snapshot',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)

    # === 美股持仓技术指标快照（北京时间 05:05，K线采集后 + regime/sector 前）===
    # 读取盈立真实持仓 → 计算 RSI/MACD/KDJ/EMA → 落库 USStrategyScore
    # 前端持仓 tab 直接读 DB，不再每次实时拉 K线
    scheduler.add_job(jobs.scheduled_us_position_indicators, 'cron',
                      hour='5', minute='5', id='us_position_indicators',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)

    # === 美股量化策略扫描（北京时间 5:00-8:00，美股收盘后每30分钟）===
    scheduler.add_job(jobs.scheduled_us_quant_scan, 'cron',
                      hour='5-7', minute='*/30', id='us_quant_scan_5_7',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    scheduler.add_job(jobs.scheduled_us_quant_scan, 'cron',
                      hour='8', minute='0', id='us_quant_scan_8',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    scheduler.add_job(jobs.scheduled_us_strategy_track, 'cron',
                      hour='8', minute='20', id='us_strategy_track_30d',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)

    # === 美股市场环境 + 行业轮动快照（北京时间 05:15/05:20，落库后前端直接读 DB）===
    scheduler.add_job(jobs.scheduled_us_regime_snapshot, 'cron',
                      hour='5', minute='15', id='us_regime_snapshot',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    scheduler.add_job(jobs.scheduled_us_sector_snapshot, 'cron',
                      hour='5', minute='20', id='us_sector_snapshot',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)

    # === 港美股统一因子生产链路 ===
    # 每次只补一个批次；页面读取最近成功快照，不在打开页面时采集。
    scheduler.add_job(_scheduled_us_market_pipeline, 'cron',
                      hour='5-8', minute='0,30', id='market_quant_us_pipeline',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    scheduler.add_job(_scheduled_hk_market_pipeline, 'cron',
                      hour='18', minute='30', id='market_quant_hk_pipeline',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    # 港股盘后统一因子补偿重试：18:30 上游数据未就绪时，19:00 再补一次。
    scheduler.add_job(_scheduled_hk_market_pipeline, 'cron',
                      hour='19', minute='0', id='market_quant_hk_pipeline_retry',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    scheduler.add_job(_scheduled_us_market_research, 'cron',
                      hour='6', minute='30', id='market_quant_us_research',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    scheduler.add_job(_scheduled_hk_market_research, 'cron',
                      hour='19', minute='30', id='market_quant_hk_research',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)

    # === 港股盘后结构快照（北京时间 16:30 首次，18:00 补偿）===
    scheduler.add_job(jobs.scheduled_hk_market_scan, 'cron',
                      hour='16', minute='30', id='hk_market_scan_16_30',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)
    scheduler.add_job(jobs.scheduled_hk_market_scan, 'cron',
                      hour='18', minute='0', id='hk_market_scan_18',
                      misfire_grace_time=3600, max_instances=1, coalesce=True)


    # === 平安证券数据采集（盘中每30分钟）===
    # 采集自选股实时行情 + 主力资金流向
    scheduler.add_job(jobs.scheduled_pingan_collect, 'cron',
                      hour='9-11,13-14', minute='*/30', id='pingan_collect_intraday',
                      misfire_grace_time=300, max_instances=1, coalesce=True)
    scheduler.add_job(jobs.scheduled_pingan_collect, 'cron',
                      hour='15', minute='0', id='pingan_collect_close',
                      misfire_grace_time=300, max_instances=1, coalesce=True)


    scheduler.start()
    logger.info('[scheduler] Started (realtime snapshot every 1min, key orderbook every 10s during trading hours)')

    # 启动后台线程
    t = threading.Thread(target=_startup_backfill, daemon=True)
    t.start()
    logger.info('[scheduler] Backfill check thread started')

    t3 = threading.Thread(target=_startup_lifecycle_catchup, daemon=True)
    t3.start()
    logger.info('[scheduler] Lifecycle catchup thread started')

    # 美股数据启动补采（regime/sectors/持仓指标缺失时自动补采）
    t4 = threading.Thread(target=jobs._startup_us_backfill, daemon=True)
    t4.start()
    logger.info('[scheduler] US backfill check thread started')

    def _startup_concept_sync():
        import time
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        time.sleep(10)
        if jobs._is_before_a_share_postmarket_ready():
            logger.info('[scheduler] startup concept sync deferred until post-market data is ready')
            return
        now = datetime.now()
        if now.weekday() < 5 and 900 <= now.hour * 100 + now.minute < 2000:
            logger.info('[scheduler] startup concept sync deferred to the post-market collection pipeline')
            return
        try:
            jobs._sync_concept_sectors()
        except Exception as e:
            logger.warning(f'[scheduler] startup concept sync error (ignored): {e}', exc_info=True)

    t2 = threading.Thread(target=_startup_concept_sync, daemon=True)
    t2.start()
    logger.info('[scheduler] Concept sector sync thread started')

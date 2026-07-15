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

# 实时数据断层检测上一次运行时间（避免每5秒重复记录）
_last_gap_check_time = 0

# misfire_grace_time=3600: 任务在计划时间后 1 小时内仍可补执行
# coalesce=True: 多次错过的任务只执行一次
scheduler = AsyncIOScheduler(misfire_grace_time=3600, coalesce=True, timezone='Asia/Shanghai')


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
    """采集 + 分析一条龙（带去重检查）"""
    today = datetime.now().strftime('%Y-%m-%d')
    date_no_dash = datetime.now().strftime('%Y%m%d')

    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, skipping')
        return False

    if _has_today_data():
        logger.info(f'[scheduler] {today} data already exists, skipping collection')
        return True

    logger.info(f'[scheduler] Collecting data for {today}')
    try:
        from collectors.tdx_collector import collect_daily_data
        collect_daily_data(date_no_dash)
    except Exception as e:
        logger.error(f'[scheduler] Collect error: {e}')
        return False

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

    return _has_today_data()


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
                      hour='9-11,13-14', minute='*/2', id='emdatah5_fund_flow_intraday',
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

    # === 龙虎榜采集（18:30 独立任务，19:00 补一次）===
    scheduler.add_job(jobs.scheduled_dragon_tiger, 'cron', hour='18', minute='30', id='dragon_tiger_evening')
    scheduler.add_job(jobs.scheduled_dragon_tiger, 'cron', hour='19', minute='0', id='dragon_tiger_fallback')

    # === 4档资金流采集（17:30）===
    scheduler.add_job(jobs.scheduled_moneyflow_detail, 'cron', hour='17', minute='30', id='moneyflow_detail')

    # === 市场状态更新（16:00）===
    scheduler.add_job(_sync_wrapper_scheduled_market_state_update, 'cron', hour='16', minute='0', id='market_state')

    # === 策略扫描（15:30-19:00）===
    scheduler.add_job(jobs.scheduled_strategy_scan, 'cron', hour='15', minute='30,45', id='strategy_scan_15')
    scheduler.add_job(jobs.scheduled_strategy_scan, 'cron', hour='16-18', minute='*/15', id='strategy_scan_16_18')
    scheduler.add_job(jobs.scheduled_strategy_scan, 'cron', hour='19', minute='0', id='strategy_scan_19')

    # === 热点缓存定时刷新 ===
    scheduler.add_job(jobs.scheduled_refresh_caches, 'cron', hour='15-22', minute='*/30', id='refresh_caches_post')
    scheduler.add_job(jobs.scheduled_refresh_caches, 'cron', hour='9-14', minute='*/10', id='refresh_caches_intraday')

    # === 个股信号预计算 ===
    scheduler.add_job(jobs.scheduled_watchlist_signal_compute, 'cron', hour='16-18', minute='*/15', id='watchlist_signal_compute')
    scheduler.add_job(jobs.scheduled_watchlist_signal_compute, 'cron', hour='19', minute='0', id='watchlist_signal_compute_19')

    # === BS策略预扫描 ===
    scheduler.add_job(_sync_wrapper_scheduled_bs_strategy_precompute, 'cron', hour='16-18', minute='*/30', id='bs_strategy_precompute')
    scheduler.add_job(_sync_wrapper_scheduled_bs_strategy_precompute, 'cron', hour='19', minute='0', id='bs_strategy_precompute_19')

    # === 4.0 交易信号预计算 ===
    scheduler.add_job(jobs.scheduled_trading_system_compute, 'cron', hour='16-18', minute='*/15', id='trading_system_compute')
    scheduler.add_job(jobs.scheduled_trading_system_compute, 'cron', hour='19', minute='0', id='trading_system_compute_19')

    # === 盘后研究采集（19:30）===
    scheduler.add_job(_sync_wrapper_scheduled_research_collection, 'cron',
                      hour='19', minute='30', id='research_collection')

    # === 盘后综合日报（20:00）===
    scheduler.add_job(_sync_wrapper_scheduled_daily_report, 'cron',
                      hour='20', minute='0', id='daily_report')

    # === 自选股全量同步（交易时段每5分钟）===
    scheduler.add_job(_sync_wrapper_scheduled_watchlist_sync, 'cron',
                      hour='9-15', minute='*/5', id='watchlist_sync')

    # === 自动化交易（盘中每5分钟）===
    scheduler.add_job(_sync_wrapper_scheduled_auto_trade, 'cron',
                      hour='9-14', minute='*/5', id='auto_trade')
    scheduler.add_job(_sync_wrapper_scheduled_auto_trade, 'cron',
                      hour='11', minute='0-30', id='auto_trade_11')
    scheduler.add_job(_sync_wrapper_scheduled_auto_trade, 'cron',
                      hour='13-14', minute='*/5', id='auto_trade_pm')

    # === 数据维护（每日凌晨清理 730 天前数据）===
    scheduler.add_job(jobs.cleanup_old_data, 'cron', hour='6', minute='0', id='cleanup')

    # === 每日新鲜度自检（早 7:30）===
    scheduler.add_job(jobs.scheduled_freshness_check, 'cron', hour='7', minute='30', id='freshness_check')

    # === 外部数据采集（两波）===
    scheduler.add_job(jobs.scheduled_external_wave1, 'cron', hour='16', minute='0', id='ext_wave1')
    scheduler.add_job(jobs.scheduled_external_wave2, 'cron', hour='9', minute='30', id='ext_wave2')

    # === 盘后复盘报告（16:30）===
    scheduler.add_job(jobs.scheduled_generate_recap, 'cron', hour='16', minute='30', id='market_recap')

    # === 盘后 F10 增量预拉（19:10）===
    scheduler.add_job(jobs.scheduled_f10_backfill, 'cron', hour='19', minute='10', id='f10_backfill')

    # === 盘中五档盘口采集（每3秒）===
    scheduler.add_job(jobs.scheduled_orderbook_snapshot, 'interval',
                      seconds=3, id='orderbook_snapshot_3s',
                      misfire_grace_time=30, max_instances=1)

    # === 盘中实时聚合（5秒轮询）===
    scheduler.add_job(_safe_realtime_aggregator, 'interval',
                      seconds=5, id='realtime_aggregator_5s',
                      misfire_grace_time=30, max_instances=1)

    scheduler.start()
    logger.info('[scheduler] Started (realtime snapshot every 1min, orderbook every 3s during trading hours)')

    # 启动后台线程
    t = threading.Thread(target=_startup_backfill, daemon=True)
    t.start()
    logger.info('[scheduler] Backfill check thread started')

    t3 = threading.Thread(target=_startup_lifecycle_catchup, daemon=True)
    t3.start()
    logger.info('[scheduler] Lifecycle catchup thread started')

    def _startup_concept_sync():
        import time
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        time.sleep(10)
        jobs._sync_concept_sectors()

    t2 = threading.Thread(target=_startup_concept_sync, daemon=True)
    t2.start()
    logger.info('[scheduler] Concept sector sync thread started')

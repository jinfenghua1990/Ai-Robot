"""
定时采集调度器
- 盘中实时快照采集（每15分钟）→ realtime_*_flow 表
- 收盘归档（15:05）→ 历史表 sector_flow / stock_flow
- 盘后分析（15:30）
- 数据维护
"""
import logging
import sys, os, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from collectors.tdx_collector import collect_daily_data, call_tushare_mcp
from collectors.realtime_collector import collect_realtime_snapshot, archive_today_snapshot_to_history
from collectors.money_flow_middleman import collect_realtime_money_flow_snapshot
from analyzers.heat_score import calculate_heat_scores
from analyzers.lifecycle import update_lifecycle
from analyzers.rotation import calculate_rotation
from analyzers.money_flow import calculate_money_flow_path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def _sync_concept_sectors():
    """同步概念板块成分股"""
    try:
        from scripts.sync_concept_sectors import sync
        sync()
    except Exception as e:
        logger.error(f'[scheduler] Concept sector sync error: {e}')


def _compute_concept_sector_flow(target_date=None):
    """计算概念板块日度资金流向"""
    try:
        from scripts.compute_concept_sector_flow import compute_for_date
        compute_for_date(target_date)
    except Exception as e:
        logger.error(f'[scheduler] Concept sector flow compute error: {e}')


def _compute_realtime_concept_sector_flow():
    """计算概念板块实时资金流向"""
    try:
        from scripts.compute_realtime_concept_sector_flow import compute_for_snapshot
        compute_for_snapshot()
    except Exception as e:
        logger.error(f'[scheduler] Realtime concept sector flow compute error: {e}')


def _collect_money_flow_concept():
    """采集中转层概念板块资金流向"""
    try:
        collect_realtime_money_flow_snapshot(dimension='concept')
    except Exception as e:
        logger.error(f'[scheduler] Money flow concept collect error: {e}')


def _collect_money_flow_industry():
    """采集中转层行业板块资金流向"""
    try:
        collect_realtime_money_flow_snapshot(dimension='industry')
    except Exception as e:
        logger.error(f'[scheduler] Money flow industry collect error: {e}')


# misfire_grace_time=3600: 任务在计划时间后 1 小时内仍可补执行（避免后端重启/繁忙时任务被跳过）
# coalesce=True: 多次错过的任务只执行一次
scheduler = AsyncIOScheduler(misfire_grace_time=3600, coalesce=True)


def _has_today_data():
    """检查数据库中是否已有今天的完整数据（SectorFlow + StockFlow + StockDailyKline 同时有记录才算）"""
    from db.connection import get_db
    from db.session import get_db_session
    from db.models import SectorFlow, StockFlow, StockDailyKline
    today = datetime.now().date()
    try:
        with get_db_session() as db:
            sector_count = db.query(SectorFlow).filter(SectorFlow.trade_date == today).count()
            stock_count = db.query(StockFlow).filter(StockFlow.trade_date == today).count()
            kline_count = db.query(StockDailyKline).filter(StockDailyKline.trade_date == today).count()
            # 板块>30 + 个股>500 + K线>1000 才算完成
            return sector_count > 30 and stock_count > 500 and kline_count > 1000
    except Exception:
        logger.debug(f"_has_today_data failed", exc_info=True)
        return False


def _is_intraday_trading_hours():
    """判断当前是否在盘中交易时段（9:25-11:30, 13:00-15:00）"""
    now = datetime.now()
    # 周末不采集
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    # 9:25-11:30 或 13:00-15:00
    return (925 <= t <= 1130) or (1300 <= t <= 1500)


def _collect_and_analyze():
    """采集 + 分析一条龙（带去重检查）"""
    today = datetime.now().strftime('%Y-%m-%d')
    date_no_dash = datetime.now().strftime('%Y%m%d')

    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, skipping')
        return False

    # 检查是否已有数据
    if _has_today_data():
        logger.info(f'[scheduler] {today} data already exists, skipping collection')
        return True

    logger.info(f'[scheduler] Collecting data for {today}')
    try:
        collect_daily_data(date_no_dash)
    except Exception as e:
        logger.error(f'[scheduler] Collect error: {e}')
        return False

    # 采集成功后执行分析
    logger.info(f'[scheduler] Analyzing for {today}')
    try:
        calculate_heat_scores(today)
        update_lifecycle(today)
        calculate_rotation(today)
        calculate_money_flow_path(today)
    except Exception as e:
        logger.error(f'[scheduler] Analyze error: {e}')

    return _has_today_data()


def _startup_backfill():
    """启动时后台线程：检查今天数据是否缺失，缺失则补采；未成功则每小时重试"""
    # 等待应用完全启动
    import time
    time.sleep(5)

    today = datetime.now().strftime('%Y-%m-%d')
    now_hour = datetime.now().hour

    # 非交易时段（凌晨0-6点）不补采
    if now_hour < 7:
        logger.info(f'[scheduler] Too early for backfill (hour={now_hour})')
        return

    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, no backfill needed')
        return

    # 首次尝试
    success = _collect_and_analyze()

    if success:
        logger.info(f'[scheduler] Backfill succeeded for {today}')
        return

    # 首次失败，注册每小时重试任务
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

    scheduler.add_job(
        retry_job, 'interval', hours=1, id='backfill_retry',
        next_run_time=datetime.now() + timedelta(hours=1),
    )


def _startup_lifecycle_catchup():
    """启动时检查游资20天跟踪是否落后于信号表，落后则自动补跑"""
    import time
    time.sleep(15)  # 等待主数据采集完成

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

        # 补跑缺失的每一天
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


def scheduled_realtime_snapshot():
    """盘中实时快照采集任务（每15分钟）"""
    today = datetime.now().strftime('%Y-%m-%d')

    if not _is_trading_day(today):
        return

    if not _is_intraday_trading_hours():
        logger.info(f'[scheduler] Not in trading hours, skipping realtime snapshot')
        return

    logger.info(f'[scheduler] Realtime snapshot for {today}')
    try:
        collect_realtime_snapshot(today)
    except Exception as e:
        logger.error(f'[scheduler] Realtime snapshot error: {e}')

    # 实时快照采集完成后，计算概念板块实时资金流向
    _compute_realtime_concept_sector_flow()


def scheduled_archive():
    """收盘归档：把最后一次实时快照写入历史表"""
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        return
    logger.info(f'[scheduler] Archiving {today} snapshots to history')
    try:
        archive_today_snapshot_to_history(today)
    except Exception as e:
        logger.error(f'[scheduler] Archive error: {e}')

    # 收盘归档后，快照模拟盘持仓到本地（支持回溯历史盈亏）
    # 注：snapshot_today_positions 是 async；当前函数在 AsyncIOScheduler 的 sync job 上下文中
    # 用 run_coroutine_threadsafe 把任务丢到 scheduler 的 event loop（不阻塞当前 job）
    logger.info(f'[scheduler] Snapshotting sim positions for {today}')
    try:
        import asyncio
        from api.analysis import snapshot_today_positions
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已在事件循环中（如 AsyncIOScheduler 内部），schedule 异步执行
            loop.create_task(snapshot_today_positions())
        else:
            # 兜底：直接同步等结果
            loop.run_until_complete(snapshot_today_positions())
    except Exception as e:
        logger.error(f'[scheduler] Sim snapshot error: {e}')

    # 收盘归档后，同步概念板块成分股并计算日度资金流向
    _sync_concept_sectors()
    _compute_concept_sector_flow(today)


async def scheduled_watchlist_sync():
    """定时全量同步自选股（同花顺 ↔ AIROBOT ↔ 妙想）
    交易时段每5分钟执行一次：拉取同花顺新增 → 推送 AIROBOT 到同花顺/妙想
    AsyncIOScheduler 要求 job 是 async 函数才能在主 event loop 里 await，
    否则会被丢到 ThreadPoolExecutor 线程执行，触发 "no current event loop" 错误。
    """
    from api.sync_pkg import full_sync

    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        return
    # 仅在交易时段执行（避免开盘前/收盘后频繁请求）
    if not _is_intraday_trading_hours():
        return
    logger.info(f'[scheduler] Watchlist full sync for {today}')
    try:
        await full_sync()
    except Exception as e:
        logger.error(f'[scheduler] Watchlist sync error: {e}')


def scheduled_refresh_caches():
    """定时刷新热点缓存（纯DB缓存，避免请求时现场计算）"""
    try:
        from api.concept_sector import _refresh_hot_cache
        from api.heatmap import refresh_heatmap_cache
        _refresh_hot_cache()
        refresh_heatmap_cache()
    except Exception as e:
        logger.error(f'[scheduler] Refresh caches error: {e}')


async def scheduled_auto_trade():
    """盘中自动化交易（每5分钟检查信号+风控+下单）
    - async def: AsyncIOScheduler 共用 event loop，避免新建 loop 导致 ResourceWarning
    """
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        return
    if not _is_intraday_trading_hours():
        return
    try:
        from db.session import get_db_session
        from db.models import AutoTradeConfig
        from services.auto_trade_engine import execute_auto_trade
        with get_db_session() as db:
            config = db.query(AutoTradeConfig).filter_by(id=1).first()
            if not config or not config.enabled:
                return
            await execute_auto_trade(db, dry_run=False)
            logger.info(f'[scheduler] auto_trade executed at {datetime.now().strftime("%H:%M:%S")}')
    except Exception as e:
        logger.error(f'[scheduler] Auto trade error: {e}')


def start_scheduler():
    """启动定时采集调度器"""
    # === 盘中实时快照（每5分钟）===
    # 9:25-15:00 之间每5分钟采集一次（scheduler 内部会判断是否在交易时段）
    scheduler.add_job(scheduled_realtime_snapshot, 'cron',
                      hour='9', minute='25,30,35,40,45,50,55', id='realtime_snapshot_morning_9')
    scheduler.add_job(scheduled_realtime_snapshot, 'cron',
                      hour='10-11', minute='*/5', id='realtime_snapshot_morning')
    scheduler.add_job(scheduled_realtime_snapshot, 'cron',
                      hour='13-14', minute='*/5', id='realtime_snapshot_afternoon')
    scheduler.add_job(scheduled_realtime_snapshot, 'cron',
                      hour='15', minute='0', id='realtime_snapshot_close')

    # === 中转层资金流向（每 5 分钟，概念+行业）===
    scheduler.add_job(_collect_money_flow_concept, 'cron',
                      hour='9-11,13-14', minute='*/5', id='money_flow_concept')
    scheduler.add_job(_collect_money_flow_industry, 'cron',
                      hour='9-11,13-14', minute='*/5', id='money_flow_industry')

    # === 收盘归档（15:05）===
    scheduler.add_job(scheduled_archive, 'cron', hour='15', minute='5', id='archive')

    # === 盘后分析（15:30）===
    scheduler.add_job(scheduled_analyze, 'cron', hour='15', minute='30', id='analyze')

    # === 龙虎榜采集（18:30 独立任务，Tushare 18:00 后数据完整）===
    # 15:30 的 analyze 里也有兜底调用,这里 18:30 再跑一次确保数据完整
    scheduler.add_job(scheduled_dragon_tiger, 'cron', hour='18', minute='30', id='dragon_tiger_evening')
    # 19:00 再补一次（防止 Tushare 数据延迟）
    scheduler.add_job(scheduled_dragon_tiger, 'cron', hour='19', minute='0', id='dragon_tiger_fallback')

    # === 4档资金流采集（17:30 盘后，Tushare 17:00 后 moneyflow 数据完整）===
    scheduler.add_job(scheduled_moneyflow_detail, 'cron', hour='17', minute='30', id='moneyflow_detail')

    # === 市场状态更新（16:00，收盘后计算所有自选股 CHOPPY/TREND/IMPULSE）===
    scheduler.add_job(scheduled_market_state_update, 'cron', hour='16', minute='0', id='market_state')

    # === 策略扫描（15:30-19:00 每15分钟轮询，数据就绪后跑一次4个策略）===
    # 15:30/15:45 启动轮询（盘后分析之后）
    scheduler.add_job(scheduled_strategy_scan, 'cron', hour='15', minute='30,45', id='strategy_scan_15')
    # 16:00-18:45 每15分钟轮询
    scheduler.add_job(scheduled_strategy_scan, 'cron', hour='16-18', minute='*/15', id='strategy_scan_16_18')
    # 19:00 最后一次（收尾）
    scheduler.add_job(scheduled_strategy_scan, 'cron', hour='19', minute='0', id='strategy_scan_19')

    # === 热点缓存定时刷新（纯DB缓存，避免请求时现场计算）===
    # 盘后 15-22 点每30分（归档后保持热缓存）
    scheduler.add_job(scheduled_refresh_caches, 'cron', hour='15-22', minute='*/30', id='refresh_caches_post')
    # 盘中 9-14 点每10分（行情变化后更新）
    scheduler.add_job(scheduled_refresh_caches, 'cron', hour='9-14', minute='*/10', id='refresh_caches_intraday')

    # === 个股信号预计算（16:00-19:00 每15分钟轮询，数据就绪后跑一次）===
    scheduler.add_job(scheduled_watchlist_signal_compute, 'cron', hour='16-18', minute='*/15', id='watchlist_signal_compute')
    scheduler.add_job(scheduled_watchlist_signal_compute, 'cron', hour='19', minute='0', id='watchlist_signal_compute_19')

    # === BS策略预扫描（16:30-19:00 每30分钟轮询，跑一次最近10个回测策略）===
    scheduler.add_job(scheduled_bs_strategy_precompute, 'cron', hour='16-18', minute='*/30', id='bs_strategy_precompute')
    scheduler.add_job(scheduled_bs_strategy_precompute, 'cron', hour='19', minute='0', id='bs_strategy_precompute_19')

    # === 4.0 交易信号预计算（16:30-19:00 每15分钟轮询，watchlist_signal 跑完后跑）===
    scheduler.add_job(scheduled_trading_system_compute, 'cron', hour='16-18', minute='*/15', id='trading_system_compute')
    scheduler.add_job(scheduled_trading_system_compute, 'cron', hour='19', minute='0', id='trading_system_compute_19')

    # === 自选股全量同步（交易时段每5分钟：同花顺↔AIROBOT↔妙想）===
    # scheduler 内部会判断是否在交易时段
    scheduler.add_job(scheduled_watchlist_sync, 'cron',
                      hour='9-15', minute='*/5', id='watchlist_sync')

    # === 自动化交易（盘中每5分钟检查信号+风控+下单）===
    scheduler.add_job(scheduled_auto_trade, 'cron',
                      hour='9-14', minute='*/5', id='auto_trade')
    scheduler.add_job(scheduled_auto_trade, 'cron',
                      hour='11', minute='0-30', id='auto_trade_11')
    scheduler.add_job(scheduled_auto_trade, 'cron',
                      hour='13-14', minute='*/5', id='auto_trade_pm')

    # === 数据维护（每日凌晨清理730天前数据）===
    scheduler.add_job(cleanup_old_data, 'cron', hour='6', minute='0', id='cleanup')

    # === 盘中实时聚合（5 秒轮询,仅交易时段）===
    # 原 3 秒间隔因执行时间 >3s 导致 max_instances=1 频繁 skipped（4734次/日）
    # 改为 5 秒间隔，消除 skipped，保证数据稳定更新
    from collectors.realtime_aggregator import collect_realtime_snapshot
    scheduler.add_job(_safe_realtime_aggregator, 'interval',
                      seconds=5, id='realtime_aggregator_5s')

    scheduler.start()
    logger.info('[scheduler] Started (realtime snapshot every 5min, watchlist sync every 5min during trading hours)')

    # 启动后台线程检查是否需要补采
    t = threading.Thread(target=_startup_backfill, daemon=True)
    t.start()
    logger.info('[scheduler] Backfill check thread started')

    # 启动后台线程检查游资20天跟踪是否落后
    t3 = threading.Thread(target=_startup_lifecycle_catchup, daemon=True)
    t3.start()
    logger.info('[scheduler] Lifecycle catchup thread started')

    # 启动时同步一次概念板块成分股（后台线程，不阻塞）
    def _startup_concept_sync():
        import time
        time.sleep(10)
        _sync_concept_sectors()
    t2 = threading.Thread(target=_startup_concept_sync, daemon=True)
    t2.start()
    logger.info('[scheduler] Concept sector sync thread started')


def _safe_realtime_aggregator():
    """3 秒轮询的安全包装:仅交易时段执行,避免盘前/盘后污染数据"""
    from datetime import datetime, time as dtime
    now = datetime.now().time()
    is_trading = (
        dtime(9, 30) <= now <= dtime(11, 30)
    ) or (
        dtime(13, 0) <= now <= dtime(15, 0)
    )
    # 周一到周五
    is_weekday = datetime.now().weekday() < 5
    if not (is_trading and is_weekday):
        return
    from collectors.realtime_aggregator import collect_realtime_snapshot
    try:
        collect_realtime_snapshot()
    except Exception as e:
        logger.error(f'[realtime_aggregator] error: {e}', exc_info=True)


def _is_trading_day(date_str):
    """判断是否为交易日"""
    try:
        result = call_tushare_mcp(
            'trade_cal',
            params={'start_date': date_str.replace('-', ''), 'end_date': date_str.replace('-', '')},
            fields=['cal_date', 'is_open']
        )
        if result:
            return result[0].get('is_open', 0) == 1
    except Exception as e:
        logger.debug(f'[scheduler] trade_cal 查询失败 {date_str}: {e}')
    return False


def scheduled_collect():
    """定时采集任务（保留兼容，已由实时快照+归档替代）"""
    today = datetime.now().strftime('%Y-%m-%d')
    date_no_dash = datetime.now().strftime('%Y%m%d')

    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, skipping collection')
        return

    logger.info(f'[scheduler] Collecting data for {today}')
    try:
        collect_daily_data(date_no_dash)
    except Exception as e:
        logger.error(f'[scheduler] Collect error: {e}')


def scheduled_analyze():
    """盘后分析任务"""
    today = datetime.now().strftime('%Y-%m-%d')

    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, skipping analysis')
        return

    logger.info(f'[scheduler] Analyzing for {today}')
    try:
        calculate_heat_scores(today)
        update_lifecycle(today)
        calculate_rotation(today)
        calculate_money_flow_path(today)
    except Exception as e:
        logger.error(f'[scheduler] Analyze error: {e}')

    # 龙虎榜清洗（Tushare 18:00 后才出当日数据，15:30 跑可能拉空，作为兜底）
    try:
        from collectors.dragon_tiger_collector import run_today as run_yuzi_today
        r = run_yuzi_today()
        logger.info(f'[scheduler] Dragon-Tiger (15:30 fallback): {r}')
    except Exception as e:
        logger.error(f'[scheduler] Dragon-Tiger error: {e}')


def scheduled_dragon_tiger():
    """龙虎榜采集（18:30 独立任务，Tushare 18:00 后数据完整）
    - 拉当日 top_list + top_inst
    - 匹配 yuzi_dict → 写 yuzi_seat_daily + yuzi_quant_signals
    - 触发 D1 + 更新 D2-D20 游资 20 天跟踪
    """
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        return
    try:
        from collectors.dragon_tiger_collector import run_today
        r = run_today()
        logger.info(f'[scheduler] Dragon-Tiger 18:30: {r}')
    except Exception as e:
        logger.error(f'[scheduler] Dragon-Tiger 18:30 error: {e}', exc_info=True)

    # 游资 20 天跟踪：D1 触发 + D2-D20 更新
    try:
        from collectors.lifecycle_tracker import trigger_d1, update_lifecycle
        today_compact = datetime.now().strftime('%Y%m%d')
        inserted = trigger_d1(today_compact)
        upd = update_lifecycle(today_compact)
        logger.info(f'[scheduler] Lifecycle tracker: D1 inserted={inserted}, update={upd}')
    except Exception as e:
        logger.error(f'[scheduler] Lifecycle tracker error: {e}', exc_info=True)


def scheduled_moneyflow_detail():
    """4 档资金流采集(17:30 盘后,Tushare 17:00 后 moneyflow 数据完整)
    - 拉当日全市场 moneyflow
    - 写 stock_money_flow_detail(4 档净流入 + 主力/散户拆分)
    """
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        return
    try:
        from collectors.moneyflow_detail import fetch_moneyflow_for_date
        date_str = datetime.now().strftime('%Y%m%d')
        r = fetch_moneyflow_for_date(date_str)
        logger.info(f'[scheduler] moneyflow_detail 17:30: {r}')
    except Exception as e:
        logger.error(f'[scheduler] moneyflow_detail 17:30 error: {e}', exc_info=True)


def scheduled_strategy_scan():
    """盘后策略扫描（15:30-19:00 每15分钟轮询，数据就绪后跑一次）
    - 数据就绪检测：SectorFlow + StockFlow 都有当日数据
    - 防重复：strategy_runner.has_run_today 检查当日是否已 success
    - 跑完4个策略后，后续轮询会因 all_done 直接跳过
    """
    today = datetime.now().date()
    today_str = today.strftime('%Y-%m-%d')

    if not _is_trading_day(today_str):
        return

    # 时间窗口：15:30-19:00
    now = datetime.now()
    t = now.hour * 100 + now.minute
    if t < 1530 or t > 1900:
        return

    try:
        from services.strategy_runner import STRATEGIES, has_run_today, run_all_strategies, check_data_ready

        # 所有策略都已 success → 跳过
        all_done = all(has_run_today(s['key'], today) for s in STRATEGIES)
        if all_done:
            return

        # 数据未就绪 → 跳过，等下次轮询
        if not check_data_ready(today):
            logger.info(f'[scheduler] Strategy scan: data not ready for {today_str}, will retry')
            return

        logger.info(f'[scheduler] Strategy scan trigger for {today_str}')
        run_all_strategies(today_str)
    except Exception as e:
        logger.error(f'[scheduler] Strategy scan error: {e}')


def scheduled_watchlist_signal_compute():
    """盘后个股信号预计算（16:00-19:00 每15分钟轮询，数据就绪后跑一次）
    - 消除 /api/watchlist、/api/panorama/stocks、/api/leader/system 的现场计算
    - 防重复：watchlist_signal_runner.has_run_today 检查
    """
    today = datetime.now().date()
    today_str = today.strftime('%Y-%m-%d')

    if not _is_trading_day(today_str):
        return

    now = datetime.now()
    t = now.hour * 100 + now.minute
    if t < 1600 or t > 1900:
        return

    try:
        from services.watchlist_signal_runner import has_run_today, compute_for_date, check_data_ready

        if has_run_today(today):
            return

        if not check_data_ready(today):
            logger.info(f'[scheduler] Watchlist signal: data not ready for {today_str}, will retry')
            return

        logger.info(f'[scheduler] Watchlist signal compute trigger for {today_str}')
        compute_for_date(today_str)
    except Exception as e:
        logger.error(f'[scheduler] Watchlist signal compute error: {e}')


def scheduled_trading_system_compute():
    """盘后 4.0 交易信号预计算（16:30-19:00 每15分钟轮询，watchlist_signal 跑完后跑）
    - 依赖：WatchlistSignalDaily 已跑完
    - 防重复：trading_system.runner.has_run_today 检查
    - 输出：TradingSignalDaily 表
    """
    today = datetime.now().date()
    today_str = today.strftime('%Y-%m-%d')

    if not _is_trading_day(today_str):
        return

    now = datetime.now()
    t = now.hour * 100 + now.minute
    if t < 1630 or t > 1900:
        return

    try:
        from services.trading_system.runner import has_run_today, compute_for_date
        from services.watchlist_signal_runner import has_run_today as wl_done

        if has_run_today(today):
            return

        if not wl_done(today):
            logger.info(f'[scheduler] Trading system: watchlist_signal not ready for {today_str}, will retry')
            return

        logger.info(f'[scheduler] Trading system compute trigger for {today_str}')
        compute_for_date(today_str)
    except Exception as e:
        logger.error(f'[scheduler] Trading system compute error: {e}')


async def scheduled_bs_strategy_precompute():
    """盘后 BS 策略预扫描（16:30-19:00 每30分钟轮询，跑一次最近10个回测策略）
    - 消除 /api/bs-screener/run 的现场全市场扫描
    - 防重复：bs_daily_scan 表 (trade_date, backtest_id) 唯一约束
    - async def: AsyncIOScheduler 与 FastAPI 共用 event loop，必须 await 而非 asyncio.run
    """
    today = datetime.now().date()
    today_str = today.strftime('%Y-%m-%d')

    if not _is_trading_day(today_str):
        return

    now = datetime.now()
    t = now.hour * 100 + now.minute
    if t < 1630 or t > 1900:
        return

    try:
        from services.bs_strategy_runner import precompute_bs_strategies
        from db.session import get_db_session
        from db.models import BSDailyScan, BSBacktestResult

        # 检查是否所有 backtest_id 都已预计算
        with get_db_session() as db:
            recent_count = db.query(BSBacktestResult).order_by(
                BSBacktestResult.run_at.desc()
            ).limit(10).count()
            done_count = db.query(BSDailyScan).filter(
                BSDailyScan.trade_date == today
            ).count()
            if recent_count > 0 and done_count >= recent_count:
                return  # 全部已预计算

        logger.info(f'[scheduler] BS strategy precompute trigger for {today_str}')
        await precompute_bs_strategies(today)
    except Exception as e:
        logger.error(f'[scheduler] BS strategy precompute error: {e}')


async def scheduled_market_state_update():
    """收盘后更新所有自选股的市场状态（CHOPPY/TREND/IMPULSE）
    - async def: AsyncIOScheduler 共用 event loop，避免新建 loop 导致 ResourceWarning
    """
    from db.session import get_db_session
    from db.models import Watchlist
    from analyzers.market_state import update_stock_state

    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, skipping market state update')
        return

    try:
        with get_db_session() as db:
            stocks = db.query(Watchlist).all()
            logger.info(f'[scheduler] Updating market state for {len(stocks)} stocks...')
            sector_strength = 0  # 板块强度可后续从板块数据获取

            for i, item in enumerate(stocks):
                try:
                    await update_stock_state(item.stock_code, sector_strength)
                    if (i + 1) % 10 == 0:
                        logger.info(f'[scheduler] Market state {i+1}/{len(stocks)} done')
                except Exception as e:
                    logger.error(f'[scheduler] Market state error for {item.stock_code}: {e}')

            logger.info(f'[scheduler] Market state update completed for {len(stocks)} stocks')
    except Exception as e:
        logger.error(f'[scheduler] Market state update error: {e}')


def cleanup_old_data():
    """清理2年前的数据（保留730天用于回测）

    在宽 misfire_grace_time(3600s) 下，盘后任务可补执行；
    但本任务若被 mfire 推迟到 6:00 之后 1 小时内会与盘后任务抢资源，
    因此函数内自检：仅在 6:00-7:00 之间执行，错过则跳过当日。
    """
    from db.connection import get_db
    from db.session import get_db_session
    from db.models import (SectorFlow, StockFlow, LeaderLifecycle,
                           RealtimeStockFlow, RealtimeSectorFlow,
                           RealtimeMoneyFlowSnapshot, RealtimeConceptSectorFlow)
    now_h = datetime.now().hour
    if now_h >= 7:
        logger.info(f'[scheduler] cleanup skipped (misfired too late, now_hour={now_h})')
        return
    cutoff = (datetime.now() - timedelta(days=730)).date()
    # realtime_* 表只保留 7 天（盘中每 5 秒写入，膨胀快）
    realtime_cutoff = datetime.now() - timedelta(days=7)
    try:
        with get_db_session() as db:
            # 历史表：保留 730 天
            db.query(SectorFlow).filter(SectorFlow.trade_date < cutoff).delete()
            db.query(StockFlow).filter(StockFlow.trade_date < cutoff).delete()
            db.query(LeaderLifecycle).filter(LeaderLifecycle.trade_date < cutoff).delete()
            # 实时表：保留 7 天（271MB → ~50MB）
            db.query(RealtimeStockFlow).filter(RealtimeStockFlow.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.query(RealtimeSectorFlow).filter(RealtimeSectorFlow.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.query(RealtimeMoneyFlowSnapshot).filter(RealtimeMoneyFlowSnapshot.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.query(RealtimeConceptSectorFlow).filter(RealtimeConceptSectorFlow.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.commit()
            logger.info(f'[scheduler] Cleaned history before {cutoff}, realtime before {realtime_cutoff}')
    except Exception as e:
        logger.error(f'[scheduler] Cleanup error: {e}')
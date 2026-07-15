"""所有 scheduled_* 定时任务函数
- 拆分自 collectors/scheduler.py（1337 行 → 约 600 行）
- 此文件只放被 APScheduler 调用的具体任务实现
- 注册逻辑、scheduler 实例、start_scheduler() 仍保留在 collectors/scheduler.py

分组：
  A) 盘中实时：scheduled_emdatah5_fund_flow, scheduled_realtime_snapshot,
               scheduled_orderbook_snapshot
  B) 收盘归档：scheduled_archive
  C) 盘后分析：scheduled_analyze, scheduled_dragon_tiger, scheduled_moneyflow_detail,
               scheduled_strategy_scan, scheduled_watchlist_signal_compute,
               scheduled_trading_system_compute, scheduled_bs_strategy_precompute,
               scheduled_market_state_update
  D) 缓存/研究：scheduled_refresh_caches, scheduled_research_collection,
               scheduled_daily_report
  E) 自选股/交易：scheduled_watchlist_sync, scheduled_auto_trade
  F) 维护/告警：scheduled_freshness_check, cleanup_old_data,
               scheduled_external_wave1/2, scheduled_f10_backfill,
               scheduled_generate_recap
"""
import asyncio
import json
import logging
import sys
import os
from datetime import datetime, timedelta

from sqlalchemy import text, func

# 与 scheduler.py 保持一致的 sys.path 处理
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.tdx_collector import collect_daily_data, call_tushare_mcp
from collectors.realtime_collector import collect_realtime_snapshot, archive_today_snapshot_to_history
from collectors.money_flow_middleman import collect_realtime_money_flow_snapshot
from collectors.extended_collectors import sina_orderbook_batch
from analyzers.heat_score import calculate_heat_scores
from analyzers.lifecycle import update_lifecycle
from analyzers.rotation import calculate_rotation
from analyzers.money_flow import calculate_money_flow_path
from services.alert_service import record_alert, check_realtime_data_gap

from db.session import get_db_session
from db.models import (
    Watchlist, AutoTradeConfig, AIAnalysisCache,
    YuziLifecycleTracker, YuziQuantSignal,
)

logger = logging.getLogger(__name__)


# ============================================================
# 共享帮助函数（与 scheduler.py 中同步，便于本文件自包含）
# ============================================================

def _is_trading_day(date_str):
    """判断是否为交易日（Tushare trade_cal）"""
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


def _is_intraday_trading_hours():
    """判断当前是否在盘中交易时段（9:25-11:30, 13:00-15:00）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return (925 <= t <= 1130) or (1300 <= t <= 1500)


def _to_ts_code(code):
    """6位A股代码转 ts_code（含北交所）"""
    code = str(code).strip()
    if not code.isdigit() or len(code) != 6:
        return None
    if code.startswith(('6', '9')):
        return f'{code}.SH'
    if code.startswith(('8', '4', '92', '87', '89')):
        return f'{code}.BJ'
    return f'{code}.SZ'


def _has_today_data():
    """检查数据库中是否已有今天的完整数据"""
    from db.models import SectorFlow, StockFlow, StockDailyKline
    today = datetime.now().date()
    try:
        with get_db_session() as db:
            sector_count = db.query(SectorFlow).filter(SectorFlow.trade_date == today).count()
            stock_count = db.query(StockFlow).filter(StockFlow.trade_date == today).count()
            kline_count = db.query(StockDailyKline).filter(StockDailyKline.trade_date == today).count()
            return sector_count > 30 and stock_count > 500 and kline_count > 1000
    except Exception:
        logger.debug(f"_has_today_data failed", exc_info=True)
        return False


def _get_orderbook_stock_pool():
    """构建五档盘口关键股票池（watchlist + portfolio + focus + 游资20天 + 当日游资共振高分）"""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    codes = set()

    # 1) 自选股
    try:
        with open(root / 'watchlist.json', 'r', encoding='utf-8') as f:
            for s in json.load(f).get('stocks', []):
                c = str(s.get('code') or '').strip()
                if c:
                    codes.add(c)
    except Exception as e:
        logger.debug(f'[orderbook] read watchlist.json failed: {e}')

    # 2) 模拟盘/共享持仓
    try:
        with open(root / 'portfolio.json', 'r', encoding='utf-8') as f:
            for p in json.load(f).get('positions', []):
                c = str(p.get('symbol') or p.get('code') or '').strip()
                if c:
                    codes.add(c)
    except Exception as e:
        logger.debug(f'[orderbook] read portfolio.json failed: {e}')

    # 3) 重点关注板块成分股
    try:
        with open(root / 'focus.json', 'r', encoding='utf-8') as f:
            for sec in json.load(f).get('sectors', []):
                for st in sec.get('stocks', []):
                    c = str(st.get('code') or '').strip()
                    if c:
                        codes.add(c)
    except Exception as e:
        logger.debug(f'[orderbook] read focus.json failed: {e}')

    # 4) 近20天游资生命周期跟踪股
    try:
        today = datetime.now().date()
        with get_db_session() as db:
            recent = db.query(YuziLifecycleTracker.ts_code).filter(
                func.to_date(YuziLifecycleTracker.trigger_date, 'YYYYMMDD') >= today - timedelta(days=20)
            ).distinct().all()
            for r in recent:
                c = str(r[0] or '').replace('.SZ', '').replace('.SH', '').replace('.BJ', '').strip()
                if c:
                    codes.add(c)
    except Exception as e:
        logger.debug(f'[orderbook] read lifecycle tracker failed: {e}')

    # 5) 当日游资共振高分股
    try:
        today_str = datetime.now().strftime('%Y%m%d')
        with get_db_session() as db:
            high = db.query(YuziQuantSignal.ts_code).filter(
                YuziQuantSignal.trade_date == today_str,
                YuziQuantSignal.resonance_count >= 2
            ).distinct().all()
            for r in high:
                c = str(r[0] or '').replace('.SZ', '').replace('.SH', '').replace('.BJ', '').strip()
                if c:
                    codes.add(c)
    except Exception as e:
        logger.debug(f'[orderbook] read yuzi quant signal failed: {e}')

    valid = []
    for c in codes:
        c = str(c).strip()
        if c.isdigit() and len(c) == 6:
            valid.append(c)
    return valid


# ============================================================
# 概念板块辅助（被多个 scheduled_* 调用）
# ============================================================

def _sync_concept_sectors():
    """同步概念板块成分股"""
    try:
        from scripts.sync_concept_sectors import sync
        sync()
    except Exception as e:
        logger.error(f'[scheduler] Concept sector sync error: {e}', exc_info=True)
        try:
            record_alert(level='warning', category='source_failure',
                         message=f'[concept] 概念板块成分股同步异常: {str(e)[:160]}',
                         trade_date=datetime.now().date())
        except Exception:
            logger.debug("[concept] stock sync logging failed", exc_info=False)


def _compute_concept_sector_flow(target_date=None):
    """计算概念板块日度资金流向"""
    try:
        from scripts.compute_concept_sector_flow import compute_for_date
        compute_for_date(target_date)
    except Exception as e:
        logger.error(f'[scheduler] Concept sector flow compute error: {e}', exc_info=True)
        try:
            record_alert(level='warning', category='source_failure',
                         message=f'[concept] 概念板块日度资金流向计算异常: {str(e)[:160]}',
                         trade_date=datetime.now().date())
        except Exception:
            logger.debug("[concept] stock sync logging failed", exc_info=False)


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


# ============================================================
# A) 盘中实时
# ============================================================

def scheduled_emdatah5_fund_flow():
    """盘中实时资金流采集（自选股，每 5 分钟轮询）"""
    if not _is_intraday_trading_hours():
        return
    if datetime.now().weekday() >= 5:
        return
    try:
        from collectors.emdatah5_collector import batch_save_realtime, is_trading_time
        if not is_trading_time():
            return
        with get_db_session() as db:
            codes = [r.stock_code for r in db.query(Watchlist).all() if r.stock_code]
        if not codes:
            return
        result = batch_save_realtime(codes)
        logger.info(f'[emdatah5] 盘中资金流采集: {result}')
    except Exception as e:
        logger.error(f'[emdatah5] 盘中采集异常: {e}', exc_info=True)


def scheduled_realtime_snapshot():
    """盘中实时快照采集任务（每分钟）"""
    today = datetime.now().strftime('%Y-%m-%d')
    today_date = datetime.now().date()

    if not _is_trading_day(today):
        return
    if not _is_intraday_trading_hours():
        logger.info(f'[scheduler] Not in trading hours, skipping realtime snapshot')
        return

    logger.info(f'[scheduler] Realtime snapshot for {today}')
    try:
        collect_realtime_snapshot(today)
    except Exception as e:
        logger.error(f'[scheduler] Realtime snapshot error: {e}', exc_info=True)
        record_alert(
            level='error', category='source_failure',
            message=f'[{today}] 实时个股快照采集异常: {str(e)[:120]}',
            trade_date=today_date,
        )

    try:
        _compute_realtime_concept_sector_flow()
    except Exception as e:
        logger.error(f'[scheduler] Realtime concept sector compute error: {e}', exc_info=True)
        record_alert(
            level='warning', category='source_failure',
            message=f'[{today}] 概念板块实时资金流向计算异常: {str(e)[:120]}',
            trade_date=today_date,
        )

    try:
        check_realtime_data_gap(trade_date=today_date)
    except Exception as e:
        logger.error(f'[scheduler] check_realtime_data_gap error: {e}', exc_info=True)


def scheduled_orderbook_snapshot():
    """盘中五档盘口定时采集（每3秒）"""
    if not _is_intraday_trading_hours():
        return

    codes = _get_orderbook_stock_pool()
    if not codes:
        logger.debug('[orderbook] no stock pool')
        return

    ts_codes = [_to_ts_code(c) for c in codes if _to_ts_code(c)]
    if not ts_codes:
        return

    snapshot_time = datetime.now().replace(microsecond=0)
    trade_date = snapshot_time.date()
    rows = []
    batch_size = 50
    fetched_total = 0
    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i:i + batch_size]
        try:
            data = sina_orderbook_batch(batch)
            fetched_total += len(data)
            for ts_code, ob in data.items():
                rows.append({
                    'snapshot_time': snapshot_time,
                    'trade_date': trade_date,
                    'ts_code': ts_code,
                    'bid_prices': json.dumps(ob.get('bid_prices', [])),
                    'bid_vols': json.dumps(ob.get('bid_vols', [])),
                    'ask_prices': json.dumps(ob.get('ask_prices', [])),
                    'ask_vols': json.dumps(ob.get('ask_vols', [])),
                    'source': 'sina',
                })
        except Exception as e:
            logger.error(f'[orderbook] batch {i // batch_size + 1} failed: {e}')

    if not rows:
        return

    try:
        from db.connection import engine
        with engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO stock_realtime_orderbook
                    (snapshot_time, trade_date, ts_code, bid_prices, bid_vols, ask_prices, ask_vols, source)
                    VALUES (:snapshot_time, :trade_date, :ts_code, :bid_prices, :bid_vols, :ask_prices, :ask_vols, :source)
                """),
                rows
            )
            conn.commit()
        logger.info(f'[orderbook] saved {len(rows)} snapshots from {fetched_total} fetched (pool={len(ts_codes)})')
    except Exception as e:
        logger.error(f'[orderbook] save error: {e}', exc_info=True)


# ============================================================
# B) 收盘归档
# ============================================================

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

    logger.info(f'[scheduler] Snapshotting sim positions for {today}')
    try:
        from api.analysis import snapshot_today_positions
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(snapshot_today_positions())
        else:
            loop.run_until_complete(snapshot_today_positions())
    except Exception as e:
        logger.error(f'[scheduler] Sim snapshot error: {e}')

    try:
        _compute_concept_sector_flow(today)
    except Exception as e:
        logger.error(f'[scheduler] Concept sector flow compute (outer) error: {e}')
    try:
        _sync_concept_sectors()
    except Exception as e:
        logger.error(f'[scheduler] Concept sector sync (outer) error: {e}')


# ============================================================
# C) 盘后分析
# ============================================================

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

    try:
        from collectors.dragon_tiger_collector import run_today as run_yuzi_today
        r = run_yuzi_today()
        logger.info(f'[scheduler] Dragon-Tiger (15:30 fallback): {r}')
    except Exception as e:
        logger.error(f'[scheduler] Dragon-Tiger error: {e}')


def scheduled_dragon_tiger():
    """龙虎榜采集（18:30 独立任务）"""
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        return
    try:
        from collectors.dragon_tiger_collector import run_today
        r = run_today()
        logger.info(f'[scheduler] Dragon-Tiger 18:30: {r}')
    except Exception as e:
        logger.error(f'[scheduler] Dragon-Tiger 18:30 error: {e}', exc_info=True)

    try:
        from collectors.lifecycle_tracker import trigger_d1, update_lifecycle
        today_compact = datetime.now().strftime('%Y%m%d')
        inserted = trigger_d1(today_compact)
        upd = update_lifecycle(today_compact)
        logger.info(f'[scheduler] Lifecycle tracker: D1 inserted={inserted}, update={upd}')
    except Exception as e:
        logger.error(f'[scheduler] Lifecycle tracker error: {e}', exc_info=True)


def scheduled_moneyflow_detail():
    """4 档资金流采集（17:30 盘后）"""
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
    """盘后策略扫描（15:30-19:00 每15分钟轮询）"""
    today = datetime.now().date()
    today_str = today.strftime('%Y-%m-%d')
    if not _is_trading_day(today_str):
        return
    now = datetime.now()
    t = now.hour * 100 + now.minute
    if t < 1530 or t > 1900:
        return
    try:
        from services.strategy_runner import STRATEGIES, has_run_today, run_all_strategies, check_data_ready
        all_done = all(has_run_today(s['key'], today) for s in STRATEGIES)
        if all_done:
            return
        if not check_data_ready(today):
            logger.info(f'[scheduler] Strategy scan: data not ready for {today_str}, will retry')
            return
        logger.info(f'[scheduler] Strategy scan trigger for {today_str}')
        run_all_strategies(today_str)
    except Exception as e:
        logger.error(f'[scheduler] Strategy scan error: {e}')


def scheduled_watchlist_signal_compute():
    """盘后个股信号预计算（16:00-19:00 每15分钟轮询）"""
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
    """盘后 4.0 交易信号预计算（16:30-19:00 每15分钟轮询）"""
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
    """盘后 BS 策略预扫描（16:30-19:00 每30分钟轮询）"""
    from db.models import BSDailyScan, BSBacktestResult
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
        with get_db_session() as db:
            recent_count = db.query(BSBacktestResult).order_by(
                BSBacktestResult.run_at.desc()
            ).limit(10).count()
            done_count = db.query(BSDailyScan).filter(
                BSDailyScan.trade_date == today
            ).count()
            if recent_count > 0 and done_count >= recent_count:
                return
        logger.info(f'[scheduler] BS strategy precompute trigger for {today_str}')
        await precompute_bs_strategies(today)
    except Exception as e:
        logger.error(f'[scheduler] BS strategy precompute error: {e}')


async def scheduled_market_state_update():
    """收盘后更新所有自选股的市场状态（CHOPPY/TREND/IMPULSE）"""
    from analyzers.market_state import update_stock_state

    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, skipping market state update')
        return

    try:
        with get_db_session() as db:
            stocks = db.query(Watchlist).all()
            logger.info(f'[scheduler] Updating market state for {len(stocks)} stocks...')
            sector_strength = 0

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


# ============================================================
# D) 缓存/研究
# ============================================================

def scheduled_refresh_caches():
    """定时刷新热点缓存（纯DB缓存，避免请求时现场计算）"""
    try:
        from api.concept_sector import _refresh_hot_cache
        from api.heatmap import refresh_heatmap_cache
        _refresh_hot_cache()
        refresh_heatmap_cache()
    except Exception as e:
        logger.error(f'[scheduler] Refresh caches error: {e}')


async def scheduled_research_collection():
    """盘后研究采集（19:30，所有数据就绪后）"""
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} 非交易日，跳过研究采集')
        return
    try:
        from collectors.research_collector import run_research_collection
        n = await run_research_collection(today)
        logger.info(f'[scheduler] research_collection 完成：{n} 只')
    except Exception as e:
        logger.error(f'[scheduler] research_collection 异常: {e}', exc_info=True)


async def scheduled_daily_report():
    """盘后综合日报生成（20:00）"""
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} 非交易日，跳过年报生成')
        return
    try:
        from reports.daily_report import generate_daily_report
        path = generate_daily_report(today)
        logger.info(f'[scheduler] daily_report 已生成: {path}')
    except Exception as e:
        logger.error(f'[scheduler] daily_report 异常: {e}', exc_info=True)


# ============================================================
# E) 自选股/交易
# ============================================================

async def scheduled_watchlist_sync():
    """定时全量同步自选股（同花顺 ↔ AIROBOT ↔ 妙想）"""
    from api.sync_pkg import full_sync

    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        return
    if not _is_intraday_trading_hours():
        return
    logger.info(f'[scheduler] Watchlist full sync for {today}')
    try:
        await full_sync()
    except Exception as e:
        logger.error(f'[scheduler] Watchlist sync error: {e}')


async def scheduled_auto_trade():
    """盘中自动化交易（每5分钟检查信号+风控+下单）"""
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        return
    if not _is_intraday_trading_hours():
        return
    try:
        from services.auto_trade_engine import execute_auto_trade
        with get_db_session() as db:
            config = db.query(AutoTradeConfig).filter_by(id=1).first()
            if not config or not config.enabled:
                return
            await execute_auto_trade(db, dry_run=False)
            logger.info(f'[scheduler] auto_trade executed at {datetime.now().strftime("%H:%M:%S")}')
    except Exception as e:
        logger.error(f'[scheduler] Auto trade error: {e}')


# ============================================================
# F) 维护/告警/外部
# ============================================================

# 每日新鲜度自检白名单（白名单避免 SQL 拼接注入）
_DAILY_FRESHNESS_TABLES = [
    ("sector_flow", "trade_date"),
    ("stock_flow", "trade_date"),
    ("concept_sector_flow", "trade_date"),
    ("leader_lifecycle", "trade_date"),
    ("watchlist_signal_daily", "trade_date"),
    ("trading_signal_daily", "trade_date"),
    ("stock_news_search", "created_at"),
    ("stock_data_query", "query_time"),
    ("ai_analysis_cache", "created_at"),
    ("stock_adj_factor", "trade_date"),
    ("stock_margin_data", "trade_date"),
    ("north_money_flow", "trade_date"),
    ("hsgt_top10", "trade_date"),
]


def _previous_complete_market_day(db):
    """以 stock_flow 最大交易日作为"最近一个已完成交易日"（早间检查基准）"""
    return db.execute(text("SELECT max(trade_date) FROM stock_flow")).scalar()


def scheduled_freshness_check():
    """每日早间新鲜度自检：落后则告警+补采"""
    today = datetime.now().date()
    with get_db_session() as db:
        expected = _previous_complete_market_day(db)
        if not expected:
            logger.info('[freshness] 无基准交易日，跳过自检')
            return
        if expected >= today:
            logger.info(f'[freshness] 基准日 {expected} 不早于今日，跳过（可能尚在当日盘前）')
            return

        stale = []
        _allowed_tables = {t for t, _ in _DAILY_FRESHNESS_TABLES}
        _allowed_cols = {c for _, c in _DAILY_FRESHNESS_TABLES}
        for tbl, col in _DAILY_FRESHNESS_TABLES:
            try:
                if tbl not in _allowed_tables or col not in _allowed_cols:
                    raise ValueError(f"table/column not in whitelist: {tbl}.{col}")
                latest = db.execute(text(f"SELECT max({col})::date FROM {tbl}")).scalar()
            except Exception as e:
                logger.warning(f'[freshness] 查询 {tbl} 失败: {e}')
                continue
            if latest is None or latest < expected:
                gap = (expected - latest).days if latest else '?'
                record_alert(
                    level='error', category='data_stale',
                    message=f'[{expected}] {tbl} 数据滞后：最新 {latest}，期望 {expected}（落后 {gap} 天）',
                    trade_date=expected,
                )
                stale.append(tbl)
                logger.warning(f'[freshness] {tbl} 滞后（最新 {latest} / 期望 {expected}）')

        # 概念板块资金流缺失补采
        try:
            cf_latest = db.execute(text("SELECT max(trade_date) FROM concept_sector_flow")).scalar()
            if cf_latest is None or cf_latest < expected:
                logger.info(f'[freshness] 触发 concept_sector_flow 补采 -> {expected}')
                _compute_concept_sector_flow(expected.isoformat())
        except Exception as e:
            logger.error(f'[freshness] concept 补采失败: {e}', exc_info=True)

        # 研究层缺失补采（依赖外部 scheduler.add_job，避免在 with 块中嵌套调度）
        try:
            ai_latest = db.execute(text("SELECT max(created_at)::date FROM ai_analysis_cache")).scalar()
            if ai_latest is None or ai_latest < expected:
                logger.info(f'[freshness] 触发研究采集补采 -> {expected}')
                from collectors.research_collector import run_research_collection
                # 注意：依赖 scheduler 实例，从 collectors.scheduler 导入
                from collectors.scheduler import scheduler
                scheduler.add_job(
                    run_research_collection, 'date',
                    run_date=datetime.now() + timedelta(minutes=1),
                    id='freshness_research_backfill', replace_existing=True,
                )
        except Exception as e:
            logger.error(f'[freshness] 研究补采调度失败: {e}', exc_info=True)

    logger.info('[freshness] 自检完成')


def cleanup_old_data():
    """清理过期数据（历史 730 天 / 实时 30 天）"""
    from db.connection import get_db
    from db.models import (SectorFlow, StockFlow, LeaderLifecycle,
                           RealtimeStockFlow, RealtimeSectorFlow,
                           RealtimeMoneyFlowSnapshot, RealtimeConceptSectorFlow,
                           StockRealtimeTick, StockRealtimeOrderbook,
                           StockMoneyFlowRealtime)
    now_h = datetime.now().hour
    if now_h >= 7:
        logger.info(f'[scheduler] cleanup skipped (misfired too late, now_hour={now_h})')
        return
    cutoff = (datetime.now() - timedelta(days=730)).date()
    realtime_cutoff = datetime.now() - timedelta(days=30)
    try:
        with get_db_session() as db:
            db.query(SectorFlow).filter(SectorFlow.trade_date < cutoff).delete()
            db.query(StockFlow).filter(StockFlow.trade_date < cutoff).delete()
            db.query(LeaderLifecycle).filter(LeaderLifecycle.trade_date < cutoff).delete()
            db.query(StockRealtimeTick).filter(StockRealtimeTick.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.query(StockRealtimeOrderbook).filter(StockRealtimeOrderbook.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.query(RealtimeStockFlow).filter(RealtimeStockFlow.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.query(StockMoneyFlowRealtime).filter(StockMoneyFlowRealtime.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.query(RealtimeSectorFlow).filter(RealtimeSectorFlow.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.query(RealtimeMoneyFlowSnapshot).filter(RealtimeMoneyFlowSnapshot.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.query(RealtimeConceptSectorFlow).filter(RealtimeConceptSectorFlow.snapshot_time < realtime_cutoff).delete(synchronize_session=False)
            db.commit()
            logger.info(f'[scheduler] Cleaned: history<{cutoff}, realtime<{realtime_cutoff.date()}')
    except Exception as e:
        logger.error(f'[scheduler] Cleanup error: {e}')


def scheduled_f10_backfill():
    """盘后增量预拉全市场 F10（财务/机构/估值）"""
    if not _is_trading_day(datetime.now().strftime('%Y-%m-%d')):
        logger.info('[scheduler] 非交易日，跳过 F10 预拉')
        return
    import subprocess
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts', 'backfill_f10_full.py'))
    log = '/tmp/backfill_f10_cron.log'
    try:
        subprocess.Popen(
            ['nohup', '/usr/bin/python3', script, '--layer', 'all'],
            stdout=open(log, 'a'), stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        logger.info('[scheduler] F10 预拉已触发（子进程，日志 %s）', log)
    except Exception as e:
        logger.error(f'[scheduler] F10 预拉触发失败: {e}')


def _sync_external_with_retry(target_date, collectors, max_retries=3):
    """通用外部数据采集重试包装器"""
    from collectors.external_data_collector import (
        collect_stock_adj_factor, collect_suspend_stock_daily,
        collect_stock_margin_data, collect_north_money_flow, collect_hsgt_top10,
    )
    func_map = {
        'adj_factor': collect_stock_adj_factor,
        'suspend': collect_suspend_stock_daily,
        'margin': collect_stock_margin_data,
        'north': collect_north_money_flow,
        'hsgt': collect_hsgt_top10,
    }
    results = {}
    for name in collectors:
        fn = func_map[name]
        for attempt in range(1, max_retries + 1):
            try:
                cnt = fn(target_date)
                if cnt > 0:
                    results[name] = cnt
                    logger.info(f'[sync_ext] {name}({target_date}): {cnt}条 (attempt {attempt})')
                    break
                else:
                    logger.info(f'[sync_ext] {name}({target_date}): 空结果，稍后重试 (attempt {attempt})')
            except Exception as e:
                logger.warning(f'[sync_ext] {name}({target_date}) 失败: {e} (attempt {attempt})')
            if attempt < max_retries:
                import time
                time.sleep(600 * attempt)
        else:
            logger.warning(f'[sync_ext] {name}({target_date}): 重试{max_retries}次后仍无数据')
            results[name] = 0
    return results


def scheduled_external_wave1():
    """第一波(16:00)：adj_factor + suspend_d"""
    from datetime import datetime as _dt
    today = _dt.now().strftime('%Y%m%d')
    logger.info(f'[scheduler] 外部数据第一波(波1/16:00) {today}...')
    try:
        results = _sync_external_with_retry(today, ['adj_factor', 'suspend'], max_retries=1)
        logger.info(f'[scheduler] 外部数据第一波完成: {results}')
    except Exception as e:
        logger.error(f'[scheduler] 外部数据第一波失败: {e}', exc_info=True)


def scheduled_external_wave2():
    """第二波(次日09:30)：margin_data + north_money_flow + hsgt_top10"""
    from datetime import datetime as _dt, timedelta as _td
    yesterday = (_dt.now() - _td(days=1)).strftime('%Y%m%d')
    logger.info(f'[scheduler] 外部数据第二波(波2/09:30) {yesterday}...')
    try:
        results = _sync_external_with_retry(yesterday, ['margin', 'north', 'hsgt'], max_retries=2)
        logger.info(f'[scheduler] 外部数据第二波完成: {results}')
    except Exception as e:
        logger.error(f'[scheduler] 外部数据第二波失败: {e}', exc_info=True)


def scheduled_generate_recap():
    """盘后复盘报告生成（16:30）"""
    logger.info('[scheduler] 盘后复盘生成开始...')
    try:
        from api.analysis_reports import build_and_persist_recap
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        rid, created = build_and_persist_recap(date_str, now)
        logger.info(f'[scheduler] 盘后复盘生成{"完成" if created else "已存在"}: {date_str}')
    except Exception as e:
        logger.error(f'[scheduler] 盘后复盘生成失败: {e}', exc_info=True)

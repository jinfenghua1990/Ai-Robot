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
from __future__ import annotations

import asyncio
import json
import logging
import sys
import os
from datetime import datetime, timedelta

from sqlalchemy import text, func, or_

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
logger.setLevel(logging.INFO)  # 定时任务需要留痕（全局默认 WARNING 会吞掉 info）


async def scheduled_google_sheets_sync():
    """授权后每 15 分钟同步 Google Sheets；未授权时无外部请求并静默跳过。"""
    try:
        from services.google_sheets_sync import sync_if_configured
        result = await sync_if_configured()
        if result.get("skipped"):
            return result
        logger.info("[google-sheets] 自动同步完成: %s", result.get("counts", {}))
        return result
    except Exception as exc:
        logger.warning("[google-sheets] 自动同步失败: %s", exc)
        return {"ok": False, "error": str(exc)}


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


def _latest_a_share_trade_date(on_or_before: datetime) -> str | None:
    """返回不晚于指定日期的最近 A 股交易日（YYYYMMDD）。"""
    for offset in range(10):
        candidate = on_or_before - timedelta(days=offset)
        date_text = candidate.strftime('%Y-%m-%d')
        if _is_trading_day(date_text):
            return candidate.strftime('%Y%m%d')
    return None


def _is_intraday_trading_hours():
    """判断当前是否在盘中交易时段（9:25-11:30, 13:00-15:00）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return (925 <= t <= 1130) or (1300 <= t <= 1500)


def _is_before_a_share_daily_close(now: datetime | None = None):
    """当天日线尚未稳定前，不允许启动补采把未完成数据当作收盘数据。"""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    return now.hour * 100 + now.minute < 1510


def _is_before_a_share_postmarket_ready(now: datetime | None = None):
    """盘后采集与策略尚未就绪时，不运行启动型全市场补采。"""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    return now.hour * 100 + now.minute < 1530


def _to_ts_code(code):
    """6位A股代码转 ts_code（含北交所）"""
    code = str(code).strip()
    if not code.isdigit() or len(code) != 6:
        return None
    if code.startswith(('5', '6', '9')):
        return f'{code}.SH'
    if code.startswith(('8', '4', '92', '87', '89')):
        return f'{code}.BJ'
    return f'{code}.SZ'


def _today_daily_data_counts():
    """返回当天板块、个股资金流与日线条数。"""
    from db.models import SectorFlow, StockFlow, StockDailyKline
    today = datetime.now().date()
    try:
        with get_db_session() as db:
            sector_count = db.query(SectorFlow).filter(SectorFlow.trade_date == today).count()
            stock_count = db.query(StockFlow).filter(StockFlow.trade_date == today).count()
            kline_count = db.query(StockDailyKline).filter(StockDailyKline.trade_date == today).count()
            return sector_count, stock_count, kline_count
    except Exception:
        logger.debug('_today_daily_data_counts failed', exc_info=True)
        return 0, 0, 0


def _has_today_flow_data():
    """检查当天基础资金流是否已完整，供日线补采走轻量路径。"""
    sector_count, stock_count, _ = _today_daily_data_counts()
    return sector_count > 30 and stock_count > 500


def _has_today_data():
    """检查数据库中是否已有今天可用于盘后分析的完整数据。"""
    sector_count, stock_count, kline_count = _today_daily_data_counts()
    return sector_count > 30 and stock_count > 500 and kline_count > 1000


ORDERBOOK_MAX_SYMBOLS = 80


def _prioritize_orderbook_codes(groups, limit: int = ORDERBOOK_MAX_SYMBOLS):
    """按业务优先级去重并截断盘口池，保证持仓优先且输出稳定。"""
    selected = []
    seen = set()
    for group in groups:
        for raw_code in group:
            code = str(raw_code or '').strip()
            if not (code.isdigit() and len(code) == 6) or code in seen:
                continue
            seen.add(code)
            selected.append(code)
            if len(selected) >= limit:
                return selected
    return selected


def _get_orderbook_stock_pool(max_symbols: int = ORDERBOOK_MAX_SYMBOLS):
    """构建受限的五档盘口关键池。

    持仓和自选优先，旧重点关注与游资来源仅补足余量。这样不会影响日线、
    因子或策略数据，只避免每数秒对全量候选池重复抓取并写入原始盘口明细。
    """
    watchlist_codes = []
    portfolio_codes = []
    focus_codes = []
    lifecycle_codes = []
    resonance_codes = []

    # 1) 自选股与持仓都从数据库读取，兼容 JSON 不参与采集决策。
    try:
        from db.session import get_db_session
        from db.models import SimPosition, Watchlist
        with get_db_session() as db:
            watchlist_codes = [
                str(row[0] or '').strip()
                for row in db.query(Watchlist.stock_code).all()
                if row[0]
            ]
            portfolio_codes = [
                str(row[0] or '').strip()
                for row in db.query(SimPosition.sec_code).filter(SimPosition.count > 0).all()
                if row[0]
            ]
    except Exception as e:
        logger.debug(f'[orderbook] read database stock pool failed: {e}')

    # 自选通常已足以填满盘口池；此时不再为了会被截断的数据查询数据库。
    primary_codes = _prioritize_orderbook_codes(
        [portfolio_codes, watchlist_codes], limit=max_symbols
    )
    if len(primary_codes) >= max_symbols:
        return primary_codes

    # 3) 旧重点关注板块成分股，仅作为池子补足来源。
    try:
        with open(root / 'focus.json', 'r', encoding='utf-8') as f:
            for sec in json.load(f).get('sectors', []):
                for st in sec.get('stocks', []):
                    c = str(st.get('code') or '').strip()
                    if c:
                        focus_codes.append(c)
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
                    lifecycle_codes.append(c)
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
                    resonance_codes.append(c)
    except Exception as e:
        logger.debug(f'[orderbook] read yuzi quant signal failed: {e}')

    return _prioritize_orderbook_codes(
        [primary_codes, focus_codes, lifecycle_codes, resonance_codes],
        limit=max_symbols,
    )


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


async def scheduled_portfolio_refresh():
    """每10分钟采集妙想模拟盘账户、持仓与委托并写入数据库。"""
    try:
        from api.shared import _refresh_portfolio
        await _refresh_portfolio(force=True)
        logger.info('[scheduler] portfolio cache refreshed')
    except Exception as e:
        logger.warning('[scheduler] portfolio refresh failed: %s', e)


def scheduled_orderbook_snapshot():
    """盘中关键股票池的五档盘口定时采集。"""
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


# ============================================================
# C) 盘后分析
# ============================================================

def scheduled_analyze():
    """盘后分析任务"""
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, skipping analysis')
        return

    if not _has_today_data():
        logger.info('[scheduler] Post-market analysis deferred: daily K-line data is incomplete')
        return

    logger.info(f'[scheduler] Analyzing for {today}')
    try:
        from collectors.tdx_collector import aggregate_stock_sector_flows
        aggregate_stock_sector_flows(today, force=True)
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
    """4 档资金流采集（17:30 盘后）并补齐最近漏采的交易日。"""
    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        return
    try:
        from collectors.moneyflow_detail import fetch_moneyflow_for_date
        from db.models import StockDailyKline, StockMoneyFlowDetail

        # 日K是交易日序列的权威来源。只补最近 10 个日K日中明细覆盖率明显不足的日期，
        # 避免某次服务重启错过 17:30 后，资金维度永久缺一日却仍被页面标成“近 N 日”。
        with get_db_session() as db:
            dates = [row[0] for row in db.query(StockDailyKline.trade_date).distinct().filter(
                StockDailyKline.trade_date <= datetime.now().date(),
            ).order_by(StockDailyKline.trade_date.desc()).limit(10).all()]
            kline_counts = dict(db.query(
                StockDailyKline.trade_date, func.count(StockDailyKline.id),
            ).filter(StockDailyKline.trade_date.in_(dates)).group_by(StockDailyKline.trade_date).all()) if dates else {}
            detail_counts = dict(db.query(
                StockMoneyFlowDetail.trade_date, func.count(StockMoneyFlowDetail.id),
            ).filter(StockMoneyFlowDetail.trade_date.in_(dates)).group_by(StockMoneyFlowDetail.trade_date).all()) if dates else {}

        pending_dates = [
            trade_date for trade_date in dates
            if kline_counts.get(trade_date, 0) and detail_counts.get(trade_date, 0) < kline_counts[trade_date] * 0.95
        ]
        results = {}
        for trade_date in sorted(pending_dates):
            compact_date = trade_date.strftime('%Y%m%d')
            results[compact_date] = fetch_moneyflow_for_date(compact_date)
        logger.info(f'[scheduler] moneyflow_detail 17:30: pending={len(pending_dates)} results={results}')
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


def scheduled_leader_snapshot():
    """盘后从数据库计算龙头结果并写入历史；页面查询不承担持久化。"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today_str):
        return {"status": "SKIPPED", "reason": "not_trading_day"}
    try:
        from analyzers.leader_engine import run_leader_engine
        from services.leader_history_service import save_daily_leader

        result = run_leader_engine(persist=True)
        leader = result.get('leader')
        trade_date = result.get('date')
        if not leader or not trade_date:
            logger.info('[scheduler] Leader snapshot not ready: %s', result.get('message'))
            return {"status": "NOT_READY", "message": result.get('message')}
        with get_db_session() as db:
            save_daily_leader(db, trade_date, leader.get('sector', ''), leader)
        logger.info('[scheduler] Leader snapshot saved: %s %s', trade_date, leader.get('name'))
        return {"status": "READY", "trade_date": trade_date, "leader": leader.get('ts_code')}
    except Exception as exc:
        logger.error('[scheduler] Leader snapshot error: %s', exc, exc_info=True)
        return {"status": "ERROR", "error": str(exc)}


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


def scheduled_medium_term_snapshot():
    """盘后持久化中线纸面候选；只读取已入库日K/资金流，不触发订单。"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today_str):
        return
    try:
        from services.medium_term_strategy import run_medium_term_snapshot
        result = run_medium_term_snapshot()
        logger.info('[scheduler] Medium-term snapshot: %s', result.get('status'))
    except Exception as e:
        logger.error(f'[scheduler] Medium-term snapshot error: {e}')


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
    """收盘后更新市场状态（CHOPPY/TREND/IMPULSE）：自选股 + 仪表盘宇宙。

    个股页会对未自选、但进入策略/共振列表的股票走 kline_fallback。
    因此除自选股外，再从最近一个有分单资金明细的交易日取候选池补算缺失的精确特征，
    让这些股票的个股页自动从「近似」落成「精确」。
    数据源与 update_stock_state 一致：本地 DB 日K + StockMoneyFlowDetail，纯本地无外部请求。
    """
    from analyzers.market_state import update_stock_state

    today = datetime.now().strftime('%Y-%m-%d')
    if not _is_trading_day(today):
        logger.info(f'[scheduler] {today} is not a trading day, skipping market state update')
        return

    processed = set()
    try:
        with get_db_session() as db:
            stocks = db.query(Watchlist).all()
            logger.info(f'[scheduler] Updating market state for {len(stocks)} watchlist stocks...')
            # 当前没有可信的个股所属板块强度快照时保持空值，不能用 0 冒充中性。
            sector_strength = None

            for i, item in enumerate(stocks):
                code = item.stock_code
                processed.add(code)
                try:
                    await update_stock_state(code, sector_strength)
                    if (i + 1) % 10 == 0:
                        logger.info(f'[scheduler] Market state {i+1}/{len(stocks)} done')
                except Exception as e:
                    logger.error(f'[scheduler] Market state error for {code}: {e}')

            logger.info(f'[scheduler] Market state update completed for {len(stocks)} watchlist stocks')

        # ---- 扩展：补算「仪表盘宇宙」精确特征 ----
        from db.models import StockMoneyFlowDetail, StockFeaturesDaily, StockDailyKline
        try:
            with get_db_session() as db:
                latest_flow_day = db.query(func.max(StockMoneyFlowDetail.trade_date)).scalar()
                if not latest_flow_day:
                    logger.info('[scheduler] No stock money flow detail day, skip dashboard backfill')
                    return
                day_str = str(latest_flow_day)[:10].replace('-', '')
                done_codes = {r[0] for r in db.query(StockFeaturesDaily.stock_code).filter(
                    StockFeaturesDaily.trade_date == day_str)}
                # 候选池：全部有日K线的股票（K线是预估特征的必要数据源，覆盖看板/共振/策略/任意个股页）。
                # 已入库/已处理的自选股跳过，避免重复计算。
                candidates = db.query(StockDailyKline.ts_code).distinct().all()

                codes = []
                for (ts_code,) in candidates:
                    c = (ts_code or '').split('.')[0]
                    if c and c not in processed and c not in done_codes:
                        codes.append(c)

                logger.info(f'[scheduler] Backfilling dashboard features for {len(codes)} non-watchlist stocks...')
                for idx, code in enumerate(codes):
                    try:
                        await update_stock_state(code, None)
                        if (idx + 1) % 50 == 0:
                            logger.info(f'[scheduler] dashboard features {idx+1}/{len(codes)} done')
                    except Exception as e:
                        logger.error(f'[scheduler] dashboard feature error for {code}: {e}')
                logger.info(f'[scheduler] dashboard feature backfill completed for {len(codes)} stocks')
        except Exception as e:
            logger.error(f'[scheduler] dashboard universe feature backfill error: {e}')
    except Exception as e:
        logger.error(f'[scheduler] Market state update error: {e}')


def scheduled_index_daily_update():
    """收盘后维护指数日表（index_daily）：常规更新最近一个有效交易日行情。

    从 stock_flow 成分股聚合（纯 DB），供 dashboard 强弱对比等常规读取。
    盘中快照 price_chg 全 0 的采集日会被跳过，只落有真实涨跌的交易日。
    """
    try:
        from api.index_daily import update_index_daily
        n = update_index_daily()
        logger.info(f'[scheduler] index_daily update done, written {n}')
    except Exception as e:
        logger.error(f'[scheduler] index_daily update error: {e}')


# ============================================================
# D) 缓存/研究
# ============================================================

def scheduled_refresh_caches():
    """定时刷新热点缓存（纯DB缓存，避免请求时现场计算）"""
    try:
        from api.concept_sector import _refresh_hot_cache
        from api.heatmap import refresh_heatmap_cache
        from api.sector_rotation import preheat_cache as preheat_a_sector_rotation
        from api.us_sector_rotation import preheat_cache as preheat_us_sector_rotation
        _refresh_hot_cache()
        refresh_heatmap_cache()
        preheat_a_sector_rotation()
        preheat_us_sector_rotation()
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


async def scheduled_usmart_watchlist_sync():
    """定时同步盈立客户端自选股（美股→US_WATCHLIST 池，港股→HK_WATCHLIST 池）

    依赖：本地盈立客户端已启动（CDP 9222）且已登录；
    客户端未启动时静默跳过，不影响其他任务。
    """
    try:
        from services.usmart_watchlist_sync import run_sync
        logger.info('[scheduler] uSmart watchlist sync trigger')
        result = await asyncio.to_thread(run_sync, 'US,HK')
        logger.info('[scheduler] uSmart watchlist sync done: %s', result.get('error') or 'ok')
    except Exception as e:
        logger.error(f'[scheduler] uSmart watchlist sync error: {e}')


async def scheduled_usmart_positions_sync():
    """定时同步盈立客户端真实持仓（只读）

    依赖：本地盈立客户端已启动（CDP 9222）且已登录；
    客户端未启动时静默跳过，不影响其他任务。
    """
    try:
        from services.usmart_positions_sync import run_sync as run_pos_sync
        logger.info('[scheduler] uSmart positions sync trigger')
        result = await asyncio.to_thread(run_pos_sync)
        logger.info('[scheduler] uSmart positions sync done: %s',
                    result.get('error') or f"ok ({result.get('count', 0)} 只)")
        # 同步成功后自动计算持仓技术指标
        if isinstance(result, dict) and result.get('ok') and result.get('count', 0) > 0:
            try:
                from db.session import get_db_session
                from us_quant.repository import USRealPosition
                from api.us_quant import compute_position_indicators
                with get_db_session() as db:
                    rows = db.query(USRealPosition).filter(
                        USRealPosition.status == "ACTIVE"
                    ).all()
                    symbols = [r.symbol for r in rows if r.symbol]
                if symbols:
                    ind_result = await asyncio.to_thread(compute_position_indicators, symbols)
                    logger.info('[scheduler] US position indicators after sync: '
                                f'{ind_result.get("stored", 0)} stored, {ind_result.get("failed", 0)} failed')
            except Exception as ie:
                logger.warning(f'[scheduler] US position indicators after sync failed: {ie}')
    except Exception as e:
        logger.error(f'[scheduler] uSmart positions sync error: {e}')


async def scheduled_tiger_watchlist_sync():
    """定时同步 Tiger Trade 本地自选股（只负责美股 → US_WATCHLIST 池）

    依赖：Tiger Trade App 在本机至少登录过一次（生成 plist 缓存）；
    同步前先尝试从 Container 目录复制最新 plist 到本地副本（绕过 macOS TCC 限制）。
    """
    try:
        # 预同步：从 Tiger Container 刷新本地 plist 副本
        import os, shutil
        src = os.path.expanduser(
            "~/Library/Containers/com.itiger.TigerTrade-Mac/Data/Documents/User/"
        )
        dst = os.path.join(os.path.dirname(__file__), "..", "data", "tiger_trade_watchlist.plist")
        if os.path.isdir(src):
            for d in sorted(os.listdir(src), reverse=True):
                dd = os.path.join(src, d)
                plist = os.path.join(dd, f"{d}.plist")
                if os.path.isfile(plist) and d.isdigit() and len(d) > 10:
                    try:
                        shutil.copy2(plist, dst)
                        logger.debug('[scheduler] Tiger plist refreshed from Container')
                    except (PermissionError, OSError):
                        pass  # TCC 阻止则用现有副本
                    break

        from services.tiger_watchlist_sync import run_sync
        logger.info('[scheduler] Tiger watchlist sync trigger')
        result = await asyncio.to_thread(run_sync, 'US')
        logger.info('[scheduler] Tiger watchlist sync done: %s | US=%s',
                    result.get('error') or 'ok', result.get('US', {}).get('count', 0))
    except Exception as e:
        logger.error(f'[scheduler] Tiger watchlist sync error: {e}')


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
            if not config or not config.enabled or config.paused:
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
        with open(log, 'a') as log_file:
            subprocess.Popen(
                ['nohup', '/usr/bin/python3', script, '--layer', 'all'],
                stdout=log_file, stderr=subprocess.STDOUT,
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
    target_date = _latest_a_share_trade_date(datetime.now())
    if not target_date:
        logger.warning('[scheduler] 外部数据第一波：无法确认最近交易日，跳过')
        return
    logger.info(f'[scheduler] 外部数据第一波(波1/16:00) {target_date}...')
    try:
        results = _sync_external_with_retry(target_date, ['adj_factor', 'suspend'], max_retries=1)
        logger.info(f'[scheduler] 外部数据第一波完成: {results}')
    except Exception as e:
        logger.error(f'[scheduler] 外部数据第一波失败: {e}', exc_info=True)


def scheduled_external_wave2():
    """第二波(次日09:30)：margin_data + north_money_flow + hsgt_top10"""
    target_date = _latest_a_share_trade_date(datetime.now() - timedelta(days=1))
    if not target_date:
        logger.warning('[scheduler] 外部数据第二波：无法确认最近交易日，跳过')
        return
    logger.info(f'[scheduler] 外部数据第二波(波2/09:30) {target_date}...')
    try:
        results = _sync_external_with_retry(target_date, ['margin', 'north', 'hsgt'], max_retries=2)
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


# ============================================================
# G) 美股量化扫描
# ============================================================

def scheduled_us_quant_collect(force_window: bool = False):
    """美股日K线和因子采集（北京时间 4:00-7:00 幂等重试）

    数据流：新浪 → 东财 push2 → AkShare → Nasdaq → Yahoo → 数据库 → 因子库。
    """
    now = datetime.now()
    t = now.hour * 100 + now.minute
    # 夏令时/冬令时收盘对应北京时间不同，计划任务在 4-6 点重试；
    # 手动或启动补采可绕过本地时间窗口。
    if not force_window and (t < 400 or t > 700):
        return {"status": "outside_window"}

    from market_quant.calendar import latest_completed_session
    target_session = latest_completed_session("US")

    logger.info(
        '[scheduler] US quant data collection triggered at %s for session %s',
        now.strftime("%H:%M"), target_session,
    )
    try:
        from us_quant.collector import collect_all, _get_collector_pool
        from us_quant.repository import USStockDaily
        result = collect_all(target_date=target_session)
        pool = sorted(set(_get_collector_pool()))
        with get_db_session() as db:
            covered_symbols = {
                row[0] for row in db.query(USStockDaily.symbol).filter(
                    USStockDaily.symbol.in_(pool),
                    USStockDaily.trade_date == target_session,
                    USStockDaily.close.isnot(None),
                    or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
                ).distinct().all()
            }
        missing_symbols = sorted(set(pool) - covered_symbols)
        result["coverage"] = {
            "target": target_session.isoformat(),
            "covered": len(covered_symbols),
            "total": len(pool),
            "missing": missing_symbols,
        }
        if missing_symbols:
            record_alert(
                level="warning",
                category="collection_gap",
                message=(
                    f"美股日K自动采集后仍缺 {len(missing_symbols)}/{len(pool)} 只，"
                    f"目标交易日 {target_session.isoformat()}"
                ),
                trade_date=target_session,
                details={"market": "US", **result["coverage"]},
                cooldown_seconds=3600,
            )
        factors = result.get("factors") or {}
        logger.info(
            '[scheduler] US quant collect done: %s inserted, %s skipped, %s total; '
            'factors=%s symbols/%s rows',
            result.get("inserted", 0), result.get("skipped", 0), result.get("total", 0),
            factors.get("symbols", 0), factors.get("stored_rows", 0),
        )
        return {"status": "completed", **result}
    except Exception as e:
        logger.error(f'[scheduler] US quant collect error: {e}', exc_info=True)
        return {"status": "failed", "error": str(e)}


def scheduled_us_quant_catchup():
    """北京时间盘后检查美股数据库新鲜度，补偿启动时错过的凌晨采集窗口。"""
    from market_quant.calendar import latest_completed_session
    from us_quant.collector import _get_collector_pool
    from us_quant.repository import USStockDaily

    target_session = latest_completed_session("US")
    pool = _get_collector_pool()
    with get_db_session() as db:
        real_source = or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic")
        latest_bar = db.query(func.max(USStockDaily.trade_date)).filter(real_source).scalar()
        covered = db.query(func.count(func.distinct(USStockDaily.symbol))).filter(
            USStockDaily.symbol.in_(pool),
            USStockDaily.trade_date == target_session,
            USStockDaily.close.isnot(None),
            real_source,
        ).scalar() or 0
    missing = max(0, len(pool) - covered)
    if pool and missing == 0:
        logger.info(
            '[scheduler] US quant catchup not needed: coverage=%s/%s target=%s',
            covered, len(pool), target_session,
        )
        return {
            "status": "current", "latest": latest_bar.isoformat() if latest_bar else None,
            "target": target_session.isoformat(), "covered": covered, "total": len(pool), "missing": 0,
        }

    logger.info(
        '[scheduler] US quant catchup required: coverage=%s/%s missing=%s target=%s',
        covered, len(pool), missing, target_session,
    )
    return scheduled_us_quant_collect(force_window=True)


def scheduled_us_bs_snapshot(force_window: bool = False):
    """美股收盘后补算并落库强 B/S 策略因子。"""
    now = datetime.now()
    t = now.hour * 100 + now.minute
    if not force_window and (t < 500 or t > 830):
        return {"status": "outside_window"}
    try:
        from market_quant.calendar import latest_completed_session
        from us_quant.factor_storage import store_bs_strategy_factor_from_db
        target = latest_completed_session("US")
        result = store_bs_strategy_factor_from_db(target_date=target)
        logger.info('[scheduler] US B/S snapshot done: %s', result)
        return {"status": "completed", **result}
    except Exception as e:
        logger.error('[scheduler] US B/S snapshot error: %s', e, exc_info=True)
        return {"status": "failed", "error": str(e)}


def scheduled_us_quant_scan(force_window: bool = False):
    """美股盘后策略扫描（北京时间 5:00-8:00，美股收盘后约 4:00 ET）
    
    扫描预设美股池，运行 3 套策略，结果落库到 USStrategyScore 表，
    高分自动生成信号到 USSignal 表。
    """
    now = datetime.now()
    t = now.hour * 100 + now.minute
    
    # 北京时间 5:00-8:00 执行（美股收盘后）
    if not force_window and (t < 500 or t > 800):
        return {"status": "outside_window"}

    from market_quant.calendar import latest_completed_session
    target_session = latest_completed_session("US")
    
    logger.info(f'[scheduler] US quant scan triggered at {now.strftime("%H:%M")}')
    try:
        from api.us_quant import run_us_quant_scan
        result = run_us_quant_scan(target_session.isoformat())
        logger.info(f'[scheduler] US quant scan done: {result.get("scored", 0)} scored, '
                    f'{result.get("count", 0)} candidates')
        return result
    except Exception as e:
        logger.error(f'[scheduler] US quant scan error: {e}', exc_info=True)
        return {"status": "failed", "error": str(e)}


def scheduled_us_strategy_track():
    """盘后将美股策略命中入池，并补写 30 日跟踪日线。"""
    try:
        from api.us_strategy_track import build_pool, daily_update
        build_pool(None, "daily_decision")
        daily_update()
    except Exception as exc:
        logger.exception('[scheduler] US strategy tracking failed: %s', exc)


def _run_us_regime_snapshot_core():
    """美股市场环境快照核心逻辑（无时间检查，供定时任务和启动补采共用）。"""
    from api.us_quant import build_regime_snapshot_from_db
    from db.connection import SessionLocal
    from market_quant.calendar import latest_completed_session
    from us_quant.repository import USMarketRegime

    target_session = latest_completed_session("US")
    data = build_regime_snapshot_from_db(target_session)

    if not data or data.get('status') != 'READY' or not data.get('regime'):
        logger.warning('[scheduler] US regime snapshot not ready for %s: %s', target_session, data)
        return False

    with SessionLocal() as db:
        row = db.query(USMarketRegime).filter(
            USMarketRegime.trade_date == target_session
        ).first() or USMarketRegime(trade_date=target_session, regime=data['regime'])
        row.regime = data['regime']
        row.score = data.get('score')
        row.label = data.get('label')
        row.allow_new_positions = data.get('allow_new_positions')
        row.reason = data.get('reason')
        row.breakout_mult = data.get('multipliers', {}).get('breakout')
        row.pullback_mult = data.get('multipliers', {}).get('pullback')
        row.earnings_gap_mult = data.get('multipliers', {}).get('earnings_gap')
        row.spy_price = data.get('indices', {}).get('SPY', {}).get('price')
        row.qqq_price = data.get('indices', {}).get('QQQ', {}).get('price')
        row.vix = data.get('vix')
        row.breadth = data.get('breadth', {}).get('advancers_pct')
        if row.id is None:
            db.add(row)
        db.commit()
        logger.info('[scheduler] US regime snapshot saved: date=%s regime=%s score=%s',
                    target_session, data['regime'], data.get('score'))
        return True


def scheduled_us_regime_snapshot():
    """美股市场环境快照（北京时间 05:15，美股收盘后）

    从已入库的同日 ETF/VIX 日线计算 → 落库 USMarketRegime 表，
    之后前端 /api/us-quant/regime 仅读数据库。
    """
    now = datetime.now()
    if now.weekday() >= 5:
        return
    t = now.hour * 100 + now.minute
    if t < 510 or t > 545:
        return
    logger.info(f'[scheduler] US regime snapshot triggered at {now.strftime("%H:%M")}')
    try:
        _run_us_regime_snapshot_core()
    except Exception as e:
        logger.error(f'[scheduler] US regime snapshot error: {e}', exc_info=True)


def _run_us_sector_snapshot_core():
    """美股行业轮动快照核心逻辑（无时间检查，供定时任务和启动补采共用）。"""
    from api.us_quant import build_sector_snapshot_from_db
    from db.connection import SessionLocal
    from market_quant.calendar import latest_completed_session
    from us_quant.repository import USSectorScore

    target_session = latest_completed_session("US")
    data = build_sector_snapshot_from_db(target_session)

    if not data or data.get('status') != 'READY' or not data.get('sectors'):
        logger.warning('[scheduler] US sector snapshot not ready for %s: %s', target_session, data)
        return False

    with SessionLocal() as db:
        db.query(USSectorScore).filter(
            USSectorScore.trade_date == target_session
        ).delete()
        for s in data['sectors']:
            row = USSectorScore(
                trade_date=target_session,
                etf_symbol=s.get('etf_symbol', ''),
                etf_name=s.get('etf_name'),
                industry=s.get('industry'),
                total_score=s.get('total_score'),
                ret_5d=s.get('ret_5d'),
                ret_20d=s.get('ret_20d'),
                ret_60d=s.get('ret_60d'),
                rel_strength_20d=s.get('rel_strength_20d'),
                rel_strength_60d=s.get('rel_strength_60d'),
                ma_trend=s.get('ma_trend'),
                volume_activity=s.get('volume_activity'),
                rank=s.get('rank'),
                grade=s.get('grade'),
            )
            db.add(row)
        db.commit()
        logger.info('[scheduler] US sector snapshot saved: date=%s sectors=%s',
                    target_session, len(data['sectors']))
        return True


def scheduled_us_sector_snapshot():
    """美股行业轮动快照（北京时间 05:20，regime 之后）"""
    now = datetime.now()
    if now.weekday() >= 5:
        return
    t = now.hour * 100 + now.minute
    if t < 515 or t > 550:
        return
    logger.info(f'[scheduler] US sector snapshot triggered at {now.strftime("%H:%M")}')
    try:
        _run_us_sector_snapshot_core()
    except Exception as e:
        logger.error(f'[scheduler] US sector snapshot error: {e}', exc_info=True)


def _run_us_position_indicators_core():
    """美股持仓技术指标核心逻辑（无时间检查，供定时任务和启动补采共用）。"""
    from db.session import get_db_session
    from us_quant.repository import USRealPosition
    from api.us_quant import compute_position_indicators

    with get_db_session() as db:
        rows = db.query(USRealPosition).filter(
            USRealPosition.status == "ACTIVE"
        ).all()
        symbols = [r.symbol for r in rows if r.symbol]

    if not symbols:
        logger.info('[scheduler] US position indicators: no active positions')
        return False

    result = compute_position_indicators(symbols)
    logger.info(f'[scheduler] US position indicators done: '
                 f'{result.get("stored", 0)} stored, {result.get("failed", 0)} failed')
    return result.get("stored", 0) > 0


def scheduled_us_position_indicators():
    """美股持仓技术指标快照（北京时间 05:05，数据采集后 + regime/sector 前）

    读取 us_real_positions 表中活跃持仓 → 计算 RSI/MACD/KDJ/EMA 等指标 → 落库 USStrategyScore
    之后前端持仓 tab 的 scanner?symbols=xxx 直接读 DB，毫秒级返回，不再实时拉 K线。
    """
    now = datetime.now()
    if now.weekday() >= 5:
        return
    t = now.hour * 100 + now.minute
    if t < 450 or t > 520:
        return
    logger.info(f'[scheduler] US position indicators triggered at {now.strftime("%H:%M")}')
    try:
        _run_us_position_indicators_core()
    except Exception as e:
        logger.error(f'[scheduler] US position indicators error: {e}', exc_info=True)


def _startup_us_backfill():
    """启动时检查并补齐最近已完成美股交易日的数据和因子。

    核心日线、旧因子和统一因子不受北京时间周末限制；展示用的市场环境、
    行业和持仓快照仍只在工作日白天补采。
    """
    import time
    time.sleep(20)  # 等后端完全启动

    now = datetime.now()
    from market_quant.calendar import latest_completed_session
    target_session = latest_completed_session("US")

    # 启动时的大批历史与因子补齐会争抢 CPU、数据库和网络；在 A 股收盘前
    # 让页面和实时行情优先，统一链路会在既定的美股盘后窗口继续补齐。
    if _is_before_a_share_postmarket_ready(now):
        logger.info(
            '[scheduler] US startup backfill deferred until A-share post-market data is ready '
            '(target=%s)', target_session,
        )
        return

    # 日线、旧因子表和统一生产快照按纽约最近已完成交易日补齐；即使
    # 北京时间是周末也不能跳过，因为周六凌晨对应纽约周五收盘。
    try:
        from db.connection import SessionLocal
        from us_quant.repository import USFactorScore, USStockDaily
        with SessionLocal() as db:
            latest_bar = db.query(func.max(USStockDaily.trade_date)).scalar()
            latest_factor = db.query(func.max(USFactorScore.trade_date)).scalar()
        if latest_bar is None or latest_bar < target_session or latest_factor is None or latest_factor < target_session:
            logger.info(
                '[scheduler] US backfill: daily/factors behind target %s '
                '(bar=%s factor=%s), collecting...',
                target_session, latest_bar, latest_factor,
            )
            scheduled_us_quant_collect(force_window=True)
        else:
            logger.info(
                '[scheduler] US backfill: daily/factors current for %s',
                target_session,
            )
    except Exception as e:
        logger.warning(f'[scheduler] US backfill daily/factor error: {e}', exc_info=True)

    # 启动只补一批，避免服务重启后与网页请求争抢 CPU、数据库和网络；
    # 失败标的会在随后 5:00-8:30 的计划任务继续补齐。
    try:
        max_batches = max(1, int(os.getenv('MARKET_STARTUP_CATCHUP_BATCHES', '1')))
        previous_valid_count = None
        for _attempt in range(max_batches):
            result = scheduled_market_pipeline('US', target_session)
            snapshot = (result or {}).get('snapshot') or {}
            valid_count = int(snapshot.get('valid_count', 0) or 0)
            pool_total = int(snapshot.get('pool_total', 0) or 0)
            if (
                snapshot.get('trade_date') == target_session.isoformat()
                and pool_total > 0
                and valid_count >= pool_total
            ):
                break
            if previous_valid_count is not None and valid_count <= previous_valid_count:
                logger.info(
                    '[scheduler] US unified factor catchup stopped: coverage did not improve '
                    '(%s/%s)', valid_count, pool_total,
                )
                break
            previous_valid_count = valid_count
        scheduled_us_quant_scan(force_window=True)
    except Exception as e:
        logger.warning(f'[scheduler] US unified factor catchup error: {e}', exc_info=True)

    # 以下旧 regime/sector/持仓快照仍按北京时间白天执行；核心日线和因子
    # 已在上面独立补齐，不再受这个展示层窗口影响。
    if now.weekday() >= 5:
        logger.info('[scheduler] US display snapshot backfill: weekend, skipping')
        return
    hour = now.hour
    if hour < 6 or hour > 23:
        logger.info(f'[scheduler] US display snapshot backfill: hour={hour}, skipping')
        return

    logger.info(f'[scheduler] US startup backfill check at {now.strftime("%H:%M")}')

    # 1. 检查 regime
    try:
        from us_quant.repository import USMarketRegime
        with SessionLocal() as db:
            has_regime = db.query(USMarketRegime).filter(
                USMarketRegime.trade_date == target_session
            ).first()
        if not has_regime:
            logger.info('[scheduler] US backfill: regime missing, computing...')
            _run_us_regime_snapshot_core()
        else:
            logger.info('[scheduler] US backfill: regime already exists')
    except Exception as e:
        logger.warning(f'[scheduler] US backfill regime error: {e}')

    # 2. 检查 sectors
    try:
        from us_quant.repository import USSectorScore
        with SessionLocal() as db:
            has_sectors = db.query(USSectorScore).filter(
                USSectorScore.trade_date == target_session
            ).count()
        if not has_sectors:
            logger.info('[scheduler] US backfill: sectors missing, computing...')
            _run_us_sector_snapshot_core()
        else:
            logger.info(f'[scheduler] US backfill: sectors already exist ({has_sectors} rows)')
    except Exception as e:
        logger.warning(f'[scheduler] US backfill sectors error: {e}')

    # 3. 检查 position indicators
    try:
        from us_quant.repository import USStrategyScore, USRealPosition
        with SessionLocal() as db:
            has_positions = db.query(USRealPosition).filter(
                USRealPosition.status == "ACTIVE"
            ).count()
            has_indicators = db.query(USStrategyScore).filter(
                USStrategyScore.trade_date == target_session
            ).count()
        if has_positions > 0 and has_indicators == 0:
            logger.info('[scheduler] US backfill: position indicators missing, computing...')
            _run_us_position_indicators_core()
        else:
            logger.info(f'[scheduler] US backfill: position indicators exist ({has_indicators} rows, {has_positions} positions)')
    except Exception as e:
        logger.warning(f'[scheduler] US backfill position indicators error: {e}')

    logger.info('[scheduler] US startup backfill done')


# ============================================================
# I) 港美股统一因子生产链路
# ============================================================

def _market_backfill_targets(
    market: str,
    members: list[str],
    limit: int,
    target_date=None,
) -> list[str]:
    """优先补采没有历史或历史最短的标的，形成可恢复的队列。"""
    from market_quant.history import history_status

    status = history_status(market, members)
    items = status.get('items', {})
    return sorted(
        members,
        key=lambda symbol: (
            (items.get(symbol, {}).get('latest') or '') >= (
                target_date.isoformat() if target_date else '9999-12-31'
            ),
            int(items.get(symbol, {}).get('rows', 0)),
            items.get(symbol, {}).get('latest') or '',
            symbol,
        ),
    )[:max(1, limit)]


def scheduled_market_pipeline(market: str, target_session=None):
    """盘后运行港美股统一链路：股票池→历史缺口→因子→共振快照。

    每次只补一个可恢复批次，避免一次调度阻塞整个 9000 服务；页面只读
    ``market_scan_runs`` 中的最近成功快照。
    """
    from market_quant.calendar import latest_completed_session
    from market_quant.history import backfill_market
    from market_quant.outcomes import refresh_market_signal_outcomes
    from market_quant.service import run_market_snapshot
    from market_quant.universe import get_members, sync_market_universe, universe_code

    market = market.upper()
    if market not in ('HK', 'US'):
        return {"status": "unsupported_market", "market": market}
    session_day = target_session or latest_completed_session(market)
    batch_size = max(1, int(os.getenv('MARKET_BACKFILL_BATCH', '50')))
    code = universe_code(market, 'CORE')
    try:
        sync_market_universe(market, refresh_remote=False)
        members = get_members(market, code)
        if not members:
            logger.warning('[market-quant] %s core universe is empty', market)
            return
        targets = _market_backfill_targets(market, members, batch_size, session_day)
        backfill = backfill_market(
            market, targets, days=1260, max_workers=3, target_date=session_day,
        )
        snapshot = run_market_snapshot(market, 'CORE', display_limit=100, persist=True)
        outcomes = (
            refresh_market_signal_outcomes(market, 'CORE', days=60)
            if snapshot.get('status') == 'SUCCESS' else None
        )
        logger.info(
            '[market-quant] %s pipeline done: pool=%s backfill=%s/%s failed=%s '
            'date=%s valid=%s candidates=%s outcomes=%s',
            market, len(members), backfill.get('updated', 0), len(targets),
            backfill.get('failed', 0), snapshot.get('trade_date'),
            snapshot.get('valid_count', 0), snapshot.get('candidate_count', 0),
            (outcomes or {}).get('upserted', 0),
        )
        return {
            "status": snapshot.get("status"),
            "target_session": session_day.isoformat(),
            "targets": len(targets),
            "backfill": backfill,
            "snapshot": snapshot,
            "outcomes": outcomes,
        }
    except Exception as exc:
        logger.error('[market-quant] %s pipeline failed: %s', market, exc, exc_info=True)
        return {"status": "FAILED", "market": market, "error": str(exc)}


def scheduled_market_research(market: str):
    """对统一快照中的少量候选执行市场感知妙想研究。"""
    from market_quant.calendar import is_session, now_in_market_timezone

    market = market.upper()
    session_day = now_in_market_timezone(market).date()
    if market not in ('HK', 'US') or not is_session(market, session_day):
        return
    try:
        from market_quant.research import run_market_research_sync
        result = run_market_research_sync(market, 'CORE', limit=50)
        logger.info('[market-quant] %s Miaoxiang research done: %s', market, result)
    except Exception as exc:
        logger.error('[market-quant] %s Miaoxiang research failed: %s', market, exc, exc_info=True)


# ============================================================
# J) 平安证券数据采集
# ============================================================

def scheduled_pingan_collect():
    """平安证券数据采集（盘中每30分钟采集自选股行情+资金流向）

    依赖：pa-market-query skill 已安装，PINGAN_SKILL_APIKEY 已配置。
    采集内容：自选股实时行情、主力资金流向。
    """
    try:
        from collectors.pingan_collector import pingan_scheduled_collect
        pingan_scheduled_collect()
    except Exception as e:
        logger.error('[scheduler] pingan collect error: %s', e, exc_info=True)


# ============================================================
# H) 港股盘后快照
# ============================================================

def scheduled_hk_market_scan():
    """港股收盘后采集技术结构并保存快照（北京时间 16:30-18:00）。"""
    now = datetime.now()
    if now.weekday() >= 5:
        return
    t = now.hour * 100 + now.minute
    if t < 1630 or t > 1800:
        return

    logger.info(f'[scheduler] HK market scan triggered at {now.strftime("%H:%M")}')
    try:
        from api.hk_snapshot import run_hk_postmarket_scan
        result = run_hk_postmarket_scan(str(now.date()))
        meta = result.get('scan_run') or {}
        logger.info('[scheduler] HK market scan done: %s valid, %s candidates',
                    meta.get('valid_count', 0), meta.get('candidate_count', 0))
    except Exception as e:
        logger.error(f'[scheduler] HK market scan error: {e}', exc_info=True)

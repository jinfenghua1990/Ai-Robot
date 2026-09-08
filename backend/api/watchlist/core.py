"""watchlist 核心 API
- GET /api/watchlist  列出（含行情/K线/BS信号）
- POST /api/watchlist/add
- DELETE /api/watchlist/{code}
- PATCH /api/watchlist/{code}  备注
- PUT /api/watchlist/{code}/note
- PUT /api/watchlist/{code}/quality
- POST /api/watchlist/{code}/pin
- POST /api/watchlist/{code}/move-group
- POST /api/watchlist/sync-quality
"""
import time
import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func, text

from db.session import get_db_session, run_db
from db.models import Watchlist
from analyzers.strategy_engine import _find_sector_for_stock, _get_sector_trend
from analyzers.buy_power import is_junk_stock, calc_buy_power_for_signal
from analyzers.market_state import get_latest_state, compute_quality_from_features
from analyzers.stock_scores import calc_sentiment, calc_risk, calc_momentum, calc_main_force, calc_technical, calc_sector_resonance
from analyzers.holding_state import evaluate_holding_state

from ._shared import (
    _watchlist_cache, WATCHLIST_CACHE_TTL,
    get_quote, fetch_kline_cached, reset_watchlist_cache,
    batch_get_quotes, batch_fetch_kline_cached, normalize_stock_code, normalize_ts_code,
)

_watchlist_build_task: asyncio.Task | None = None


def _batch_moneyflow_map(db, stock_codes: list) -> dict:
    """批量查所有自选股的最新一日 4 档资金流 + 1/2/3/4/5 日累计 + 连续天数

    用 3 个独立查询并行执行（ThreadPoolExecutor），将首次耗时 6-9s 降到 2-3s。
    每个线程使用独立 Session（SQLAlchemy Session 非线程安全）。
    返回 {ts_code: {main_net(万), super_large(万), large(万), small(万), tiny(万),
                    inflow_1d/2d/3d/4d/5d(元), flow_continuity, available}}
    """
    from db.models import StockMoneyFlowDetail, StockFeaturesDaily
    from db.connection import SessionLocal
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not stock_codes:
        return {}
    valid_codes = list(dict.fromkeys(
        normalize_stock_code(code) for code in stock_codes
        if normalize_stock_code(code)
    ))
    if not valid_codes:
        return {}
    ts_codes = [normalize_ts_code(code) for code in valid_codes]

    out = {ts: {'available': False, 'status': 'MISSING', 'source': 'database',
                'main_net': None, 'super_large': None, 'large': None,
                'small': None, 'tiny': None, 'turnover_rate': None,
                'main_buy': None, 'main_sell': None, 'retail_buy': None, 'retail_sell': None,
                'super_large_pct': None, 'large_pct': None, 'small_pct': None, 'tiny_pct': None,
                'inflow_1d': None, 'inflow_2d': None, 'inflow_3d': None, 'inflow_4d': None, 'inflow_5d': None,
                'inflow_6d': None, 'inflow_7d': None, 'inflow_8d': None, 'inflow_9d': None, 'inflow_10d': None,
                'flow_continuity': None}
           for ts in ts_codes}

    # === Q1: 取最新交易日期（必须先获取，Q2 依赖）===
    latest = db.query(StockMoneyFlowDetail.trade_date)\
        .order_by(StockMoneyFlowDetail.trade_date.desc()).first()
    td = latest[0] if latest else None

    def _q2_latest_details():
        """Q2: 最新一日 StockMoneyFlowDetail 的 4 档资金流"""
        if not td:
            return []
        thread_db = SessionLocal()
        try:
            return thread_db.query(StockMoneyFlowDetail).filter(
                StockMoneyFlowDetail.trade_date == td,
                StockMoneyFlowDetail.ts_code.in_(ts_codes),
            ).all()
        except Exception as e:
            logger.warning(f'[moneyflow] Q2 latest details failed: {e}')
            return []
        finally:
            thread_db.close()

    def _q3_features_daily():
        """Q3: StockFeaturesDaily 最新一日的 1/3/5 日累计 + 连续天数"""
        thread_db = SessionLocal()
        try:
            latest_sub = thread_db.query(
                StockFeaturesDaily.stock_code,
                func.max(StockFeaturesDaily.trade_date).label('max_date')
            ).filter(
                StockFeaturesDaily.stock_code.in_(valid_codes)
            ).group_by(StockFeaturesDaily.stock_code).subquery()

            return thread_db.query(StockFeaturesDaily).join(
                latest_sub,
                (StockFeaturesDaily.stock_code == latest_sub.c.stock_code) &
                (StockFeaturesDaily.trade_date == latest_sub.c.max_date)
            ).all()
        except Exception as e:
            logger.warning(f'[moneyflow] Q3 features daily failed: {e}')
            return []
        finally:
            thread_db.close()

    def _q4_history_10d():
        """Q4: 最近 10 个交易日的 main_net 用于累计 1d..10d"""
        thread_db = SessionLocal()
        try:
            recent_dates = thread_db.query(StockMoneyFlowDetail.trade_date)\
                .distinct().order_by(StockMoneyFlowDetail.trade_date.desc()).limit(10).all()
            if not recent_dates:
                return [], []
            date_objs = [d[0] for d in recent_dates]
            rows = thread_db.query(
                StockMoneyFlowDetail.ts_code, StockMoneyFlowDetail.trade_date,
                StockMoneyFlowDetail.main_net
            ).filter(
                StockMoneyFlowDetail.trade_date.in_(date_objs),
                StockMoneyFlowDetail.ts_code.in_(ts_codes),
            ).all()
            return rows, date_objs
        except Exception as e:
            logger.warning(f'[moneyflow] Q4 10d history failed: {e}')
            return [], []
        finally:
            thread_db.close()

    # === 并行执行 3 个独立查询 ===
    with ThreadPoolExecutor(max_workers=3) as executor:
        f_details = executor.submit(_q2_latest_details)
        f_features = executor.submit(_q3_features_daily)
        f_history = executor.submit(_q4_history_10d)

        details_rows = f_details.result()
        feat_rows = f_features.result()
        hist_rows, _ = f_history.result()

    # === 合并 Q2: 最新一日 4 档资金流 ===
    if td:
        for r in details_rows:
            def y2w(v):
                return round(float(v) / 10000, 2) if v is not None else None
            detail_values = [
                r.main_net, r.super_large_net, r.large_net,
                r.small_net, r.tiny_net,
            ]
            valid_detail_count = sum(value is not None for value in detail_values)
            out[r.ts_code].update({
                'available': valid_detail_count > 0,
                'status': (
                    'READY' if valid_detail_count == len(detail_values)
                    else 'PARTIAL' if valid_detail_count > 0
                    else 'MISSING'
                ),
                'trade_date': td.strftime('%Y%m%d'),
                'main_net': y2w(r.main_net),
                'super_large': y2w(r.super_large_net),
                'large': y2w(r.large_net),
                'small': y2w(r.small_net),
                'tiny': y2w(r.tiny_net),
                'main_buy': y2w(r.main_buy),
                'main_sell': y2w(r.main_sell),
                'retail_buy': y2w(r.retail_buy),
                'retail_sell': y2w(r.retail_sell),
                'super_large_pct': float(r.super_large_pct) if r.super_large_pct is not None else None,
                'large_pct': float(r.large_pct) if r.large_pct is not None else None,
                'small_pct': float(r.small_pct) if r.small_pct is not None else None,
                'tiny_pct': float(r.tiny_pct) if r.tiny_pct is not None else None,
                'turnover_rate': float(r.turnover_rate) if r.turnover_rate is not None else None,
            })

    # === 合并 Q3: features daily 1/3/5 日累计 ===
    for r in feat_rows:
        ts = normalize_ts_code(r.stock_code)
        if ts in out:
            out[ts].update({
                'inflow_1d': float(r.main_net_inflow_1d) if r.main_net_inflow_1d is not None else None,
                'inflow_3d': float(r.main_net_inflow_3d) if r.main_net_inflow_3d is not None else None,
                'inflow_5d': float(r.main_net_inflow_5d) if r.main_net_inflow_5d is not None else None,
                'flow_continuity': int(r.flow_continuity) if r.flow_continuity is not None else None,
            })

    # === 合并 Q4: 10 日累计 ===
    from collections import defaultdict
    hist_by_ts = defaultdict(list)
    for r in hist_rows:
        hist_by_ts[r.ts_code].append((
            r.trade_date,
            float(r.main_net) / 10000 if r.main_net is not None else None,
        ))
    for ts, items in hist_by_ts.items():
        items_sorted = sorted(items, key=lambda x: x[0], reverse=True)
        cum = 0.0
        complete = True
        for i, (_, v) in enumerate(items_sorted[:10]):
            day_key = f'inflow_{i+1}d'
            if day_key in out[ts]:
                if v is None:
                    complete = False
                if complete:
                    cum += v
                    out[ts][day_key] = round(cum, 2)
                else:
                    out[ts][day_key] = None
        if len(items_sorted) < 10:
            for i in range(len(items_sorted), 10):
                day_key = f'inflow_{i+1}d'
                if day_key in out[ts]:
                    out[ts][day_key] = None

    return out


# ========================= 6 大命中标签批量计算 =========================

def _hit_yuzi(db, ts_codes: list) -> set:
    """🎯 游资命中：YuziQuantSignal 最新一日 resonance_count >= 2 且 total_net_buy > 0"""
    from db.models import YuziQuantSignal
    if not ts_codes:
        return set()
    latest_date = db.query(func.max(YuziQuantSignal.trade_date)).scalar()
    if not latest_date:
        return set()
    rows = db.query(YuziQuantSignal.ts_code, YuziQuantSignal.resonance_count, YuziQuantSignal.total_net_buy, YuziQuantSignal.boss_list).filter(
        YuziQuantSignal.trade_date == latest_date,
        YuziQuantSignal.ts_code.in_(ts_codes),
        YuziQuantSignal.resonance_count >= 2,
        YuziQuantSignal.total_net_buy > 0,
    ).all()
    return {r.ts_code for r in rows}


def _hit_strategy(db, valid_codes: list) -> dict:
    """🤖 策略命中：BSDailyScan 最新一日 signals_json 含本股
    返回 {code: strategy_name}，让前端直接显示具体策略名（如 BS-全市场），
    替代原来的 'strategy' 通用布尔标签，避免与 strategyTags（顶部 BS-XXX 标签）重复。
    """
    from db.models import BSDailyScan
    import json as _json
    if not valid_codes:
        return {}
    latest_date = db.query(func.max(BSDailyScan.trade_date)).scalar()
    if not latest_date:
        return {}
    today_rows = db.query(BSDailyScan).filter(
        BSDailyScan.trade_date == latest_date
    ).all()
    hit_map = {}
    for r in today_rows:
        try:
            sigs = _json.loads(r.signals_json or '[]')
        except Exception:
            sigs = []
        for s in sigs:
            raw = s.get('secCode') or s.get('code') or ''
            code = raw.split('.')[0] if raw else ''
            if code in valid_codes:
                hit_map[code] = r.strategy_name  # 后写覆盖先写，保留最新策略名
    return hit_map


def _hit_trend(db, valid_codes: list) -> set:
    """📈 趋势命中：StockFeaturesDaily 最新一日 ma5 > ma20 > ma60 或 high_break_20d > 0"""
    from db.models import StockFeaturesDaily
    if not valid_codes:
        return set()
    latest_sub = db.query(
        StockFeaturesDaily.stock_code,
        func.max(StockFeaturesDaily.trade_date).label('max_date')
    ).filter(StockFeaturesDaily.stock_code.in_(valid_codes))\
     .group_by(StockFeaturesDaily.stock_code).subquery()
    rows = db.query(StockFeaturesDaily).join(
        latest_sub,
        (StockFeaturesDaily.stock_code == latest_sub.c.stock_code) &
        (StockFeaturesDaily.trade_date == latest_sub.c.max_date)
    ).all()
    hit = set()
    for r in rows:
        ma5, ma20, ma60 = r.ma5 or 0, r.ma20 or 0, r.ma60 or 0
        if ma5 > ma20 > ma60 and ma5 > 0:
            hit.add(r.stock_code)
        elif (r.high_break_20d or 0) > 0:
            hit.add(r.stock_code)
    return hit


def _hit_capital(db, ts_codes: list) -> set:
    """💰 资金命中：StockMoneyFlowDetail 今日 main_net 创 30 天新高且 > 0"""
    from db.models import StockMoneyFlowDetail
    from datetime import timedelta
    if not ts_codes:
        return set()
    latest = db.query(func.max(StockMoneyFlowDetail.trade_date)).scalar()
    if not latest:
        return set()
    cutoff = latest - timedelta(days=30)
    # 子查询：每只股 30 天内 max(main_net)
    max_sub = db.query(
        StockMoneyFlowDetail.ts_code,
        func.max(StockMoneyFlowDetail.main_net).label('max_net')
    ).filter(
        StockMoneyFlowDetail.trade_date >= cutoff,
        StockMoneyFlowDetail.trade_date <= latest,
        StockMoneyFlowDetail.ts_code.in_(ts_codes),
    ).group_by(StockMoneyFlowDetail.ts_code).subquery()
    # 今日 main_net == 30 天 max 且 > 0
    today_rows = db.query(StockMoneyFlowDetail).filter(
        StockMoneyFlowDetail.trade_date == latest,
        StockMoneyFlowDetail.ts_code.in_(ts_codes),
    ).all()
    max_map = {r.ts_code: r.max_net for r in db.query(max_sub.c.ts_code, max_sub.c.max_net).all()}
    hit = set()
    for r in today_rows:
        if r.main_net and r.main_net > 0 and max_map.get(r.ts_code, 0) == r.main_net:
            hit.add(r.ts_code)
    return hit


def _hit_popularity(db, sectors_map: dict) -> set:
    """🔥 人气命中：自选股所属板块 ConceptSectorFlow 最新一日 limit_up_count >= 5"""
    from db.models import ConceptSectorFlow
    sectors = list(set(s for s in sectors_map.values() if s and s != '未知'))
    if not sectors:
        return set()
    latest_date = db.query(func.max(ConceptSectorFlow.trade_date)).scalar()
    if not latest_date:
        return set()
    rows = db.query(ConceptSectorFlow.concept_name, ConceptSectorFlow.limit_up_count).filter(
        ConceptSectorFlow.trade_date == latest_date,
        ConceptSectorFlow.concept_name.in_(sectors),
        ConceptSectorFlow.limit_up_count >= 5,
    ).all()
    hot_sectors = {r.concept_name for r in rows}
    return {code for code, sec in sectors_map.items() if sec in hot_sectors}


def _hit_accumulation(db, ts_codes: list) -> set:
    """🧲 吸筹命中：最近两期股东户数连续减少（Tushare 暂未返回 avg_shares，先以户数减少为准）"""
    from db.models import StockHolderNumber
    if not ts_codes:
        return set()
    # 取每只股最近一期
    sub = db.query(
        StockHolderNumber.ts_code,
        func.max(StockHolderNumber.ann_date).label('latest_date')
    ).filter(StockHolderNumber.ts_code.in_(ts_codes)).group_by(StockHolderNumber.ts_code).subquery()
    latest_rows = db.query(StockHolderNumber).join(
        sub,
        (StockHolderNumber.ts_code == sub.c.ts_code) &
        (StockHolderNumber.ann_date == sub.c.latest_date)
    ).all()
    if not latest_rows:
        return set()
    # 取每只股第二新一期
    prev_sub = db.query(
        StockHolderNumber.ts_code,
        func.max(StockHolderNumber.ann_date).label('prev_date')
    ).filter(
        StockHolderNumber.ts_code.in_(ts_codes),
        StockHolderNumber.ann_date < sub.c.latest_date
    ).group_by(StockHolderNumber.ts_code).subquery()
    prev_rows = db.query(StockHolderNumber).join(
        prev_sub,
        (StockHolderNumber.ts_code == prev_sub.c.ts_code) &
        (StockHolderNumber.ann_date == prev_sub.c.prev_date)
    ).all()
    prev_map = {r.ts_code: r for r in prev_rows}
    hit = set()
    for cur in latest_rows:
        prev = prev_map.get(cur.ts_code)
        if not prev:
            continue
        if (cur.holder_num or 0) > 0 and (prev.holder_num or 0) > 0 and cur.holder_num < prev.holder_num:
            hit.add(cur.ts_code)
    return hit


def _hit_support(db, ts_codes: list) -> set:
    """🛡️ 承接命中：昨日 YuziQuantSignal 上榜 + 今日 StockRealtimeTick 分时 V 字反转"""
    from db.models import YuziQuantSignal, StockRealtimeTick
    from datetime import date as _date, timedelta as _td
    if not ts_codes:
        return set()
    # 1. 找昨日龙虎榜上榜股
    latest_date = db.query(func.max(YuziQuantSignal.trade_date)).scalar()
    if not latest_date:
        return set()
    yesterday = latest_date
    yuzi_rows = db.query(YuziQuantSignal.ts_code).filter(
        YuziQuantSignal.trade_date == yesterday,
        YuziQuantSignal.ts_code.in_(ts_codes),
    ).all()
    yuzi_set = {r.ts_code for r in yuzi_rows}
    if not yuzi_set:
        return set()
    # 2. 查今日分时 Tick
    today = _date.today()
    tick_rows = db.query(StockRealtimeTick).filter(
        StockRealtimeTick.trade_date == today,
        StockRealtimeTick.ts_code.in_(list(yuzi_set)),
    ).order_by(StockRealtimeTick.ts_code, StockRealtimeTick.snapshot_time).all()
    # 3. 按 ts_code 分组算 V 字反转
    ticks_by_code = {}
    for t in tick_rows:
        ticks_by_code.setdefault(t.ts_code, []).append(t)
    hit = set()
    for ts_code, ticks in ticks_by_code.items():
        if len(ticks) < 5:
            continue
        if any(t.price is None for t in ticks):
            continue
        prices = [float(t.price) for t in ticks]
        if not prices or prices[0] <= 0:
            continue
        min_idx = prices.index(min(prices))
        if min_idx == len(prices) - 1:
            continue  # 最低点在最后，未回升
        min_price = prices[min_idx]
        last_price = prices[-1]
        if min_price <= 0:
            continue
        recovery_pct = (last_price - min_price) / min_price
        if recovery_pct < 0.01:
            continue  # 回升不足 1%
        # 最低点后主力净流入累计 > 0
        post_values = [
            float(t.main_force_inflow)
            for t in ticks[min_idx+1:]
            if t.main_force_inflow is not None
        ]
        if not post_values:
            continue
        post_inflow = sum(post_values)
        if post_inflow > 0:
            hit.add(ts_code)
    return hit


def _gen_action_hint(tags: list) -> str:
    """根据命中标签组合生成操作方向文案"""
    s = set(tags)
    if {'yuzi', 'popularity'} <= s:
        return '主流抱团龙头，分时拉升直接打板抢筹'
    if {'yuzi', 'capital'} <= s:
        return '游资+主力双共振，低吸跟随'
    if {'support', 'trend'} <= s:
        return '趋势大单护盘，回踩均线低吸'
    if 'yuzi' in s:
        return '游资共振净买入，关注次日溢价'
    if 'trend' in s:
        return '多头排列，回踩均线低吸'
    if 'capital' in s:
        return '主力爆买创30天新高，防踏空'
    if 'popularity' in s:
        return '板块爆发人气龙头，打板'
    if 'support' in s:
        return '昨日上榜今日V反，深水低吸'
    if 'accumulation' in s:
        return '股东户数减少筹码集中，主力吸筹待拉升'
    return ''


def _batch_hit_tags(stock_codes: list, sectors_map: dict) -> dict:
    """批量计算 7 大命中标签，返回 {ts_code: {hit_tags: [], action_hint: ''}}

    7 个批量查询相互独立，并行执行（ThreadPoolExecutor）将首次耗时 6-9s 降到 1-2s。
    每个线程使用独立 Session（SQLAlchemy Session 非线程安全）。
    """
    if not stock_codes:
        return {}
    valid_codes = list(dict.fromkeys(
        normalize_stock_code(code) for code in stock_codes
        if normalize_stock_code(code)
    ))
    ts_codes = [normalize_ts_code(code) for code in valid_codes]
    code_to_ts = {code: normalize_ts_code(code) for code in valid_codes}

    from db.connection import SessionLocal
    from concurrent.futures import ThreadPoolExecutor, as_completed

    hit_tasks = [
        ('yuzi',         _hit_yuzi,         (ts_codes,)),
        ('strategy',     _hit_strategy,     (valid_codes,)),
        ('trend',        _hit_trend,        (valid_codes,)),
        ('capital',      _hit_capital,      (ts_codes,)),
        ('popularity',   _hit_popularity,   (sectors_map,)),
        ('support',      _hit_support,      (ts_codes,)),
        ('accumulation', _hit_accumulation, (ts_codes,)),
    ]
    sets = {name: set() for name, _, _ in hit_tasks}

    def _run_in_thread(name, fn, args):
        # 每个线程独占一个 Session，避免 SQLAlchemy 状态污染
        thread_db = SessionLocal()
        try:
            return name, fn(thread_db, *args)
        except Exception as e:
            logger.warning(f'_hit_{name} failed: {e}')
            try:
                thread_db.rollback()
            except Exception:
                logger.debug(f'_hit_{name} rollback failed', exc_info=True)
            return name, set()
        finally:
            thread_db.close()

    with ThreadPoolExecutor(max_workers=7) as executor:
        future_to_name = {executor.submit(_run_in_thread, name, fn, args): name
                          for name, fn, args in hit_tasks}
        for future in as_completed(future_to_name):
            try:
                name, result = future.result()
                sets[name] = result or set()
            except Exception as e:
                logger.warning(f'_hit task future failed: {e}')

    out = {}
    # _hit_strategy 返回 dict（{code: strategy_name}），其他返回 set
    strategy_map = sets.get('strategy') or {}
    # strategy 命中时不加 'strategy' 通用标签（与顶部 strategyTags 重复），
    # 改为加 'strategy:BS-全市场' 形式，让前端直接显示具体策略名
    # _gen_action_hint 只看基础 6 个标签，不受影响
    for code in valid_codes:
        ts = code_to_ts[code]
        tags = []
        if ts in sets.get('yuzi', set()):
            tags.append('yuzi')
        # strategy 标签合并：跳过通用 'strategy' 标签，由 strategyTags 顶部标签承担显示
        # 如需保留命中信息可加：if code in strategy_map: tags.append(f'strategy:{strategy_map[code]}')
        if code in sets.get('trend', set()):
            tags.append('trend')
        if ts in sets.get('capital', set()):
            tags.append('capital')
        if code in sets.get('popularity', set()):
            tags.append('popularity')
        if ts in sets.get('support', set()):
            tags.append('support')
        if ts in sets.get('accumulation', set()):
            tags.append('accumulation')
        out[ts] = {
            'hit_tags': tags,
            'action_hint': _gen_action_hint(tags),
            'strategy_name': strategy_map.get(code),  # 附加策略名，供前端选用
        }
    return out


logger = logging.getLogger(__name__)
router = APIRouter()


def _batch_compute_dashboard(codes: list, max_workers: int = 8) -> dict:
    """并行计算 8 维综合评分（_compute_dashboard 单只 ~0.12s，116只串行=14s，并行=2s）

    SQLAlchemy Session 非线程安全，每个 worker 独占一个 Session。
    返回 {code: dashboard_dict}，失败 code 值为 None。
    """
    from db.connection import SessionLocal
    from concurrent.futures import ThreadPoolExecutor
    from api.stock_dashboard import _compute_dashboard, _dash_cache_get, _dash_cache_set

    if not codes:
        return {}

    def _worker(code):
        cached = _dash_cache_get(code)
        if cached is not None:
            return code, cached
        thread_db = SessionLocal()
        try:
            dashboard = _compute_dashboard(code, thread_db)
            if dashboard is not None:
                _dash_cache_set(code, dashboard)
            return code, dashboard
        except Exception as e:
            logger.debug(f'[_batch_compute_dashboard] {code} failed: {e}')
            return code, None
        finally:
            thread_db.close()

    out = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for code, dash in executor.map(_worker, codes):
            out[code] = dash
    return out


def _calc_junk_for_signal(stock_name: str, quote: dict, sector_trend: dict) -> dict:
    avg_turnover = quote.get('avg_turnover_yi', 0) if quote else 0
    sector_heat = sector_trend.get('latest_heat', 0) if sector_trend.get('available') else 0
    return is_junk_stock(stock_name=stock_name, avg_turnover=avg_turnover, sector_heat=sector_heat)


def _classify_watchlist_data_status(code: str, stock_name: str, quote: dict | None, kline_count: int) -> tuple[str, str]:
    """仅根据本地已落库数据说明决策可用性，不触发任何补数。"""
    if not stock_name and quote is None and kline_count == 0:
        return 'UNSUPPORTED', '本地证券主数据、行情和日K均不存在'
    if kline_count == 0:
        if code.startswith(('5', '15', '16')):
            return 'ETF_KLINE_MISSING', '本地 ETF 日K尚未入库，暂停技术与资金流评分'
        return 'KLINE_MISSING', '本地日K尚未入库，暂停技术评分'
    if kline_count < 60:
        return 'INSUFFICIENT_HISTORY', f'本地日K仅 {kline_count} 根，少于 60 根策略窗口'
    if not quote or quote.get('status') != 'READY':
        return 'QUOTE_PARTIAL', '本地行情字段不完整，暂停完整决策评分'
    return 'READY', ''


async def _fetch_stock_data(item, prefetched_quote=None, prefetched_klines=None):
    code = normalize_stock_code(item.stock_code)
    # 优先使用批量读取的数据库行情与日 K，避免逐股重复查询。
    if prefetched_quote is not None:
        quote = prefetched_quote
    else:
        quote = await get_quote(code)
    if prefetched_klines is not None:
        klines = prefetched_klines
    else:
        klines = await fetch_kline_cached(code, 60)
    if isinstance(quote, Exception):
        quote = None
    if isinstance(klines, Exception):
        klines = []

    stock_name = item.stock_name or (quote['name'] if quote else '')
    data_status, data_issue = _classify_watchlist_data_status(
        code, stock_name, quote, len(klines),
    )
    ts_code = normalize_ts_code(code)
    # 行情/K 线请求完成后才短暂打开只读会话，避免等待外部源时占用事务。
    with get_db_session() as sector_db:
        sector = _find_sector_for_stock(sector_db, ts_code)
        sector_trend = _get_sector_trend(sector_db, sector, 7) if sector else {"sector": "", "available": False}

    bs_signal = None
    bs_reasons = []
    bs_interval = {'state': 'unknown'}
    indicators = {}
    try:
        if klines and len(klines) > 0:
            from api.bs_signals import _generate_bs_signals
            from services.indicators import calc_rsi as _calc_rsi
            # 返回 12 个值：signals, dif, dea, macd, ma5, ma20, k, d, j, support, resistance, trend
            bs_signals, dif, dea, macd, ma5, ma20, k_vals, d_vals, j_vals, support, resistance, _trend = _generate_bs_signals(klines)
            if bs_signals:
                last = bs_signals[-1]
                bs_signal = last.get('type')
                bs_reasons = last.get('reasons', [])
                # 计算 BS 区间：B→今=持仓中；B→S=已平仓区间
                from services.signal_builder import _calc_bs_interval
                bs_interval = _calc_bs_interval(bs_signals, quote.get('price') if quote else 0.0)
                # 提取最新 KDJ/MACD/支撑/阻力（最后一根 K 线对应的值）
                def _last(arr):
                    return arr[-1] if arr and arr[-1] is not None else None
                # MA20 斜率：当前 MA20 与 6 根 K 线前的 MA20 对比，反映中期趋势方向（向上/走平/向下）
                ma20_slope = None
                if ma20 and len(ma20) >= 6 and ma20[-1] is not None and ma20[-6]:
                    ma20_slope = (ma20[-1] - ma20[-6]) / ma20[-6] * 100
                # MA10：最近 10 根 K 线收盘价简单均值（10 日线），供前端展示 站上/破位
                ma10_val = None
                if klines and len(klines) >= 10:
                    _c10 = [k.get('close', 0.0) for k in klines[-10:]]
                    if all(c for c in _c10):
                        ma10_val = sum(_c10) / len(_c10)
                indicators = {
                    'macd': round(_last(macd), 4) if _last(macd) is not None else None,
                    'dif': round(_last(dif), 4) if _last(dif) is not None else None,
                    'dea': round(_last(dea), 4) if _last(dea) is not None else None,
                    'kdj_k': round(_last(k_vals), 2) if _last(k_vals) is not None else None,
                    'kdj_d': round(_last(d_vals), 2) if _last(d_vals) is not None else None,
                    'kdj_j': round(_last(j_vals), 2) if _last(j_vals) is not None else None,
                    'ma5': round(_last(ma5), 2) if _last(ma5) is not None else None,
                    'ma10': round(ma10_val, 2) if ma10_val is not None else None,
                    'ma20': round(_last(ma20), 2) if _last(ma20) is not None else None,
                    'ma20_slope': round(ma20_slope, 2) if ma20_slope is not None else None,
                    'support': round(_last(support), 2) if _last(support) is not None else None,
                    'resistance': round(_last(resistance), 2) if _last(resistance) is not None else None,
                    'rsi': round(_last(_calc_rsi([k.get('close', 0.0) for k in klines], 14)), 1) if klines and len(klines) >= 15 else None,
                }
    except Exception as e:
        logger.debug(f"BS signal compute failed for {code}: {e}")

    return {
        'item': item,
        'code': code,
        'quote': quote,
        'stock_name': stock_name,
        'sector': sector,
        'sector_trend': sector_trend,
        'bs_signal': bs_signal,
        'bs_reasons': bs_reasons,
        'bs_interval': bs_interval,
        'indicators': indicators,
        'data_status': data_status,
        'data_issue': data_issue,
        'kline_count': len(klines),
    }


def _load_watchlist_base():
    """同步加载自选股列表 + 批量资金流（在线程池执行，不阻塞事件循环）。"""
    with get_db_session() as db:
        items = db.query(Watchlist).order_by(
            Watchlist.sort_order, Watchlist.created_at.desc()
        ).all()
        _moneyflow_map = _batch_moneyflow_map(db, [i.stock_code for i in items if i.stock_code])
        # 后续会等待行情与持仓接口。保留已加载的标量字段、结束只读事务，
        # 避免长时间 idle in transaction 占住连接。
        db.expunge_all()
        db.rollback()
        return items, _moneyflow_map


def _load_tracker_notes():
    """同步加载共振选股跟踪 note（在线程池执行，不阻塞事件循环）。"""
    from db.models import StockTracker
    with get_db_session() as tracker_db:
        tracker_rows = tracker_db.query(StockTracker).filter(
            StockTracker.active == True,
            StockTracker.note.like('%共振选股%'),
        ).all()
        return {normalize_stock_code(t.stock_code): t.note for t in tracker_rows}


async def build_watchlist() -> dict:
    """构建完整自选股数据（耗时操作：164只×行情+K线+板块趋势+BS计算）"""
    items, _moneyflow_map = await run_db(_load_watchlist_base)

    # 批量读取数据库行情，避免逐股重复查询。
    all_codes = [normalize_stock_code(i.stock_code) for i in items if normalize_stock_code(i.stock_code)]
    try:
        _quotes_map = await batch_get_quotes(all_codes)
    except Exception as e:
        logger.warning(f'[build_watchlist] batch_get_quotes failed, fallback to per-stock: {e}')
        _quotes_map = {}
    try:
        _klines_map = await batch_fetch_kline_cached(all_codes, 60)
    except Exception as e:
        logger.warning(f'[build_watchlist] batch_fetch_kline_cached failed, fallback to per-stock: {e}')
        _klines_map = {}

    # 持仓是状态判断的第一事实来源。行情接口失败时，使用持仓快照中的
    # 成本、数量、现价和浮盈亏；接口失败则按未持仓处理，不伪造持仓结论。
    _positions_map = {}
    _positions_as_of = None
    try:
        from api.trading import get_positions
        position_data = await get_positions(force=False)
        _positions_as_of = (position_data or {}).get('data_as_of')
        for position in (position_data or {}).get('positions', []):
            position_code = str(position.get('secCode') or '').split('.')[0]
            if position_code:
                _positions_map[position_code] = position
    except Exception as e:
        logger.warning(f'[build_watchlist] fetch positions failed: {e}')

    results = []
    BATCH = 20
    for i in range(0, len(items), BATCH):
        batch = items[i:i + BATCH]
        tasks = [
            _fetch_stock_data(
                item,
                prefetched_quote=_quotes_map.get(normalize_stock_code(item.stock_code)),
                prefetched_klines=_klines_map.get(normalize_stock_code(item.stock_code)),
            )
            for item in batch
        ]
        results.extend(await asyncio.gather(*tasks, return_exceptions=True))

    # 批量计算 6 大命中标签（需要 sectors_map，从 results 提取）
    _sectors_map = {}
    for r in results:
        if not isinstance(r, Exception) and r.get('item') and r['item'].stock_code:
            _sectors_map[r['code']] = r.get('sector') or ''
    _hit_tags_map = _batch_hit_tags(all_codes, _sectors_map)

    # 预加载跟踪表共振 note（用于前端显示共振标签）
    try:
        _tracker_note_map = await run_db(_load_tracker_notes)
    except Exception:
        _tracker_note_map = {}

    # 并行预计算所有自选股的 8 维综合评分（_compute_dashboard 单只 ~0.12s，
    # 116只串行=14s+，8 worker 并行=2s 左右）。每 worker 用独立 Session。
    _dashboard_map = _batch_compute_dashboard(all_codes)

    signals = []
    buy_count = 0
    sell_count = 0
    watch_count = 0
    sector_heating_count = 0
    inflow_count = 0
    buy_top = []
    sector_heating_top = []
    inflow_top = []

    for r in results:
        if isinstance(r, Exception):
            continue
        bs_signal = r['bs_signal']
        bs_reasons = r['bs_reasons']
        bs_interval = r.get('bs_interval') or {'state': 'unknown'}
        indicators = r.get('indicators') or {}
        quote = r['quote']
        sector = r['sector']
        sector_trend = r['sector_trend']
        item = r['item']
        code = r['code']
        stock_name = r['stock_name']
        data_status = r['data_status']
        data_issue = r['data_issue']
        holding = _positions_map.get(code) or {}

        # 持仓快照是行情接口失败时的受控回退，只补充持仓判断所需字段。
        if quote is None and holding.get('price') is not None:
            holding_change_pct = (
                float(holding['dayProfitPct'])
                if holding.get('dayProfitPct') is not None else None
            )
            quote = {
                'name': holding.get('secName') or stock_name,
                'price': float(holding['price']),
                'changePct': holding_change_pct,
                'change': None,
                'source': 'database',
                'upstreamSource': 'position_snapshot',
                'dataAsOf': _positions_as_of,
                'status': 'PARTIAL',
                'missingFields': ['change', 'open', 'high', 'low', 'volume', 'amount'],
            }

        # 解析当前股的资金流(批量预拉的)
        ts_code_cur = normalize_ts_code(code)
        money_flow = _moneyflow_map.get(ts_code_cur) or {
            'available': False, 'status': 'MISSING', 'source': 'database',
            'main_net': None, 'super_large': None, 'large': None,
            'small': None, 'tiny': None, 'turnover_rate': None,
        }
        main_net_wan = money_flow.get('main_net')

        if sector_trend.get('available'):
            if sector_trend.get('heat_trend') == 'up':
                sector_heating_count += 1
                if len(sector_heating_top) < 9:
                    sector_heating_top.append({"code": code, "name": stock_name, "heat": round(sector_trend.get("latest_heat", 0), 1)})

        # 资金流入/流出统计：基于个股 4 档资金流(优先) > 板块资金流(降级)
        if money_flow.get('available'):
            if main_net_wan is not None and main_net_wan > 0.01:
                inflow_count += 1
                inflow_top.append({
                    "code": code,
                    "name": stock_name,
                    "main_net": round(main_net_wan, 2),
                    "chg": round(quote['changePct'], 2) if quote and quote.get('changePct') is not None else None,
                })
        elif sector_trend.get('available') and sector_trend.get('flow_direction') == 'inflow':
            inflow_count += 1
            chg = quote.get('changePct') if quote else None
            inflow_top.append({
                "code": code,
                "name": stock_name,
                "main_net": None,
                "chg": round(chg, 2) if chg is not None else None,
            })

        if bs_signal == 'B':
            # 持仓中（区间详情在下方独立分组展示）
            signal_label = 'B 持仓中'
            signal_color = '#ef4444'
            signal_type = 'ADD'
            buy_count += 1
            if len(buy_top) < 9:
                buy_top.append({"code": code, "name": stock_name})
        elif bs_signal == 'S':
            # 已平仓（区间详情在下方独立分组展示）
            signal_label = 'S 已平仓'
            signal_color = '#f97316'
            signal_type = 'SELL'
            sell_count += 1
        else:
            signal_label = '关注'
            signal_color = '#3b82f6'
            signal_type = 'WATCH'
            watch_count += 1

        price = quote.get('price') if quote else None
        change_pct = quote.get('changePct') if quote else None

        reasons = list(bs_reasons or [])
        if change_pct is not None:
            reasons.append(f'当日涨跌: {change_pct:+.2f}%')
        if bs_interval.get('pnl_pct'):
            reasons.append(f'BS区间盈亏: {bs_interval["pnl_pct"]:+.2f}%')

        positive_factors = []
        negative_factors = []

        if bs_signal == 'B':
            positive_factors.append({'factor': 'BS买入', 'detail': bs_reasons[0] if bs_reasons else 'SuperTrend突破', 'weight': 2})
        if change_pct is not None and change_pct > 0:
            positive_factors.append({'factor': '当日上涨', 'detail': f'涨幅 {change_pct:+.2f}%', 'weight': 1})
        if sector_trend.get('available') and sector_trend.get('heat_trend') == 'up':
            positive_factors.append({'factor': '板块升温', 'detail': f'板块热度上升至 {sector_trend["latest_heat"]:.1f}', 'weight': 1})
        if sector_trend.get('available') and sector_trend.get('flow_direction') == 'inflow':
            positive_factors.append({'factor': '资金流入', 'detail': f'净流入 {sector_trend["total_net_flow"]:.0f}万', 'weight': 1})

        if bs_signal == 'S':
            negative_factors.append({'factor': 'BS卖出', 'detail': bs_reasons[0] if bs_reasons else 'SuperTrend跌破', 'weight': -2})
        if change_pct is not None and change_pct < 0:
            negative_factors.append({'factor': '当日下跌', 'detail': f'跌幅 {change_pct:+.2f}%', 'weight': -1})
        if sector_trend.get('available') and sector_trend.get('heat_trend') == 'down':
            negative_factors.append({'factor': '板块降温', 'detail': f'板块热度下降至 {sector_trend["latest_heat"]:.1f}', 'weight': -1})
        if sector_trend.get('available') and sector_trend.get('flow_direction') == 'outflow':
            negative_factors.append({'factor': '资金流出', 'detail': f'净流出 {abs(sector_trend["total_net_flow"]):.0f}万', 'weight': -1})

        score = len(positive_factors) - len(negative_factors)
        reasons.append(f'综合评分: {"看多" if score > 0 else "看空" if score < 0 else "中性"} → {signal_label}')

        signals.append({
            'secCode': code,
            'secName': stock_name,
            'signal': signal_type,
            'signalLabel': signal_label,
            'signalColor': signal_color,
            'score': score,
            'reasons': reasons,
            'positiveFactors': positive_factors,
            'negativeFactors': negative_factors,
            'sector': sector or '',
            'sectorTrend': sector_trend,
            'quote': quote,
            'bsSignal': bs_signal,
            'bsInterval': bs_interval,  # BS 区间：state/start_date/start_price/end_date/end_price/hold_days/pnl_pct
            'indicators': indicators,  # KDJ/MACD/MA 技术指标（最新一根 K 线）
            'moneyFlow': money_flow,  # 4 档资金流(主/特大/大/小/散, 单位:万元)
            'hitTags': _hit_tags_map.get(ts_code_cur, {}).get('hit_tags', []),
            'actionHint': _hit_tags_map.get(ts_code_cur, {}).get('action_hint', ''),
            'strategyName': _hit_tags_map.get(ts_code_cur, {}).get('strategy_name'),  # 具体策略名（如 BS-全市场）
            'position': {
                'profitPct': float(holding['profitPct']) if holding and holding.get('profitPct') is not None else None,
                'posPct': float(holding['posPct']) if holding and holding.get('posPct') is not None else (0 if not holding else None),
                'dayProfit': float(holding['dayProfit']) if holding and holding.get('dayProfit') is not None else (0 if not holding else None),
                'dayProfitPct': float(holding['dayProfitPct']) if holding and holding.get('dayProfitPct') is not None else (change_pct if not holding else None),
                'count': int(holding.get('count') or 0) if holding else 0,
                'price': float(holding['price']) if holding and holding.get('price') is not None else price,
                'costPrice': float(holding['costPrice']) if holding and holding.get('costPrice') is not None else (0 if not holding else None),
                'value': float(holding['value']) if holding and holding.get('value') is not None else (0 if not holding else None),
                'profit': float(holding['profit']) if holding and holding.get('profit') is not None else (0 if not holding else None),
            },
            'note': item.note,
            'trackerNote': _tracker_note_map.get(code, ''),
            'group': item.group_name or '默认',
            'watchlistId': item.id,
            'qualityStatus': item.quality_status or '普通',
            'dataStatus': data_status,
            'dataIssue': data_issue or None,
            'klineCount': r['kline_count'],
            # buyPower 字段已下线：与 8 维综合评分重复，统一改用 overall_score + trend_strength
            # 内部仍计算 bp_internal 供 calc_risk 等下游使用，但不再暴露到响应
            'marketState': get_latest_state(code) or {'market_state': 'PENDING', 'reasons': ['待计算']},
        })
        # 为上一条 signal 补充 5 维评分（需要 marketState.features）
        last_signal = signals[-1]
        ms_data = last_signal.get('marketState', {})
        ms_features = ms_data.get('features') or {}
        last_signal['sentiment'] = calc_sentiment(quote, sector_trend, ms_features)
        last_signal['risk'] = calc_risk(ms_features, None, last_signal.get('position'))
        last_signal['momentum'] = calc_momentum(sector_trend, ms_features)
        last_signal['mainForce'] = calc_main_force(quote, ms_features, sector_trend)
        technical_result = calc_technical(ms_features)
        last_signal['technical'] = technical_result
        last_signal['sectorResonance'] = calc_sector_resonance(sector_trend, ms_features)
        if last_signal['dataStatus'] == 'READY' and not technical_result:
            last_signal['dataStatus'] = 'FEATURES_MISSING'
            last_signal['dataIssue'] = '日K已入库，但当日策略特征尚未生成'

        # === 8 维综合评分（与 /api/stock-dashboard 完全对齐）===
        # 直接取预计算的 _compute_dashboard 结果（已在外层并行执行），保证与个股详情页完全一致。
        # 失败时只暴露已有子项，综合分保持空值，避免用不同口径拼成伪完整结果。
        try:
            dash = _dashboard_map.get(code)
            if dash and dash.get('overall_score') is not None:
                last_signal['overallScore'] = dash['overall_score']
                last_signal['trendStrength'] = dash.get('trend_strength')
                # 暴露 8 维子项分数（可选，前端用于显示维度雷达）
                last_signal['scoreDimensions'] = {
                    'trend_strength': dash.get('trend_strength'),
                    'capital_momentum': dash.get('capital_momentum'),
                    'sector_resonance': dash.get('sector_resonance'),
                    'relative_strength': dash.get('relative_strength'),
                    'volume_health': dash.get('volume_health'),
                    'volatility_health': dash.get('volatility_health'),
                    'drawdown_status': dash.get('drawdown_status'),
                    'institution_signal': dash.get('institution_signal'),
                }
                last_signal['actionLabel'] = dash.get('action_label')
                last_signal['actionColor'] = dash.get('action_color')
            else:
                raise ValueError('dash returns None')
        except Exception:
            # 降级：仅保留已有 6 维数据的结构映射，不计算综合分。
            _sentiment = (last_signal.get('sentiment') or {}).get('score')
            _risk = (last_signal.get('risk') or {}).get('score')
            _momentum = (last_signal.get('momentum') or {}).get('score')
            _mainForce = (last_signal.get('mainForce') or {}).get('score')
            _technical = (last_signal.get('technical') or {}).get('score')
            _sectorResonance = (last_signal.get('sectorResonance') or {}).get('score')
            last_signal['overallScore'] = None
            last_signal['trendStrength'] = (technical_result or {}).get('score')
            # 6 维 → 8 维映射：trend=technical, capital=mainForce, resonance=sector, relative=momentum,
            # volume=50(默认), volatility=risk, drawdown=sentiment, institution=mainForce
            last_signal['scoreDimensions'] = {
                'trend_strength': _technical,
                'capital_momentum': _mainForce,
                'sector_resonance': _sectorResonance,
                'relative_strength': _momentum,
                'volume_health': None,
                'volatility_health': _risk,
                'drawdown_status': _sentiment,
                'institution_signal': _mainForce,
            }
            last_signal['actionLabel'] = None
            last_signal['actionColor'] = None

        # 持仓状态覆盖旧的“B/S 直接决定标签”逻辑。B/S 保留在 bsSignal 中，
        # 只作为持仓因子之一，不再把它直接显示成买入/卖出结论。
        holding_state = evaluate_holding_state(
            code=code,
            name=stock_name,
            position=last_signal.get('position'),
            quote=quote,
            market_state=last_signal.get('marketState'),
            score_dimensions=last_signal.get('scoreDimensions'),
            overall_score=last_signal.get('overallScore'),
            technical=technical_result,
            bs_signal=bs_signal,
        )
        last_signal['holdingState'] = holding_state
        last_signal['originalSignalLabel'] = last_signal.get('signalLabel')
        last_signal['signalLabel'] = holding_state['statusLabel']
        last_signal['signalColor'] = holding_state['statusColor']
        last_signal['actionLabel'] = holding_state['action']
        last_signal['actionColor'] = holding_state['statusColor']

    inflow_top = sorted(
        inflow_top,
        key=lambda item: item.get('main_net') if item.get('main_net') is not None else float('-inf'),
        reverse=True,
    )[:9]

    quote_ready = sum(
        1 for signal in signals
        if signal.get('quote') and signal['quote'].get('status') == 'READY'
    )
    technical_ready = sum(1 for signal in signals if signal.get('technical'))
    data_status_counts = {}
    for signal in signals:
        key = signal.get('dataStatus') or 'UNKNOWN'
        data_status_counts[key] = data_status_counts.get(key, 0) + 1
    dates = []
    for signal in signals:
        quote_date = (signal.get('quote') or {}).get('dataAsOf')
        feature_date = (signal.get('marketState') or {}).get('trade_date')
        flow_date = (signal.get('moneyFlow') or {}).get('trade_date')
        dates.extend(str(value) for value in (quote_date, feature_date, flow_date) if value)
    data_as_of = max(dates) if dates else _positions_as_of
    status = (
        'MISSING' if not signals
        else 'READY' if quote_ready == len(signals) and technical_ready == len(signals)
        else 'PARTIAL'
    )

    result = {
        'signals': signals,
        'summary': {
            'total': len(signals),
            'buy': buy_count,
            'sector_heating': sector_heating_count,
            'inflow': inflow_count,
            'buy_top': buy_top,
            'sector_heating_top': sector_heating_top,
            'inflow_top': inflow_top,
            'sell': sell_count,
            'hold': watch_count,
            'add': buy_count,
        },
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_as_of': data_as_of,
        'source': 'database',
        'status': status,
        'coverage': {
            'total': len(signals),
            'quote_ready': quote_ready,
            'technical_ready': technical_ready,
            'decision_ready': data_status_counts.get('READY', 0),
            'data_status_counts': data_status_counts,
        },
    }
    _watchlist_cache["data"] = result
    _watchlist_cache["ts"] = time.time()
    return result


async def refresh_watchlist_cache():
    """后台刷新缓存（stale-while-revalidate）"""
    try:
        await _build_watchlist_singleflight()
    except Exception as e:
        logger.warning(f"background watchlist refresh failed: {e}")


def _sync_build_watchlist():
    """在线程池中运行 build_watchlist，避免同步 DB 操作阻塞主 event loop"""
    import asyncio
    return asyncio.run(build_watchlist())


async def _build_watchlist_singleflight():
    """同一进程内只允许一个完整自选构建，避免冷启动耗尽数据库连接池。"""
    global _watchlist_build_task
    task = _watchlist_build_task
    if task is None or task.done():
        task = asyncio.create_task(run_in_threadpool(_sync_build_watchlist))
        _watchlist_build_task = task
    try:
        return await asyncio.shield(task)
    finally:
        if _watchlist_build_task is task and task.done():
            _watchlist_build_task = None


# ==================== Core Endpoints ====================

class AddStockRequest(BaseModel):
    stockCode: str
    stockName: str = ''
    note: str = ''
    group: str = '默认'


class UpdateQualityRequest(BaseModel):
    quality_status: str


class UpdateNoteRequest(BaseModel):
    note: str = ''


class MoveGroupRequest(BaseModel):
    target_group: str = '默认'


def _required_stock_code(value: str) -> str:
    code = normalize_stock_code(value)
    if not code:
        raise HTTPException(status_code=400, detail="股票代码必须包含6位数字")
    return code


@router.get("/api/watchlist")
async def get_watchlist(force: bool = False):
    """获取自选股列表（stale-while-revalidate）"""
    if force:
        # force 语义是同步等待最新结果：直接清空并立即构建，
        # 不走 reset 的 stale + 后台重建路径（避免多一次重复重建）。
        _watchlist_cache["data"] = None
        _watchlist_cache["ts"] = 0
        return await _build_watchlist_singleflight()

    now = time.time()
    cached = _watchlist_cache["data"]
    cache_age = now - _watchlist_cache["ts"]

    if cached is not None and cache_age < WATCHLIST_CACHE_TTL:
        return cached

    if cached is not None:
        asyncio.create_task(refresh_watchlist_cache())
        return cached

    # 首次加载：在线程池中执行，避免同步 DB/计算阻塞主 event loop
    return await _build_watchlist_singleflight()


@router.post("/api/watchlist/add")
def add_to_watchlist(req: AddStockRequest):
    from .watchlist_local import export_db_to_local
    code = _required_stock_code(req.stockCode)
    with get_db_session() as db:
        existing = db.query(Watchlist).filter_by(stock_code=code).first()
        if existing:
            if req.stockName:
                existing.stock_name = req.stockName
            if req.note:
                existing.note = req.note
            if req.group:
                existing.group_name = req.group
            db.commit()
            export_db_to_local()
            reset_watchlist_cache()
            try:
                from api.sync_pkg import trigger_cloud_sync
                trigger_cloud_sync(f"update {code}")
            except Exception as e:
                logger.debug(f"cloud sync trigger failed: {e}")
            return {'success': True, 'id': existing.id}
        item = Watchlist(
            stock_code=code,
            stock_name=req.stockName,
            note=req.note,
            group_name=req.group,
        )
        db.add(item)
        db.commit()
        export_db_to_local()
        reset_watchlist_cache()
        try:
            from api.sync_pkg import trigger_cloud_sync
            trigger_cloud_sync(f"add {code}")
        except Exception as e:
            logger.debug(f"cloud sync trigger failed: {e}")
        return {'success': True, 'id': item.id}


@router.delete("/api/watchlist/{stock_code}")
def remove_from_watchlist(stock_code: str):
    """从自选列表移除指定股票（含云端删除触发）"""
    from .watchlist_local import export_db_to_local
    stock_code = _required_stock_code(stock_code)
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=stock_code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        stock_name = item.stock_name or stock_code
        db.delete(item)
        db.commit()
        export_db_to_local()
        reset_watchlist_cache()
        try:
            from api.sync_pkg import trigger_cloud_delete
            trigger_cloud_delete(stock_code, stock_name)
        except Exception as e:
            logger.debug(f"cloud delete trigger failed: {e}")
        return {'success': True}


@router.patch("/api/watchlist/{stock_code}")
def update_watchlist_note(stock_code: str, note: str = Query('')):
    from .watchlist_local import export_db_to_local
    stock_code = _required_stock_code(stock_code)
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=stock_code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        item.note = note
        db.commit()
        export_db_to_local()
        reset_watchlist_cache()
        return {'success': True}


@router.put("/api/watchlist/{code}/note")
def update_note(code: str, req: UpdateNoteRequest):
    from .watchlist_local import export_db_to_local
    code = _required_stock_code(code)
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        item.note = req.note[:200]
        db.commit()
        export_db_to_local()
        reset_watchlist_cache()
        return {'success': True, 'code': code, 'note': item.note}


@router.put("/api/watchlist/{stock_code}/quality")
def update_watchlist_quality(stock_code: str, req: UpdateQualityRequest):
    valid = {'劣质', '中性', '偏强', '强势', '极强', '核心', '淘汰', '杂毛', '普通', '合格', '优质'}
    if req.quality_status not in valid:
        raise HTTPException(status_code=400, detail=f"非法质量状态，可选：{','.join(valid)}")
    stock_code = _required_stock_code(stock_code)
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=stock_code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        item.quality_status = req.quality_status
        db.commit()
        reset_watchlist_cache()
        return {'success': True, 'quality_status': req.quality_status}


@router.post("/api/watchlist/sync-quality")
def sync_quality_from_market_state():
    """根据 market_state + 特征数据同步 quality_status"""
    from db.models import StockFeaturesDaily
    from sqlalchemy import func as sa_func
    with get_db_session() as db:
        items = db.query(Watchlist).all()
        latest_sub = db.query(
            StockFeaturesDaily.stock_code,
            func.max(StockFeaturesDaily.trade_date).label('latest_date')
        ).filter(
            StockFeaturesDaily.stock_code.in_([normalize_stock_code(i.stock_code) for i in items])
        ).group_by(StockFeaturesDaily.stock_code).subquery()

        rows = db.query(StockFeaturesDaily).join(
            latest_sub,
            (StockFeaturesDaily.stock_code == latest_sub.c.stock_code) &
            (StockFeaturesDaily.trade_date == latest_sub.c.latest_date)
        ).all()
        feat_map = {normalize_stock_code(r.stock_code): r for r in rows}

        junk_map = {}
        for item in items:
            stock_name = item.stock_name or ''
            is_junk = 'ST' in stock_name.upper() or '退' in stock_name
            junk_map[normalize_stock_code(item.stock_code)] = is_junk

        updated, skipped = 0, 0
        details = []
        for item in items:
            old_q = item.quality_status or '普通'
            if old_q == '淘汰':
                skipped += 1
                continue
            code = normalize_stock_code(item.stock_code)
            f = feat_map.get(code)
            if not f:
                new_q = '普通'
                market_state = None
            else:
                market_state = f.market_state
                features = {
                    'close_vs_ma20': f.close_vs_ma20,
                    'volume_ratio': f.volume_ratio,
                    'noise_ratio': f.noise_ratio,
                    'flow_continuity': f.flow_continuity,
                }
                new_q = compute_quality_from_features(market_state, features, junk_map[code])
            if new_q != old_q:
                item.quality_status = new_q
                updated += 1
                details.append({
                    'code': code, 'name': item.stock_name,
                    'old': old_q, 'new': new_q, 'market_state': market_state,
                })
        db.commit()
        reset_watchlist_cache()
        return {
            'success': True,
            'updated': updated,
            'skipped': skipped,
            'total': len(items),
            'details': details[:20],
        }


@router.post("/api/watchlist/{code}/pin")
def pin_stock(code: str):
    """置顶自选股（sort_order 前移到最前）"""
    code = _required_stock_code(code)
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        min_order = db.query(func.min(Watchlist.sort_order)).scalar() or 0
        item.sort_order = min_order - 1
        db.commit()
        reset_watchlist_cache()
        return {'success': True, 'code': code, 'sort_order': item.sort_order}


@router.post("/api/watchlist/{code}/move-group")
def move_single_group(code: str, req: MoveGroupRequest):
    code = _required_stock_code(code)
    target = (req.target_group or '').strip() or '默认'
    from .watchlist_local import export_db_to_local
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        item.group_name = target
        db.commit()
        export_db_to_local()
        reset_watchlist_cache()
        return {'success': True, 'code': code, 'group': target}


@router.get("/api/watchlist/realtime-flow/{code}")
def get_realtime_fund_flow(code: str):
    """获取个股实时资金流（从 realtime_stock_flow 沉淀数据读取）"""
    from datetime import date as _date
    code = _required_stock_code(code)
    td = _date.today()
    ts_code_pattern = normalize_ts_code(code)

    with get_db_session() as db:
        row = db.execute(text("""
            SELECT * FROM realtime_stock_flow
            WHERE ts_code = :ts AND trade_date = :td
            ORDER BY snapshot_time DESC LIMIT 1
        """), {"ts": ts_code_pattern, "td": td}).fetchone()

    if not row:
        return {"success": False, "data": None, "source": "database", "status": "MISSING"}

    d = dict(row._mapping)
    return {
        "success": True,
        "source": "database",
        "status": "PARTIAL" if any(d.get(key) is None for key in (
            "main_force_inflow", "retail_flow", "price", "price_chg",
        )) else "READY",
        "data": {
            "ts_code": d["ts_code"],
            "name": d["name"],
            "main_buy": None,
            "main_sell": None,
            "main_net": float(d["main_force_inflow"]) * 10000 if d.get("main_force_inflow") is not None else None,
            "retail_buy": None,
            "retail_sell": None,
            "retail_net": float(d["retail_flow"]) * 10000 if d.get("retail_flow") is not None else None,
            "turnover": None,
            "price": float(d["price"]) if d.get("price") is not None else None,
            "price_chg": float(d["price_chg"]) if d.get("price_chg") is not None else None,
            "snapshot_time": str(d["snapshot_time"]),
            "confidence": d.get("confidence"),
            "sources_count": d.get("sources_count"),
        },
    }


@router.get("/api/watchlist/realtime-flow/{code}/history")
def get_realtime_fund_flow_history(code: str, date_str: str = None):
    """获取个股全天分钟级资金流快照历史（从 realtime_stock_flow 沉淀数据读取）

    date_str: YYYYMMDD，默认今天
    """
    from datetime import date as _date
    td = _date.today() if not date_str else _date(
        int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8])
    )
    code = _required_stock_code(code)
    ts_code_pattern = normalize_ts_code(code)

    with get_db_session() as db:
        rows = db.execute(text("""
            SELECT snapshot_time, main_force_inflow, retail_flow,
                   price, price_chg
            FROM realtime_stock_flow
            WHERE ts_code = :ts AND trade_date = :td
            ORDER BY snapshot_time ASC
        """), {"ts": ts_code_pattern, "td": td}).fetchall()

        return {
            "success": True,
            "source": "database",
            "status": "READY" if rows else "MISSING",
            "ts_code": ts_code_pattern,
            "trade_date": str(td),
            "total_snapshots": len(rows),
            "snapshots": [
                {
                    "time": str(r.snapshot_time),
                    "main_buy": None,
                    "main_sell": None,
                    "main_net": float(r.main_force_inflow) * 10000 if r.main_force_inflow is not None else None,
                    "retail_buy": None,
                    "retail_sell": None,
                    "retail_net": float(r.retail_flow) * 10000 if r.retail_flow is not None else None,
                    "turnover": None,
                    "price": float(r.price) if r.price is not None else None,
                    "price_chg": float(r.price_chg) if r.price_chg is not None else None,
                }
                for r in rows
            ],
        }


@router.get("/api/watchlist/realtime-flow-batch")
def get_realtime_fund_flow_batch(codes: str = Query(..., description="逗号分隔的股票代码,如 002245,600519")):
    """批量获取自选股实时资金流（emdatah5 口径）

    从 stock_money_flow_realtime 表查询每只股票的最新快照。
    无数据时明确标记不可用；采集与写库由后台采集任务负责。
    返回 { code -> { ts_code, main_buy, main_sell, main_net, ... } }
    """
    from datetime import date as _date

    raw_codes = [c.strip() for c in codes.split(",") if c.strip()]
    if not raw_codes:
        return {"success": True, "data": {}}

    td = _date.today()
    result = {}

    with get_db_session() as db:
        for code in raw_codes:
            normalized_code = _required_stock_code(code)
            ts_pattern = normalize_ts_code(normalized_code)

            row = db.execute(text("""
                SELECT ts_code, name, main_buy, main_sell, main_net,
                       retail_buy, retail_sell, retail_net, turnover
                FROM stock_money_flow_realtime
                WHERE ts_code = :ts AND trade_date = :td
                ORDER BY snapshot_time DESC LIMIT 1
            """), {"ts": ts_pattern, "td": td}).fetchone()

            if row:
                d = dict(row._mapping)
                result[code] = {
                    "ts_code": d["ts_code"],
                    "name": d["name"],
                    "main_buy": float(d["main_buy"]) if d["main_buy"] is not None else None,
                    "main_sell": float(d["main_sell"]) if d["main_sell"] is not None else None,
                    "main_net": float(d["main_net"]) if d["main_net"] is not None else None,
                    "retail_buy": float(d["retail_buy"]) if d["retail_buy"] is not None else None,
                    "retail_sell": float(d["retail_sell"]) if d["retail_sell"] is not None else None,
                    "retail_net": float(d["retail_net"]) if d["retail_net"] is not None else None,
                    "turnover": float(d["turnover"]) if d["turnover"] is not None else None,
                    "available": True,
                    "source": "database",
                    "status": "PARTIAL" if any(d[key] is None for key in (
                        "main_buy", "main_sell", "main_net", "retail_buy",
                        "retail_sell", "retail_net", "turnover",
                    )) else "READY",
                }
            else:
                result[code] = {
                    "available": False,
                    "name": code,
                    "status": "MISSING",
                    "message": "数据库暂无今日实时资金流，请等待采集任务入库",
                }

    return {"success": True, "source": "database", "data": result}

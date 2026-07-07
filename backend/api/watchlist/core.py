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
from pydantic import BaseModel
from sqlalchemy import func

from db.connection import get_db
from db.session import get_db_session
from db.models import Watchlist
from analyzers.strategy_engine import _find_sector_for_stock, _get_sector_trend
from analyzers.buy_power import is_junk_stock, calc_buy_power_for_signal
from analyzers.market_state import get_latest_state, compute_quality_from_features
from analyzers.stock_scores import calc_sentiment, calc_risk, calc_momentum, calc_main_force, calc_technical, calc_sector_resonance

from ._shared import (
    _watchlist_cache, _watchlist_refreshing, WATCHLIST_CACHE_TTL,
    get_quote, fetch_kline_cached, reset_watchlist_cache,
)


def _batch_moneyflow_map(db, stock_codes: list) -> dict:
    """批量查所有自选股的最新一日 4 档资金流 + 1/2/3/4/5 日累计 + 连续天数

    用 2 次批量 IN 查询避免 N+1, 替代每卡片单独请求 stock-flow-detail。
    返回 {ts_code: {main_net(万), super_large(万), large(万), small(万), tiny(万),
                    inflow_1d/2d/3d/4d/5d(元), flow_continuity, available}}
    """
    from db.models import StockMoneyFlowDetail, StockFeaturesDaily
    if not stock_codes:
        return {}
    valid_codes = [c for c in stock_codes if c and len(c) == 6]
    if not valid_codes:
        return {}
    ts_codes = [f"{c}.SH" if c[0] in ('6', '9') else f"{c}.SZ" for c in valid_codes]

    # 第 1 次查询: StockMoneyFlowDetail 最新一日的 4 档(特大/大/小/散)
    latest = db.query(StockMoneyFlowDetail.trade_date)\
        .order_by(StockMoneyFlowDetail.trade_date.desc()).first()
    out = {ts: {'available': False, 'main_net': 0, 'super_large': 0, 'large': 0,
                'small': 0, 'tiny': 0, 'turnover_rate': 0,
                'inflow_1d': 0, 'inflow_2d': 0, 'inflow_3d': 0, 'inflow_4d': 0, 'inflow_5d': 0,
                'flow_continuity': 0}
           for ts in ts_codes}
    if latest:
        td = latest[0]
        rows = db.query(StockMoneyFlowDetail).filter(
            StockMoneyFlowDetail.trade_date == td,
            StockMoneyFlowDetail.ts_code.in_(ts_codes),
        ).all()
        for r in rows:
            def y2w(v):
                return round(float(v or 0) / 10000, 2)
            out[r.ts_code].update({
                'available': True,
                'trade_date': td.strftime('%Y%m%d'),
                'main_net': y2w(r.main_net),
                'super_large': y2w(r.super_large_net),
                'large': y2w(r.large_net),
                'small': y2w(r.small_net),
                'tiny': y2w(r.tiny_net),
                'main_buy': y2w(r.main_buy),
                'main_sell': y2w(r.main_sell),
                'turnover_rate': float(r.turnover_rate or 0),
            })

    # 第 2 次查询: StockFeaturesDaily 取最新一日的 1/3/5 日累计 + 连续天数
    # 用子查询取每个 stock_code 的最大 trade_date,再 join 回原表
    from sqlalchemy import func as sa_func
    latest_sub = db.query(
        StockFeaturesDaily.stock_code,
        sa_func.max(StockFeaturesDaily.trade_date).label('max_date')
    ).filter(
        StockFeaturesDaily.stock_code.in_(valid_codes)
    ).group_by(StockFeaturesDaily.stock_code).subquery()

    feat_rows = db.query(StockFeaturesDaily).join(
        latest_sub,
        (StockFeaturesDaily.stock_code == latest_sub.c.stock_code) &
        (StockFeaturesDaily.trade_date == latest_sub.c.max_date)
    ).all()
    for r in feat_rows:
        ts = f"{r.stock_code}.SH" if r.stock_code[0] in ('6', '9') else f"{r.stock_code}.SZ"
        if ts in out:
            out[ts].update({
                'inflow_1d': float(r.main_net_inflow_1d or 0),
                'inflow_3d': float(r.main_net_inflow_3d or 0),
                'inflow_5d': float(r.main_net_inflow_5d or 0),
                'flow_continuity': int(r.flow_continuity or 0),
            })

    # 第 3 次查询: 取最近 5 个交易日(含最新日)的 main_net, 按日累计得 2d/4d
    # 用一次批量 IN 查询 + 内存聚合, 避免 N+1
    try:
        recent_dates = db.query(StockMoneyFlowDetail.trade_date)\
            .distinct().order_by(StockMoneyFlowDetail.trade_date.desc()).limit(5).all()
        if recent_dates:
            date_objs = [d[0] for d in recent_dates]
            hist_rows = db.query(StockMoneyFlowDetail.ts_code, StockMoneyFlowDetail.trade_date,
                                 StockMoneyFlowDetail.main_net).filter(
                StockMoneyFlowDetail.trade_date.in_(date_objs),
                StockMoneyFlowDetail.ts_code.in_(ts_codes),
            ).all()
            from collections import defaultdict
            hist_by_ts = defaultdict(list)
            for r in hist_rows:
                hist_by_ts[r.ts_code].append((r.trade_date, float(r.main_net or 0) / 10000))
            for ts, items in hist_by_ts.items():
                # 按日期倒序(最新在前)
                items_sorted = sorted(items, key=lambda x: x[0], reverse=True)
                cum = 0.0
                for i, (_, v) in enumerate(items_sorted[:5]):
                    cum += v
                    day_key = f'inflow_{i+1}d'
                    if day_key in out[ts]:
                        out[ts][day_key] = round(cum, 2)
    except Exception as e:
        logger.warning(f'[watchlist] moneyflow 5日聚合失败: {e}')

    # 数据不足时降级：2d 默认继承 1d, 4d 默认继承 3d，避免前端显示 0/None
    for ts in ts_codes:
        if out[ts]['inflow_2d'] == 0 and out[ts]['inflow_1d'] != 0:
            out[ts]['inflow_2d'] = out[ts]['inflow_1d']
        if out[ts]['inflow_4d'] == 0 and out[ts]['inflow_3d'] != 0:
            out[ts]['inflow_4d'] = out[ts]['inflow_3d']

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


def _hit_strategy(db, valid_codes: list) -> set:
    """🤖 策略命中：BSDailyScan 最新一日 signals_json 含本股"""
    from db.models import BSDailyScan
    import json as _json
    if not valid_codes:
        return set()
    rows = db.query(BSDailyScan).filter(
        BSDailyScan.strategy_name.in_(['BS-科创-V7', 'BS-创业-V9'])
    ).order_by(BSDailyScan.trade_date.desc()).limit(10).all()
    if not rows:
        return set()
    latest_date = max(r.trade_date for r in rows)
    today_rows = [r for r in rows if r.trade_date == latest_date]
    hit_set = set()
    for r in today_rows:
        try:
            sigs = _json.loads(r.signals_json or '[]')
        except Exception:
            sigs = []
        for s in sigs:
            raw = s.get('secCode') or s.get('code') or ''
            code = raw.split('.')[0] if raw else ''
            if code in valid_codes:
                hit_set.add(code)
    return hit_set


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
    from sqlalchemy import func
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
        prices = [float(t.price or 0) for t in ticks]
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
        post_inflow = sum(float(t.main_force_inflow or 0) for t in ticks[min_idx+1:])
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
    if {'strategy', 'trend'} <= s:
        return '策略+趋势双确认，突破买点'
    if {'support', 'trend'} <= s:
        return '趋势大单护盘，回踩均线低吸'
    if 'yuzi' in s:
        return '游资共振净买入，关注次日溢价'
    if 'strategy' in s:
        return '量化策略命中，按模式死磕'
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


def _batch_hit_tags(db, stock_codes: list, sectors_map: dict) -> dict:
    """批量计算 7 大命中标签，返回 {ts_code: {hit_tags: [], action_hint: ''}}"""
    if not stock_codes:
        return {}
    valid_codes = [c for c in stock_codes if c and len(c) == 6]
    ts_codes = [f"{c}.SH" if c[0] in ('6', '9') else f"{c}.SZ" for c in valid_codes]
    code_to_ts = {c: (f"{c}.SH" if c[0] in ('6', '9') else f"{c}.SZ") for c in valid_codes}

    # 7 个批量查询（各自 try-except，单个失败不阻塞整体）
    sets = {}
    for name, fn, args in [
        ('yuzi', _hit_yuzi, (db, ts_codes)),
        ('strategy', _hit_strategy, (db, valid_codes)),
        ('trend', _hit_trend, (db, valid_codes)),
        ('capital', _hit_capital, (db, ts_codes)),
        ('popularity', _hit_popularity, (db, sectors_map)),
        ('support', _hit_support, (db, ts_codes)),
        ('accumulation', _hit_accumulation, (db, ts_codes)),
    ]:
        try:
            sets[name] = fn(*args)
        except Exception as e:
            logger.warning(f'_hit_{name} failed: {e}')
            db.rollback()
            sets[name] = set()

    out = {}
    for code in valid_codes:
        ts = code_to_ts[code]
        tags = []
        if ts in sets.get('yuzi', set()):
            tags.append('yuzi')
        if code in sets.get('strategy', set()):
            tags.append('strategy')
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
        out[ts] = {'hit_tags': tags, 'action_hint': _gen_action_hint(tags)}
    return out


logger = logging.getLogger(__name__)
router = APIRouter()


def _calc_junk_for_signal(stock_name: str, quote: dict, sector_trend: dict) -> dict:
    avg_turnover = quote.get('avg_turnover_yi', 0) if quote else 0
    sector_heat = sector_trend.get('latest_heat', 0) if sector_trend.get('available') else 0
    return is_junk_stock(stock_name=stock_name, avg_turnover=avg_turnover, sector_heat=sector_heat)


async def _fetch_stock_data(item, db):
    code = item.stock_code
    quote_task = get_quote(code)
    kline_task = fetch_kline_cached(code, 60)
    quote, klines = await asyncio.gather(quote_task, kline_task, return_exceptions=True)
    if isinstance(quote, Exception):
        quote = None
    if isinstance(klines, Exception):
        klines = []

    stock_name = item.stock_name or (quote['name'] if quote else '')
    ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
    sector = _find_sector_for_stock(db, ts_code)
    sector_trend = _get_sector_trend(db, sector, 7) if sector else {"sector": "", "available": False}

    bs_signal = None
    bs_reasons = []
    try:
        if klines and len(klines) > 0:
            from api.bs_signals import _generate_bs_signals
            bs_signals, *_ = _generate_bs_signals(klines)
            if bs_signals:
                last = bs_signals[-1]
                bs_signal = last.get('type')
                bs_reasons = last.get('reasons', [])
    except Exception as e:
        logger.debug(f"BS signal compute failed for {code}: {e}")

    return {
        'item': item,
        'quote': quote,
        'stock_name': stock_name,
        'sector': sector,
        'sector_trend': sector_trend,
        'bs_signal': bs_signal,
        'bs_reasons': bs_reasons,
    }


async def build_watchlist() -> dict:
    """构建完整自选股数据（耗时操作：164只×行情+K线+板块趋势+BS计算）"""
    with get_db_session() as db:
        items = db.query(Watchlist).order_by(
            Watchlist.sort_order, Watchlist.created_at.desc()
        ).all()

        from services.signal_builder import _get_lifecycle_map
        _wl_ts_codes = [f"{c}.SH" if c[0] in ('6', '9') else f"{c}.SZ"
                        for c in (i.stock_code for i in items) if c and len(c) == 6]
        _lifecycle_map = _get_lifecycle_map(db, _wl_ts_codes)

        # 批量拉所有自选股的最新一日 4 档资金流（一次 IN 查询避免 N+1）
        _moneyflow_map = _batch_moneyflow_map(db, [i.stock_code for i in items if i.stock_code])

        results = []
        BATCH = 20
        for i in range(0, len(items), BATCH):
            batch = items[i:i + BATCH]
            tasks = [_fetch_stock_data(item, db) for item in batch]
            results.extend(await asyncio.gather(*tasks, return_exceptions=True))

        # 批量计算 6 大命中标签（需要 sectors_map，从 results 提取）
        _sectors_map = {}
        for r in results:
            if not isinstance(r, Exception) and r.get('item') and r['item'].stock_code:
                _sectors_map[r['item'].stock_code] = r.get('sector') or ''
        _hit_tags_map = _batch_hit_tags(db, [i.stock_code for i in items if i.stock_code], _sectors_map)

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
            quote = r['quote']
            sector = r['sector']
            sector_trend = r['sector_trend']
            item = r['item']
            stock_name = r['stock_name']

            # 解析当前股的资金流(批量预拉的)
            ts_code_cur = f"{item.stock_code}.SH" if item.stock_code and item.stock_code[0] in ('6', '9') else f"{item.stock_code}.SZ"
            money_flow = _moneyflow_map.get(ts_code_cur) or {'available': False, 'main_net': 0, 'super_large': 0, 'large': 0, 'small': 0, 'tiny': 0, 'turnover_rate': 0}
            main_net_wan = money_flow.get('main_net', 0) or 0

            if sector_trend.get('available'):
                if sector_trend.get('heat_trend') == 'up':
                    sector_heating_count += 1
                    if len(sector_heating_top) < 9:
                        sector_heating_top.append({"code": item.stock_code, "name": stock_name, "heat": round(sector_trend.get("latest_heat", 0), 1)})

            # 资金流入/流出统计：基于个股 4 档资金流(优先) > 板块资金流(降级)
            if money_flow.get('available') and abs(main_net_wan) > 0.01:
                if main_net_wan > 0:
                    inflow_count += 1
                if len(inflow_top) < 9:
                    inflow_top.append({
                        "code": item.stock_code,
                        "name": stock_name,
                        "main_net": round(main_net_wan, 2),
                        "chg": round(quote['changePct'], 2) if quote else 0,
                    })
            elif sector_trend.get('available') and sector_trend.get('flow_direction') == 'inflow':
                inflow_count += 1
                if len(inflow_top) < 9:
                    chg = quote['changePct'] if quote else 0
                    inflow_top.append({"code": item.stock_code, "name": stock_name, "chg": round(chg, 2)})

            if bs_signal == 'B':
                signal_label = '买入'
                signal_color = '#ef4444'
                signal_type = 'ADD'
                buy_count += 1
                if len(buy_top) < 9:
                    buy_top.append({"code": item.stock_code, "name": stock_name})
            elif bs_signal == 'S':
                signal_label = '回避'
                signal_color = '#22c55e'
                signal_type = 'SELL'
                sell_count += 1
            else:
                signal_label = '关注'
                signal_color = '#3b82f6'
                signal_type = 'WATCH'
                watch_count += 1

            price = quote['price'] if quote else 0
            change_pct = quote['changePct'] if quote else 0

            reasons = list(bs_reasons or [])
            if quote:
                reasons.append(f'当日涨跌: {change_pct:+.2f}%')

            positive_factors = []
            negative_factors = []

            if bs_signal == 'B':
                positive_factors.append({'factor': 'BS买入', 'detail': bs_reasons[0] if bs_reasons else 'SuperTrend突破', 'weight': 2})
            if change_pct > 0:
                positive_factors.append({'factor': '当日上涨', 'detail': f'涨幅 {change_pct:+.2f}%', 'weight': 1})
            if sector_trend.get('available') and sector_trend.get('heat_trend') == 'up':
                positive_factors.append({'factor': '板块升温', 'detail': f'板块热度上升至 {sector_trend["latest_heat"]:.1f}', 'weight': 1})
            if sector_trend.get('available') and sector_trend.get('flow_direction') == 'inflow':
                positive_factors.append({'factor': '资金流入', 'detail': f'净流入 {sector_trend["total_net_flow"]:.0f}万', 'weight': 1})

            if bs_signal == 'S':
                negative_factors.append({'factor': 'BS卖出', 'detail': bs_reasons[0] if bs_reasons else 'SuperTrend跌破', 'weight': -2})
            if change_pct < 0:
                negative_factors.append({'factor': '当日下跌', 'detail': f'跌幅 {change_pct:+.2f}%', 'weight': -1})
            if sector_trend.get('available') and sector_trend.get('heat_trend') == 'down':
                negative_factors.append({'factor': '板块降温', 'detail': f'板块热度下降至 {sector_trend["latest_heat"]:.1f}', 'weight': -1})
            if sector_trend.get('available') and sector_trend.get('flow_direction') == 'outflow':
                negative_factors.append({'factor': '资金流出', 'detail': f'净流出 {abs(sector_trend["total_net_flow"]):.0f}万', 'weight': -1})

            score = len(positive_factors) - len(negative_factors)
            reasons.append(f'综合评分: {"看多" if score > 0 else "看空" if score < 0 else "中性"} → {signal_label}')

            signals.append({
                'secCode': item.stock_code,
                'secName': stock_name,
                'signal': signal_type,
                'signalLabel': signal_label,
                'signalColor': signal_color,
                'riskLevel': 'low',
                'score': score,
                'reasons': reasons,
                'positiveFactors': positive_factors,
                'negativeFactors': negative_factors,
                'sector': sector or '',
                'sectorTrend': sector_trend,
                'quote': quote,
                'bsSignal': bs_signal,
                'moneyFlow': money_flow,  # 4 档资金流(主/特大/大/小/散, 单位:万元)
                'hitTags': _hit_tags_map.get(ts_code_cur, {}).get('hit_tags', []),
                'actionHint': _hit_tags_map.get(ts_code_cur, {}).get('action_hint', ''),
                'position': {
                    'profitPct': 0,
                    'posPct': 0,
                    'dayProfit': 0,
                    'dayProfitPct': change_pct,
                    'count': 0,
                    'price': price,
                    'costPrice': 0,
                    'value': 0,
                    'profit': 0,
                },
                'note': item.note,
                'group': item.group_name or '默认',
                'watchlistId': item.id,
                'qualityStatus': item.quality_status or '普通',
                'lifecycleStage': _lifecycle_map.get(
                    f"{item.stock_code}.SH" if item.stock_code[0] in ('6', '9') else f"{item.stock_code}.SZ"
                ) if item.stock_code and len(item.stock_code) == 6 else None,
                'buyPower': calc_buy_power_for_signal(quote, sector_trend, bs_signal),
                'marketState': get_latest_state(item.stock_code) or {'market_state': 'PENDING', 'reasons': ['待计算']},
            })
            # 为上一条 signal 补充 5 维评分（需要 marketState.features）
            last_signal = signals[-1]
            ms_data = last_signal.get('marketState', {})
            ms_features = ms_data.get('features') or {}
            bp_data = last_signal.get('buyPower')
            last_signal['sentiment'] = calc_sentiment(quote, sector_trend, ms_features)
            last_signal['risk'] = calc_risk(ms_features, bp_data, None)
            last_signal['momentum'] = calc_momentum(sector_trend, ms_features)
            last_signal['mainForce'] = calc_main_force(quote, ms_features, sector_trend)
            last_signal['technical'] = calc_technical(ms_features)
            last_signal['sectorResonance'] = calc_sector_resonance(sector_trend, ms_features)

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
        }
        _watchlist_cache["data"] = result
        _watchlist_cache["ts"] = time.time()
        return result


async def refresh_watchlist_cache():
    """后台刷新缓存（stale-while-revalidate）"""
    global _watchlist_refreshing
    if _watchlist_refreshing:
        return
    _watchlist_refreshing = True
    try:
        await build_watchlist()
    except Exception as e:
        logger.warning(f"background watchlist refresh failed: {e}")
    finally:
        _watchlist_refreshing = False


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


@router.get("/api/watchlist")
async def get_watchlist():
    """获取自选股列表（stale-while-revalidate）"""
    now = time.time()
    cached = _watchlist_cache["data"]
    cache_age = now - _watchlist_cache["ts"]

    if cached is not None and cache_age < WATCHLIST_CACHE_TTL:
        return cached

    if cached is not None:
        asyncio.create_task(refresh_watchlist_cache())
        return cached

    return await build_watchlist()


@router.post("/api/watchlist/add")
async def add_to_watchlist(req: AddStockRequest):
    with get_db_session() as db:
        existing = db.query(Watchlist).filter_by(stock_code=req.stockCode).first()
        if existing:
            raise HTTPException(status_code=400, detail="该股票已在自选列表中")
        item = Watchlist(
            stock_code=req.stockCode,
            stock_name=req.stockName,
            note=req.note,
            group_name=req.group,
        )
        db.add(item)
        db.commit()
        reset_watchlist_cache()
        try:
            from api.sync_pkg import trigger_cloud_sync
            trigger_cloud_sync(f"add {req.stockCode}")
        except Exception as e:
            logger.debug(f"cloud sync trigger failed: {e}")
        return {'success': True, 'id': item.id}


@router.delete("/api/watchlist/{stock_code}")
async def remove_from_watchlist(stock_code: str):
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=stock_code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        stock_name = item.stock_name or stock_code
        db.delete(item)
        db.commit()
        reset_watchlist_cache()
        try:
            from api.sync_pkg import trigger_cloud_delete
            trigger_cloud_delete(stock_code, stock_name)
        except Exception as e:
            logger.debug(f"cloud delete trigger failed: {e}")
        return {'success': True}


@router.patch("/api/watchlist/{stock_code}")
async def update_watchlist_note(stock_code: str, note: str = Query('')):
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=stock_code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        item.note = note
        db.commit()
        return {'success': True}


@router.put("/api/watchlist/{code}/note")
async def update_note(code: str, req: UpdateNoteRequest):
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        item.note = req.note[:200]
        db.commit()
        reset_watchlist_cache()
        return {'success': True, 'code': code, 'note': item.note}


@router.put("/api/watchlist/{stock_code}/quality")
async def update_watchlist_quality(stock_code: str, req: UpdateQualityRequest):
    valid = {'劣质', '中性', '偏强', '强势', '极强', '核心', '淘汰', '杂毛', '普通', '合格', '优质'}
    if req.quality_status not in valid:
        raise HTTPException(status_code=400, detail=f"非法质量状态，可选：{','.join(valid)}")
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=stock_code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        item.quality_status = req.quality_status
        db.commit()
        reset_watchlist_cache()
        return {'success': True, 'quality_status': req.quality_status}


@router.post("/api/watchlist/sync-quality")
async def sync_quality_from_market_state():
    """根据 market_state + 特征数据同步 quality_status"""
    from db.models import StockFeaturesDaily
    from sqlalchemy import func as sa_func
    with get_db_session() as db:
        items = db.query(Watchlist).all()
        latest_sub = db.query(
            StockFeaturesDaily.stock_code,
            sa_func.max(StockFeaturesDaily.trade_date).label('latest_date')
        ).filter(
            StockFeaturesDaily.stock_code.in_([i.stock_code for i in items])
        ).group_by(StockFeaturesDaily.stock_code).subquery()

        rows = db.query(StockFeaturesDaily).join(
            latest_sub,
            (StockFeaturesDaily.stock_code == latest_sub.c.stock_code) &
            (StockFeaturesDaily.trade_date == latest_sub.c.latest_date)
        ).all()
        feat_map = {r.stock_code: r for r in rows}

        junk_map = {}
        for item in items:
            stock_name = item.stock_name or ''
            is_junk = 'ST' in stock_name.upper() or '退' in stock_name
            junk_map[item.stock_code] = is_junk

        updated, skipped = 0, 0
        details = []
        for item in items:
            old_q = item.quality_status or '普通'
            if old_q == '淘汰':
                skipped += 1
                continue
            f = feat_map.get(item.stock_code)
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
                new_q = compute_quality_from_features(market_state, features, junk_map[item.stock_code])
            if new_q != old_q:
                item.quality_status = new_q
                updated += 1
                details.append({
                    'code': item.stock_code, 'name': item.stock_name,
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
async def pin_stock(code: str):
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
async def move_single_group(code: str, req: MoveGroupRequest):
    target = (req.target_group or '').strip() or '默认'
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=code).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选股不存在")
        item.group_name = target
        db.commit()
        reset_watchlist_cache()
        return {'success': True, 'code': code, 'group': target}

"""
统一信号构造器：为任意股票代码构造与自选股完全一致的 18 字段 signal 数据结构

共享字段：secCode/secName/signal/signalLabel/signalColor/riskLevel/score/reasons/
         positiveFactors/negativeFactors/sector/sectorTrend/position/marketState/
         buyPower/qualityStatus/quote/bsSignal

被以下 API 共用：
- /api/focus-stocks        重点关注
- /api/screener            智能选股（热度/青龙）
- /api/baihu-screen        白虎V3.0
- /api/leader/system       双引擎决策
- /api/panorama/stocks     板块全景个股
"""
import logging
import time
import asyncio
import json
import httpx
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)
from db.connection import get_db
from api.bs_signals import _fetch_kline, _generate_bs_signals
from api.watchlist._shared import get_quote, fetch_kline_cached
from analyzers.strategy_engine import _find_sector_for_stock, _get_sector_trend
from analyzers.buy_power import calc_buy_power_for_signal
from analyzers.market_state import get_latest_state, compute_quality_from_features
from analyzers.stock_scores import calc_sentiment, calc_risk, calc_momentum, calc_main_force, calc_technical, calc_sector_resonance


# ============================================================
# 生命周期阶段查询（统一入口，所有接口共用，避免重复代码）
# ============================================================
_lifecycle_cache: Dict[str, Optional[str]] = {}
_LIFECYCLE_CACHE_TTL = 300  # 5分钟缓存（LeaderLifecycle 每日更新一次）

def _get_lifecycle_stage(db, ts_code: str) -> Optional[str]:
    """查询单只股票的最新生命周期阶段（LeaderLifecycle 表），带缓存"""
    cached = _lifecycle_cache.get(ts_code)
    if cached and time.time() - cached[1] < _LIFECYCLE_CACHE_TTL:
        return cached[0]
    from db.models import LeaderLifecycle
    _ll = db.query(LeaderLifecycle).filter(
        LeaderLifecycle.ts_code == ts_code
    ).order_by(LeaderLifecycle.trade_date.desc()).first()
    stage = _ll.stage if _ll else None
    _lifecycle_cache[ts_code] = (stage, time.time())
    return stage

def _get_lifecycle_map(db, ts_codes: List[str], trade_date: str = None) -> Dict[str, str]:
    """批量查询多只股票的生命周期阶段（默认取最新交易日），用于批量场景"""
    if not ts_codes:
        return {}
    from db.models import LeaderLifecycle
    from sqlalchemy import func
    if trade_date:
        rows = db.query(LeaderLifecycle).filter(
            LeaderLifecycle.trade_date == trade_date,
            LeaderLifecycle.ts_code.in_(ts_codes),
        ).all()
    else:
        latest_date = db.query(func.max(LeaderLifecycle.trade_date)).scalar()
        if not latest_date:
            return {}
        rows = db.query(LeaderLifecycle).filter(
            LeaderLifecycle.trade_date == latest_date,
            LeaderLifecycle.ts_code.in_(ts_codes),
        ).all()
    return {r.ts_code: r.stage for r in rows}


async def build_signal_for_stock(
    code: str,
    name: str,
    sector_name: str,
    db,
    *,
    stage: Optional[str] = None,
    strength: Optional[float] = None,
    change_rate: Optional[float] = None,
    consecutive_days: Optional[int] = None,
    extra_positive: Optional[List[dict]] = None,
    extra_negative: Optional[List[dict]] = None,
    lifecycle_stage: Optional[str] = None,
) -> dict:
    """为单只股票构造与自选股完全一致的 signal 数据结构

    可选参数用于在基础行情之上叠加策略维度信息（如龙头阶段、强度等）。
    """
    # 并发获取行情和K线
    quote, klines = await asyncio.gather(
        get_quote(code),
        fetch_kline_cached(code, 60),
        return_exceptions=True,
    )
    if isinstance(quote, Exception):
        quote = None
    if isinstance(klines, Exception):
        klines = []

    # 查找板块 + 板块趋势
    ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
    sector = _find_sector_for_stock(db, ts_code) or sector_name
    sector_trend = _get_sector_trend(db, sector, 7) if sector else {"sector": "", "available": False}

    # 自动查 LeaderLifecycle 真实生命周期阶段（调用方未传时 fallback 查询）
    if lifecycle_stage is None:
        lifecycle_stage = _get_lifecycle_stage(db, ts_code)

    # 获取 BS 信号
    bs_signal = None
    bs_reasons = []
    try:
        if klines and len(klines) > 0:
            bs_signals, *_ = _generate_bs_signals(klines)
            if bs_signals:
                last = bs_signals[-1]
                logger.debug('handled exception', exc_info=True)
                bs_reasons = last.get('reasons', [])
    except Exception as e:
        logger.debug(f'生成 BS 信号失败，跳过: {e}')

    price = quote['price'] if quote else 0
    change_pct = quote['changePct'] if quote else (change_rate or 0)

    # 信号标签（与自选股一致：买入/回避/关注）
    if bs_signal == 'B':
        signal_label, signal_color, signal_type = '买入', '#ef4444', 'ADD'
    elif bs_signal == 'S':
        signal_label, signal_color, signal_type = '回避', '#22c55e', 'SELL'
    else:
        signal_label, signal_color, signal_type = '关注', '#3b82f6', 'WATCH'

    # reasons / positiveFactors / negativeFactors
    reasons = []
    positive_factors = []
    negative_factors = []

    if bs_reasons:
        reasons.extend(bs_reasons)
    if quote:
        reasons.append(f'当日涨跌: {change_pct:+.2f}%')
    if stage:
        reasons.append(f'策略阶段: {stage}')

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

    # 策略维度附加因素（兼容新旧命名）
    if stage:
        if stage in ('突破', '加速', '启动', '发酵'):
            positive_factors.append({'factor': f'{stage}阶段', 'detail': f'{stage}阶段龙头', 'weight': 2})
        elif stage == '主升':
            positive_factors.append({'factor': '主升阶段', 'detail': f'{consecutive_days or 0}连板', 'weight': 1})
            negative_factors.append({'factor': '高位风险', 'detail': '连板高度较大，回调风险增加', 'weight': -1})
        elif stage in ('分歧', '衰退', '退潮'):
            negative_factors.append({'factor': f'{stage}阶段', 'detail': f'{stage}阶段，谨慎参与', 'weight': -2})
    if strength and strength > 50:
        positive_factors.append({'factor': '强度领先', 'detail': f'强度评分 {strength:.0f}', 'weight': 1})
    if consecutive_days and consecutive_days >= 3:
        positive_factors.append({'factor': '连板强势', 'detail': f'{consecutive_days}连板', 'weight': 1})

    if extra_positive:
        positive_factors.extend(extra_positive)
    if extra_negative:
        negative_factors.extend(extra_negative)

    score = len(positive_factors) - len(negative_factors)
    reasons.append(f'综合评分: {"看多" if score > 0 else "看空" if score < 0 else "中性"} → {signal_label}')

    # 市场状态 + 购买力 + 质量状态
    market_state_data = get_latest_state(code) or {'market_state': 'PENDING', 'reasons': ['待计算']}
    buy_power = calc_buy_power_for_signal(quote, sector_trend, bs_signal)

    ms = market_state_data.get('market_state', 'PENDING')
    features = market_state_data.get('features') or {}
    is_junk = 'ST' in (name or '').upper() or '退' in (name or '')
    quality_status = compute_quality_from_features(ms, features, is_junk)

    # 6 维状态评分
    pos_dict = None  # signal_builder 不涉及持仓
    sentiment = calc_sentiment(quote, sector_trend, features)
    risk = calc_risk(features, buy_power, pos_dict)
    momentum = calc_momentum(sector_trend, features)
    main_force = calc_main_force(quote, features, sector_trend)
    technical = calc_technical(features)
    sector_resonance = calc_sector_resonance(sector_trend, features)

    return {
        'secCode': code,
        'secName': name,
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
        'position': {
            'profitPct': 0,
            'posPct': 0,
            'dayProfit': 0,
            'dayProfitPct': change_pct,
            'count': consecutive_days or 0,
            'price': price,
            'costPrice': 0,
            'value': 0,
            'profit': 0,
        },
        'qualityStatus': quality_status,
        'buyPower': buy_power,
        'marketState': market_state_data,
        'lifecycleStage': lifecycle_stage,
        'sentiment': sentiment,
        'risk': risk,
        'momentum': momentum,
        'mainForce': main_force,
        'technical': technical,
        'sectorResonance': sector_resonance,
    }


async def build_signals_batch(
    stocks: List[dict],
    db,
    *,
    code_key: str = 'code',
    name_key: str = 'name',
    sector_key: str = 'sector',
    stage_key: Optional[str] = None,
    strength_key: Optional[str] = None,
    change_key: Optional[str] = None,
    days_key: Optional[str] = None,
    batch_size: int = 20,
) -> List[dict]:
    """批量构造 signal 数据（分批并发，避免新浪限流）

    Args:
        stocks: 股票列表（dict）
        code_key/name_key/sector_key: 字段名映射
        stage_key/strength_key/change_key/days_key: 可选的策略维度字段名
        batch_size: 每批并发数
    """
    # 收集所有 ts_code，批量查 LeaderLifecycle 真实生命周期阶段
    _all_ts_codes = []
    for s in stocks:
        code = s.get(code_key) or s.get('ts_code') or s.get('secCode') or ''
        if '.' not in code and len(code) == 6:
            code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
        if '.' in code:
            _all_ts_codes.append(code)
    lifecycle_map = _get_lifecycle_map(db, _all_ts_codes)

    all_signals = []
    for i in range(0, len(stocks), batch_size):
        batch = stocks[i:i + batch_size]
        tasks = []
        for s in batch:
            code = s.get(code_key) or s.get('ts_code') or s.get('secCode') or ''
            # ts_code 形如 "600000.SH"，提取6位数字
            if '.' in code:
                code = code.split('.')[0]
            if not code or len(code) != 6:
                continue
            ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
            name = s.get(name_key) or s.get('secName') or ''
            sector = s.get(sector_key) or ''
            kwargs = {}
            if stage_key and s.get(stage_key):
                kwargs['stage'] = s[stage_key]
            if strength_key and s.get(strength_key) is not None:
                kwargs['strength'] = float(s[strength_key])
            if change_key and s.get(change_key) is not None:
                kwargs['change_rate'] = float(s[change_key])
            if days_key and s.get(days_key) is not None:
                kwargs['consecutive_days'] = int(s[days_key])
            kwargs['lifecycle_stage'] = lifecycle_map.get(ts_code) or '未入选'
            tasks.append(build_signal_for_stock(code, name, sector, db, **kwargs))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if not isinstance(r, Exception) and r is not None:
                all_signals.append(r)
    return all_signals


async def build_signal_from_precomputed(
    code: str,
    name: str,
    precomputed_row,
    *,
    stage: Optional[str] = None,
    strength: Optional[float] = None,
    consecutive_days: Optional[int] = None,
    extra_positive: Optional[List[dict]] = None,
    extra_negative: Optional[List[dict]] = None,
    lifecycle_stage: Optional[str] = None,
    db=None,
) -> dict:
    """从预计算表行 + 实时行情组装 signal（消除 K线/BS/板块/市场状态的现场计算）

    与 build_signal_for_stock 返回结构完全一致，但跳过最慢的部分：
    - 不拉 K线（预计算已存 bs_signal）
    - 不查板块趋势（预计算已存 sector_trend_json）
    - 不查市场状态（预计算已存 market_state_json）
    - 仅拉实时 quote（30s缓存）
    """
    # 实时行情（30s缓存，盘后为收盘价）
    quote = await get_quote(code)

    # 自动查 LeaderLifecycle 真实生命周期阶段（调用方未传时 fallback 查询）
    if lifecycle_stage is None:
        _ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
        if db is not None:
            lifecycle_stage = _get_lifecycle_stage(db, _ts_code)
        else:
            with get_db_session() as _db:
                lifecycle_stage = _get_lifecycle_stage(_db, _ts_code)

    # 从预计算行读数据
    sector = precomputed_row.sector or ''
    sector_trend = json.loads(precomputed_row.sector_trend_json or '{}')
    market_state_data = json.loads(precomputed_row.market_state_json or '{}')
    bs_signal = precomputed_row.bs_signal
    bs_reasons = json.loads(precomputed_row.bs_reasons_json or '[]')
    quality_status = precomputed_row.quality_status
    buy_power = json.loads(precomputed_row.buy_power_base) if precomputed_row.buy_power_base else {'score': 0, 'level': '弱', 'color': '#3b82f6', 'dimensions': {}}
    precomputed_change_rate = float(precomputed_row.change_rate or 0) if precomputed_row.change_rate else 0

    price = quote['price'] if quote else 0
    change_pct = quote['changePct'] if quote else precomputed_change_rate

    # 信号标签
    if bs_signal == 'B':
        signal_label, signal_color, signal_type = '买入', '#ef4444', 'ADD'
    elif bs_signal == 'S':
        signal_label, signal_color, signal_type = '回避', '#22c55e', 'SELL'
    else:
        signal_label, signal_color, signal_type = '关注', '#3b82f6', 'WATCH'

    # reasons / positiveFactors / negativeFactors（与 build_signal_for_stock 一致）
    reasons = []
    positive_factors = []
    negative_factors = []

    if bs_reasons:
        reasons.extend(bs_reasons)
    if quote:
        reasons.append(f'当日涨跌: {change_pct:+.2f}%')
    if stage:
        reasons.append(f'策略阶段: {stage}')

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

    if stage:
        if stage in ('突破', '加速', '启动', '发酵'):
            positive_factors.append({'factor': f'{stage}阶段', 'detail': f'{stage}阶段龙头', 'weight': 2})
        elif stage == '主升':
            positive_factors.append({'factor': '主升阶段', 'detail': f'{consecutive_days or 0}连板', 'weight': 1})
            negative_factors.append({'factor': '高位风险', 'detail': '连板高度较大，回调风险增加', 'weight': -1})
        elif stage in ('分歧', '衰退', '退潮'):
            negative_factors.append({'factor': f'{stage}阶段', 'detail': f'{stage}阶段，谨慎参与', 'weight': -2})
    if strength and strength > 50:
        positive_factors.append({'factor': '强度领先', 'detail': f'强度评分 {strength:.0f}', 'weight': 1})
    if consecutive_days and consecutive_days >= 3:
        positive_factors.append({'factor': '连板强势', 'detail': f'{consecutive_days}连板', 'weight': 1})

    if extra_positive:
        positive_factors.extend(extra_positive)
    if extra_negative:
        negative_factors.extend(extra_negative)

    score = len(positive_factors) - len(negative_factors)
    reasons.append(f'综合评分: {"看多" if score > 0 else "看空" if score < 0 else "中性"} → {signal_label}')

    return {
        'secCode': code,
        'secName': name,
        'signal': signal_type,
        'signalLabel': signal_label,
        'signalColor': signal_color,
        'riskLevel': 'low',
        'score': score,
        'reasons': reasons,
        'positiveFactors': positive_factors,
        'negativeFactors': negative_factors,
        'sector': sector,
        'sectorTrend': sector_trend,
        'quote': quote,
        'bsSignal': bs_signal,
        'position': {
            'profitPct': 0,
            'posPct': 0,
            'dayProfit': 0,
            'dayProfitPct': change_pct,
            'count': consecutive_days or 0,
            'price': price,
            'costPrice': 0,
            'value': 0,
            'profit': 0,
        },
        'qualityStatus': quality_status,
        'buyPower': buy_power,
        'marketState': market_state_data,
        'lifecycleStage': lifecycle_stage,
    }


async def build_signals_from_strategy_result(
    db, strategy_key: str, trade_date: str, *,
    stage: str = '策略选股',
) -> Optional[List[dict]]:
    """从 strategy_result 预计算表读取策略命中，用 WatchlistSignalDaily 富化

    返回 enriched signals 列表；无预计算数据时返回 None（调用方 fallback 现场计算）。
    跳过 K线/BS/板块/市场状态的现场计算，仅拉实时 quote（30s缓存）。
    """
    from db.models import StrategyResult, WatchlistSignalDaily
    from sqlalchemy import func

    rows = db.query(StrategyResult).filter(
        StrategyResult.trade_date == trade_date,
        StrategyResult.strategy_key == strategy_key,
    ).order_by(StrategyResult.score.desc()).all()
    if not rows:
        return None

    ts_codes = [r.ts_code for r in rows]
    latest_date = db.query(func.max(WatchlistSignalDaily.trade_date)).scalar()
    precomputed_map = {}
    if latest_date:
        wl_rows = db.query(WatchlistSignalDaily).filter(
            WatchlistSignalDaily.trade_date == latest_date,
            WatchlistSignalDaily.ts_code.in_(ts_codes),
        ).all()
        for wl_row in wl_rows:
            precomputed_map[wl_row.ts_code] = wl_row

    # 批量查 LeaderLifecycle 真实生命周期阶段（非龙头股查不到则显示"未入选"）
    lifecycle_map = _get_lifecycle_map(db, ts_codes, trade_date)

    tasks = []
    for row in rows:
        code = row.ts_code.split('.')[0] if '.' in row.ts_code else row.ts_code
        precomputed = precomputed_map.get(row.ts_code)
        _lifecycle = lifecycle_map.get(row.ts_code) or '未入选'
        if precomputed:
            tasks.append(build_signal_from_precomputed(
                code, row.name, precomputed,
                stage=stage, strength=float(row.score or 0),
                lifecycle_stage=_lifecycle,
            ))
        else:
            tasks.append(build_signal_for_stock(
                code, row.name, row.sector, db,
                stage=stage, strength=float(row.score or 0),
                lifecycle_stage=_lifecycle,
            ))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    enriched = []
    for i, r in enumerate(results):
        if isinstance(r, Exception) or r is None:
            continue
        row = rows[i]
        detail = json.loads(row.detail_json or '{}')
        r['strategyScore'] = float(row.score or 0)
        r['deviation'] = float(detail.get('deviation', 0))
        r['rsi'] = float(detail.get('rsi', 0))
        r['scores'] = json.loads(row.scores_json or '{}')
        r['lowerShadow'] = float(detail.get('lower_shadow', 0))
        if strategy_key in ('baihu_v26', 'baihu_v30'):
            r['ma20'] = float(detail.get('ma20', 0))
            r['volRatio'] = float(detail.get('vol_ratio', 0))
            r['20dayGain'] = float(detail.get('20day_gain', 0))
        if strategy_key == 'baihu_v30':
            r['strategyMode'] = detail.get('mode', '')
            r['ma5'] = float(detail.get('ma5', 0))
            r['ma10'] = float(detail.get('ma10', 0))
            r['distanceToHigh20'] = float(detail.get('distance_to_high_20', 0))
        if strategy_key == 'zhushenglang':
            r['ma5'] = float(detail.get('ma5', 0))
            r['ma10'] = float(detail.get('ma10', 0))
            r['ma20'] = float(detail.get('ma20', 0))
            r['ma60'] = float(detail.get('ma60', 0))
            r['maSpread'] = float(detail.get('ma_spread', 0))
            r['bias20'] = float(detail.get('bias_20', 0))
            r['continuityDays'] = int(detail.get('continuity_days', 0))
            r['hasMainForce'] = detail.get('has_main_force', False)
            r['exitSignal'] = detail.get('exit_signal')
        if strategy_key == 'wave_band':
            r['ma5'] = float(detail.get('ma5', 0))
            r['ma10'] = float(detail.get('ma10', 0))
            r['ma20'] = float(detail.get('ma20', 0))
            r['rsi6'] = float(detail.get('rsi6') or 0)
            r['volRatio'] = float(detail.get('vol_ratio', 0))
            r['changePct'] = float(detail.get('change_pct', 0))
            r['confidence'] = float(detail.get('confidence', 0))
            r['waveReason'] = detail.get('reason', '')
            r['waveSignal'] = detail.get('signal', 'buy')
        if strategy_key == 'liangjia_report':
            # 量价报告策略：5种形态 + 3层分层 + 交易计划
            r['pattern'] = detail.get('pattern', '')
            r['patternDesc'] = detail.get('pattern_desc', '')
            r['tier'] = detail.get('tier', '')
            r['tierLabel'] = detail.get('tier_label', '')
            r['gain5d'] = float(detail.get('gain5d', 0))
            r['gain20d'] = float(detail.get('gain20d', 0))
            r['volRatio20'] = float(detail.get('vol_ratio_20', 0))
            r['distanceToHigh20'] = float(detail.get('distance_to_high_20', 0))
            r['deviationMa20'] = float(detail.get('deviation_ma20', 0))
            r['deviationMa5'] = float(detail.get('deviation_ma5', 0))
            r['ma5'] = float(detail.get('ma5', 0))
            r['ma10'] = float(detail.get('ma10', 0))
            r['ma20'] = float(detail.get('ma20', 0))
            r['ma20Rising'] = bool(detail.get('ma20_rising', False))
            r['bullAlignment'] = bool(detail.get('bull_alignment', False))
            r['tradePlan'] = detail.get('trade_plan', {})
            r['strategyMode'] = detail.get('pattern', '')  # 复用 SignalCard 模式标签
        enriched.append(r)

    # 补充自选股个股模块字段（moneyFlow/hitTags/actionHint），让 SignalCard 显示完整信息
    await _enrich_signals_with_watchlist_extras(db, enriched)
    return enriched


# 缓存 _enrich_signals_with_watchlist_extras 的中间结果（moneyflow_map + hit_tags_map）
# 这些都是盘后数据，2 分钟内不会变化；避免 81 只股票的 11+ 次 DB 查询重复执行（首次 6-9s → 命中 <100ms）
_enrich_extras_cache = {}  # key: frozenset(codes) -> (timestamp, moneyflow_map, hit_tags_map)
_ENRICH_EXTRAS_CACHE_TTL = 120  # 2 分钟


async def _enrich_signals_with_watchlist_extras(db, signals: List[dict]) -> None:
    """为 signal 列表批量补充自选股个股模块的 3 个字段（原地修改）：
    - moneyFlow: 4 档资金流 + 1/2/3/4/5 日累计（盘后数据）
    - hitTags:   7 大命中标签（yuzi/strategy/trend/capital/popularity/support/accumulation）
    - actionHint: 根据命中标签组合生成的操作方向文案

    与自选股 build_watchlist 完全一致的口径，确保 SignalCard 中列资金流向模块和 HitTagBar 正常渲染。
    """
    if not signals:
        return
    # 复用 watchlist.core 的批量函数，保证口径一致
    from api.watchlist.core import _batch_moneyflow_map, _batch_hit_tags

    stock_codes = [s.get('secCode') for s in signals if s.get('secCode')]
    if not stock_codes:
        return

    # 检查缓存（盘后数据，2 分钟 TTL）
    cache_key = frozenset(stock_codes)
    now = time.time()
    cached = _enrich_extras_cache.get(cache_key)
    if cached and now - cached[0] < _ENRICH_EXTRAS_CACHE_TTL:
        moneyflow_map, hit_tags_map = cached[1], cached[2]
    else:
        # 批量拉资金流 + 命中标签（11+ 次 DB 查询，首次 6-9s）
        moneyflow_map = _batch_moneyflow_map(db, stock_codes)
        sectors_map = {s.get('secCode'): s.get('sector', '') for s in signals}
        hit_tags_map = _batch_hit_tags(db, stock_codes, sectors_map)
        _enrich_extras_cache[cache_key] = (now, moneyflow_map, hit_tags_map)

    for s in signals:
        code = s.get('secCode')
        if not code or len(code) != 6:
            continue
        ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
        # moneyFlow（缺失时给空壳，前端显示"暂无盘后数据"）；浅拷贝避免污染缓存
        if 'moneyFlow' not in s or not s.get('moneyFlow'):
            mf = moneyflow_map.get(ts_code)
            s['moneyFlow'] = dict(mf) if mf else {
                'available': False, 'main_net': 0, 'super_large': 0,
                'large': 0, 'small': 0, 'tiny': 0, 'turnover_rate': 0,
                'inflow_1d': 0, 'inflow_2d': 0, 'inflow_3d': 0,
                'inflow_4d': 0, 'inflow_5d': 0, 'flow_continuity': 0,
            }
        # hitTags + actionHint；浅拷贝 list 避免污染缓存
        hit_info = hit_tags_map.get(ts_code, {})
        s.setdefault('hitTags', list(hit_info.get('hit_tags', [])))
        s.setdefault('actionHint', hit_info.get('action_hint', ''))
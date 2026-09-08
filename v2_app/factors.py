from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean, pstdev
from typing import Mapping, Sequence

from .alpha158 import alpha158_definitions, calculate_alpha158
from .domain import Bar, FactorDefinition, MarketContext


DIMENSION_LABELS = {
    "market": "市场环境",
    "sector": "板块主线",
    "strength": "个股强度",
    "trend": "趋势结构",
    "volume_price": "量价行为",
    "position": "交易位置",
    "risk": "风险质量",
}

FACTOR_STATUS_LABELS = {
    "candidate": "候选因子",
    "observation": "观察因子",
    "production": "生产因子",
    "suspended": "停用因子",
    "retired": "淘汰因子",
}

FACTOR_STATUSES = tuple(FACTOR_STATUS_LABELS)


def _defs() -> list[FactorDefinition]:
    f = FactorDefinition
    return [
        # 市场环境
        f("market_breadth", "上涨家数比例", "market", "全市场日线", "上涨家数/有效股票数", ("pct_chg",), 1, 1),
        f("market_limit_balance", "涨跌停结构", "market", "全市场日线", "(涨停数-跌停数)/(涨停数+跌停数+10)", ("pct_chg",), 1, 1),
        f("market_trend_20d", "市场20日趋势", "market", "全市场截面", "有效股票平均20日收益", ("close",), 20, 1),
        f("market_sentiment", "市场情绪", "market", "市场结构", "宽度/涨跌停综合情绪", ("pct_chg",), 1, 1),

        # 板块主线
        f("sector_rank", "行业排名", "sector", "个股横截面", "行业平均20日收益百分位", ("close", "sector"), 20, 1),
        f("sector_return_5d", "板块5日涨幅", "sector", "个股横截面", "行业平均5日收益", ("close", "sector"), 5, 1),
        f("sector_return_20d", "板块20日涨幅", "sector", "个股横截面", "行业平均20日收益", ("close", "sector"), 20, 1),
        f("sector_fund_flow", "板块资金", "sector", "sector_flow", "板块净流入截面百分位", ("net_flow", "sector"), 1, 1),
        f("sector_strength", "板块强度", "sector", "sector_flow+日线", "涨幅/上涨率/热度综合", ("pct_chg", "sector"), 5, 1),

        # 个股相对强度
        f("return_20d", "个股20日收益", "strength", "stock_daily_kline", "close[t]/close[t-20]-1", ("close",), 20, 1),
        f("return_60d", "个股60日收益", "strength", "stock_daily_kline", "close[t]/close[t-60]-1", ("close",), 60, 1),
        f("relative_index_20d", "相对市场强度", "strength", "全市场截面", "个股20日收益-市场20日收益", ("close",), 20, 1),
        f("relative_sector_20d", "相对行业强度", "strength", "行业截面", "个股20日收益-行业20日收益", ("close", "sector"), 20, 1),
        f("sector_inner_rank", "板块内部排名", "strength", "行业截面", "个股20日收益行业内百分位", ("close", "sector"), 20, 1),

        # 趋势结构
        f("ma_alignment", "均线排列", "trend", "stock_daily_kline", "MA5>MA10>MA20", ("close",), 20, 1),
        f("ma20_slope", "MA20斜率", "trend", "stock_daily_kline", "近5个MA20斜率/价格", ("close",), 25, 1),
        f("new_high_20d", "20日新高突破", "trend", "stock_daily_kline", "收盘价突破前20日高点", ("high", "close"), 20, 1),
        f("trend_continuity", "趋势连续性", "trend", "stock_daily_kline", "近20日上涨日比例", ("close",), 20, 1),

        # 量价行为
        f("up_volume_ratio", "上涨放量", "volume_price", "stock_daily_kline", "上涨日均量/20日均量", ("close", "volume"), 20, 1),
        f("pullback_volume_shrink", "回调缩量", "volume_price", "stock_daily_kline", "回调日均量/前期均量", ("close", "volume"), 20, -1),
        f("volume_change", "成交量变化", "volume_price", "stock_daily_kline", "量比20日均量", ("volume",), 20, 1),
        f("price_volume_corr", "量价相关性", "volume_price", "stock_daily_kline", "收益与成交量20日相关系数", ("close", "volume"), 20, 1),

        # 交易位置
        f("distance_high_20d", "距离阶段高点", "position", "stock_daily_kline", "close/max(high,20)-1", ("close", "high"), 20, 1),
        f("distance_ma20", "距离MA20", "position", "stock_daily_kline", "-abs(close/MA20-1)", ("close",), 20, 1),
        f("pullback_depth", "回踩深度", "position", "stock_daily_kline", "close/max(close,20)-1", ("close",), 20, 1),
        f("breakout_days", "突破后天数", "position", "stock_daily_kline", "距20日高点的交易日数", ("high",), 20, -1),
        f("risk_reward", "盈亏比", "position", "stock_daily_kline", "向上空间/(2ATR)", ("high", "low", "close"), 60, 1),

        # 风险质量：风险分高代表风险较低，仅作为闸门和负向惩罚。
        f("volatility_20d", "20日波动率", "risk", "stock_daily_kline", "20日收益标准差", ("close",), 20, -1),
        f("drawdown_60d", "60日回撤", "risk", "stock_daily_kline", "close/max(close,60)-1", ("close",), 60, 1),
        f("high_position_risk", "高位风险", "risk", "stock_daily_kline", "接近阶段高点且短期过热", ("close", "high"), 20, -1),
        f("abnormal_volatility", "异常波动", "risk", "stock_daily_kline", "近20日极端波动比例", ("pct_chg",), 20, -1),
    ]


# The first block is the existing A-share right-side feature set.  The local
# Qlib Alpha158 mapping is appended as candidate formulas; lifecycle status,
# not implementation order, controls whether a factor enters the score.
BASE_FACTOR_CATALOG = _defs()
BASE_FACTOR_NAMES = frozenset(item.name for item in BASE_FACTOR_CATALOG)
FACTOR_CATALOG = BASE_FACTOR_CATALOG + alpha158_definitions()
# Kept as an alias so older V2 imports continue to work.  This is a catalogue,
# not an assertion that every formula is production.
PRODUCTION_FACTORS = FACTOR_CATALOG
FACTOR_BY_NAME = {item.name: item for item in FACTOR_CATALOG}


def _mean(values: Sequence[float]) -> float | None:
    return mean(values) if values else None


def _ret(closes: Sequence[float], period: int) -> float | None:
    if len(closes) <= period or not closes[-period - 1]:
        return None
    return closes[-1] / closes[-period - 1] - 1


def _corr(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    lx, rx = mean(left), mean(right)
    ld = sum((x - lx) ** 2 for x in left) ** 0.5
    rd = sum((x - rx) ** 2 for x in right) ** 0.5
    return sum((a - lx) * (b - rx) for a, b in zip(left, right)) / (ld * rd) if ld and rd else None


def _slope(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    xbar = (len(values) - 1) / 2
    ybar = mean(values)
    den = sum((i - xbar) ** 2 for i in range(len(values)))
    return sum((i - xbar) * (v - ybar) for i, v in enumerate(values)) / den if den else None


def _atr(bars: Sequence[Bar], period: int = 14) -> float | None:
    if len(bars) < period + 1 or not bars[-1].close:
        return None
    tr = []
    for prev, cur in zip(bars[-period - 1:-1], bars[-period:]):
        tr.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return mean(tr) / bars[-1].close if tr else None


def _percentile(values: Sequence[float], value: float) -> float:
    if len(values) < 2:
        return 50.0
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return 100.0 * (below + equal / 2) / len(values)


def _sector_key(bar: Bar) -> str:
    return bar.sector.strip() if bar.sector else "未分类"


def calculate_raw(
    history: Mapping[str, Sequence[Bar]],
    market: MarketContext,
    sector_flow: Mapping[str, Mapping[str, float | None]],
    include_candidate: bool = False,
) -> dict[str, dict[str, float | None]]:
    """Calculate date-bounded raw factors for every eligible stock.

    Candidate Alpha158 formulas are available to research jobs but are not
    evaluated on every dashboard refresh.  This keeps the operational path
    responsive while preserving a reproducible full-catalog research path.
    """

    stock_20: dict[str, float | None] = {}
    stock_60: dict[str, float | None] = {}
    sector_returns: dict[str, list[float]] = defaultdict(list)
    sector_returns_5: dict[str, list[float]] = defaultdict(list)
    for code, bars in history.items():
        closes = [bar.close for bar in bars]
        r20, r60 = _ret(closes, 20), _ret(closes, 60)
        stock_20[code], stock_60[code] = r20, r60
        sector = _sector_key(bars[-1]) if bars else "未分类"
        if r20 is not None:
            sector_returns[sector].append(r20)
        r5 = _ret(closes, 5)
        if r5 is not None:
            sector_returns_5[sector].append(r5)

    sector_20 = {key: _mean(value) for key, value in sector_returns.items()}
    sector_5 = {key: _mean(value) for key, value in sector_returns_5.items()}
    sector_rank_values = [value for value in sector_20.values() if value is not None]

    result: dict[str, dict[str, float | None]] = {}
    market_limit_balance = (market.limit_up - market.limit_down) / (market.limit_up + market.limit_down + 10)
    sentiment_raw = max(0.0, min(1.0, market.breadth * 0.65 + (market_limit_balance + 1) / 2 * 0.20 + (0.15 if market.state == "STRONG" else 0.05 if market.state == "RANGE" else 0.0)))
    for code, source_bars in history.items():
        bars = list(source_bars)
        if not bars:
            continue
        latest = bars[-1]
        closes = [bar.close for bar in bars]
        highs = [bar.high for bar in bars]
        volumes = [bar.volume for bar in bars]
        daily_returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
        changes = [bar.pct_chg * 100 if abs(bar.pct_chg) <= 1 else bar.pct_chg for bar in bars]
        sector = _sector_key(latest)
        s20 = sector_20.get(sector)
        s5 = sector_5.get(sector)
        ma5 = _mean(closes[-5:]) if len(closes) >= 5 else None
        ma10 = _mean(closes[-10:]) if len(closes) >= 10 else None
        ma20 = _mean(closes[-20:]) if len(closes) >= 20 else None
        ma20_series = [_mean(closes[i - 19:i + 1]) for i in range(max(19, len(closes) - 5), len(closes))] if len(closes) >= 20 else []
        high20 = max(highs[-20:]) if len(highs) >= 20 else None
        high60 = max(highs[-60:]) if len(highs) >= 60 else None
        recent_down_volume = [bar.volume for prev, bar in zip(bars[-5:-1], bars[-4:]) if bar.close < prev.close]
        prior_volume = _mean(volumes[-25:-5]) if len(volumes) >= 25 else None
        recent_volume = _mean(volumes[-5:]) if len(volumes) >= 5 else None
        atr_pct = _atr(bars)
        r20, r60 = stock_20[code], stock_60[code]
        breakout_days = None
        if len(highs) >= 21:
            prior_highs = highs[-21:-1]
            max_prior = max(prior_highs)
            if latest.close >= max_prior:
                breakout_days = 0.0
            else:
                last_high_idx = max(i for i, value in enumerate(prior_highs) if value == max_prior)
                breakout_days = float(len(prior_highs) - 1 - last_high_idx)
        up_vol = [bar.volume for prev, bar in zip(bars[-20:-1], bars[-19:]) if bar.close > prev.close]
        rr = None
        if high60 and latest.close and atr_pct:
            upside = max(high60 / latest.close - 1, 0.0)
            rr = upside / max(atr_pct * 2, 0.01)
        raw = {
            "market_breadth": market.breadth,
            "market_limit_balance": market_limit_balance,
            "market_trend_20d": market.market_return_20d,
            "market_sentiment": sentiment_raw,
            "sector_rank": _percentile(sector_rank_values, s20) if s20 is not None else None,
            "sector_return_5d": s5,
            "sector_return_20d": s20,
            "sector_fund_flow": sector_flow.get(sector, {}).get("net_flow_percentile"),
            "sector_strength": sector_flow.get(sector, {}).get("strength"),
            "return_20d": r20,
            "return_60d": r60,
            "relative_index_20d": r20 - market.market_return_20d if r20 is not None and market.market_return_20d is not None else None,
            "relative_sector_20d": r20 - s20 if r20 is not None and s20 is not None else None,
            "sector_inner_rank": _percentile(sector_returns.get(sector, []), r20) if r20 is not None else None,
            "ma_alignment": 1.0 if ma5 is not None and ma10 is not None and ma20 is not None and ma5 > ma10 > ma20 else 0.0 if ma20 is not None else None,
            "ma20_slope": _slope(ma20_series) / latest.close if len(ma20_series) >= 2 and latest.close else None,
            "new_high_20d": 1.0 if len(highs) >= 21 and latest.close >= max(highs[-21:-1]) else 0.0 if len(highs) >= 21 else None,
            "trend_continuity": _mean([1.0 if value > 0 else 0.0 for value in daily_returns[-20:]]) if len(daily_returns) >= 20 else None,
            "up_volume_ratio": _mean(up_vol) / _mean(volumes[-20:]) if up_vol and len(volumes) >= 20 and _mean(volumes[-20:]) else None,
            "pullback_volume_shrink": _mean(recent_down_volume) / prior_volume if recent_down_volume and prior_volume else None,
            "volume_change": latest.volume / _mean(volumes[-20:]) if len(volumes) >= 20 and _mean(volumes[-20:]) else None,
            "price_volume_corr": _corr(daily_returns[-20:], volumes[-20:]) if len(daily_returns) >= 20 else None,
            "distance_high_20d": latest.close / high20 - 1 if high20 else None,
            "distance_ma20": -(abs(latest.close / ma20 - 1)) if ma20 else None,
            "pullback_depth": latest.close / max(closes[-20:]) - 1 if len(closes) >= 20 else None,
            "breakout_days": breakout_days,
            "risk_reward": rr,
            "volatility_20d": pstdev(daily_returns[-20:]) if len(daily_returns) >= 20 else None,
            "drawdown_60d": latest.close / max(closes[-60:]) - 1 if len(closes) >= 60 else None,
            "high_position_risk": 1.0 if high20 and latest.close / high20 >= 0.97 and (_ret(closes, 5) or 0) >= 0.10 else 0.0 if high20 else None,
            "abnormal_volatility": sum(abs(value) >= 0.095 for value in changes[-20:]) / 20 if len(changes) >= 20 else None,
        }
        if include_candidate:
            raw.update(calculate_alpha158(bars))
        result[code] = raw
    return result


def factor_registry_payload() -> list[dict]:
    return [
        {
            "name": item.name,
            "label": item.label,
            "category": item.category,
            "category_label": DIMENSION_LABELS[item.category],
            "source": item.source,
            "formula": item.formula,
            "inputs": list(item.inputs),
            "period": item.period,
            "direction": item.direction,
            "status": item.status,
            "status_label": FACTOR_STATUS_LABELS[item.status],
            "validity": item.validity,
            "allow_production": item.allow_production,
            "production": item.production,
        }
        for item in FACTOR_CATALOG
    ]

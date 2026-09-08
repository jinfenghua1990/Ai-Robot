"""US Quant System — 三套独立策略评分

按照文档实现：
1. breakout_score — 平台突破 Breakout V1
2. pullback_score — 趋势回踩 Pullback V1
3. earnings_gap_score — 财报跳空 Earnings Gap V1

三套策略独立评分，不共用总分。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BreakoutScore:
    total: float = 0.0
    market: float = 0.0
    sector: float = 0.0
    trend: float = 0.0
    platform: float = 0.0
    relative_strength: float = 0.0
    volume: float = 0.0
    intraday: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


@dataclass
class PullbackScore:
    total: float = 0.0
    market: float = 0.0
    sector: float = 0.0
    mid_trend: float = 0.0
    pullback_position: float = 0.0
    contraction_quality: float = 0.0
    trigger: float = 0.0
    relative_strength: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


@dataclass
class EarningsGapScore:
    total: float = 0.0
    event_quality: float = 0.0
    price_reaction: float = 0.0
    volume: float = 0.0
    gap_hold: float = 0.0
    sector: float = 0.0
    intraday: float = 0.0
    risk: float = 0.0
    catalyst_grade: str = ""  # A / B / low
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


# ─── 平台突破 Breakout V1 ────────────────────────────────────────────────────

def score_breakout(
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    high_52w: Optional[float] = None,
    base_high: Optional[float] = None,     # 平台高点
    base_low: Optional[float] = None,      # 平台低点
    base_days: Optional[int] = None,       # 整理天数
    avg_dollar_volume: Optional[float] = None,
    current_volume: Optional[float] = None,
    avg_volume: Optional[float] = None,
    rel_volume: Optional[float] = None,    # 相对成交量
    rsi: Optional[float] = None,
    change_pct_today: Optional[float] = None,
    sector_aligned: bool = False,
    market_mult: float = 1.0,
    sector_mult: float = 1.0,
    above_vwap: bool = False,
    above_opening_range: bool = False,
    relative_spy_strong: bool = False,
    earnings_soon: bool = False,
) -> BreakoutScore:
    """评分 Breakout 策略"""
    result = BreakoutScore()
    reasons = []

    # ─── 硬条件检查 ───
    if price is None:
        return BreakoutScore(hard_pass=False, hard_fail_reasons=["无价格数据"])
    if ema10 and price <= ema10:
        reasons.append(f"价格 {price:.2f} <= EMA10 {ema10:.2f}")
    if ema10 and ema20 and ema10 <= ema20:
        reasons.append(f"EMA10 {ema10:.2f} <= EMA20 {ema20:.2f}")
    if ema20 and ma50 and ema20 <= ma50:
        reasons.append(f"EMA20 {ema20:.2f} <= MA50 {ma50:.2f}")
    if ma50 and ma50 <= 0:
        pass  # 无法判断MA50方向
    if high_52w and price and (high_52w - price) / high_52w > 0.15:
        reasons.append(f"距52周高点 {(high_52w-price)/high_52w*100:.1f}% > 15%")
    if base_days is not None and (base_days < 5 or base_days > 20):
        reasons.append(f"整理天数 {base_days} 不在 5-20 天范围")
    if change_pct_today and change_pct_today > 8:
        reasons.append(f"当日已涨 {change_pct_today:.1f}% > 8%")
    if earnings_soon:
        reasons.append("未来1-2日有财报")

    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result

    result.hard_pass = True

    # ─── 评分 ───
    # 市场 (10分)
    result.market = 10.0 * market_mult

    # 行业 (10分)
    result.sector = 10.0 * sector_mult

    # 趋势 (20分)
    trend_score = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50:
            trend_score = 20.0
        elif price > ema10 > ema20:
            trend_score = 15.0
        elif price > ema10:
            trend_score = 10.0
        else:
            trend_score = 5.0
    result.trend = trend_score

    # 平台质量 (20分)
    platform_score = 0.0
    if base_high and base_low and base_days:
        range_pct = (base_high - base_low) / base_high * 100
        if range_pct < 10:
            platform_score = 20.0
        elif range_pct < 15:
            platform_score = 15.0
        elif range_pct < 20:
            platform_score = 10.0
        else:
            platform_score = 5.0
        # 整理天数加分
        if 10 <= base_days <= 15:
            platform_score = min(20, platform_score + 3)
    result.platform = platform_score

    # 相对强度 (15分)
    rs_score = 0.0
    if relative_spy_strong:
        rs_score += 10.0
    if rsi and 50 <= rsi <= 70:
        rs_score += 5.0
    elif rsi and rsi > 70:
        rs_score += 2.0
    result.relative_strength = rs_score

    # 突破量能 (10分)
    vol_score = 0.0
    if rel_volume and rel_volume >= 1.5:
        vol_score = 10.0
    elif rel_volume and rel_volume >= 1.2:
        vol_score = 7.0
    elif rel_volume and rel_volume >= 1.0:
        vol_score = 5.0
    result.volume = vol_score

    # 盘中确认 (10分)
    intraday_score = 0.0
    if above_vwap:
        intraday_score += 5.0
    if above_opening_range:
        intraday_score += 3.0
    if sector_aligned:
        intraday_score += 2.0
    result.intraday = intraday_score

    # 风险 (5分) — 高分表示低风险
    risk_score = 5.0
    if change_pct_today and change_pct_today > 5:
        risk_score -= 2.0
    result.risk = max(0, risk_score)

    result.total = round(
        result.market + result.sector + result.trend + result.platform +
        result.relative_strength + result.volume + result.intraday + result.risk, 1
    )
    result.details = {
        "market_mult": market_mult,
        "sector_mult": sector_mult,
        "rel_volume": rel_volume,
        "rsi": rsi,
        "above_vwap": above_vwap,
        "above_opening_range": above_opening_range,
    }
    return result


# ─── 趋势回踩 Pullback V1 ────────────────────────────────────────────────────

def score_pullback(
    price: Optional[float] = None,
    ema5: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    pullback_pct: Optional[float] = None,    # 回撤幅度
    prior_uptrend: bool = False,              # 前期有上涨段
    first_pullback: bool = False,             # 首次回调
    volume_contracted: bool = False,          # 回调缩量
    no_consecutive_bearish: bool = False,     # 无连续放量长阴
    re_above_ema5: bool = False,
    re_above_ema10: bool = False,
    break_prev_high: bool = False,
    break_15min_downtrend: bool = False,
    re_above_vwap: bool = False,
    sector_aligned: bool = False,
    relative_spy_strong: bool = False,
    earnings_soon: bool = False,
    market_mult: float = 1.0,
    sector_mult: float = 1.0,
    stop_distance_pct: Optional[float] = None,
) -> PullbackScore:
    """评分 Pullback 策略"""
    result = PullbackScore()
    reasons = []

    if price is None:
        return PullbackScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件
    if ema10 and ema20 and ma50 and not (ema10 > ema20 > ma50):
        reasons.append("均线排列不符合 EMA10 > EMA20 > MA50")
    if not prior_uptrend:
        reasons.append("前期无上涨段")
    if not first_pullback and first_pullback is not None:
        reasons.append("非首次或第二次回调")
    if pullback_pct is not None and (pullback_pct < 3 or pullback_pct > 10):
        reasons.append(f"回撤 {pullback_pct:.1f}% 不在 3%-10% 范围")
    if not volume_contracted:
        reasons.append("未缩量")
    if not no_consecutive_bearish:
        reasons.append("有连续放量长阴")
    if stop_distance_pct is not None and stop_distance_pct > 6:
        reasons.append(f"止损距离 {stop_distance_pct:.1f}% > 6%")
    if earnings_soon:
        reasons.append("临近财报")

    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result

    result.hard_pass = True

    # 市场 (10分)
    result.market = 10.0 * market_mult

    # 行业 (15分)
    result.sector = 15.0 * sector_mult

    # 中期趋势 (20分)
    trend_score = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50:
            trend_score = 20.0
        elif ema10 > ema20 > ma50:
            trend_score = 15.0
        elif ema20 > ma50:
            trend_score = 10.0
        else:
            trend_score = 5.0
    result.mid_trend = trend_score

    # 回踩位置 (20分)
    pos_score = 0.0
    if ema10 and price and abs(price - ema10) / ema10 < 0.02:
        pos_score = 20.0
    elif ema20 and price and abs(price - ema20) / ema20 < 0.03:
        pos_score = 15.0
    elif ma50 and price and abs(price - ma50) / ma50 < 0.03:
        pos_score = 10.0
    else:
        pos_score = 5.0
    result.pullback_position = pos_score

    # 缩量质量 (15分)
    result.contraction_quality = 15.0 if volume_contracted else 5.0

    # 转强触发 (10分)
    trigger_score = 0.0
    if re_above_ema5 or re_above_ema10:
        trigger_score += 3.0
    if break_prev_high:
        trigger_score += 3.0
    if break_15min_downtrend:
        trigger_score += 2.0
    if re_above_vwap:
        trigger_score += 2.0
    result.trigger = min(10, trigger_score)

    # 相对强度 (5分)
    result.relative_strength = 5.0 if relative_spy_strong else 2.0

    # 风险 (5分)
    result.risk = 5.0

    result.total = round(
        result.market + result.sector + result.mid_trend + result.pullback_position +
        result.contraction_quality + result.trigger + result.relative_strength + result.risk, 1
    )
    result.details = {
        "market_mult": market_mult,
        "sector_mult": sector_mult,
        "pullback_pct": pullback_pct,
        "re_above_ema5": re_above_ema5,
        "re_above_ema10": re_above_ema10,
        "break_prev_high": break_prev_high,
    }
    return result


# ─── 财报跳空 Earnings Gap V1 ────────────────────────────────────────────────

def score_earnings_gap(
    price: Optional[float] = None,
    gap_pct: Optional[float] = None,          # 跳空幅度
    volume_ratio: Optional[float] = None,      # 成交量倍数
    first_day_close_strong: bool = False,      # 首日收盘位置强
    gap_not_filled: bool = False,              # 缺口未回补
    event_source_reliable: bool = False,       # 事件来源可靠
    catalyst_grade: str = "",                  # A/B/low
    next_day_break_high: bool = False,         # 次日突破首日高点
    pullback_gap_hold: bool = False,           # 缩量回踩不破缺口
    re_above_vwap: bool = False,
    sector_aligned: bool = False,
    market_mult: float = 1.0,
    risk_mult: float = 1.0,
) -> EarningsGapScore:
    """评分 Earnings Gap 策略"""
    result = EarningsGapScore(catalyst_grade=catalyst_grade)
    reasons = []

    if price is None:
        return EarningsGapScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件
    if gap_pct is None or gap_pct < 5:
        reasons.append(f"跳空幅度 {gap_pct}% < 5%")
    if volume_ratio is None or volume_ratio < 2:
        reasons.append(f"成交量倍数 {volume_ratio} < 2")
    if not first_day_close_strong:
        reasons.append("首日收盘位置不强")
    if not gap_not_filled:
        reasons.append("缺口已回补")
    if not event_source_reliable:
        reasons.append("事件来源不可靠")
    if catalyst_grade == "low":
        reasons.append("低质量催化，不得自动交易")

    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result

    result.hard_pass = True

    # 事件质量 (25分)
    event_score = 0.0
    if catalyst_grade == "A":
        event_score = 25.0
    elif catalyst_grade == "B":
        event_score = 15.0
    else:
        event_score = 10.0
    result.event_quality = event_score

    # 价格反应 (20分)
    price_score = 0.0
    if gap_pct and gap_pct >= 10:
        price_score = 20.0
    elif gap_pct and gap_pct >= 7:
        price_score = 15.0
    else:
        price_score = 10.0
    result.price_reaction = price_score

    # 成交量 (15分)
    vol_score = 0.0
    if volume_ratio and volume_ratio >= 5:
        vol_score = 15.0
    elif volume_ratio and volume_ratio >= 3:
        vol_score = 12.0
    elif volume_ratio and volume_ratio >= 2:
        vol_score = 8.0
    result.volume = vol_score

    # 缺口保持 (15分)
    gap_score = 0.0
    if gap_not_filled:
        gap_score = 10.0
    if pullback_gap_hold:
        gap_score += 5.0
    result.gap_hold = gap_score

    # 行业 (10分)
    result.sector = 10.0 * market_mult

    # 盘中确认 (10分)
    intraday_score = 0.0
    if next_day_break_high:
        intraday_score += 5.0
    if re_above_vwap:
        intraday_score += 3.0
    if sector_aligned:
        intraday_score += 2.0
    result.intraday = intraday_score

    # 风险 (5分)
    result.risk = 5.0 * risk_mult

    result.total = round(
        result.event_quality + result.price_reaction + result.volume +
        result.gap_hold + result.sector + result.intraday + result.risk, 1
    )
    result.details = {
        "market_mult": market_mult,
        "risk_mult": risk_mult,
        "gap_pct": gap_pct,
        "volume_ratio": volume_ratio,
        "catalyst_grade": catalyst_grade,
        "next_day_break_high": next_day_break_high,
        "pullback_gap_hold": pullback_gap_hold,
    }
    return result
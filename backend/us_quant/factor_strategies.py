"""US Quant System — 基于因子库的新策略评分

新增4套独立策略：
1. Momentum Factor V1 — 动量因子策略
2. Low Volatility V1 — 低波动率策略
3. Volume-Price V1 — 量价共振策略
4. Mean Reversion V1 — 均值回归策略
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ====================================================================
# 1. 动量因子策略 Momentum Factor V1
# ====================================================================

@dataclass
class MomentumFactorScore:
    total: float = 0.0
    momentum_12_1: float = 0.0
    momentum_risk_adjusted: float = 0.0
    momentum_6m: float = 0.0
    reversal_1w: float = 0.0
    reversal_1m: float = 0.0
    trend_alignment: float = 0.0
    volume_confirmation: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_momentum_factor(
    # 动量因子值
    momentum_12_1: Optional[float] = None,
    momentum_risk_adjusted: Optional[float] = None,
    momentum_6m: Optional[float] = None,
    reversal_1w: Optional[float] = None,
    reversal_1m: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    high_52w: Optional[float] = None,
    # 量价确认
    volume_ratio: Optional[float] = None,
    cmf: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
    sector_mult: float = 1.0,
) -> MomentumFactorScore:
    """动量因子策略评分

    核心逻辑：寻找中期动量强劲 + 短期超跌 + 趋势向上的股票
    """
    result = MomentumFactorScore()
    reasons = []

    if price is None:
        return MomentumFactorScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件
    if momentum_12_1 is not None and momentum_12_1 < -0.3:
        reasons.append(f"中期动量过弱 {momentum_12_1:.2f}")
    if ema10 and ema20 and ma50 and not (ema10 > ema20 > ma50):
        reasons.append("均线排列不符合 EMA10 > EMA20 > MA50")
    if high_52w and (high_52w - price) / high_52w > 0.30:
        reasons.append(f"距52周高点超过30%")
    if volume_ratio is not None and volume_ratio < 0.3:
        reasons.append("成交量极度萎缩")

    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result

    result.hard_pass = True

    # 中期动量 (25分)
    mom_score = 0.0
    if momentum_12_1 is not None:
        mom_score = max(0, min(25, (momentum_12_1 + 1) * 12.5))
    result.momentum_12_1 = mom_score

    # 风险调整动量 (15分)
    risk_mom = 0.0
    if momentum_risk_adjusted is not None:
        risk_mom = max(0, min(15, (momentum_risk_adjusted + 1) * 7.5))
    result.momentum_risk_adjusted = risk_mom

    # 6个月动量 (15分)
    mom6 = 0.0
    if momentum_6m is not None:
        mom6 = max(0, min(15, (momentum_6m + 1) * 7.5))
    result.momentum_6m = mom6

    # 短期反转 (15分) — 反转分数越高越好（超跌反弹）
    rev_score = 0.0
    if reversal_1w is not None:
        rev_score += max(0, min(7.5, reversal_1w * 7.5))
    if reversal_1m is not None:
        rev_score += max(0, min(7.5, reversal_1m * 7.5))
    result.reversal_1w = min(7.5, max(0, reversal_1w * 7.5) if reversal_1w else 0)
    result.reversal_1m = min(7.5, max(0, reversal_1m * 7.5) if reversal_1m else 0)

    # 趋势排列 (15分)
    trend = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50:
            trend = 15.0
        elif price > ema10 > ema20:
            trend = 10.0
        elif price > ema10:
            trend = 5.0
    result.trend_alignment = trend

    # 量能确认 (10分)
    vol_score = 0.0
    if volume_ratio is not None and volume_ratio >= 1.2:
        vol_score = 5.0
    if cmf is not None and cmf > 0:
        vol_score += 5.0
    result.volume_confirmation = vol_score

    # 风险 (5分)
    result.risk = 5.0

    result.total = round(
        result.momentum_12_1 + result.momentum_risk_adjusted + result.momentum_6m +
        result.reversal_1w + result.reversal_1m +
        result.trend_alignment + result.volume_confirmation + result.risk, 1
    )
    result.details = {
        "momentum_12_1": momentum_12_1,
        "momentum_risk_adjusted": momentum_risk_adjusted,
        "volume_ratio": volume_ratio,
        "cmf": cmf,
    }
    return result


# ====================================================================
# 2. 低波动率策略 Low Volatility V1
# ====================================================================

@dataclass
class LowVolatilityScore:
    total: float = 0.0
    low_volatility: float = 0.0
    volatility_ratio: float = 0.0
    atr_percent: float = 0.0
    bollinger_width: float = 0.0
    trend_stability: float = 0.0
    dividend_yield_proxy: float = 0.0
    volume_stability: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_low_volatility(
    # 波动率因子
    low_volatility: Optional[float] = None,
    volatility_ratio: Optional[float] = None,
    atr_percent: Optional[float] = None,
    bollinger_width: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    # 成交量
    volume_trend: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
) -> LowVolatilityScore:
    """低波动率策略评分

    核心逻辑：寻找低波动 + 稳定趋势 + 量价健康的防御型股票
    Ang et al. 2006: 低波动异常收益
    """
    result = LowVolatilityScore()
    reasons = []

    if price is None:
        return LowVolatilityScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    if low_volatility is not None and low_volatility < 0.2:
        reasons.append(f"低波动评分过低 {low_volatility:.2f}")
    if ema20 and ma50 and not (ema20 > ma50):
        reasons.append("中期均线排列不佳")
    if atr_percent is not None and atr_percent > 0.08:
        reasons.append(f"ATR%过高 {atr_percent:.4f}")

    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result

    result.hard_pass = True

    # 低波动率评分 (25分)
    lv = 0.0
    if low_volatility is not None:
        lv = low_volatility * 25
    result.low_volatility = lv

    # 波动率比 (20分) — 收缩状态加分
    vr = 0.0
    if volatility_ratio is not None:
        if volatility_ratio < 1.0:
            vr = 20.0
        elif volatility_ratio < 1.2:
            vr = 15.0
        elif volatility_ratio < 1.5:
            vr = 10.0
        else:
            vr = 5.0
    result.volatility_ratio = vr

    # ATR% (15分) — 低ATR%加分
    atr_s = 0.0
    if atr_percent is not None:
        if atr_percent < 0.02:
            atr_s = 15.0
        elif atr_percent < 0.035:
            atr_s = 12.0
        elif atr_percent < 0.05:
            atr_s = 8.0
        else:
            atr_s = 4.0
    result.atr_percent = atr_s

    # 布林带宽度 (15分)
    bw = 0.0
    if bollinger_width is not None:
        if bollinger_width < 0.1:
            bw = 15.0
        elif bollinger_width < 0.2:
            bw = 10.0
        elif bollinger_width < 0.3:
            bw = 5.0
    result.bollinger_width = bw

    # 趋势稳定性 (10分)
    ts = 0.0
    if ema20 and ma50 and price:
        if price > ema20 > ma50:
            ts = 10.0
        elif price > ema20:
            ts = 6.0
        elif price > ma50:
            ts = 3.0
    result.trend_stability = ts

    # 成交量稳定性 (10分)
    vs = 0.0
    if volume_trend is not None:
        if -0.2 < volume_trend < 0.2:
            vs = 10.0
        elif -0.5 < volume_trend < 0.5:
            vs = 6.0
        else:
            vs = 3.0
    result.volume_stability = vs

    # 风险 (5分)
    result.risk = 5.0

    result.total = round(
        result.low_volatility + result.volatility_ratio + result.atr_percent +
        result.bollinger_width + result.trend_stability + result.volume_stability + result.risk, 1
    )
    result.details = {
        "low_volatility": low_volatility,
        "volatility_ratio": volatility_ratio,
        "atr_percent": atr_percent,
        "bollinger_width": bollinger_width,
    }
    return result


# ====================================================================
# 3. 量价共振策略 Volume-Price V1
# ====================================================================

@dataclass
class VolumePriceScore:
    total: float = 0.0
    cmf: float = 0.0
    mfi: float = 0.0
    obv_signal: float = 0.0
    volume_ratio: float = 0.0
    vpt: float = 0.0
    price_trend: float = 0.0
    sector_support: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_volume_price(
    # 量价因子
    cmf_val: Optional[float] = None,
    mfi_val: Optional[float] = None,
    obv_signal: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    vpt_val: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
    sector_mult: float = 1.0,
) -> VolumePriceScore:
    """量价共振策略评分

    核心逻辑：寻找资金流入 + 量价配合 + 趋势健康的股票
    """
    result = VolumePriceScore()
    reasons = []

    if price is None:
        return VolumePriceScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件
    if cmf_val is not None and cmf_val < -0.1:
        reasons.append(f"CMF资金流出 {cmf_val:.3f}")
    if mfi_val is not None and mfi_val > 80:
        reasons.append(f"MFI超买 {mfi_val:.1f}")
    if volume_ratio is not None and volume_ratio < 0.5:
        reasons.append(f"成交量过低 {volume_ratio:.2f}")
    if ema10 and ema20 and not (ema10 > ema20):
        reasons.append("短期均线趋势向下")

    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result

    result.hard_pass = True

    # CMF 资金流 (20分)
    cmf_score = 0.0
    if cmf_val is not None:
        if cmf_val > 0.2:
            cmf_score = 20.0
        elif cmf_val > 0.1:
            cmf_score = 15.0
        elif cmf_val > 0.0:
            cmf_score = 10.0
        else:
            cmf_score = 5.0
    result.cmf = cmf_score

    # MFI 资金流指数 (15分)
    mfi_score = 0.0
    if mfi_val is not None:
        if 40 <= mfi_val <= 60:
            mfi_score = 15.0  # 中性偏强
        elif 20 <= mfi_val < 40:
            mfi_score = 12.0  # 超卖反弹
        elif 60 < mfi_val <= 80:
            mfi_score = 10.0  # 偏强
        elif mfi_val > 80:
            mfi_score = 5.0   # 超买风险
        else:
            mfi_score = 8.0   # 极度超卖
    result.mfi = mfi_score

    # OBV 信号 (15分)
    obv_score = 0.0
    if obv_signal is not None:
        obv_score = max(0, min(15, (obv_signal + 1) * 7.5))
    result.obv_signal = obv_score

    # 成交量比 (15分)
    vol_score = 0.0
    if volume_ratio is not None:
        if volume_ratio >= 1.5:
            vol_score = 15.0
        elif volume_ratio >= 1.2:
            vol_score = 12.0
        elif volume_ratio >= 1.0:
            vol_score = 8.0
        elif volume_ratio >= 0.7:
            vol_score = 5.0
        else:
            vol_score = 2.0
    result.volume_ratio = vol_score

    # VPT 量价趋势 (15分)
    vpt_score = 0.0
    if vpt_val is not None:
        vpt_score = max(0, min(15, (vpt_val / 1e10) * 7.5 + 7.5))
    result.vpt = vpt_score

    # 价格趋势 (10分)
    trend = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50:
            trend = 10.0
        elif price > ema10 > ema20:
            trend = 7.0
        elif price > ema10:
            trend = 4.0
    result.price_trend = trend

    # 行业支持 (5分)
    result.sector_support = 5.0 * sector_mult

    # 风险 (5分)
    result.risk = 5.0

    result.total = round(
        result.cmf + result.mfi + result.obv_signal + result.volume_ratio +
        result.vpt + result.price_trend + result.sector_support + result.risk, 1
    )
    result.details = {
        "cmf": cmf_val,
        "mfi": mfi_val,
        "obv_signal": obv_signal,
        "volume_ratio": volume_ratio,
        "vpt": vpt_val,
    }
    return result


# ====================================================================
# 4. 均值回归策略 Mean Reversion V1
# ====================================================================

@dataclass
class MeanReversionScore:
    total: float = 0.0
    bollinger_b: float = 0.0
    rsi_14: float = 0.0
    rsi_divergence: float = 0.0
    price_to_ma_20: float = 0.0
    price_to_ma_50: float = 0.0
    reversal_1w: float = 0.0
    volume_ratio: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_mean_reversion(
    # 均值回归因子
    bollinger_b: Optional[float] = None,
    rsi_14: Optional[float] = None,
    rsi_divergence: Optional[float] = None,
    price_to_ma_20: Optional[float] = None,
    price_to_ma_50: Optional[float] = None,
    reversal_1w: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
) -> MeanReversionScore:
    """均值回归策略评分

    核心逻辑：寻找超卖 + 回归信号 + 基本面支撑的股票
    """
    result = MeanReversionScore()
    reasons = []

    if price is None:
        return MeanReversionScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件
    if bollinger_b is not None and bollinger_b > 1.0:
        reasons.append(f"布林带超买 %B={bollinger_b:.2f}")
    if rsi_14 is not None and rsi_14 > 70:
        reasons.append(f"RSI超买 {rsi_14:.1f}")
    if volume_ratio is not None and volume_ratio < 0.4:
        reasons.append("成交量过低")

    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result

    result.hard_pass = True

    # Bollinger %B (20分) — 越接近下轨越好
    bb_score = 0.0
    if bollinger_b is not None:
        if bollinger_b <= 0.0:
            bb_score = 20.0  # 跌破下轨
        elif bollinger_b <= 0.2:
            bb_score = 18.0
        elif bollinger_b <= 0.4:
            bb_score = 14.0
        elif bollinger_b <= 0.6:
            bb_score = 10.0  # 中轨附近
        elif bollinger_b <= 0.8:
            bb_score = 6.0
        else:
            bb_score = 3.0
    result.bollinger_b = bb_score

    # RSI (20分)
    rsi_score = 0.0
    if rsi_14 is not None:
        if rsi_14 <= 30:
            rsi_score = 20.0  # 超卖
        elif rsi_14 <= 40:
            rsi_score = 16.0
        elif rsi_14 <= 50:
            rsi_score = 12.0
        elif rsi_14 <= 60:
            rsi_score = 8.0
        else:
            rsi_score = 4.0
    result.rsi_14 = rsi_score

    # RSI 背离 (15分)
    div_score = 0.0
    if rsi_divergence is not None:
        if rsi_divergence > 0.5:
            div_score = 15.0  # 底背离
        elif rsi_divergence > 0:
            div_score = 10.0
        elif rsi_divergence < -0.5:
            div_score = 0.0  # 顶背离 → 看跌
        else:
            div_score = 5.0
    result.rsi_divergence = div_score

    # 价格/MA20 (15分)
    pma20 = 0.0
    if price_to_ma_20 is not None:
        if price_to_ma_20 < 0.95:
            pma20 = 15.0  # 跌破MA20 5%以上
        elif price_to_ma_20 < 0.98:
            pma20 = 12.0
        elif price_to_ma_20 < 1.02:
            pma20 = 8.0  # 在MA20附近
        elif price_to_ma_20 < 1.05:
            pma20 = 5.0
        else:
            pma20 = 2.0
    result.price_to_ma_20 = pma20

    # 价格/MA50 (15分)
    pma50 = 0.0
    if price_to_ma_50 is not None:
        if price_to_ma_50 < 0.92:
            pma50 = 15.0
        elif price_to_ma_50 < 0.97:
            pma50 = 12.0
        elif price_to_ma_50 < 1.03:
            pma50 = 8.0
        elif price_to_ma_50 < 1.08:
            pma50 = 5.0
        else:
            pma50 = 2.0
    result.price_to_ma_50 = pma50

    # 短期反转 (10分)
    rev_score = 0.0
    if reversal_1w is not None:
        rev_score = max(0, min(10, reversal_1w * 10))
    result.reversal_1w = rev_score

    # 量能确认 (5分)
    vs = 0.0
    if volume_ratio is not None:
        if 0.7 <= volume_ratio <= 1.3:
            vs = 5.0  # 正常量
        else:
            vs = 2.0
    result.volume_ratio = vs

    # 风险 (5分)
    result.risk = 5.0

    result.total = round(
        result.bollinger_b + result.rsi_14 + result.rsi_divergence +
        result.price_to_ma_20 + result.price_to_ma_50 +
        result.reversal_1w + result.volume_ratio + result.risk, 1
    )
    result.details = {
        "bollinger_b": bollinger_b,
        "rsi_14": rsi_14,
        "rsi_divergence": rsi_divergence,
        "price_to_ma_20": price_to_ma_20,
        "price_to_ma_50": price_to_ma_50,
    }
    return result



# ====================================================================
# 5. 价值型策略 Value Factor V1
# ====================================================================
# 核心逻辑：寻找被低估的股票（基于价格位置代理）
# 参考：Fama-French HML, Asness (2014) QMJ 价值维度

@dataclass
class ValueFactorScore:
    total: float = 0.0
    price_to_52w_high: float = 0.0
    price_to_ma_ratio: float = 0.0
    bollinger_position: float = 0.0
    drawdown_depth: float = 0.0
    volume_ratio: float = 0.0
    trend_filter: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_value_factor(
    value_price_to_52w_high: Optional[float] = None,
    value_price_to_ma_ratio: Optional[float] = None,
    value_bollinger_position: Optional[float] = None,
    value_drawdown_depth: Optional[float] = None,
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    market_mult: float = 1.0,
) -> ValueFactorScore:
    """价值型策略评分 - 寻找价格在低位 + 有趋势反转迹象 + 量能配合的股票"""
    result = ValueFactorScore()
    reasons = []
    if price is None:
        return ValueFactorScore(hard_pass=False, hard_fail_reasons=["无价格数据"])
    if value_price_to_52w_high is not None and value_price_to_52w_high > 0.6:
        reasons.append(f"价格距52周高点过近 {value_price_to_52w_high:.2f}")
    if value_drawdown_depth is not None and value_drawdown_depth > 0.8:
        reasons.append(f"回撤过深 {value_drawdown_depth:.2f}")
    if volume_ratio is not None and volume_ratio < 0.3:
        reasons.append("成交量极度萎缩")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True
    v52 = 0.0
    if value_price_to_52w_high is not None:
        if value_price_to_52w_high < -0.5: v52 = 25.0
        elif value_price_to_52w_high < -0.2: v52 = 20.0
        elif value_price_to_52w_high < 0.1: v52 = 15.0
        elif value_price_to_52w_high < 0.3: v52 = 10.0
        else: v52 = 5.0
    result.price_to_52w_high = v52
    vma = 0.0
    if value_price_to_ma_ratio is not None:
        if value_price_to_ma_ratio < -0.4: vma = 20.0
        elif value_price_to_ma_ratio < -0.2: vma = 16.0
        elif value_price_to_ma_ratio < 0.0: vma = 12.0
        elif value_price_to_ma_ratio < 0.15: vma = 8.0
        else: vma = 4.0
    result.price_to_ma_ratio = vma
    bp = 0.0
    if value_bollinger_position is not None:
        if value_bollinger_position > 0.6: bp = 20.0
        elif value_bollinger_position > 0.3: bp = 15.0
        elif value_bollinger_position > 0.0: bp = 10.0
        elif value_bollinger_position > -0.3: bp = 6.0
        else: bp = 3.0
    result.bollinger_position = bp
    dd = 0.0
    if value_drawdown_depth is not None:
        if 0.15 <= value_drawdown_depth <= 0.30: dd = 15.0
        elif 0.05 <= value_drawdown_depth < 0.15: dd = 12.0
        elif 0.30 < value_drawdown_depth <= 0.50: dd = 10.0
        elif value_drawdown_depth < 0.05: dd = 5.0
        else: dd = 3.0
    result.drawdown_depth = dd
    tf = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20: tf = 10.0
        elif price > ema10: tf = 7.0
        elif price > ma50: tf = 5.0
        elif price > ema20: tf = 3.0
    result.trend_filter = tf
    vs = 0.0
    if volume_ratio is not None:
        if 0.7 <= volume_ratio <= 1.5: vs = 5.0
        elif volume_ratio > 1.5: vs = 3.0
        else: vs = 1.0
    result.volume_ratio = vs
    result.risk = 5.0
    result.total = round(result.price_to_52w_high + result.price_to_ma_ratio + result.bollinger_position +
                         result.drawdown_depth + result.trend_filter + result.volume_ratio + result.risk, 1)
    result.details = {"value_price_to_52w_high": value_price_to_52w_high, "value_price_to_ma_ratio": value_price_to_ma_ratio,
                      "value_bollinger_position": value_bollinger_position, "value_drawdown_depth": value_drawdown_depth}
    return result


# ====================================================================
# 6. 质量趋势策略 Quality Trend V1
# ====================================================================
# 参考：Asness (2014) QMJ 质量维度, 趋势稳定性

@dataclass
class QualityTrendScore:
    total: float = 0.0
    trend_stability: float = 0.0
    earnings_stability: float = 0.0
    serial_correlation: float = 0.0
    drawdown_ratio: float = 0.0
    price_acceleration: float = 0.0
    volume_trend: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_quality_trend(
    quality_trend_stability: Optional[float] = None,
    quality_earnings_stability: Optional[float] = None,
    quality_serial_correlation: Optional[float] = None,
    quality_drawdown_ratio: Optional[float] = None,
    growth_price_acceleration: Optional[float] = None,
    growth_volume_trend: Optional[float] = None,
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    market_mult: float = 1.0,
) -> QualityTrendScore:
    """质量趋势策略评分 - 寻找趋势稳定向上 + 走势质量高 + 回撤可控的优质股"""
    result = QualityTrendScore()
    reasons = []
    if price is None:
        return QualityTrendScore(hard_pass=False, hard_fail_reasons=["无价格数据"])
    if quality_earnings_stability is not None and quality_earnings_stability < 0.1:
        reasons.append(f"收益稳定性过低 {quality_earnings_stability:.2f}")
    if quality_drawdown_ratio is not None and quality_drawdown_ratio < -0.5:
        reasons.append(f"收益回撤比过差 {quality_drawdown_ratio:.2f}")
    if ema20 and ma50 and not (ema20 > ma50):
        reasons.append("中期均线趋势向下")
    if quality_serial_correlation is not None and quality_serial_correlation < -0.5:
        reasons.append("序列强负相关（趋势不稳定）")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True
    ts = 0.0
    if quality_trend_stability is not None:
        if quality_trend_stability > 0.7: ts = 25.0
        elif quality_trend_stability > 0.5: ts = 20.0
        elif quality_trend_stability > 0.3: ts = 15.0
        elif quality_trend_stability > 0.0: ts = 10.0
        elif quality_trend_stability > -0.2: ts = 5.0
        else: ts = 2.0
    result.trend_stability = ts
    es = 0.0
    if quality_earnings_stability is not None:
        es = min(20.0, quality_earnings_stability * 40)
    result.earnings_stability = es
    sc = 0.0
    if quality_serial_correlation is not None:
        if quality_serial_correlation > 0.3: sc = 15.0
        elif quality_serial_correlation > 0.1: sc = 12.0
        elif quality_serial_correlation > -0.1: sc = 8.0
        elif quality_serial_correlation > -0.3: sc = 5.0
        else: sc = 2.0
    result.serial_correlation = sc
    dr = 0.0
    if quality_drawdown_ratio is not None:
        if quality_drawdown_ratio > 0.5: dr = 15.0
        elif quality_drawdown_ratio > 0.2: dr = 12.0
        elif quality_drawdown_ratio > 0.0: dr = 8.0
        elif quality_drawdown_ratio > -0.2: dr = 5.0
        else: dr = 2.0
    result.drawdown_ratio = dr
    pa = 0.0
    if growth_price_acceleration is not None:
        if growth_price_acceleration > 0.3: pa = 10.0
        elif growth_price_acceleration > 0.1: pa = 8.0
        elif growth_price_acceleration > 0.0: pa = 5.0
        elif growth_price_acceleration > -0.1: pa = 3.0
        else: pa = 1.0
    result.price_acceleration = pa
    vt = 0.0
    if growth_volume_trend is not None:
        if -0.1 < growth_volume_trend < 0.3: vt = 10.0
        elif -0.3 < growth_volume_trend <= -0.1: vt = 7.0
        elif 0.3 <= growth_volume_trend < 0.5: vt = 7.0
        elif growth_volume_trend >= 0.5: vt = 4.0
        else: vt = 3.0
    result.volume_trend = vt
    result.risk = 5.0
    result.total = round(result.trend_stability + result.earnings_stability + result.serial_correlation +
                         result.drawdown_ratio + result.price_acceleration + result.volume_trend + result.risk, 1)
    result.details = {"quality_trend_stability": quality_trend_stability, "quality_earnings_stability": quality_earnings_stability,
                      "quality_drawdown_ratio": quality_drawdown_ratio, "growth_price_acceleration": growth_price_acceleration}
    return result


# ====================================================================
# 7. 复合Alpha策略 Composite Alpha V1
# ====================================================================
# 参考：Asness (2014) 多因子组合, Fama-French 5因子

@dataclass
class CompositeAlphaScore:
    total: float = 0.0
    momentum_component: float = 0.0
    value_component: float = 0.0
    quality_component: float = 0.0
    low_vol_component: float = 0.0
    volume_component: float = 0.0
    seasonality_component: float = 0.0
    diversification_bonus: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_composite_alpha(
    momentum_12_1: Optional[float] = None,
    momentum_6m: Optional[float] = None,
    value_price_to_52w_high: Optional[float] = None,
    value_drawdown_depth: Optional[float] = None,
    quality_trend_stability: Optional[float] = None,
    quality_drawdown_ratio: Optional[float] = None,
    low_volatility: Optional[float] = None,
    atr_percent: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    price_to_ma_20: Optional[float] = None,
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    seasonality_month: Optional[float] = None,
    market_mult: float = 1.0,
    sector_mult: float = 1.0,
) -> CompositeAlphaScore:
    """复合Alpha策略评分 - 多因子共振，不依赖单一因子"""
    result = CompositeAlphaScore()
    reasons = []
    if price is None:
        return CompositeAlphaScore(hard_pass=False, hard_fail_reasons=["无价格数据"])
    weak_factors = 0
    if momentum_12_1 is not None and momentum_12_1 < -0.2: weak_factors += 1
    if value_price_to_52w_high is not None and value_price_to_52w_high > 0.5: weak_factors += 1
    if quality_trend_stability is not None and quality_trend_stability < 0.1: weak_factors += 1
    if low_volatility is not None and low_volatility < 0.2: weak_factors += 1
    if weak_factors >= 3:
        reasons.append(f"多因子共振不足（{weak_factors}/4个因子偏弱）")
    if ema10 and ema20 and not (ema10 > ema20):
        reasons.append("短期均线趋势向下")
    if volume_ratio is not None and volume_ratio < 0.3:
        reasons.append("成交量过低")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True
    mc = 0.0
    if momentum_12_1 is not None:
        if momentum_12_1 > 0.3: mc = 25.0
        elif momentum_12_1 > 0.15: mc = 20.0
        elif momentum_12_1 > 0.0: mc = 15.0
        elif momentum_12_1 > -0.1: mc = 10.0
        else: mc = 5.0
    if momentum_6m is not None:
        if momentum_6m > 0.15: mc = min(25.0, mc + 3.0)
        elif momentum_6m < -0.1: mc = max(0.0, mc - 3.0)
    result.momentum_component = mc
    vc = 0.0
    if value_price_to_52w_high is not None:
        if value_price_to_52w_high < -0.3: vc = 12.0
        elif value_price_to_52w_high < 0.0: vc = 9.0
        elif value_price_to_52w_high < 0.2: vc = 6.0
        else: vc = 3.0
    if value_drawdown_depth is not None:
        if 0.1 <= value_drawdown_depth <= 0.25: vc += 8.0
        elif 0.05 <= value_drawdown_depth < 0.1: vc += 5.0
        elif 0.25 < value_drawdown_depth <= 0.40: vc += 5.0
    result.value_component = vc
    qc = 0.0
    if quality_trend_stability is not None:
        if quality_trend_stability > 0.6: qc = 12.0
        elif quality_trend_stability > 0.3: qc = 8.0
        elif quality_trend_stability > 0.0: qc = 5.0
        else: qc = 2.0
    if quality_drawdown_ratio is not None:
        if quality_drawdown_ratio > 0.3: qc += 8.0
        elif quality_drawdown_ratio > 0.0: qc += 5.0
        elif quality_drawdown_ratio > -0.2: qc += 3.0
    result.quality_component = qc
    lc = 0.0
    if low_volatility is not None:
        if low_volatility > 0.6: lc = 10.0
        elif low_volatility > 0.4: lc = 7.0
        elif low_volatility > 0.2: lc = 4.0
        else: lc = 2.0
    if atr_percent is not None:
        if atr_percent < 0.03: lc += 5.0
        elif atr_percent < 0.05: lc += 3.0
        elif atr_percent < 0.08: lc += 1.0
    result.low_vol_component = lc
    vpc = 0.0
    if volume_ratio is not None:
        if 0.8 <= volume_ratio <= 1.5: vpc = 5.0
        elif volume_ratio > 1.5: vpc = 3.0
        else: vpc = 1.0
    if price_to_ma_20 is not None:
        if 0.98 <= price_to_ma_20 <= 1.05: vpc += 5.0
        elif 0.95 <= price_to_ma_20 < 0.98: vpc += 3.0
        elif 1.05 < price_to_ma_20 <= 1.10: vpc += 3.0
    result.volume_component = vpc
    sc = 0.0
    if seasonality_month is not None:
        if seasonality_month > 0.2: sc = 10.0
        elif seasonality_month > 0.0: sc = 7.0
        elif seasonality_month > -0.1: sc = 4.0
        else: sc = 2.0
    result.seasonality_component = sc
    db = 0.0
    positive_factors = 0
    if mc >= 15: positive_factors += 1
    if vc >= 12: positive_factors += 1
    if qc >= 12: positive_factors += 1
    if lc >= 8: positive_factors += 1
    if positive_factors >= 3: db = 5.0
    elif positive_factors >= 2: db = 3.0
    elif positive_factors >= 1: db = 1.0
    result.diversification_bonus = db
    result.risk = 5.0
    result.total = round(result.momentum_component + result.value_component + result.quality_component +
                         result.low_vol_component + result.volume_component + result.seasonality_component +
                         result.diversification_bonus + result.risk, 1)
    result.details = {"momentum_12_1": momentum_12_1, "value_price_to_52w_high": value_price_to_52w_high,
                      "quality_trend_stability": quality_trend_stability, "low_volatility": low_volatility,
                      "volume_ratio": volume_ratio, "seasonality_month": seasonality_month}
    return result


# ====================================================================
# 8. 短期反转策略 Short-term Reversal V1
# ====================================================================
# 参考：Jegadeesh (1990) 短期反转, Lehmann (1990)

@dataclass
class ShortTermReversalScore:
    total: float = 0.0
    one_day_reversal: float = 0.0
    three_day_reversal: float = 0.0
    five_day_reversal: float = 0.0
    rsi_oversold: float = 0.0
    volume_spike_reversal: float = 0.0
    support_bounce: float = 0.0
    trend_filter: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_short_term_reversal(
    price: Optional[float] = None,
    closes: Optional[list[float]] = None,
    highs: Optional[list[float]] = None,
    lows: Optional[list[float]] = None,
    volumes: Optional[list[float]] = None,
    rsi_14: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    market_mult: float = 1.0,
) -> ShortTermReversalScore:
    """短期反转策略评分 - 寻找短期超跌+放量恐慌+临近支撑的反弹机会"""
    result = ShortTermReversalScore()
    reasons = []
    if price is None:
        return ShortTermReversalScore(hard_pass=False, hard_fail_reasons=["无价格数据"])
    ret_1d = 0.0; ret_3d = 0.0; ret_5d = 0.0
    if closes and len(closes) >= 2:
        ret_1d = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 0
    if closes and len(closes) >= 4:
        ret_3d = (closes[-1] - closes[-4]) / closes[-4] if closes[-4] > 0 else 0
    if closes and len(closes) >= 6:
        ret_5d = (closes[-1] - closes[-6]) / closes[-6] if closes[-6] > 0 else 0
    if rsi_14 is not None and rsi_14 > 60:
        reasons.append(f"RSI偏强，不适合反转策略 {rsi_14:.1f}")
    if ret_5d > 0.05:
        reasons.append(f"5日涨幅过大 {ret_5d:.2%}")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True
    odr = 0.0
    if ret_1d < -0.03: odr = 25.0
    elif ret_1d < -0.02: odr = 20.0
    elif ret_1d < -0.01: odr = 15.0
    elif ret_1d < 0.0: odr = 10.0
    elif ret_1d < 0.01: odr = 5.0
    else: odr = 2.0
    result.one_day_reversal = odr
    tdr = 0.0
    if ret_3d < -0.05: tdr = 20.0
    elif ret_3d < -0.03: tdr = 16.0
    elif ret_3d < -0.01: tdr = 12.0
    elif ret_3d < 0.0: tdr = 8.0
    elif ret_3d < 0.02: tdr = 4.0
    else: tdr = 2.0
    result.three_day_reversal = tdr
    fdr = 0.0
    if ret_5d < -0.08: fdr = 15.0
    elif ret_5d < -0.05: fdr = 12.0
    elif ret_5d < -0.02: fdr = 9.0
    elif ret_5d < 0.0: fdr = 6.0
    elif ret_5d < 0.02: fdr = 3.0
    else: fdr = 1.0
    result.five_day_reversal = fdr
    rs = 0.0
    if rsi_14 is not None:
        if rsi_14 <= 25: rs = 15.0
        elif rsi_14 <= 30: rs = 13.0
        elif rsi_14 <= 40: rs = 10.0
        elif rsi_14 <= 50: rs = 7.0
        elif rsi_14 <= 55: rs = 4.0
        else: rs = 2.0
    result.rsi_oversold = rs
    vs = 0.0
    if volumes and len(volumes) >= 5 and ret_1d < -0.01:
        avg_vol = sum(volumes[-5:-1]) / 4 if len(volumes) >= 5 else 0
        if avg_vol > 0 and volumes[-1] > avg_vol * 1.5: vs = 10.0
        elif avg_vol > 0 and volumes[-1] > avg_vol * 1.2: vs = 7.0
        elif avg_vol > 0 and volumes[-1] > avg_vol: vs = 4.0
    result.volume_spike_reversal = vs
    sb = 0.0
    if closes and highs and lows and len(closes) >= 20:
        recent_low = min(lows[-20:])
        if price and recent_low > 0:
            dist_to_low = (price - recent_low) / recent_low
            if dist_to_low < 0.01: sb = 10.0
            elif dist_to_low < 0.03: sb = 8.0
            elif dist_to_low < 0.05: sb = 5.0
            elif dist_to_low < 0.08: sb = 3.0
    result.support_bounce = sb
    tf = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ma50: tf = 5.0
        elif price > ema20: tf = 3.0
        elif price > ema10: tf = 2.0
    result.trend_filter = tf
    result.risk = 5.0
    result.total = round(result.one_day_reversal + result.three_day_reversal + result.five_day_reversal +
                         result.rsi_oversold + result.volume_spike_reversal + result.support_bounce +
                         result.trend_filter + result.risk, 1)
    result.details = {"ret_1d": ret_1d, "ret_3d": ret_3d, "ret_5d": ret_5d, "rsi_14": rsi_14}
    return result


# ====================================================================
# 9. 突破动量策略 Breakout Momentum V1
# ====================================================================

@dataclass
class BreakoutMomentumScore:
    total: float = 0.0
    price_level_breakout: float = 0.0
    momentum_confirm: float = 0.0
    volume_confirm: float = 0.0
    trend_strength: float = 0.0
    relative_strength: float = 0.0
    volatility_confirm: float = 0.0
    sector_support: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_breakout_momentum(
    momentum_12_1: Optional[float] = None,
    momentum_risk_adjusted: Optional[float] = None,
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    high_52w: Optional[float] = None,
    closes: Optional[list[float]] = None,
    volume_ratio: Optional[float] = None,
    pattern_volume_breakout: Optional[float] = None,
    market_mult: float = 1.0,
    sector_mult: float = 1.0,
) -> BreakoutMomentumScore:
    """突破动量策略评分 - 突破+动量+量能三重确认，过滤假突破"""
    result = BreakoutMomentumScore()
    reasons = []
    if price is None:
        return BreakoutMomentumScore(hard_pass=False, hard_fail_reasons=["无价格数据"])
    recent_high = None
    if closes and len(closes) >= 20:
        recent_high = max(closes[-20:])
    if momentum_12_1 is not None and momentum_12_1 < -0.1:
        reasons.append(f"动量不足 {momentum_12_1:.2f}")
    if ema10 and ema20 and not (ema10 > ema20):
        reasons.append("短期均线未多头排列")
    if volume_ratio is not None and volume_ratio < 0.7:
        reasons.append("成交量不足")
    if recent_high and price and price < recent_high * 0.97:
        reasons.append("价格未接近近期高点")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True
    plb = 0.0
    if recent_high and price:
        dist_to_high = (price - recent_high) / recent_high
        if dist_to_high >= 0.0: plb = 25.0
        elif dist_to_high > -0.01: plb = 20.0
        elif dist_to_high > -0.02: plb = 15.0
        elif dist_to_high > -0.03: plb = 10.0
        else: plb = 5.0
    if high_52w and price:
        dist_to_52w = (high_52w - price) / high_52w
        if dist_to_52w < 0.05: plb = min(25.0, plb + 5.0)
    result.price_level_breakout = plb
    mc = 0.0
    if momentum_12_1 is not None:
        if momentum_12_1 > 0.3: mc = 20.0
        elif momentum_12_1 > 0.2: mc = 16.0
        elif momentum_12_1 > 0.1: mc = 12.0
        elif momentum_12_1 > 0.0: mc = 8.0
        else: mc = 4.0
    if momentum_risk_adjusted is not None and momentum_risk_adjusted > 0.2:
        mc = min(20.0, mc + 3.0)
    result.momentum_confirm = mc
    vc = 0.0
    if volume_ratio is not None:
        if volume_ratio >= 1.5: vc = 20.0
        elif volume_ratio >= 1.2: vc = 16.0
        elif volume_ratio >= 1.0: vc = 12.0
        elif volume_ratio >= 0.8: vc = 8.0
        else: vc = 4.0
    if pattern_volume_breakout is not None and pattern_volume_breakout > 0.5:
        vc = min(20.0, vc + 3.0)
    result.volume_confirm = vc
    ts = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50: ts = 15.0
        elif price > ema10 > ema20: ts = 12.0
        elif price > ema10: ts = 8.0
        elif price > ema20: ts = 5.0
    result.trend_strength = ts
    rs = 0.0
    if closes and len(closes) >= 63:
        ret_3m = (closes[-1] - closes[-63]) / closes[-63] if closes[-63] > 0 else 0
        if ret_3m > 0.15: rs = 10.0
        elif ret_3m > 0.10: rs = 8.0
        elif ret_3m > 0.05: rs = 6.0
        elif ret_3m > 0.0: rs = 4.0
        else: rs = 2.0
    result.relative_strength = rs
    result.sector_support = 5.0 * sector_mult
    result.risk = 5.0
    result.total = round(result.price_level_breakout + result.momentum_confirm + result.volume_confirm +
                         result.trend_strength + result.relative_strength + result.volatility_confirm +
                         result.sector_support + result.risk, 1)
    result.details = {"momentum_12_1": momentum_12_1, "volume_ratio": volume_ratio,
                      "recent_high": recent_high, "high_52w": high_52w, "pattern_volume_breakout": pattern_volume_breakout}
    return result


# ====================================================================
# 10. 季节动量策略 Seasonality Momentum V1
# ====================================================================
# 参考：January Effect, Turn-of-Month, Santa Claus Rally

@dataclass
class SeasonalityMomentumScore:
    total: float = 0.0
    month_effect: float = 0.0
    turn_of_month: float = 0.0
    day_of_week: float = 0.0
    momentum_6m: float = 0.0
    trend_alignment: float = 0.0
    volume_activity: float = 0.0
    recent_performance: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_seasonality_momentum(
    seasonality_month: Optional[float] = None,
    seasonality_turn_of_month: Optional[float] = None,
    seasonality_day_of_week: Optional[float] = None,
    momentum_6m: Optional[float] = None,
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    closes: Optional[list[float]] = None,
    volume_ratio: Optional[float] = None,
    market_mult: float = 1.0,
) -> SeasonalityMomentumScore:
    """季节动量策略评分 - 在有利的季节/月份窗口 + 动量趋势向上时入场"""
    result = SeasonalityMomentumScore()
    reasons = []
    if price is None:
        return SeasonalityMomentumScore(hard_pass=False, hard_fail_reasons=["无价格数据"])
    if seasonality_month is not None and seasonality_month < -0.1:
        reasons.append(f"月份效应偏负面 {seasonality_month:.2f}")
    if momentum_6m is not None and momentum_6m < -0.15:
        reasons.append(f"中期动量偏弱 {momentum_6m:.2f}")
    if ema10 and ema20 and not (ema10 > ema20):
        reasons.append("短期均线趋势向下")
    if volume_ratio is not None and volume_ratio < 0.4:
        reasons.append("成交量过低")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True
    me = 0.0
    if seasonality_month is not None:
        if seasonality_month > 0.3: me = 25.0
        elif seasonality_month > 0.1: me = 20.0
        elif seasonality_month > 0.0: me = 15.0
        elif seasonality_month > -0.1: me = 10.0
        else: me = 5.0
    result.month_effect = me
    tom = 0.0
    if seasonality_turn_of_month is not None:
        if seasonality_turn_of_month > 0.2: tom = 20.0
        elif seasonality_turn_of_month > 0.0: tom = 15.0
        elif seasonality_turn_of_month > -0.1: tom = 10.0
        else: tom = 5.0
    result.turn_of_month = tom
    dw = 0.0
    if seasonality_day_of_week is not None:
        if seasonality_day_of_week > 0.2: dw = 10.0
        elif seasonality_day_of_week > 0.0: dw = 7.0
        elif seasonality_day_of_week > -0.1: dw = 4.0
        else: dw = 2.0
    result.day_of_week = dw
    m6 = 0.0
    if momentum_6m is not None:
        if momentum_6m > 0.2: m6 = 20.0
        elif momentum_6m > 0.1: m6 = 16.0
        elif momentum_6m > 0.0: m6 = 12.0
        elif momentum_6m > -0.1: m6 = 8.0
        else: m6 = 4.0
    result.momentum_6m = m6
    ta = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50: ta = 15.0
        elif price > ema10 > ema20: ta = 12.0
        elif price > ema10: ta = 8.0
        elif price > ema20: ta = 5.0
    result.trend_alignment = ta
    va = 0.0
    if volume_ratio is not None:
        if 0.7 <= volume_ratio <= 1.5: va = 5.0
        elif volume_ratio > 1.5: va = 3.0
        else: va = 1.0
    result.volume_activity = va
    rp = 0.0
    if closes and len(closes) >= 5:
        ret_5d = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0
        if ret_5d > 0.02: rp = 5.0
        elif ret_5d > 0.0: rp = 3.0
        elif ret_5d > -0.02: rp = 2.0
        else: rp = 1.0
    result.recent_performance = rp
    result.risk = 5.0
    result.total = round(result.month_effect + result.turn_of_month + result.day_of_week +
                         result.momentum_6m + result.trend_alignment + result.volume_activity +
                         result.recent_performance + result.risk, 1)
    result.details = {"seasonality_month": seasonality_month, "seasonality_turn_of_month": seasonality_turn_of_month,
                      "seasonality_day_of_week": seasonality_day_of_week, "momentum_6m": momentum_6m}
    return result

# ====================================================================
# 策略注册表
# ====================================================================





# ====================================================================
# 11. 技术指标策略 Technical Indicator V1
# ====================================================================
# 使用KDJ、WILLR、ADX、CCI、AROON、Chaikin等技术指标综合评分
# 参考：Welles Wilder (1978), Lambert (1980), Achelis (1995)

@dataclass
class TechnicalIndicatorScore:
    total: float = 0.0
    kdj_signal: float = 0.0
    willr_signal: float = 0.0
    adx_strength: float = 0.0
    cci_signal: float = 0.0
    aroon_trend: float = 0.0
    dmi_plus: float = 0.0
    chaikin_flow: float = 0.0
    trend_filter: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_technical_indicator(
    # 技术指标因子
    tech_kdj: Optional[float] = None,
    tech_willr: Optional[float] = None,
    tech_adx: Optional[float] = None,
    tech_cci: Optional[float] = None,
    tech_aroon: Optional[float] = None,
    tech_dmi_plus: Optional[float] = None,
    tech_chaikin_osc: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
) -> TechnicalIndicatorScore:
    """技术指标策略评分 - 多技术指标共振，寻找强势信号"""
    result = TechnicalIndicatorScore()
    reasons = []
    if price is None:
        return TechnicalIndicatorScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件
    tech_positive = 0
    tech_negative = 0
    for v in [tech_kdj, tech_willr, tech_cci, tech_aroon, tech_dmi_plus]:
        if v is not None and v > 0.2:
            tech_positive += 1
        if v is not None and v < -0.3:
            tech_negative += 1
    if tech_negative >= 3:
        reasons.append(f"技术指标过度负面（{tech_negative}/5）")
    if tech_adx is not None and tech_adx < -0.5:
        reasons.append("ADX显示趋势极弱")
    if tech_chaikin_osc is not None and tech_chaikin_osc < -0.5:
        reasons.append("Chaikin显示资金大幅流出")
    if ema10 and ema20 and not (ema10 > ema20):
        reasons.append("短期均线趋势向下")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True

    # KDJ信号 (15分)
    kdj_s = 0.0
    if tech_kdj is not None:
        if tech_kdj > 0.5: kdj_s = 15.0
        elif tech_kdj > 0.2: kdj_s = 12.0
        elif tech_kdj > 0.0: kdj_s = 8.0
        elif tech_kdj > -0.2: kdj_s = 5.0
        else: kdj_s = 2.0
    result.kdj_signal = kdj_s

    # WILLR信号 (15分)
    willr_s = 0.0
    if tech_willr is not None:
        if tech_willr > 0.5: willr_s = 15.0
        elif tech_willr > 0.2: willr_s = 12.0
        elif tech_willr > 0.0: willr_s = 8.0
        elif tech_willr > -0.2: willr_s = 5.0
        else: willr_s = 2.0
    result.willr_signal = willr_s

    # ADX趋势强度 (15分)
    adx_s = 0.0
    if tech_adx is not None:
        if tech_adx > 0.5: adx_s = 15.0
        elif tech_adx > 0.2: adx_s = 12.0
        elif tech_adx > 0.0: adx_s = 8.0
        elif tech_adx > -0.2: adx_s = 5.0
        else: adx_s = 2.0
    result.adx_strength = adx_s

    # CCI信号 (15分)
    cci_s = 0.0
    if tech_cci is not None:
        if tech_cci > 0.5: cci_s = 15.0
        elif tech_cci > 0.2: cci_s = 12.0
        elif tech_cci > 0.0: cci_s = 8.0
        elif tech_cci > -0.2: cci_s = 5.0
        else: cci_s = 2.0
    result.cci_signal = cci_s

    # AROON趋势 (15分)
    aroon_s = 0.0
    if tech_aroon is not None:
        if tech_aroon > 0.5: aroon_s = 15.0
        elif tech_aroon > 0.2: aroon_s = 12.0
        elif tech_aroon > 0.0: aroon_s = 8.0
        elif tech_aroon > -0.2: aroon_s = 5.0
        else: aroon_s = 2.0
    result.aroon_trend = aroon_s

    # DMI+ (10分)
    dmi_s = 0.0
    if tech_dmi_plus is not None:
        if tech_dmi_plus > 0.5: dmi_s = 10.0
        elif tech_dmi_plus > 0.2: dmi_s = 8.0
        elif tech_dmi_plus > 0.0: dmi_s = 5.0
        elif tech_dmi_plus > -0.2: dmi_s = 3.0
        else: dmi_s = 1.0
    result.dmi_plus = dmi_s

    # Chaikin资金流 (10分)
    chaikin_s = 0.0
    if tech_chaikin_osc is not None:
        if tech_chaikin_osc > 0.3: chaikin_s = 10.0
        elif tech_chaikin_osc > 0.1: chaikin_s = 8.0
        elif tech_chaikin_osc > 0.0: chaikin_s = 5.0
        elif tech_chaikin_osc > -0.1: chaikin_s = 3.0
        else: chaikin_s = 1.0
    result.chaikin_flow = chaikin_s

    # 趋势过滤 (5分)
    tf = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50: tf = 5.0
        elif price > ema10 > ema20: tf = 3.0
    result.trend_filter = tf

    result.risk = 5.0
    result.total = round(
        result.kdj_signal + result.willr_signal + result.adx_strength +
        result.cci_signal + result.aroon_trend + result.dmi_plus +
        result.chaikin_flow + result.trend_filter + result.risk, 1
    )
    result.details = {
        "tech_kdj": tech_kdj, "tech_willr": tech_willr, "tech_adx": tech_adx,
        "tech_cci": tech_cci, "tech_aroon": tech_aroon, "tech_dmi_plus": tech_dmi_plus,
        "tech_chaikin_osc": tech_chaikin_osc,
    }
    return result


# ====================================================================
# 12. 风险调整策略 Risk-Adjusted V1
# ====================================================================
# 参考：Sharpe (1966), Sortino (1994), Martin (1987) — 风险优先

@dataclass
class RiskAdjustedScore:
    total: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    cvar_safety: float = 0.0
    semi_variance: float = 0.0
    ulcer_index: float = 0.0
    downside_vol: float = 0.0
    trend_filter: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_risk_adjusted(
    # 风险因子
    risk_sharpe_ratio: Optional[float] = None,
    risk_sortino_ratio: Optional[float] = None,
    risk_cvar: Optional[float] = None,
    risk_semi_variance: Optional[float] = None,
    risk_ulcer_index: Optional[float] = None,
    risk_downside_volatility: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    low_volatility: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
) -> RiskAdjustedScore:
    """风险调整策略评分 - 优先选择风险调整后收益高的股票"""
    result = RiskAdjustedScore()
    reasons = []
    if price is None:
        return RiskAdjustedScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件
    if risk_sharpe_ratio is not None and risk_sharpe_ratio < -0.3:
        reasons.append(f"夏普比率过低 {risk_sharpe_ratio:.2f}")
    if risk_cvar is not None and risk_cvar < -0.3:
        reasons.append(f"尾部风险过大 {risk_cvar:.2f}")
    if risk_ulcer_index is not None and risk_ulcer_index < -0.5:
        reasons.append("溃疡指数过高（回撤深且长）")
    if ema20 and ma50 and not (ema20 > ma50):
        reasons.append("中期均线趋势向下")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True

    # 夏普比率 (20分)
    sr = 0.0
    if risk_sharpe_ratio is not None:
        if risk_sharpe_ratio > 0.5: sr = 20.0
        elif risk_sharpe_ratio > 0.3: sr = 16.0
        elif risk_sharpe_ratio > 0.1: sr = 12.0
        elif risk_sharpe_ratio > 0.0: sr = 8.0
        elif risk_sharpe_ratio > -0.1: sr = 5.0
        else: sr = 2.0
    result.sharpe_ratio = sr

    # 索提诺比率 (20分)
    sor = 0.0
    if risk_sortino_ratio is not None:
        if risk_sortino_ratio > 0.5: sor = 20.0
        elif risk_sortino_ratio > 0.3: sor = 16.0
        elif risk_sortino_ratio > 0.1: sor = 12.0
        elif risk_sortino_ratio > 0.0: sor = 8.0
        elif risk_sortino_ratio > -0.1: sor = 5.0
        else: sor = 2.0
    result.sortino_ratio = sor

    # CVaR安全性 (15分)
    cvar_s = 0.0
    if risk_cvar is not None:
        if risk_cvar > 0.5: cvar_s = 15.0
        elif risk_cvar > 0.2: cvar_s = 12.0
        elif risk_cvar > 0.0: cvar_s = 8.0
        elif risk_cvar > -0.2: cvar_s = 5.0
        else: cvar_s = 2.0
    result.cvar_safety = cvar_s

    # 下半方差 (15分)
    sv = 0.0
    if risk_semi_variance is not None:
        if risk_semi_variance > 0.5: sv = 15.0
        elif risk_semi_variance > 0.2: sv = 12.0
        elif risk_semi_variance > 0.0: sv = 8.0
        elif risk_semi_variance > -0.2: sv = 5.0
        else: sv = 2.0
    result.semi_variance = sv

    # 溃疡指数 (15分)
    ui = 0.0
    if risk_ulcer_index is not None:
        if risk_ulcer_index > 0.5: ui = 15.0
        elif risk_ulcer_index > 0.2: ui = 12.0
        elif risk_ulcer_index > 0.0: ui = 8.0
        elif risk_ulcer_index > -0.2: ui = 5.0
        else: ui = 2.0
    result.ulcer_index = ui

    # 下行波动率 (10分)
    dv = 0.0
    if risk_downside_volatility is not None:
        if risk_downside_volatility > 0.5: dv = 10.0
        elif risk_downside_volatility > 0.2: dv = 8.0
        elif risk_downside_volatility > 0.0: dv = 5.0
        elif risk_downside_volatility > -0.2: dv = 3.0
        else: dv = 1.0
    result.downside_vol = dv

    result.risk = 5.0
    result.total = round(
        result.sharpe_ratio + result.sortino_ratio + result.cvar_safety +
        result.semi_variance + result.ulcer_index + result.downside_vol + result.risk, 1
    )
    result.details = {
        "risk_sharpe_ratio": risk_sharpe_ratio, "risk_sortino_ratio": risk_sortino_ratio,
        "risk_cvar": risk_cvar, "risk_semi_variance": risk_semi_variance,
        "risk_ulcer_index": risk_ulcer_index, "risk_downside_volatility": risk_downside_volatility,
    }
    return result


# ====================================================================
# 13. 趋势跟踪策略 Trend Following V1
# ====================================================================
# 参考：Wilder (1978) DMI/ADX, Kaufman (1995), Aroon

@dataclass
class TrendFollowingScore:
    total: float = 0.0
    adx_signal: float = 0.0
    aroon_signal: float = 0.0
    dmi_plus: float = 0.0
    price_channel: float = 0.0
    money_flow: float = 0.0
    ema_alignment: float = 0.0
    volume_confirmation: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_trend_following(
    # 趋势因子
    tech_adx: Optional[float] = None,
    tech_aroon: Optional[float] = None,
    tech_dmi_plus: Optional[float] = None,
    trend_price_channel_position: Optional[float] = None,
    trend_money_flow_ratio: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    high_52w: Optional[float] = None,
    # 成交量
    volume_ratio: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
) -> TrendFollowingScore:
    """趋势跟踪策略评分 - 寻找强趋势+资金流入+趋势确认的股票"""
    result = TrendFollowingScore()
    reasons = []
    if price is None:
        return TrendFollowingScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    if tech_adx is not None and tech_adx < -0.3:
        reasons.append(f"ADX趋势强度不足 {tech_adx:.2f}")
    if tech_aroon is not None and tech_aroon < -0.3:
        reasons.append(f"AROON显示下降趋势 {tech_aroon:.2f}")
    if ema10 and ema20 and not (ema10 > ema20):
        reasons.append("短期均线趋势向下")
    if volume_ratio is not None and volume_ratio < 0.5:
        reasons.append("成交量过低")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True

    # ADX趋势强度 (20分)
    adx_s = 0.0
    if tech_adx is not None:
        if tech_adx > 0.5: adx_s = 20.0
        elif tech_adx > 0.3: adx_s = 16.0
        elif tech_adx > 0.1: adx_s = 12.0
        elif tech_adx > 0.0: adx_s = 8.0
        elif tech_adx > -0.2: adx_s = 5.0
        else: adx_s = 2.0
    result.adx_signal = adx_s

    # AROON趋势 (20分)
    aroon_s = 0.0
    if tech_aroon is not None:
        if tech_aroon > 0.5: aroon_s = 20.0
        elif tech_aroon > 0.3: aroon_s = 16.0
        elif tech_aroon > 0.1: aroon_s = 12.0
        elif tech_aroon > 0.0: aroon_s = 8.0
        elif tech_aroon > -0.2: aroon_s = 5.0
        else: aroon_s = 2.0
    result.aroon_signal = aroon_s

    # DMI+ (15分)
    dmi_s = 0.0
    if tech_dmi_plus is not None:
        if tech_dmi_plus > 0.5: dmi_s = 15.0
        elif tech_dmi_plus > 0.3: dmi_s = 12.0
        elif tech_dmi_plus > 0.1: dmi_s = 9.0
        elif tech_dmi_plus > 0.0: dmi_s = 6.0
        else: dmi_s = 3.0
    result.dmi_plus = dmi_s

    # 价格通道位置 (15分)
    pc = 0.0
    if trend_price_channel_position is not None:
        if trend_price_channel_position > 0.5: pc = 15.0
        elif trend_price_channel_position > 0.2: pc = 12.0
        elif trend_price_channel_position > 0.0: pc = 8.0
        elif trend_price_channel_position > -0.2: pc = 5.0
        else: pc = 2.0
    result.price_channel = pc

    # 资金流比率 (15分)
    mf = 0.0
    if trend_money_flow_ratio is not None:
        if trend_money_flow_ratio > 0.5: mf = 15.0
        elif trend_money_flow_ratio > 0.2: mf = 12.0
        elif trend_money_flow_ratio > 0.0: mf = 8.0
        elif trend_money_flow_ratio > -0.2: mf = 5.0
        else: mf = 2.0
    result.money_flow = mf

    # EMA排列确认 (10分)
    ema_s = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50: ema_s = 10.0
        elif price > ema10 > ema20: ema_s = 7.0
        elif price > ema10: ema_s = 4.0
    result.ema_alignment = ema_s

    result.risk = 5.0
    result.total = round(
        result.adx_signal + result.aroon_signal + result.dmi_plus +
        result.price_channel + result.money_flow + result.ema_alignment + result.risk, 1
    )
    result.details = {
        "tech_adx": tech_adx, "tech_aroon": tech_aroon, "tech_dmi_plus": tech_dmi_plus,
        "trend_price_channel_position": trend_price_channel_position,
        "trend_money_flow_ratio": trend_money_flow_ratio,
    }
    return result


# ====================================================================
# 14. 成交量流动策略 Volume Flow V1
# ====================================================================
# 参考：Granville (1963) OBV, Chaikin (1980s), Ease of Movement

@dataclass
class VolumeFlowScore:
    total: float = 0.0
    accumulation_distribution: float = 0.0
    volume_price_confirm: float = 0.0
    volume_trend: float = 0.0
    ease_of_movement: float = 0.0
    money_flow_ratio: float = 0.0
    chaikin_flow: float = 0.0
    volume_ratio: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_volume_flow(
    # 成交量因子
    trend_accumulation_distribution: Optional[float] = None,
    trend_volume_price_confirmation: Optional[float] = None,
    trend_volume_trend_intensity: Optional[float] = None,
    trend_ease_of_movement: Optional[float] = None,
    trend_money_flow_ratio: Optional[float] = None,
    tech_chaikin_osc: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
) -> VolumeFlowScore:
    """成交量流动策略评分 - 分析资金流向和量价配合"""
    result = VolumeFlowScore()
    reasons = []
    if price is None:
        return VolumeFlowScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件
    flow_positive = 0
    flow_negative = 0
    for v in [trend_accumulation_distribution, trend_money_flow_ratio, tech_chaikin_osc]:
        if v is not None and v > 0.2: flow_positive += 1
        if v is not None and v < -0.3: flow_negative += 1
    if flow_negative >= 2:
        reasons.append(f"资金流指标过度负面（{flow_negative}/3）")
    if trend_volume_price_confirmation is not None and trend_volume_price_confirmation < -0.3:
        reasons.append("量价关系严重背离")
    if volume_ratio is not None and volume_ratio < 0.3:
        reasons.append("成交量极度萎缩")
    if ema10 and ema20 and not (ema10 > ema20):
        reasons.append("短期均线趋势向下")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True

    # A/D线 (20分)
    ad = 0.0
    if trend_accumulation_distribution is not None:
        if trend_accumulation_distribution > 0.5: ad = 20.0
        elif trend_accumulation_distribution > 0.2: ad = 16.0
        elif trend_accumulation_distribution > 0.0: ad = 12.0
        elif trend_accumulation_distribution > -0.2: ad = 8.0
        else: ad = 4.0
    result.accumulation_distribution = ad

    # 量价确认 (20分)
    vpc = 0.0
    if trend_volume_price_confirmation is not None:
        if trend_volume_price_confirmation > 0.5: vpc = 20.0
        elif trend_volume_price_confirmation > 0.2: vpc = 16.0
        elif trend_volume_price_confirmation > 0.0: vpc = 12.0
        elif trend_volume_price_confirmation > -0.2: vpc = 8.0
        else: vpc = 4.0
    result.volume_price_confirm = vpc

    # 量能趋势强度 (15分)
    vt = 0.0
    if trend_volume_trend_intensity is not None:
        if trend_volume_trend_intensity > 0.4: vt = 15.0
        elif trend_volume_trend_intensity > 0.2: vt = 12.0
        elif trend_volume_trend_intensity > 0.0: vt = 8.0
        elif trend_volume_trend_intensity > -0.2: vt = 5.0
        else: vt = 2.0
    result.volume_trend = vt

    # 运动轻松度 (15分)
    emv = 0.0
    if trend_ease_of_movement is not None:
        if trend_ease_of_movement > 0.4: emv = 15.0
        elif trend_ease_of_movement > 0.2: emv = 12.0
        elif trend_ease_of_movement > 0.0: emv = 8.0
        elif trend_ease_of_movement > -0.2: emv = 5.0
        else: emv = 2.0
    result.ease_of_movement = emv

    # 资金流比率 (15分)
    mfr = 0.0
    if trend_money_flow_ratio is not None:
        if trend_money_flow_ratio > 0.5: mfr = 15.0
        elif trend_money_flow_ratio > 0.2: mfr = 12.0
        elif trend_money_flow_ratio > 0.0: mfr = 8.0
        elif trend_money_flow_ratio > -0.2: mfr = 5.0
        else: mfr = 2.0
    result.money_flow_ratio = mfr

    # Chaikin摆动 (10分)
    ch = 0.0
    if tech_chaikin_osc is not None:
        if tech_chaikin_osc > 0.3: ch = 10.0
        elif tech_chaikin_osc > 0.1: ch = 8.0
        elif tech_chaikin_osc > 0.0: ch = 5.0
        elif tech_chaikin_osc > -0.1: ch = 3.0
        else: ch = 1.0
    result.chaikin_flow = ch

    result.risk = 5.0
    result.total = round(
        result.accumulation_distribution + result.volume_price_confirm +
        result.volume_trend + result.ease_of_movement + result.money_flow_ratio +
        result.chaikin_flow + result.risk, 1
    )
    result.details = {
        "trend_accumulation_distribution": trend_accumulation_distribution,
        "trend_volume_price_confirmation": trend_volume_price_confirmation,
        "trend_volume_trend_intensity": trend_volume_trend_intensity,
        "trend_ease_of_movement": trend_ease_of_movement,
        "trend_money_flow_ratio": trend_money_flow_ratio,
        "tech_chaikin_osc": tech_chaikin_osc,
    }
    return result


# ====================================================================
# 15. 增强技术指标策略 Enhanced Technical V1
# ====================================================================
# 综合使用所有技术指标+风险因子+量价因子

@dataclass
class EnhancedTechnicalScore:
    total: float = 0.0
    tech_composite: float = 0.0
    risk_composite: float = 0.0
    volume_composite: float = 0.0
    trend_composite: float = 0.0
    momentum_component: float = 0.0
    diversification_bonus: float = 0.0
    trend_filter: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_enhanced_technical(
    # 技术指标
    tech_kdj: Optional[float] = None,
    tech_adx: Optional[float] = None,
    tech_aroon: Optional[float] = None,
    tech_cci: Optional[float] = None,
    # 风险因子
    risk_sharpe_ratio: Optional[float] = None,
    risk_sortino_ratio: Optional[float] = None,
    risk_cvar: Optional[float] = None,
    # 量价因子
    trend_volume_price_confirmation: Optional[float] = None,
    trend_money_flow_ratio: Optional[float] = None,
    trend_accumulation_distribution: Optional[float] = None,
    # 动量
    momentum_12_1: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
) -> EnhancedTechnicalScore:
    """增强技术指标策略 - 综合技术+风险+量价+动量"""
    result = EnhancedTechnicalScore()
    reasons = []
    if price is None:
        return EnhancedTechnicalScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件：至少3个维度有正面信号
    dim_positive = 0
    if tech_kdj is not None and tech_kdj > 0.2: dim_positive += 1
    if tech_adx is not None and tech_adx > 0.2: dim_positive += 1
    if risk_sharpe_ratio is not None and risk_sharpe_ratio > 0.1: dim_positive += 1
    if trend_volume_price_confirmation is not None and trend_volume_price_confirmation > 0.2: dim_positive += 1
    if momentum_12_1 is not None and momentum_12_1 > 0.1: dim_positive += 1
    if dim_positive < 2:
        reasons.append(f"多维度共振不足（{dim_positive}/5）")
    if ema10 and ema20 and not (ema10 > ema20):
        reasons.append("短期均线趋势向下")
    if volume_ratio is not None and volume_ratio < 0.3:
        reasons.append("成交量过低")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True

    # 技术指标综合 (20分)
    tech_s = 0.0
    tech_count = 0
    for v in [tech_kdj, tech_adx, tech_aroon, tech_cci]:
        if v is not None:
            tech_count += 1
            if v > 0.5: tech_s += 5.0
            elif v > 0.2: tech_s += 4.0
            elif v > 0.0: tech_s += 3.0
            elif v > -0.2: tech_s += 2.0
            else: tech_s += 1.0
    if tech_count > 0:
        tech_s = tech_s / tech_count * 4  # 归一化到20分
    result.tech_composite = min(20.0, tech_s)

    # 风险综合 (20分)
    risk_s = 0.0
    risk_count = 0
    for v in [risk_sharpe_ratio, risk_sortino_ratio, risk_cvar]:
        if v is not None:
            risk_count += 1
            if v > 0.5: risk_s += 7.0
            elif v > 0.2: risk_s += 5.0
            elif v > 0.0: risk_s += 3.0
            elif v > -0.2: risk_s += 2.0
            else: risk_s += 1.0
    if risk_count > 0:
        risk_s = risk_s / risk_count * 3
    result.risk_composite = min(20.0, risk_s)

    # 量价综合 (20分)
    vol_s = 0.0
    vol_count = 0
    for v in [trend_volume_price_confirmation, trend_money_flow_ratio, trend_accumulation_distribution]:
        if v is not None:
            vol_count += 1
            if v > 0.5: vol_s += 7.0
            elif v > 0.2: vol_s += 5.0
            elif v > 0.0: vol_s += 3.0
            elif v > -0.2: vol_s += 2.0
            else: vol_s += 1.0
    if vol_count > 0:
        vol_s = vol_s / vol_count * 3
    result.volume_composite = min(20.0, vol_s)

    # 趋势综合 (15分)
    trend_s = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50: trend_s = 15.0
        elif price > ema10 > ema20: trend_s = 12.0
        elif price > ema10: trend_s = 8.0
        elif price > ema20: trend_s = 5.0
        elif price > ma50: trend_s = 3.0
    result.trend_composite = trend_s

    # 动量成分 (15分)
    mc = 0.0
    if momentum_12_1 is not None:
        if momentum_12_1 > 0.3: mc = 15.0
        elif momentum_12_1 > 0.15: mc = 12.0
        elif momentum_12_1 > 0.0: mc = 8.0
        elif momentum_12_1 > -0.1: mc = 5.0
        else: mc = 2.0
    result.momentum_component = mc

    # 多元化加分 (5分)
    positive_dims = 0
    if result.tech_composite >= 12: positive_dims += 1
    if result.risk_composite >= 12: positive_dims += 1
    if result.volume_composite >= 12: positive_dims += 1
    if result.momentum_component >= 10: positive_dims += 1
    if positive_dims >= 3: result.diversification_bonus = 5.0
    elif positive_dims >= 2: result.diversification_bonus = 3.0

    result.risk = 5.0
    result.total = round(
        result.tech_composite + result.risk_composite + result.volume_composite +
        result.trend_composite + result.momentum_component + result.diversification_bonus + result.risk, 1
    )
    result.details = {
        "tech_kdj": tech_kdj, "tech_adx": tech_adx, "risk_sharpe_ratio": risk_sharpe_ratio,
        "trend_volume_price_confirmation": trend_volume_price_confirmation,
        "momentum_12_1": momentum_12_1,
    }
    return result


# ====================================================================
# 16. 全能Alpha策略 All-Rounder Alpha V1
# ====================================================================
# 综合所有因子类别（技术+风险+量价+趋势+基本面代理+动量）

@dataclass
class AllRounderAlphaScore:
    total: float = 0.0
    technical_alpha: float = 0.0
    risk_alpha: float = 0.0
    volume_alpha: float = 0.0
    trend_alpha: float = 0.0
    value_alpha: float = 0.0
    quality_alpha: float = 0.0
    momentum_alpha: float = 0.0
    seasonality_alpha: float = 0.0
    diversification_bonus: float = 0.0
    risk: float = 0.0
    details: dict = field(default_factory=dict)
    hard_pass: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)


def score_allrounder_alpha(
    # 技术指标
    tech_kdj: Optional[float] = None,
    tech_adx: Optional[float] = None,
    tech_aroon: Optional[float] = None,
    # 风险因子
    risk_sharpe_ratio: Optional[float] = None,
    risk_sortino_ratio: Optional[float] = None,
    risk_cvar: Optional[float] = None,
    # 量价因子
    trend_volume_price_confirmation: Optional[float] = None,
    trend_money_flow_ratio: Optional[float] = None,
    trend_accumulation_distribution: Optional[float] = None,
    # 趋势因子
    ema10: Optional[float] = None,
    ema20: Optional[float] = None,
    ma50: Optional[float] = None,
    # 价值因子
    value_price_to_52w_high: Optional[float] = None,
    value_drawdown_depth: Optional[float] = None,
    # 质量因子
    quality_trend_stability: Optional[float] = None,
    quality_drawdown_ratio: Optional[float] = None,
    # 动量因子
    momentum_12_1: Optional[float] = None,
    momentum_6m: Optional[float] = None,
    # 季节因子
    seasonality_month: Optional[float] = None,
    # 价格数据
    price: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    # 环境
    market_mult: float = 1.0,
    sector_mult: float = 1.0,
) -> AllRounderAlphaScore:
    """全能Alpha策略 - 8大维度综合评分，追求最全面的选股信号"""
    result = AllRounderAlphaScore()
    reasons = []
    if price is None:
        return AllRounderAlphaScore(hard_pass=False, hard_fail_reasons=["无价格数据"])

    # 硬条件：至少4个维度不差
    weak_dims = 0
    if tech_kdj is not None and tech_kdj < -0.2: weak_dims += 1
    if risk_sharpe_ratio is not None and risk_sharpe_ratio < -0.1: weak_dims += 1
    if trend_volume_price_confirmation is not None and trend_volume_price_confirmation < -0.2: weak_dims += 1
    if value_price_to_52w_high is not None and value_price_to_52w_high > 0.5: weak_dims += 1
    if quality_trend_stability is not None and quality_trend_stability < 0.1: weak_dims += 1
    if momentum_12_1 is not None and momentum_12_1 < -0.2: weak_dims += 1
    if weak_dims >= 4:
        reasons.append(f"过多个维度（{weak_dims}/6）表现不佳")
    if ema10 and ema20 and not (ema10 > ema20):
        reasons.append("短期均线趋势向下")
    if volume_ratio is not None and volume_ratio < 0.3:
        reasons.append("成交量过低")
    if reasons:
        result.hard_pass = False
        result.hard_fail_reasons = reasons
        return result
    result.hard_pass = True

    # 技术Alpha (12分)
    ta = 0.0
    tech_count = 0
    for v in [tech_kdj, tech_adx, tech_aroon]:
        if v is not None:
            tech_count += 1
            if v > 0.5: ta += 4.0
            elif v > 0.2: ta += 3.0
            elif v > 0.0: ta += 2.0
            elif v > -0.2: ta += 1.0
    if tech_count > 0:
        ta = ta / tech_count * 3
    result.technical_alpha = min(12.0, ta)

    # 风险Alpha (12分)
    ra = 0.0
    risk_count = 0
    for v in [risk_sharpe_ratio, risk_sortino_ratio, risk_cvar]:
        if v is not None:
            risk_count += 1
            if v > 0.5: ra += 4.0
            elif v > 0.2: ra += 3.0
            elif v > 0.0: ra += 2.0
            elif v > -0.2: ra += 1.0
    if risk_count > 0:
        ra = ra / risk_count * 3
    result.risk_alpha = min(12.0, ra)

    # 量价Alpha (12分)
    va = 0.0
    vol_count = 0
    for v in [trend_volume_price_confirmation, trend_money_flow_ratio, trend_accumulation_distribution]:
        if v is not None:
            vol_count += 1
            if v > 0.5: va += 4.0
            elif v > 0.2: va += 3.0
            elif v > 0.0: va += 2.0
            elif v > -0.2: va += 1.0
    if vol_count > 0:
        va = va / vol_count * 3
    result.volume_alpha = min(12.0, va)

    # 趋势Alpha (12分)
    result.trend_alpha = 0.0
    if ema10 and ema20 and ma50 and price:
        if price > ema10 > ema20 > ma50: result.trend_alpha = 12.0
        elif price > ema10 > ema20: result.trend_alpha = 9.0
        elif price > ema10: result.trend_alpha = 6.0
        elif price > ema20: result.trend_alpha = 4.0
        elif price > ma50: result.trend_alpha = 2.0

    # 价值Alpha (12分)
    vaa = 0.0
    if value_price_to_52w_high is not None:
        if value_price_to_52w_high < -0.3: vaa = 6.0
        elif value_price_to_52w_high < 0.0: vaa = 4.0
        elif value_price_to_52w_high < 0.3: vaa = 2.0
    if value_drawdown_depth is not None:
        if 0.1 <= value_drawdown_depth <= 0.25: vaa += 6.0
        elif 0.05 <= value_drawdown_depth < 0.1: vaa += 4.0
        elif 0.25 < value_drawdown_depth <= 0.40: vaa += 3.0
    result.value_alpha = vaa

    # 质量Alpha (12分)
    qa = 0.0
    if quality_trend_stability is not None:
        if quality_trend_stability > 0.5: qa = 6.0
        elif quality_trend_stability > 0.3: qa = 4.0
        elif quality_trend_stability > 0.0: qa = 2.0
    if quality_drawdown_ratio is not None:
        if quality_drawdown_ratio > 0.3: qa += 6.0
        elif quality_drawdown_ratio > 0.0: qa += 4.0
        elif quality_drawdown_ratio > -0.2: qa += 2.0
    result.quality_alpha = qa

    # 动量Alpha (12分)
    ma = 0.0
    if momentum_12_1 is not None:
        if momentum_12_1 > 0.3: ma = 6.0
        elif momentum_12_1 > 0.15: ma = 4.0
        elif momentum_12_1 > 0.0: ma = 3.0
        elif momentum_12_1 > -0.1: ma = 2.0
        else: ma = 1.0
    if momentum_6m is not None:
        if momentum_6m > 0.15: ma = min(12.0, ma + 6.0)
        elif momentum_6m > 0.05: ma = min(12.0, ma + 4.0)
        elif momentum_6m > 0.0: ma = min(12.0, ma + 2.0)
    result.momentum_alpha = min(12.0, ma)

    # 季节Alpha (6分)
    sa = 0.0
    if seasonality_month is not None:
        if seasonality_month > 0.2: sa = 6.0
        elif seasonality_month > 0.0: sa = 4.0
        elif seasonality_month > -0.1: sa = 2.0
    result.seasonality_alpha = sa

    # 多元化加分
    pos_dims = 0
    if result.technical_alpha >= 8: pos_dims += 1
    if result.risk_alpha >= 8: pos_dims += 1
    if result.volume_alpha >= 8: pos_dims += 1
    if result.trend_alpha >= 8: pos_dims += 1
    if result.value_alpha >= 8: pos_dims += 1
    if result.quality_alpha >= 8: pos_dims += 1
    if result.momentum_alpha >= 8: pos_dims += 1
    if pos_dims >= 4: result.diversification_bonus = 5.0
    elif pos_dims >= 3: result.diversification_bonus = 3.0
    elif pos_dims >= 2: result.diversification_bonus = 1.0

    result.risk = 5.0
    result.total = round(
        result.technical_alpha + result.risk_alpha + result.volume_alpha +
        result.trend_alpha + result.value_alpha + result.quality_alpha +
        result.momentum_alpha + result.seasonality_alpha +
        result.diversification_bonus + result.risk, 1
    )
    result.details = {
        "tech_kdj": tech_kdj, "risk_sharpe_ratio": risk_sharpe_ratio,
        "trend_volume_price_confirmation": trend_volume_price_confirmation,
        "value_price_to_52w_high": value_price_to_52w_high,
        "quality_trend_stability": quality_trend_stability,
        "momentum_12_1": momentum_12_1,
        "seasonality_month": seasonality_month,
    }
    return result



FACTOR_STRATEGIES = {
    "momentum_factor": {
        "name": "动量因子 V1",
        "description": "中期动量+风险调整动量+短期反转+趋势确认",
        "fn": score_momentum_factor,
        "category": "因子策略",
    },
    "low_volatility": {
        "name": "低波动率 V1",
        "description": "低波动+波动率收缩+低ATR+稳定趋势",
        "fn": score_low_volatility,
        "category": "因子策略",
    },
    "volume_price": {
        "name": "量价共振 V1",
        "description": "CMF+MFI+OBV+量比+量价趋势",
        "fn": score_volume_price,
        "category": "因子策略",
    },
    "mean_reversion": {
        "name": "均值回归 V1",
        "description": "布林带超卖+RSI超卖+底背离+价格回归",
        "fn": score_mean_reversion,
        "category": "因子策略",
    },
    "value_factor": {
        "name": "价值型 V1",
        "description": "52周低点价值+均线偏离+布林位置+回撤深度+趋势过滤",
        "fn": score_value_factor,
        "category": "因子策略",
    },
    "quality_trend": {
        "name": "质量趋势 V1",
        "description": "趋势稳定性+收益稳定性+自相关+回撤比+加速度",
        "fn": score_quality_trend,
        "category": "因子策略",
    },
    "composite_alpha": {
        "name": "复合Alpha V1",
        "description": "动量+价值+质量+低波+量价+季节多因子共振",
        "fn": score_composite_alpha,
        "category": "因子策略",
    },
    "short_term_reversal": {
        "name": "短期反转 V1",
        "description": "1/3/5日超跌+RSI超卖+放量恐慌+支撑反弹",
        "fn": score_short_term_reversal,
        "category": "因子策略",
    },
    "breakout_momentum": {
        "name": "突破动量 V1",
        "description": "价格突破+动量确认+量能放大+趋势强度+相对强度",
        "fn": score_breakout_momentum,
        "category": "因子策略",
    },
    "seasonality_momentum": {
        "name": "季节动量 V1",
        "description": "月份效应+月末月初+周几效应+6个月动量+趋势排列",
        "fn": score_seasonality_momentum,
        "category": "因子策略",
    },
    "technical_indicator": {
        "name": "技术指标 V1",
        "description": "KDJ+WILLR+ADX+CCI+AROON+DMI+Chaikin技术指标共振",
        "fn": score_technical_indicator,
        "category": "因子策略",
    },
    "risk_adjusted": {
        "name": "风险调整 V1",
        "description": "夏普+索提诺+CVaR+下半方差+溃疡指数+下行波动",
        "fn": score_risk_adjusted,
        "category": "因子策略",
    },
    "trend_following": {
        "name": "趋势跟踪 V1",
        "description": "ADX+AROON+DMI+价格通道+资金流+EMA排列",
        "fn": score_trend_following,
        "category": "因子策略",
    },
    "volume_flow": {
        "name": "成交量流动 V1",
        "description": "A/D线+量价确认+运动轻松度+资金流比率+Chaikin",
        "fn": score_volume_flow,
        "category": "因子策略",
    },
    "enhanced_technical": {
        "name": "增强技术 V1",
        "description": "技术+风险+量价+趋势+动量五维度综合评分",
        "fn": score_enhanced_technical,
        "category": "因子策略",
    },
    "allrounder_alpha": {
        "name": "全能Alpha V1",
        "description": "技术+风险+量价+趋势+价值+质量+动量+季节8维共振",
        "fn": score_allrounder_alpha,
        "category": "因子策略",
    },
}

"""US Quant System — 因子计算库

基于日线/分钟线数据计算各类量化因子。
涵盖以下因子类别（共 8 大类 30+ 因子）：

1. 价格价值型 (Value Proxy)      — 价格相对价值位置
2. 质量稳定性型 (Quality Proxy)  — 价格走势质量
3. 成长加速度型 (Growth Proxy)   — 价格/量能增长趋势
4. 相关性因子 (Correlation)      — 与市场/行业的关联
5. 流动性因子 (Liquidity)        — 成交活跃度
6. 技术形态因子 (Pattern)        — K线形态识别
7. 市场微观结构 (Microstructure) — 量价微观结构
8. 季节效应因子 (Seasonality)    — 日历效应

参考来源：
- Fama & French (1993, 2015) 五因子模型
- WorldQuant 101 Formulaic Alphas (Kakushadze 2016)
- Microsoft Qlib Alpha158/Alpha360
- Jegadeesh & Titman (1993) 动量因子
- Amihud (2002) 非流动性指标
- Ang et al. (2006) 低波动率异象
"""

from __future__ import annotations

from typing import Optional
import math


def _safe_div(a: float, b: float) -> float:
    if b == 0 or b is None:
        return 0.0
    return a / b


def _corr(x: list[float], y: list[float]) -> Optional[float]:
    if len(x) < 5 or len(y) < 5:
        return None
    n = min(len(x), len(y))
    x, y = x[-n:], y[-n:]
    mx, my = sum(x) / n, sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den = math.sqrt(sum((xi - mx) ** 2 for xi in x) * sum((yi - my) ** 2 for yi in y))
    if den == 0:
        return 0.0
    return num / den


# ========== 1. 价格价值型因子 ==========

def value_price_to_52w_high(closes: list[float]) -> float:
    """价格距52周高点的比例 — 越低越便宜"""
    if len(closes) < 252:
        return 0.0
    high_52w = max(closes[-252:])
    if high_52w == 0:
        return 0.0
    ratio = closes[-1] / high_52w
    return max(-1.0, min(1.0, (ratio - 0.75) * 4))


def value_price_to_ma_ratio(closes: list[float], period: int = 50) -> float:
    """价格相对均线位置"""
    if len(closes) < period:
        return 0.0
    ma = sum(closes[-period:]) / period
    if ma == 0:
        return 0.0
    ratio = closes[-1] / ma - 1.0
    return max(-1.0, min(1.0, ratio * 5))


def value_bollinger_position(closes: list[float], period: int = 20, n_std: float = 2.0) -> float:
    """布林带位置因子 — %B 指标"""
    if len(closes) < period:
        return 0.0
    recent = closes[-period:]
    ma = sum(recent) / period
    std = math.sqrt(sum((c - ma) ** 2 for c in recent) / period)
    if std == 0:
        return 0.0
    lower = ma - n_std * std
    upper = ma + n_std * std
    if upper == lower:
        return 0.0
    bb = (closes[-1] - lower) / (upper - lower)
    return max(-1.0, min(1.0, 1.0 - bb * 2))


def value_drawdown_depth(closes: list[float], lookback: int = 63) -> float:
    """回撤深度因子"""
    if len(closes) < lookback:
        return 0.0
    recent = closes[-lookback:]
    peak = max(recent)
    if peak == 0:
        return 0.0
    dd = (peak - closes[-1]) / peak
    return max(0.0, min(1.0, dd / 0.30))


# ========== 2. 质量稳定性型因子 ==========

def quality_trend_stability(closes: list[float], period: int = 60) -> float:
    """趋势稳定性 — R^2 近似"""
    if len(closes) < period:
        return 0.0
    recent = closes[-period:]
    n = len(recent)
    x_mean = (n - 1) / 2.0
    y_mean = sum(recent) / n
    num, den_x, den_y = 0.0, 0.0, 0.0
    for i, y in enumerate(recent):
        num += (i - x_mean) * (y - y_mean)
        den_x += (i - x_mean) ** 2
        den_y += (y - y_mean) ** 2
    if den_x == 0 or den_y == 0:
        return 0.0
    r = num / math.sqrt(den_x * den_y)
    r2 = r * r
    slope = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
    if slope > 0:
        return min(1.0, r2 * 1.2)
    else:
        return max(-1.0, -r2)


def quality_earnings_stability(closes: list[float], period: int = 20) -> float:
    """收益稳定性 — 波动率倒数"""
    if len(closes) < period + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), period + 1)):
        if closes[i - 1] > 0:
            returns.append((closes[-i] - closes[-i - 1]) / closes[-i - 1])
    if len(returns) < 5:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    vol = math.sqrt(var_r) if var_r > 0 else 0.01
    annual_vol = vol * math.sqrt(252)
    return max(0.0, min(1.0, 0.10 / max(annual_vol, 0.01)))


def quality_serial_correlation(closes: list[float], lookback: int = 21) -> float:
    """序列自相关性"""
    if len(closes) < lookback + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), lookback + 1)):
        if closes[-i - 1] > 0:
            returns.append((closes[-i] - closes[-i - 1]) / closes[-i - 1])
    if len(returns) < 10:
        return 0.0
    lag1 = _corr(returns[:-1], returns[1:])
    if lag1 is None:
        return 0.0
    return max(-1.0, min(1.0, lag1))


def quality_drawdown_ratio(closes: list[float], lookback: int = 252) -> float:
    """收益回撤比"""
    if len(closes) < lookback:
        return 0.0
    recent = closes[-lookback:]
    total_return = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
    peak = recent[0]
    max_dd = 0.0
    for p in recent:
        peak = max(peak, p)
        dd = (peak - p) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    if max_dd == 0:
        return 1.0 if total_return > 0 else 0.0
    ratio = total_return / max_dd
    return max(-1.0, min(1.0, ratio / 3.0))


# ========== 3. 成长加速度型因子 ==========

def growth_price_acceleration(closes: list[float], short: int = 10, long: int = 50) -> float:
    """价格加速度"""
    if len(closes) < long:
        return 0.0
    short_ret = _safe_div(closes[-1] - closes[-short], closes[-short]) if len(closes) >= short else 0
    long_ret = _safe_div(closes[-1] - closes[-long], closes[-long]) if len(closes) >= long else 0
    accel = short_ret - long_ret
    return max(-1.0, min(1.0, accel * 10))


def growth_volume_trend(volumes: list[float], short: int = 5, long: int = 20) -> float:
    """成交量增长趋势"""
    if len(volumes) < long:
        return 0.0
    short_avg = sum(volumes[-short:]) / short
    long_avg = sum(volumes[-long:]) / long
    if long_avg == 0:
        return 0.0
    ratio = short_avg / long_avg - 1.0
    return max(-1.0, min(1.0, ratio * 2))


def growth_momentum_ratio(closes: list[float], fast: int = 5, slow: int = 60) -> float:
    """动量比"""
    if len(closes) < slow:
        return 0.0
    fast_ret = _safe_div(closes[-1] - closes[-fast], closes[-fast]) if len(closes) >= fast else 0
    slow_ret = _safe_div(closes[-1] - closes[-slow], closes[-slow]) if len(closes) >= slow else 0
    if abs(slow_ret) < 0.001:
        return 0.0
    ratio = _safe_div(fast_ret, slow_ret)
    return max(-1.0, min(1.0, (ratio - 1.0) * 2))


def growth_high_low_ratio(closes: list[float], highs: list[float], lows: list[float], period: int = 20) -> float:
    """高低点扩张比"""
    if len(closes) < period or len(highs) < period or len(lows) < period:
        return 0.0
    recent_range = max(highs[-period:]) - min(lows[-period:])
    if len(closes) >= period * 2:
        old_range = max(highs[-(period * 2):-period]) - min(lows[-(period * 2):-period])
    else:
        old_range = recent_range
    if old_range == 0:
        return 0.0
    ratio = recent_range / old_range - 1.0
    return max(-1.0, min(1.0, ratio))


# ========== 4. 相关性因子 ==========

def correlation_beta(closes: list[float], market_closes: list[float], period: int = 60) -> float:
    """Beta 系数"""
    if len(closes) < period or len(market_closes) < period:
        return 0.0
    n = min(period, len(closes), len(market_closes))
    stock_rets = []
    market_rets = []
    for i in range(1, n):
        if closes[-i - 1] > 0 and market_closes[-i - 1] > 0:
            stock_rets.append((closes[-i] - closes[-i - 1]) / closes[-i - 1])
            market_rets.append((market_closes[-i] - market_closes[-i - 1]) / market_closes[-i - 1])
    if len(stock_rets) < 10:
        return 0.0
    corr = _corr(stock_rets, market_rets) or 0.0
    mr = sum(market_rets) / len(market_rets)
    sr = sum(stock_rets) / len(stock_rets)
    m_var = sum((r - mr) ** 2 for r in market_rets) / len(market_rets)
    if m_var == 0:
        return 0.0
    beta = corr * (math.sqrt(sum((r - sr) ** 2 for r in stock_rets) / len(stock_rets)) / math.sqrt(m_var))
    return max(-1.0, min(1.0, beta - 1.0))


def correlation_market_corr(closes: list[float], market_closes: list[float], period: int = 20) -> float:
    """与市场的相关性"""
    if len(closes) < period or len(market_closes) < period:
        return 0.0
    n = min(period, len(closes), len(market_closes))
    c = _corr(closes[-n:], market_closes[-n:])
    if c is None:
        return 0.0
    return max(-1.0, min(1.0, c))


def correlation_idiosyncratic_vol(closes: list[float], market_closes: list[float], period: int = 60) -> float:
    """特质波动率"""
    if len(closes) < period or len(market_closes) < period:
        return 0.0
    n = min(period, len(closes), len(market_closes))
    stock_rets, market_rets = [], []
    for i in range(1, n):
        if closes[-i - 1] > 0 and market_closes[-i - 1] > 0:
            stock_rets.append((closes[-i] - closes[-i - 1]) / closes[-i - 1])
            market_rets.append((market_closes[-i] - market_closes[-i - 1]) / market_closes[-i - 1])
    if len(stock_rets) < 10:
        return 0.0
    mr = sum(market_rets) / len(market_rets)
    sr = sum(stock_rets) / len(stock_rets)
    num = sum((r - mr) * (s - sr) for r, s in zip(market_rets, stock_rets))
    den = sum((r - mr) ** 2 for r in market_rets)
    beta = num / den if den != 0 else 0
    residuals = [s - beta * m for s, m in zip(stock_rets, market_rets)]
    ivol = math.sqrt(sum(r ** 2 for r in residuals) / len(residuals)) if residuals else 0
    annual_ivol = ivol * math.sqrt(252)
    return max(-1.0, min(1.0, 0.5 - annual_ivol * 0.033))


# ========== 5. 流动性因子 ==========

def liquidity_dollar_volume(volumes: list[float], closes: list[float], period: int = 20) -> float:
    """成交金额因子"""
    if len(volumes) < period or len(closes) < period:
        return 0.0
    n = min(period, len(volumes), len(closes))
    dv = [volumes[-i] * closes[-i] for i in range(1, n + 1)]
    mean_dv = sum(dv) / len(dv)
    if mean_dv == 0:
        return 0.0
    var_dv = sum((d - mean_dv) ** 2 for d in dv) / len(dv)
    std_dv = math.sqrt(var_dv) if var_dv > 0 else mean_dv * 0.1
    z = (dv[-1] - mean_dv) / std_dv
    return max(-1.0, min(1.0, z / 3.0))


def liquidity_turnover_ratio(volumes: list[float], period: int = 20) -> float:
    """换手率因子"""
    if len(volumes) < period * 2:
        return 0.0
    recent_avg = sum(volumes[-period:]) / period
    old_avg = sum(volumes[-(period * 2):-period]) / period
    if old_avg == 0:
        return 0.0
    ratio = recent_avg / old_avg - 1.0
    return max(-1.0, min(1.0, ratio * 2))


def liquidity_amihud_illiquidity(closes: list[float], volumes: list[float], period: int = 20) -> float:
    """Amihud 非流动性指标"""
    if len(closes) < period + 1 or len(volumes) < period:
        return 0.0
    illiq_vals = []
    for i in range(1, min(period + 1, len(closes), len(volumes) + 1)):
        ret = abs(_safe_div(closes[-i] - closes[-i - 1], closes[-i - 1]))
        dv = volumes[-i] * closes[-i]
        if dv > 0:
            illiq_vals.append(ret / dv)
    if not illiq_vals:
        return 0.0
    avg_illiq = sum(illiq_vals) / len(illiq_vals)
    if avg_illiq == 0:
        return 1.0
    return max(-1.0, min(1.0, 1.0 - math.log10(1 + avg_illiq * 1e9) / 10))


def liquidity_volume_consistency(volumes: list[float], period: int = 20) -> float:
    """成交量一致性"""
    if len(volumes) < period:
        return 0.0
    recent = volumes[-period:]
    mean_v = sum(recent) / period
    if mean_v == 0:
        return 0.0
    std_v = math.sqrt(sum((v - mean_v) ** 2 for v in recent) / period)
    cv = std_v / mean_v
    return max(-1.0, min(1.0, 1.0 - cv * 2))


# ========== 6. 技术形态因子 ==========

def pattern_candlestick_bullish(closes, opens, highs, lows):
    """看涨K线形态评分"""
    if len(closes) < 5:
        return 0.0
    score = 0.0
    body = abs(closes[-1] - opens[-1])
    upper_shadow = highs[-1] - max(closes[-1], opens[-1])
    lower_shadow = min(closes[-1], opens[-1]) - lows[-1]
    if body > 0 and lower_shadow > body * 2 and upper_shadow < body * 0.3:
        score += 0.3
    if (closes[-1] > opens[-1] and closes[-2] < opens[-2] and
            closes[-1] > opens[-2] and opens[-1] < closes[-2]):
        score += 0.3
    if (closes[-2] < opens[-2] and closes[-1] > opens[-1] and
            opens[-1] < closes[-2] and closes[-1] > (opens[-2] + closes[-2]) / 2):
        score += 0.2
    if len(closes) >= 3 and closes[-1] > closes[-2] > closes[-3]:
        score += 0.2
    return max(-1.0, min(1.0, score))


def pattern_candlestick_bearish(closes, opens, highs, lows):
    """看跌K线形态评分"""
    if len(closes) < 5:
        return 0.0
    score = 0.0
    body = abs(closes[-1] - opens[-1])
    upper_shadow = highs[-1] - max(closes[-1], opens[-1])
    lower_shadow = min(closes[-1], opens[-1]) - lows[-1]
    if body > 0 and upper_shadow > body * 2 and lower_shadow < body * 0.3:
        score += 0.3
    if (closes[-1] < opens[-1] and closes[-2] > opens[-2] and
            closes[-1] < opens[-2] and opens[-1] > closes[-2]):
        score += 0.3
    if (closes[-2] > opens[-2] and closes[-1] < opens[-1] and
            opens[-1] > closes[-2] and closes[-1] < (opens[-2] + closes[-2]) / 2):
        score += 0.2
    if len(closes) >= 3 and closes[-1] < closes[-2] < closes[-3]:
        score += 0.2
    return max(-1.0, min(1.0, score))


def pattern_support_resistance(closes, highs, lows, lookback=60):
    """支撑阻力位强度"""
    if len(closes) < lookback:
        return 0.0
    price = closes[-1]
    resistances = []
    supports = []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            resistances.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            supports.append(lows[i])
    if not resistances or not supports:
        return 0.0
    nearest_resistance = min(resistances, key=lambda r: abs(r - price))
    nearest_support = max(supports, key=lambda s: abs(s - price))
    dist_to_support = abs(price - nearest_support) / price if price > 0 else 1.0
    dist_to_resistance = abs(nearest_resistance - price) / price if price > 0 else 1.0
    if dist_to_support < 0.02:
        return 0.8
    elif dist_to_resistance < 0.02:
        return -0.8
    else:
        return max(-0.5, min(0.5, (dist_to_resistance - dist_to_support) * 5))


def pattern_volume_breakout(volumes, closes, period=20):
    """量能突破形态"""
    if len(volumes) < period or len(closes) < period:
        return 0.0
    avg_vol = sum(volumes[-period:]) / period
    if avg_vol == 0:
        return 0.0
    vol_ratio = volumes[-1] / avg_vol
    price_high = max(closes[-period:])
    near_high = (closes[-1] / price_high - 1.0) if price_high > 0 else 0
    if vol_ratio > 1.5 and near_high > -0.01:
        return max(-1.0, min(1.0, (vol_ratio - 1.0) * 0.5 + 0.5))
    elif vol_ratio > 1.0 and near_high > -0.02:
        return max(-1.0, min(1.0, (vol_ratio - 1.0) * 0.3))
    else:
        return 0.0


# ========== 7. 市场微观结构因子 ==========

def microstructure_volume_price_corr(closes, volumes, period=10):
    """量价相关性"""
    if len(closes) < period + 1 or len(volumes) < period:
        return 0.0
    n = min(period, len(volumes), len(closes) - 1)
    price_changes = [(closes[-i] - closes[-i-1]) / closes[-i-1]
                     for i in range(1, n+1) if closes[-i-1] > 0]
    vol_changes = volumes[-n:]
    n = min(len(price_changes), len(vol_changes))
    if n < 5:
        return 0.0
    c = _corr(price_changes[-n:], vol_changes[-n:])
    if c is None:
        return 0.0
    return max(-1.0, min(1.0, c))


def microstructure_volume_weighted_ret(closes, volumes, period=10):
    """成交量加权收益率"""
    if len(closes) < period + 1 or len(volumes) < period:
        return 0.0
    n = min(period, len(volumes), len(closes) - 1)
    total_vol = 0.0
    weighted_ret = 0.0
    for i in range(1, n + 1):
        if closes[-i-1] > 0:
            ret = (closes[-i] - closes[-i-1]) / closes[-i-1]
            vol = volumes[-i] if i <= len(volumes) else 0
            weighted_ret += ret * vol
            total_vol += vol
    if total_vol == 0:
        return 0.0
    vwret = weighted_ret / total_vol
    return max(-1.0, min(1.0, vwret * 50))


def microstructure_price_reversal_1d(closes, volumes):
    """日内反转信号"""
    if len(closes) < 3 or len(volumes) < 2:
        return 0.0
    ret_today = _safe_div(closes[-1] - closes[-2], closes[-2])
    ret_yesterday = _safe_div(closes[-2] - closes[-3], closes[-3])
    vol_ratio = _safe_div(volumes[-2], sum(volumes[-5:-2]) / 3) if len(volumes) >= 5 else 1.0
    if ret_yesterday > 0.02 and vol_ratio > 1.5 and ret_today < -0.01:
        return -0.8
    elif ret_yesterday < -0.02 and vol_ratio > 1.5 and ret_today > 0.01:
        return 0.8
    else:
        return max(-0.3, min(0.3, -ret_today * 5))


def microstructure_intraday_volatility(highs, lows, period=10):
    """日内波动率"""
    if len(highs) < period or len(lows) < period:
        return 0.0
    n = min(period, len(highs), len(lows))
    if highs[-1] == 0:
        return 0.0
    ranges = [(_safe_div(highs[-i] - lows[-i], highs[-i])) for i in range(1, n+1)]
    avg_range = sum(ranges) / n
    return max(-1.0, min(1.0, (avg_range - 0.03) * 50))


# ========== 8. 季节效应因子 ==========

def seasonality_day_of_week():
    """周几效应"""
    from datetime import datetime
    weekday = datetime.now().weekday()
    mapping = {0: -0.2, 1: 0.0, 2: 0.0, 3: 0.1, 4: 0.3, 5: 0.0, 6: 0.0}
    return mapping.get(weekday, 0.0)


def seasonality_month_effect():
    """月份效应"""
    from datetime import datetime
    month = datetime.now().month
    mapping = {1: 0.4, 2: 0.1, 3: 0.0, 4: 0.0, 5: -0.1, 6: -0.1,
               7: 0.0, 8: -0.1, 9: -0.2, 10: 0.1, 11: 0.3, 12: 0.4}
    return mapping.get(month, 0.0)


def seasonality_turn_of_month(closes=None):
    """月末月初效应"""
    from datetime import datetime, timedelta
    today = datetime.now()
    next_month = today.replace(day=28) + timedelta(days=4)
    last_day = next_month - timedelta(days=next_month.day)
    days_to_end = (last_day - today).days
    days_from_start = today.day
    if 0 <= days_to_end <= 3:
        return 0.3
    elif 1 <= days_from_start <= 3:
        return 0.3
    else:
        return -0.1



# ========== 14. 技术指标因子（Technical Indicator Factors） ==========

def tech_kdj(closes: list[float], highs: list[float], lows: list[float], period: int = 9) -> float:
    """KDJ随机指标 — K值，正值表示短期强势，负值表示弱势"""
    if len(closes) < period + 5 or len(highs) < period or len(lows) < period:
        return 0.0
    n = min(period, len(highs), len(lows))
    recent_high = max(highs[-n:])
    recent_low = min(lows[-n:])
    if recent_high == recent_low:
        return 0.0
    rsv = (closes[-1] - recent_low) / (recent_high - recent_low) * 100
    k = rsv  # 简化版，直接用RSV
    norm = (k - 50) / 50  # 归一化到 [-1, 1]
    return max(-1.0, min(1.0, norm))


def tech_willr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """威廉指标 %R — 超卖区（<20）为正信号，超买区（>80）为负信号"""
    if len(highs) < period or len(lows) < period or len(closes) < period:
        return 0.0
    n = min(period, len(highs), len(lows), len(closes))
    highest = max(highs[-n:])
    lowest = min(lows[-n:])
    if highest == lowest:
        return 0.0
    willr = (highest - closes[-1]) / (highest - lowest) * 100
    # willr 在0~100，<20超卖（看涨），>80超买（看跌）
    # 转换为 -1~1，正值表示超卖（看涨信号）
    if willr < 20:
        return max(0.0, min(1.0, 1.0 - willr / 20))
    elif willr > 80:
        return max(-1.0, min(0.0, (80 - willr) / 20))
    else:
        return max(-0.5, min(0.5, (40 - willr) / 40))


def tech_adx(closes: list[float], highs: list[float], lows: list[float], period: int = 14) -> float:
    """ADX 平均趋向指数 — 衡量趋势强度，>25表示强趋势"""
    if len(closes) < period + 5 or len(highs) < period + 1 or len(lows) < period + 1:
        return 0.0
    n = min(period, len(highs) - 1, len(lows) - 1)
    plus_dm_sum = 0.0
    minus_dm_sum = 0.0
    tr_sum = 0.0
    for i in range(1, n + 1):
        if i + 1 < len(highs) and i + 1 < len(lows) and i < len(closes):
            h_high = highs[-i] - highs[-i-1]
            l_low = lows[-i-1] - lows[-i]
            if h_high > 0 and h_high > l_low:
                plus_dm_sum += h_high
            if l_low > 0 and l_low > h_high:
                minus_dm_sum += l_low
            tr = max(highs[-i] - lows[-i], abs(highs[-i] - closes[-i-1]), abs(lows[-i] - closes[-i-1]))
            tr_sum += tr
    if tr_sum == 0:
        return 0.0
    plus_di = plus_dm_sum / tr_sum * 100 if tr_sum > 0 else 0
    minus_di = minus_dm_sum / tr_sum * 100 if tr_sum > 0 else 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    adx_val = dx  # 简化版，直接用单周期DX
    # ADX > 25 趋势强，用正值表示；< 20 趋势弱，用负值
    if adx_val > 25:
        return max(0.0, min(1.0, (adx_val - 25) / 50))
    else:
        return max(-1.0, min(0.0, (adx_val - 25) / 25))


def tech_cci(closes: list[float], highs: list[float], lows: list[float], period: int = 20) -> float:
    """CCI 商品通道指数 — 超卖（<-100）看涨，超买（>100）看跌"""
    if len(closes) < period or len(highs) < period or len(lows) < period:
        return 0.0
    n = min(period, len(closes), len(highs), len(lows))
    tp_vals = [(highs[-i] + lows[-i] + closes[-i]) / 3 for i in range(1, n + 1)]
    mean_tp = sum(tp_vals) / len(tp_vals)
    if mean_tp == 0:
        return 0.0
    mad = sum(abs(tp - mean_tp) for tp in tp_vals) / len(tp_vals)
    if mad == 0:
        return 0.0
    cci_val = (tp_vals[-1] - mean_tp) / (0.015 * mad)
    # CCI < -100 超卖（看涨），>100 超买（看跌）
    if cci_val < -100:
        return max(0.0, min(1.0, (-100 - cci_val) / 200))
    elif cci_val > 100:
        return max(-1.0, min(0.0, (100 - cci_val) / 200))
    else:
        return max(-0.3, min(0.3, -cci_val / 300))


def tech_aroon(highs: list[float], lows: list[float], period: int = 25) -> float:
    """阿隆指标 — Aroon-Up与Aroon-Down的差值，正值表示上升趋势"""
    if len(highs) < period + 1 or len(lows) < period + 1:
        return 0.0
    n = min(period, len(highs) - 1, len(lows) - 1)
    # 最近n天内最高价距离今天的天数
    high_val = max(highs[-n:])
    high_idx = n - 1 - [i for i, v in enumerate(highs[-n:]) if v == high_val][-1] if high_val > 0 else 0
    low_val = min(lows[-n:])
    low_idx = n - 1 - [i for i, v in enumerate(lows[-n:]) if v == low_val][-1] if low_val > 0 else 0
    aroon_up = (n - high_idx) / n * 100
    aroon_down = (n - low_idx) / n * 100
    diff = (aroon_up - aroon_down) / 100  # 归一化到 [-1, 1]
    return max(-1.0, min(1.0, diff))


def tech_dmi_plus(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """DMI+ 正向趋向指标 — 正值表示买方力量强"""
    if len(highs) < period + 2 or len(lows) < period + 2 or len(closes) < period + 2:
        return 0.0
    n = min(period, len(highs) - 1, len(lows) - 1, len(closes) - 1)
    plus_dm = 0.0
    tr = 0.0
    for i in range(1, n + 1):
        h = highs[-i] - highs[-i-1]
        l = lows[-i-1] - lows[-i]
        if h > 0 and h > l:
            plus_dm += h
        tr += max(highs[-i] - lows[-i], abs(highs[-i] - closes[-i-1]), abs(lows[-i] - closes[-i-1]))
    if tr == 0:
        return 0.0
    di_plus = (plus_dm / tr) * 100 if tr > 0 else 0
    return max(-1.0, min(1.0, (di_plus - 25) / 25))


def tech_chaikin_osc(closes: list[float], highs: list[float], lows: list[float], volumes: list[float], fast: int = 3, slow: int = 10) -> float:
    """Chaikin摆动指标 — 正值为资金流入，负值为流出"""
    n = min(slow + 5, len(closes), len(highs), len(lows), len(volumes))
    if n < slow + 3:
        return 0.0
    adl_vals = []
    adl = 0.0
    for i in range(-n, 0):
        if highs[i] > lows[i]:
            mf = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / (highs[i] - lows[i])
            adl += mf * volumes[i]
        adl_vals.append(adl)
    if len(adl_vals) < slow:
        return 0.0
    fast_ema = sum(adl_vals[-fast:]) / fast
    slow_ema = sum(adl_vals[-slow:]) / slow
    if slow_ema == 0:
        return 0.0
    chaikin = (fast_ema - slow_ema) / abs(slow_ema) if slow_ema != 0 else 0
    return max(-1.0, min(1.0, chaikin * 2))


# ========== 15. 高级风险因子（Advanced Risk Factors） ==========

def risk_semi_variance(closes: list[float], period: int = 60) -> float:
    """下半方差 — 衡量下行风险，值越低表示下行风险越小"""
    if len(closes) < period + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), period + 1)):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 10:
        return 0.0
    mean_r = sum(returns) / len(returns)
    neg_returns = [r for r in returns if r < mean_r]
    if not neg_returns:
        return 1.0
    semi_var = sum((r - mean_r) ** 2 for r in neg_returns) / len(neg_returns)
    semi_vol = math.sqrt(semi_var) * math.sqrt(252)
    # 低下行波动 = 好
    return max(-1.0, min(1.0, 0.5 - semi_vol * 2))


def risk_cvar(closes: list[float], period: int = 252, alpha: float = 0.05) -> float:
    """条件VaR (CVaR/Expected Shortfall) — 尾部风险，正值表示风险小"""
    if len(closes) < period + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), period + 1)):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 20:
        return 0.0
    sorted_rets = sorted(returns)
    n_tail = max(1, int(len(sorted_rets) * alpha))
    tail_rets = sorted_rets[:n_tail]
    cvar = sum(tail_rets) / len(tail_rets) if tail_rets else 0
    # CVaR越接近0（损失越小），分数越高
    return max(-1.0, min(1.0, cvar * 15 + 0.5))


def risk_ulcer_index(closes: list[float], period: int = 63) -> float:
    """溃疡指数 — 衡量回撤深度和持续时间，越低越好"""
    if len(closes) < period:
        return 0.0
    n = min(period, len(closes))
    recent = closes[-n:]
    peak = recent[0]
    pct_drawdowns = []
    for p in recent:
        if p > peak:
            peak = p
        dd = (peak - p) / peak if peak > 0 else 0
        pct_drawdowns.append(dd * 100)
    if not pct_drawdowns:
        return 0.0
    ulcer = math.sqrt(sum(d ** 2 for d in pct_drawdowns) / len(pct_drawdowns))
    # 溃疡指数越低越好
    if ulcer < 5:
        return 0.8
    elif ulcer < 10:
        return 0.4
    elif ulcer < 20:
        return 0.0
    elif ulcer < 30:
        return -0.4
    else:
        return -0.8


def risk_downside_volatility(closes: list[float], period: int = 60, mar: float = 0.0) -> float:
    """下行波动率 — 只考虑低于MAR的收益率波动，越低越好"""
    if len(closes) < period + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), period + 1)):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 10:
        return 0.0
    downside_rets = [r for r in returns if r < mar]
    if not downside_rets:
        return 1.0
    d_vol = math.sqrt(sum((r - mar) ** 2 for r in downside_rets) / len(downside_rets))
    annual_dvol = d_vol * math.sqrt(252)
    return max(-1.0, min(1.0, 0.5 - annual_dvol * 2))


def risk_sharpe_ratio(closes: list[float], period: int = 252, risk_free: float = 0.05) -> float:
    """夏普比率 — 风险调整后收益，>1为好，>2为优秀"""
    if len(closes) < period + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), period + 1)):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 20:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = math.sqrt(var_r) if var_r > 0 else 0.01
    annual_ret = (1 + mean_r) ** 252 - 1
    annual_vol = std_r * math.sqrt(252)
    if annual_vol == 0:
        return 0.0
    sharpe = (annual_ret - risk_free) / annual_vol
    return max(-1.0, min(1.0, sharpe / 3))


def risk_sortino_ratio(closes: list[float], period: int = 252, risk_free: float = 0.05) -> float:
    """索提诺比率 — 只考虑下行波动，越高越好"""
    if len(closes) < period + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), period + 1)):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 20:
        return 0.0
    mean_r = sum(returns) / len(returns)
    annual_ret = (1 + mean_r) ** 252 - 1
    downside_rets = [r for r in returns if r < 0]
    if not downside_rets:
        return 1.0 if annual_ret > risk_free else 0.0
    d_var = sum((r - 0) ** 2 for r in downside_rets) / len(downside_rets)
    d_vol = math.sqrt(d_var) * math.sqrt(252) if d_var > 0 else 0.01
    sortino = (annual_ret - risk_free) / d_vol if d_vol > 0 else 0
    return max(-1.0, min(1.0, sortino / 4))


# ========== 16. 趋势与成交量因子（Trend & Volume Factors） ==========

def trend_ease_of_movement(highs: list[float], lows: list[float], volumes: list[float], period: int = 14) -> float:
    """运动轻松度（Ease of Movement）— 正值表示价格轻松上涨"""
    if len(highs) < period + 1 or len(lows) < period + 1 or len(volumes) < period:
        return 0.0
    n = min(period, len(highs) - 1, len(lows) - 1, len(volumes))
    emv_sum = 0.0
    count = 0
    for i in range(1, n + 1):
        midpoint = (highs[-i] + lows[-i]) / 2
        prev_mid = (highs[-i-1] + lows[-i-1]) / 2
        midpoint_move = midpoint - prev_mid
        br = (volumes[-i] / 1000000) / ((highs[-i] - lows[-i]) if highs[-i] > lows[-i] else 1)
        if br > 0:
            emv = midpoint_move / br
            emv_sum += emv
            count += 1
    if count == 0:
        return 0.0
    avg_emv = emv_sum / count
    return max(-1.0, min(1.0, avg_emv * 10))


def trend_accumulation_distribution(closes: list[float], highs: list[float], lows: list[float], volumes: list[float], period: int = 14) -> float:
    """累积/分配线（A/D Line）— 正值为积累（买方主导）"""
    if len(closes) < period or len(highs) < period or len(lows) < period or len(volumes) < period:
        return 0.0
    n = min(period, len(closes), len(highs), len(lows), len(volumes))
    ad_sum = 0.0
    for i in range(1, n + 1):
        if highs[-i] > lows[-i]:
            mf = ((closes[-i] - lows[-i]) - (highs[-i] - closes[-i])) / (highs[-i] - lows[-i])
            ad_sum += mf * volumes[-i]
    if ad_sum == 0:
        return 0.0
    # 用成交量均值归一化
    avg_vol = sum(volumes[-n:]) / n if n > 0 else 1
    if avg_vol == 0:
        return 0.0
    norm = ad_sum / (avg_vol * n)
    return max(-1.0, min(1.0, norm * 2))


def trend_volume_price_confirmation(closes: list[float], volumes: list[float], period: int = 20) -> float:
    """量价确认因子 — 价格上涨时成交量放大/价格下跌时成交量缩小=好"""
    if len(closes) < period + 1 or len(volumes) < period:
        return 0.0
    n = min(period, len(closes) - 1, len(volumes))
    confirm_count = 0
    total = 0
    for i in range(1, n + 1):
        price_chg = (closes[-i] - closes[-i-1]) / closes[-i-1] if closes[-i-1] > 0 else 0
        vol_chg = volumes[-i] - volumes[-i-1] if i < len(volumes) else 0
        if price_chg > 0 and vol_chg > 0:
            confirm_count += 1  # 上涨放量确认
        elif price_chg < 0 and vol_chg < 0:
            confirm_count += 1  # 下跌缩量确认
        elif price_chg > 0 and vol_chg < 0:
            confirm_count -= 0.5  # 上涨缩量（背离）
        elif price_chg < 0 and vol_chg > 0:
            confirm_count -= 1  # 下跌放量（恐慌）
        total += 1
    if total == 0:
        return 0.0
    score = confirm_count / total
    return max(-1.0, min(1.0, score))


def trend_volume_trend_intensity(volumes: list[float], period: int = 20) -> float:
    """成交量趋势强度 — 量能持续放大/缩小的趋势强度"""
    if len(volumes) < period * 2:
        return 0.0
    n = min(period, len(volumes) // 2)
    recent_avg = sum(volumes[-n:]) / n
    prev_avg = sum(volumes[-(n*2):-n]) / n
    if prev_avg == 0:
        return 0.0
    trend = (recent_avg - prev_avg) / prev_avg
    # 用序列相关性衡量趋势的一致性
    vol_series = volumes[-n:]
    if len(vol_series) >= 5:
        x = list(range(len(vol_series)))
        y = vol_series
        mx = sum(x) / len(x)
        my = sum(y) / len(y)
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        den = math.sqrt(sum((xi - mx) ** 2 for xi in x) * sum((yi - my) ** 2 for yi in y))
        r = num / den if den > 0 else 0
        consistency = max(0, r)
    else:
        consistency = 0.5
    result = trend * consistency
    return max(-1.0, min(1.0, result * 2))


def trend_price_channel_position(closes: list[float], highs: list[float], lows: list[float], period: int = 20) -> float:
    """价格通道位置 — 价格在通道中的位置，上轨=1，下轨=-1"""
    if len(closes) < period or len(highs) < period or len(lows) < period:
        return 0.0
    n = min(period, len(closes), len(highs), len(lows))
    upper = max(highs[-n:])
    lower = min(lows[-n:])
    if upper == lower:
        return 0.0
    position = (closes[-1] - lower) / (upper - lower) * 2 - 1  # [-1, 1]
    return max(-1.0, min(1.0, position))


def trend_money_flow_ratio(closes: list[float], highs: list[float], lows: list[float], volumes: list[float], period: int = 14) -> float:
    """资金流比率 — 正资金流与总资金流的比值，>0.5表示买方主导"""
    if len(closes) < period or len(highs) < period or len(lows) < period or len(volumes) < period:
        return 0.0
    n = min(period, len(closes), len(highs), len(lows), len(volumes))
    positive_flow = 0.0
    total_flow = 0.0
    for i in range(1, n + 1):
        tp = (highs[-i] + lows[-i] + closes[-i]) / 3
        if i > 1:
            prev_tp = (highs[-i-1] + lows[-i-1] + closes[-i-1]) / 3 if (i+1) <= len(closes) else tp
        else:
            prev_tp = tp
        if tp > prev_tp:
            positive_flow += volumes[-i] * tp
        total_flow += volumes[-i] * tp
    if total_flow == 0:
        return 0.0
    ratio = positive_flow / total_flow
    # 0.5为中心，越接近1买方越强
    return max(-1.0, min(1.0, (ratio - 0.5) * 4))






# ========== 9. WorldQuant Alpha 风格因子（基于Kakushadze 2016） ==========

def wq_alpha_001(closes: list[float]) -> float:
    """Alpha#001: rank(Ts_ArgMax(SignedPower((returns<0?stddev(returns,20):close), 2), 5)) - 0.5
    衡量过去5天内正收益的动量强度，正值表示上涨动量强
    """
    if len(closes) < 25:
        return 0.0
    returns = [(closes[i] - closes[i-1]) / closes[i-1] if closes[i-1] > 0 else 0 for i in range(-24, 0)]
    vals = []
    for i in range(-5, 0):
        if returns[i] < 0:
            # 用最近20天std
            s = returns[max(-20, i):i]
            if len(s) < 5:
                s = returns
            mean = sum(s) / len(s) if s else 0
            var = sum((r - mean) ** 2 for r in s) / len(s) if s else 0
            std_val = math.sqrt(var) if var > 0 else 0.01
            v = std_val ** 2
        else:
            v = closes[i] ** 2
        vals.append(v)
    if not vals:
        return 0.0
    max_idx = vals.index(max(vals)) if vals else 0
    rank_val = (max_idx + 1) / len(vals)  # 归一化排名
    return max(-1.0, min(1.0, (rank_val - 0.5) * 2))


def wq_alpha_002(closes: list[float], volumes: list[float], opens: list[float]) -> float:
    """Alpha#002: -1 * correlation(rank(delta(log(volume),2)), rank(((close-open)/open)), 6)
    量价背离因子：成交量的变化与日内收益率负相关 → 看跌信号
    """
    n = min(8, len(closes), len(volumes), len(opens))
    if n < 7:
        return 0.0
    vol_chg = []
    price_ret = []
    for i in range(-n, 0):
        if i >= -n + 1:
            v1 = math.log(max(volumes[i], 1))
            v2 = math.log(max(volumes[i-1], 1))
            vol_chg.append(v1 - v2)
            if opens[i] > 0:
                price_ret.append((closes[i] - opens[i]) / opens[i])
            else:
                price_ret.append(0.0)
    if len(vol_chg) < 5 or len(price_ret) < 5:
        return 0.0
    # 简化的correlation
    corr = _corr(vol_chg, price_ret)
    if corr is None:
        return 0.0
    return max(-1.0, min(1.0, -corr))


def wq_alpha_003(closes: list[float], volumes: list[float], opens: list[float]) -> float:
    """Alpha#003: -1 * correlation(rank(open), rank(volume), 10)
    开盘价与成交量的相关性 → 负相关表示开盘拉升但量不足
    """
    n = min(12, len(opens), len(volumes))
    if n < 11:
        return 0.0
    # 用价格变化代替rank
    open_chg = []
    vol_chg = []
    for i in range(-n, 0):
        if i >= -n + 1:
            if opens[i-1] > 0:
                open_chg.append((opens[i] - opens[i-1]) / opens[i-1])
            else:
                open_chg.append(0.0)
            if volumes[i-1] > 0:
                vol_chg.append((volumes[i] - volumes[i-1]) / volumes[i-1])
            else:
                vol_chg.append(0.0)
    if len(open_chg) < 8:
        return 0.0
    corr = _corr(open_chg, vol_chg)
    if corr is None:
        return 0.0
    return max(-1.0, min(1.0, -corr))


def wq_alpha_005(closes: list[float], volumes: list[float], highs: list[float]) -> float:
    """Alpha#005: rank(-1 * correlation(rank(high), rank(volume), 3))
    高价与高量的负相关性 → 价量背离
    """
    n = min(6, len(highs), len(volumes))
    if n < 5:
        return 0.0
    high_chg = []
    vol_chg = []
    for i in range(-n, 0):
        if i >= -n + 1:
            if highs[i-1] > 0:
                high_chg.append((highs[i] - highs[i-1]) / highs[i-1])
            else:
                high_chg.append(0.0)
            if volumes[i-1] > 0:
                vol_chg.append((volumes[i] - volumes[i-1]) / volumes[i-1])
            else:
                vol_chg.append(0.0)
    if len(high_chg) < 3:
        return 0.0
    corr = _corr(high_chg, vol_chg)
    if corr is None:
        return 0.0
    return max(-1.0, min(1.0, -corr))


def wq_alpha_006(closes: list[float], volumes: list[float], lows: list[float]) -> float:
    """Alpha#006: rank(-1 * correlation(rank(open), rank(volume), 10))
    开盘价与成交量的负相关 → 弱势开盘
    """
    n = min(12, len(closes), len(volumes))
    if n < 11:
        return 0.0
    rets = []
    for i in range(-n, 0):
        if i >= -n + 1 and closes[i-1] > 0:
            rets.append((closes[i] - closes[i-1]) / closes[i-1])
    vol_norm = [v / max(volumes) for v in volumes[-n:]] if max(volumes) > 0 else volumes[-n:]
    if len(rets) < 8 or len(vol_norm) < 8:
        return 0.0
    corr = _corr(rets, vol_norm)
    if corr is None:
        return 0.0
    return max(-1.0, min(1.0, -corr))


def wq_alpha_049(closes: list[float], volumes: list[float]) -> float:
    """Alpha#049: rank(delta(log(volume), 1)) * (-1 * delta(close, 1))
    成交量增长与价格下跌的乘积 → 放量下跌信号
    """
    if len(closes) < 3 or len(volumes) < 3:
        return 0.0
    vol_log = math.log(max(volumes[-1], 1)) - math.log(max(volumes[-2], 1))
    price_chg = closes[-1] - closes[-2]
    value = vol_log * (-1 * price_chg)
    return max(-1.0, min(1.0, value / (closes[-2] * 0.1) if closes[-2] > 0 else 0))


def wq_alpha_061(closes: list[float], volumes: list[float], opens: list[float]) -> float:
    """Alpha#061: rank(avg((close - open) / open, 5)) * rank(avg(volume, 5))
    日内收益率均值与成交量均值的乘积 → 量价共振
    """
    n = min(6, len(closes), len(opens), len(volumes))
    if n < 5:
        return 0.0
    intraday_rets = []
    for i in range(-n, 0):
        if opens[i] > 0:
            intraday_rets.append((closes[i] - opens[i]) / opens[i])
    vol_avg = sum(volumes[-n:]) / n
    if not intraday_rets:
        return 0.0
    ret_avg = sum(intraday_rets) / len(intraday_rets)
    # 归一化
    ret_norm = max(-1.0, min(1.0, ret_avg * 20))
    vol_norm = max(-1.0, min(1.0, (vol_avg / (sum(volumes[-n*2:-n]) / n) - 1) * 2)) if n*2 <= len(volumes) and sum(volumes[-n*2:-n]) > 0 else 0
    return max(-1.0, min(1.0, ret_norm * 0.5 + vol_norm * 0.5))


def wq_alpha_098(closes: list[float], volumes: list[float], highs: list[float], lows: list[float]) -> float:
    """Alpha#098: 复杂量价因子 — vwap相关性与开盘价排序的差值
    衡量价格趋势与成交量的关系，正值表示上升趋势健康
    """
    n = min(30, len(closes), len(volumes), len(highs), len(lows))
    if n < 20:
        return 0.0
    # 计算vwap代理
    vwap = (closes[-1] + highs[-1] + lows[-1]) / 3
    # 计算adv5, adv15
    adv5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else sum(volumes) / len(volumes)
    adv15 = sum(volumes[-15:]) / 15 if len(volumes) >= 15 else sum(volumes) / len(volumes)
    # 相关性简化
    vwap_series = []
    adv5_series = []
    for i in range(-10, 0):
        if -i <= len(closes) and -i <= len(highs) and -i <= len(lows):
            vwap_series.append((closes[i] + highs[i] + lows[i]) / 3)
        w = 5
        if -i <= len(volumes) and -w <= len(volumes):
            adv5_series.append(sum(volumes[max(i-w, -len(volumes)):i]) / min(w, -i) if i < 0 else 0)
    corr1 = _corr(vwap_series, adv5_series) if len(vwap_series) >= 5 else 0
    # 开盘价排序代理
    open_series = []
    adv15_series = []
    for i in range(-20, 0):
        if -i <= len(closes):
            open_series.append(closes[i])  # 用close代替open
        w = 15
        if -i <= len(volumes) and -w <= len(volumes):
            adv15_series.append(sum(volumes[max(i-w, -len(volumes)):i]) / min(w, -i) if i < 0 else 0)
    corr2 = _corr(open_series, adv15_series) if len(open_series) >= 10 else 0
    if corr1 is None:
        corr1 = 0
    if corr2 is None:
        corr2 = 0
    diff = (corr1 or 0) - (corr2 or 0)
    return max(-1.0, min(1.0, diff))


# ========== 10. BARRA 风格因子（基于MSCI CNE6模型） ==========

def barra_size(closes: list[float], volumes: list[float]) -> float:
    """BARRA 规模因子 — 用成交额代理市值，大盘股倾向高分
    """
    n = min(20, len(closes), len(volumes))
    if n < 5:
        return 0.0
    # 日均成交额作为规模代理
    avg_dv = sum(closes[-i] * volumes[-i] for i in range(1, n+1)) / n
    if avg_dv == 0:
        return 0.0
    # 对数归一化
    log_dv = math.log10(avg_dv) if avg_dv > 0 else 0
    # 假设美股日成交额范围在 1M ~ 10B
    norm = (log_dv - 6) / 4  # 6 = log10(1M), 10 = log10(10B)
    return max(-1.0, min(1.0, norm))


def barra_book_to_price(closes: list[float], volumes: list[float]) -> float:
    """BARRA 账面市值比代理 — 用价格位置代替，价格越低估值越便宜
    """
    if len(closes) < 252:
        return 0.0
    high_52w = max(closes[-252:])
    if high_52w == 0:
        return 0.0
    # 价格接近52周低点 = 高账面市值比（便宜）
    ratio = closes[-1] / high_52w
    return max(-1.0, min(1.0, 1.0 - ratio * 2))


def barra_earnings_yield(closes: list[float], volumes: list[float]) -> float:
    """BARRA 盈利收益率代理 — 用过去收益率的稳定性/大小代替
    """
    if len(closes) < 63:
        return 0.0
    # 过去3个月的年化收益率作为盈利代理
    ret_3m = (closes[-1] - closes[-63]) / closes[-63] if closes[-63] > 0 else 0
    annual_ret = (1 + ret_3m) ** 4 - 1  # 年化
    return max(-1.0, min(1.0, annual_ret * 2))


def barra_growth(closes: list[float], volumes: list[float]) -> float:
    """BARRA 成长因子 — 过去1年价格增长率
    """
    if len(closes) < 252:
        return 0.0
    ret_1y = (closes[-1] - closes[-252]) / closes[-252] if closes[-252] > 0 else 0
    return max(-1.0, min(1.0, ret_1y * 2))


def barra_leverage(closes: list[float], volumes: list[float]) -> float:
    """BARRA 杠杆因子代理 — 用波动率/稳定性代替，高波动=高杠杆倾向
    """
    if len(closes) < 60:
        return 0.0
    returns = []
    for i in range(1, 61):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 20:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    vol = math.sqrt(var_r) * math.sqrt(252)
    return max(-1.0, min(1.0, (vol - 0.30) * 3))


def barra_dividend_yield(closes: list[float]) -> float:
    """BARRA 股息率代理 — 用价格稳定性代替，低波动=高股息倾向
    """
    if len(closes) < 60:
        return 0.0
    returns = []
    for i in range(1, 61):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 20:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    vol = math.sqrt(var_r) * math.sqrt(252)
    # 低波动对应高股息倾向
    if vol < 0.20:
        return 0.8
    elif vol < 0.30:
        return 0.4
    elif vol < 0.40:
        return 0.0
    elif vol < 0.60:
        return -0.4
    else:
        return -0.8


# ========== 11. 高级统计因子 ==========

def stat_return_skewness(closes: list[float], period: int = 60) -> float:
    """收益率偏度 — 正偏度表示右尾长（偶尔大涨）
    """
    if len(closes) < period + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), period + 1)):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 10:
        return 0.0
    n = len(returns)
    mean_r = sum(returns) / n
    var_r = sum((r - mean_r) ** 2 for r in returns) / n
    if var_r == 0:
        return 0.0
    std_r = math.sqrt(var_r)
    skew = sum((r - mean_r) ** 3 for r in returns) / n / (std_r ** 3)
    return max(-1.0, min(1.0, skew / 3))


def stat_return_kurtosis(closes: list[float], period: int = 60) -> float:
    """收益率峰度 — 高峰度表示厚尾（极端事件多）
    """
    if len(closes) < period + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), period + 1)):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 10:
        return 0.0
    n = len(returns)
    mean_r = sum(returns) / n
    var_r = sum((r - mean_r) ** 2 for r in returns) / n
    if var_r == 0:
        return 0.0
    std_r = math.sqrt(var_r)
    kurt = sum((r - mean_r) ** 4 for r in returns) / n / (std_r ** 4) - 3  # 超额峰度
    return max(-1.0, min(1.0, kurt / 5))


def stat_tail_risk(closes: list[float], period: int = 252) -> float:
    """尾风险 — 5% VaR（负值越大表示风险越高）
    """
    if len(closes) < period + 1:
        return 0.0
    returns = []
    for i in range(1, min(len(closes), period + 1)):
        if closes[-i-1] > 0:
            returns.append((closes[-i] - closes[-i-1]) / closes[-i-1])
    if len(returns) < 20:
        return 0.0
    sorted_rets = sorted(returns)
    var_idx = max(0, int(len(sorted_rets) * 0.05) - 1)
    var_5 = sorted_rets[var_idx]
    # 正值（损失小）→ 高分
    return max(-1.0, min(1.0, var_5 * 20 + 0.5))


def stat_calmar_ratio(closes: list[float], lookback: int = 252) -> float:
    """Calmar 比率 — 年化收益率 / 最大回撤
    """
    if len(closes) < lookback:
        return 0.0
    recent = closes[-lookback:]
    total_ret = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
    annual_ret = (1 + total_ret) ** (252 / lookback) - 1 if lookback > 0 else 0
    peak = recent[0]
    max_dd = 0.0
    for p in recent:
        peak = max(peak, p)
        dd = (peak - p) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    if max_dd == 0:
        return 1.0 if annual_ret > 0 else 0.0
    calmar = annual_ret / max_dd
    return max(-1.0, min(1.0, calmar / 5))


def stat_recovery_factor(closes: list[float], lookback: int = 252) -> float:
    """恢复因子 — 总收益 / 最大回撤绝对值
    """
    if len(closes) < lookback:
        return 0.0
    recent = closes[-lookback:]
    total_ret = (recent[-1] - recent[0]) / recent[0] if recent[0] > 0 else 0
    peak = recent[0]
    max_dd = 0.0
    for p in recent:
        peak = max(peak, p)
        dd = (peak - p) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    if max_dd == 0:
        return 1.0 if total_ret > 0 else 0.0
    rf = abs(total_ret / max_dd) if total_ret > 0 else -abs(total_ret / max_dd)
    return max(-1.0, min(1.0, rf / 3))


# ========== 12. 市场微观结构增强因子 ==========

def mi_price_impact(closes: list[float], volumes: list[float], period: int = 20) -> float:
    """价格冲击因子 — 单位成交量引起的价格变化，越低表示流动性越好
    """
    if len(closes) < period + 1 or len(volumes) < period:
        return 0.0
    impacts = []
    for i in range(1, min(period + 1, len(closes), len(volumes) + 1)):
        ret = abs((closes[-i] - closes[-i-1]) / closes[-i-1]) if closes[-i-1] > 0 else 0
        dv = volumes[-i] * closes[-i]
        if dv > 0:
            impacts.append(ret / dv)
    if not impacts:
        return 0.0
    avg_impact = sum(impacts) / len(impacts)
    # 低价格冲击 = 好流动性 = 高分
    return max(-1.0, min(1.0, 0.5 - math.log10(1 + avg_impact * 1e9) / 10))


def mi_volume_imbalance(volumes: list[float], period: int = 10) -> float:
    """成交量不平衡因子 — 最近成交量与历史均值的偏差
    """
    if len(volumes) < period * 2:
        return 0.0
    recent_avg = sum(volumes[-period:]) / period
    old_avg = sum(volumes[-(period * 2):-period]) / period
    if old_avg == 0:
        return 0.0
    imbalance = (recent_avg - old_avg) / old_avg
    return max(-1.0, min(1.0, imbalance * 2))


def mi_tick_rule_proxy(closes: list[float], period: int = 10) -> float:
    """Tick Rule 代理因子 — 价格变化的序列相关性
    """
    if len(closes) < period + 1:
        return 0.0
    signs = []
    for i in range(1, min(period + 1, len(closes))):
        diff = closes[-i] - closes[-i-1]
        if diff > 0:
            signs.append(1)
        elif diff < 0:
            signs.append(-1)
        else:
            signs.append(0)
    if len(signs) < 5:
        return 0.0
    # 正比例表示买方驱动
    buy_ratio = sum(1 for s in signs if s > 0) / len(signs)
    sell_ratio = sum(1 for s in signs if s < 0) / len(signs)
    if buy_ratio + sell_ratio == 0:
        return 0.0
    imbalance = (buy_ratio - sell_ratio) / (buy_ratio + sell_ratio)
    return max(-1.0, min(1.0, imbalance))


def mi_high_low_volatility_enhanced(highs: list[float], lows: list[float], period: int = 20) -> float:
    """增强高低波动率 — 考虑振幅的百分位位置
    """
    if len(highs) < period or len(lows) < period:
        return 0.0
    n = min(period, len(highs), len(lows))
    ranges = []
    for i in range(1, n + 1):
        if highs[-i] > 0:
            ranges.append((highs[-i] - lows[-i]) / highs[-i])
    if not ranges:
        return 0.0
    current_range = ranges[-1]
    sorted_ranges = sorted(ranges)
    # 当前振幅在历史中的百分位
    percentile = sum(1 for r in sorted_ranges if r <= current_range) / len(sorted_ranges)
    # 低百分位 = 低波动 = 高分
    return max(-1.0, min(1.0, 1.0 - percentile * 2))


def mi_gap_analysis(closes: list[float], opens: list[float], period: int = 20) -> float:
    """跳空分析因子 — 开盘跳空幅度的均值与持续性
    """
    if len(closes) < period or len(opens) < period:
        return 0.0
    n = min(period, len(closes), len(opens))
    gaps = []
    for i in range(1, n):
        if closes[-i-1] > 0:
            gap = (opens[-i] - closes[-i-1]) / closes[-i-1]
            gaps.append(gap)
    if not gaps:
        return 0.0
    avg_gap = sum(gaps) / len(gaps)
    # 正的跳空均值 = 强势
    return max(-1.0, min(1.0, avg_gap * 20))


# ========== 13. 截面/相对因子 ==========

def cs_relative_strength(closes: list[float], market_closes: list[float], period: int = 63) -> float:
    """相对强度 — 个股相对市场的表现
    """
    if len(closes) < period or len(market_closes) < period:
        return 0.0
    n = min(period, len(closes), len(market_closes))
    stock_ret = (closes[-1] - closes[-n]) / closes[-n] if closes[-n] > 0 else 0
    market_ret = (market_closes[-1] - market_closes[-n]) / market_closes[-n] if market_closes[-n] > 0 else 0
    rel = stock_ret - market_ret
    return max(-1.0, min(1.0, rel * 5))


def cs_industry_momentum(closes: list[float], market_closes: list[float], period: int = 21) -> float:
    """行业动量代理 — 个股相对市场的短期动量
    """
    if len(closes) < period or len(market_closes) < period:
        return 0.0
    n = min(period, len(closes), len(market_closes))
    stock_mom = (closes[-1] - closes[-n]) / closes[-n] if closes[-n] > 0 else 0
    market_mom = (market_closes[-1] - market_closes[-n]) / market_closes[-n] if market_closes[-n] > 0 else 0
    rel_mom = stock_mom - market_mom
    return max(-1.0, min(1.0, rel_mom * 10))


def cs_percentile_rank(closes: list[float], period: int = 252) -> float:
    """价格百分位排名 — 当前价格在历史中的位置
    """
    if len(closes) < period:
        return 0.0
    recent = closes[-period:]
    current = closes[-1]
    sorted_prices = sorted(recent)
    percentile = sum(1 for p in sorted_prices if p <= current) / len(sorted_prices)
    return max(-1.0, min(1.0, percentile * 2 - 1))


def cs_zscore_value(closes: list[float], period: int = 60) -> float:
    """Z-Score 标准化 — 当前价格偏离均值的标准差倍数
    """
    if len(closes) < period:
        return 0.0
    recent = closes[-period:]
    mean = sum(recent) / period
    if mean == 0:
        return 0.0
    var = sum((c - mean) ** 2 for c in recent) / period
    std = math.sqrt(var) if var > 0 else mean * 0.05
    z = (closes[-1] - mean) / std
    return max(-1.0, min(1.0, z / 3))


# ========== 17. Qlib Alpha158 量价因子（Microsoft Qlib, ~17k stars） ==========
# 来源: https://github.com/microsoft/qlib （qlib/contrib/data/loader.py, Alpha158DL）
# Alpha158 是 Qlib 内置 158 维量价因子库，广泛用于机器学习选股（LightGBM 等）。
# 此处实现其核心因子族：K线形态、归一化价格、滚动窗口统计/位置/相关/涨跌/量能。


def _ts_mean(x: list[float], w: int):
    if len(x) < w or w <= 0:
        return None
    return sum(x[-w:]) / w


def _ts_std(x: list[float], w: int):
    if len(x) < w or w <= 0:
        return None
    seg = x[-w:]
    m = sum(seg) / w
    return math.sqrt(sum((v - m) ** 2 for v in seg) / w)


def _ts_max(x: list[float], w: int):
    if len(x) < w or w <= 0:
        return None
    return max(x[-w:])


def _ts_min(x: list[float], w: int):
    if len(x) < w or w <= 0:
        return None
    return min(x[-w:])


def _ts_rank(x: list[float], w: int):
    """当前值在过去 w 日中的分位 [0,1]（Qlib Rank）"""
    if len(x) < w or w <= 0:
        return None
    seg = x[-w:]
    below = sum(1 for v in seg if v <= seg[-1])
    return below / w


def _ts_slope(x: list[float], w: int):
    """过去 w 日最小二乘线性回归斜率（Qlib Slope）"""
    if len(x) < w or w <= 0:
        return None
    seg = x[-w:]
    mx = (w - 1) / 2.0
    my = sum(seg) / w
    num = sum((i - mx) * (v - my) for i, v in enumerate(seg))
    den = sum((i - mx) ** 2 for i in range(w))
    if den == 0:
        return 0.0
    return num / den


def _ts_rsquare(x: list[float], w: int):
    """过去 w 日线性回归 R²，代表趋势线性度（Qlib Rsquare）"""
    if len(x) < w or w <= 0:
        return None
    seg = x[-w:]
    slope = _ts_slope(x, w)
    my = sum(seg) / w
    mx = (w - 1) / 2.0
    intercept = my - slope * mx
    ss_res = sum((v - (slope * i + intercept)) ** 2 for i, v in enumerate(seg))
    ss_tot = sum((v - my) ** 2 for v in seg)
    if ss_tot == 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - ss_res / ss_tot))


def _ts_resi(x: list[float], w: int):
    """过去 w 日线性回归最后一期残差（Qlib Resi）"""
    if len(x) < w or w <= 0:
        return None
    seg = x[-w:]
    slope = _ts_slope(x, w)
    my = sum(seg) / w
    mx = (w - 1) / 2.0
    intercept = my - slope * mx
    return seg[-1] - (slope * (w - 1) + intercept)


def _ts_idxmax(x: list[float], w: int):
    """距最近一次创新高的天数/w，0=今天创新高（Qlib IdxMax, Aroon）"""
    if len(x) < w or w <= 0:
        return None
    seg = x[-w:]
    m = max(seg)
    for i in range(w - 1, -1, -1):
        if seg[i] == m:
            return (w - 1 - i) / w
    return 0.0


def _ts_idxmin(x: list[float], w: int):
    """距最近一次创新低的天数/w（Qlib IdxMin, Aroon）"""
    if len(x) < w or w <= 0:
        return None
    seg = x[-w:]
    m = min(seg)
    for i in range(w - 1, -1, -1):
        if seg[i] == m:
            return (w - 1 - i) / w
    return 0.0


# ── KBAR K线形态（9个）──

def qlib_kmid(closes: list[float], opens: list[float]) -> float:
    """KMID: (close-open)/open 日内涨跌幅"""
    if not closes or not opens:
        return 0.0
    return _safe_div(closes[-1] - opens[-1], opens[-1])


def qlib_klen(highs: list[float], lows: list[float], opens: list[float]) -> float:
    """KLEN: (high-low)/open 日内振幅"""
    if not highs or not lows or not opens:
        return 0.0
    return _safe_div(highs[-1] - lows[-1], opens[-1])


def qlib_kmid2(closes: list[float], opens: list[float], highs: list[float], lows: list[float]) -> float:
    """KMID2: (close-open)/(high-low) 收盘位置（振幅归一）"""
    if not closes or not opens or not highs or not lows:
        return 0.0
    return _safe_div(closes[-1] - opens[-1], highs[-1] - lows[-1])


def qlib_kup(closes: list[float], opens: list[float], highs: list[float]) -> float:
    """KUP: (high-max(open,close))/open 上影线幅度"""
    if not closes or not opens or not highs:
        return 0.0
    return _safe_div(highs[-1] - max(opens[-1], closes[-1]), opens[-1])


def qlib_kup2(closes: list[float], opens: list[float], highs: list[float], lows: list[float]) -> float:
    """KUP2: (high-max(open,close))/(high-low) 上影线占比"""
    if not closes or not opens or not highs or not lows:
        return 0.0
    return _safe_div(highs[-1] - max(opens[-1], closes[-1]), highs[-1] - lows[-1])


def qlib_klow(closes: list[float], opens: list[float], lows: list[float]) -> float:
    """KLOW: (min(open,close)-low)/open 下影线幅度"""
    if not closes or not opens or not lows:
        return 0.0
    return _safe_div(min(opens[-1], closes[-1]) - lows[-1], opens[-1])


def qlib_klow2(closes: list[float], opens: list[float], highs: list[float], lows: list[float]) -> float:
    """KLOW2: (min(open,close)-low)/(high-low) 下影线占比"""
    if not closes or not opens or not highs or not lows:
        return 0.0
    return _safe_div(min(opens[-1], closes[-1]) - lows[-1], highs[-1] - lows[-1])


def qlib_ksft(closes: list[float], opens: list[float], highs: list[float], lows: list[float]) -> float:
    """KSFT: (2*close-high-low)/open 收盘偏移（正=收在上方）"""
    if not closes or not opens or not highs or not lows:
        return 0.0
    return _safe_div(2 * closes[-1] - highs[-1] - lows[-1], opens[-1])


def qlib_ksft2(closes: list[float], opens: list[float], highs: list[float], lows: list[float]) -> float:
    """KSFT2: (2*close-high-low)/(high-low) 收盘偏移（振幅归一）"""
    if not closes or not opens or not highs or not lows:
        return 0.0
    return _safe_div(2 * closes[-1] - highs[-1] - lows[-1], highs[-1] - lows[-1])


# ── 归一化价格（3个）──

def qlib_open0(closes: list[float], opens: list[float]) -> float:
    """OPEN0: open/close 开盘相对收盘"""
    if not closes or not opens:
        return 0.0
    return _safe_div(opens[-1], closes[-1])


def qlib_high0(closes: list[float], highs: list[float]) -> float:
    """HIGH0: high/close 日内高点相对收盘"""
    if not closes or not highs:
        return 0.0
    return _safe_div(highs[-1], closes[-1])


def qlib_low0(closes: list[float], lows: list[float]) -> float:
    """LOW0: low/close 日内低点相对收盘"""
    if not closes or not lows:
        return 0.0
    return _safe_div(lows[-1], closes[-1])


# ── Rolling 滚动窗口族（参数化窗口，批量注册 5/20/60）──

def qlib_roc(closes: list[float], w: int) -> float:
    """ROC: Ref(close,w)/close 过去 w 日价格变化率"""
    if len(closes) < w + 1 or w <= 0:
        return 0.0
    return _safe_div(closes[-w - 1], closes[-1])


def qlib_ma(closes: list[float], w: int) -> float:
    """MA: 过去 w 日均价/今收盘（均线偏离）"""
    m = _ts_mean(closes, w)
    if m is None or not closes:
        return 0.0
    return _safe_div(m, closes[-1])


def qlib_std(closes: list[float], w: int) -> float:
    """STD: 过去 w 日收盘标准差/今收盘（波动率）"""
    s = _ts_std(closes, w)
    if s is None or not closes:
        return 0.0
    return _safe_div(s, closes[-1])


def qlib_beta(closes: list[float], w: int) -> float:
    """BETA: 过去 w 日线性回归斜率/今收盘（趋势斜率）"""
    s = _ts_slope(closes, w)
    if s is None or not closes:
        return 0.0
    return _safe_div(s, closes[-1])


def qlib_rsqr(closes: list[float], w: int) -> float:
    """RSQR: 过去 w 日趋势线性度 R²"""
    v = _ts_rsquare(closes, w)
    return v if v is not None else 0.0


def qlib_resi(closes: list[float], w: int) -> float:
    """RESI: 过去 w 日回归残差/今收盘（偏离趋势线程度）"""
    v = _ts_resi(closes, w)
    if v is None or not closes:
        return 0.0
    return _safe_div(v, closes[-1])


def qlib_max(highs: list[float], closes: list[float], w: int) -> float:
    """MAX: 过去 w 日最高价/今收盘（距高点距离）"""
    m = _ts_max(highs, w)
    if m is None or not closes:
        return 0.0
    return _safe_div(m, closes[-1])


def qlib_min(lows: list[float], closes: list[float], w: int) -> float:
    """MIN: 过去 w 日最低价/今收盘（距低点距离）"""
    m = _ts_min(lows, w)
    if m is None or not closes:
        return 0.0
    return _safe_div(m, closes[-1])


def qlib_rsv(closes: list[float], highs: list[float], lows: list[float], w: int) -> float:
    """RSV: (close-Min(low,w))/(Max(high,w)-Min(low,w)) 随机指标位置"""
    hh = _ts_max(highs, w)
    ll = _ts_min(lows, w)
    if hh is None or ll is None or not closes:
        return 0.0
    return _safe_div(closes[-1] - ll, hh - ll)


def qlib_rank(closes: list[float], w: int) -> float:
    """RANK: 当前收盘在过去 w 日中的分位 [0,1]"""
    v = _ts_rank(closes, w)
    return v if v is not None else 0.0


def qlib_imax(highs: list[float], w: int) -> float:
    """IMAX: 距最近新高的天数/w（Aroon 上轨）"""
    v = _ts_idxmax(highs, w)
    return v if v is not None else 0.0


def qlib_imin(lows: list[float], w: int) -> float:
    """IMIN: 距最近新低的天数/w（Aroon 下轨）"""
    v = _ts_idxmin(lows, w)
    return v if v is not None else 0.0


def qlib_corr(closes: list[float], volumes: list[float], w: int) -> float:
    """CORR: 收盘价与 log(成交量+1) 的相关（量价同向性）"""
    if len(closes) < w or len(volumes) < w or w <= 0:
        return 0.0
    logv = [math.log(v + 1) for v in volumes[-w:]]
    c = _corr(closes[-w:], logv)
    return c if c is not None else 0.0


def qlib_cntp(closes: list[float], w: int) -> float:
    """CNTP: 过去 w 日上涨天数占比"""
    if len(closes) < w + 1 or w <= 0:
        return 0.0
    seg = closes[-(w + 1):]
    ups = sum(1 for i in range(1, len(seg)) if seg[i] > seg[i - 1])
    return ups / w


def qlib_cntd(closes: list[float], w: int) -> float:
    """CNTD: (上涨天数-下跌天数)/w 涨跌净占比"""
    if len(closes) < w + 1 or w <= 0:
        return 0.0
    seg = closes[-(w + 1):]
    ups = sum(1 for i in range(1, len(seg)) if seg[i] > seg[i - 1])
    downs = sum(1 for i in range(1, len(seg)) if seg[i] < seg[i - 1])
    return (ups - downs) / w


def qlib_sump(closes: list[float], w: int) -> float:
    """SUMP: 过去 w 日总涨幅/总绝对波动（RSI 类）"""
    if len(closes) < w + 1 or w <= 0:
        return 0.0
    seg = closes[-(w + 1):]
    gains = sum(max(seg[i] - seg[i - 1], 0.0) for i in range(1, len(seg)))
    total = sum(abs(seg[i] - seg[i - 1]) for i in range(1, len(seg)))
    return _safe_div(gains, total)


def qlib_vma(volumes: list[float], w: int) -> float:
    """VMA: 过去 w 日平均成交量/今成交量（量能变化）"""
    m = _ts_mean(volumes, w)
    if m is None or not volumes:
        return 0.0
    return _safe_div(m, volumes[-1])


def qlib_vstd(volumes: list[float], w: int) -> float:
    """VSTD: 过去 w 日成交量标准差/今成交量（量能波动）"""
    s = _ts_std(volumes, w)
    if s is None or not volumes:
        return 0.0
    return _safe_div(s, volumes[-1])


def qlib_wvma(closes: list[float], volumes: list[float], w: int) -> float:
    """WVMA: 量加权价格波动系数 Std(|ret|*vol)/Mean(|ret|*vol)"""
    if len(closes) < w + 1 or len(volumes) < w + 1 or w <= 0:
        return 0.0
    vals = [abs(closes[i] / closes[i - 1] - 1.0) * volumes[i]
            for i in range(len(closes) - w, len(closes)) if closes[i - 1] != 0]
    m = _ts_mean(vals, w)
    s = _ts_std(vals, w)
    if m is None or s is None:
        return 0.0
    return _safe_div(s, m)


def qlib_vsump(volumes: list[float], w: int) -> float:
    """VSUMP: 过去 w 日放量涨幅和/量总变化（量 RSI）"""
    if len(volumes) < w + 1 or w <= 0:
        return 0.0
    seg = volumes[-(w + 1):]
    gains = sum(max(seg[i] - seg[i - 1], 0.0) for i in range(1, len(seg)))
    total = sum(abs(seg[i] - seg[i - 1]) for i in range(1, len(seg)))
    return _safe_div(gains, total)


def strategy_us_bs_strong(closes, highs, lows, opens, volumes) -> float:
    """强 B/S 当前状态：1=强B持有，-1=当日S退出，0=观察。"""
    from us_quant.bs_strategy import strong_bs_factor
    return strong_bs_factor(closes, highs, lows, opens, volumes)


# ========== 因子注册表 ==========

FACTOR_REGISTRY = {
    "strategy_us_bs_strong": {
        "name": "美股强 B/S 策略",
        "fn": strategy_us_bs_strong,
        "category": "独立策略因子",
        "params": ["closes", "highs", "lows", "opens", "volumes"],
        "kind": "strategy",
        "route": "/us-bs-strategy",
        "description": "1=强B持有，-1=当日S退出，0=观察；8%止盈或30日退出。",
        "version": "strong-v1",
    },
    # 1. 价格价值型
    "value_price_to_52w_high": {"name": "52周高点价值", "fn": value_price_to_52w_high, "category": "价格价值型", "params": ["closes"]},
    "value_price_to_ma_ratio": {"name": "均线偏离价值", "fn": value_price_to_ma_ratio, "category": "价格价值型", "params": ["closes"]},
    "value_bollinger_position": {"name": "布林带位置", "fn": value_bollinger_position, "category": "价格价值型", "params": ["closes"]},
    "value_drawdown_depth": {"name": "回撤深度", "fn": value_drawdown_depth, "category": "价格价值型", "params": ["closes"]},
    # 2. 质量稳定性型
    "quality_trend_stability": {"name": "趋势稳定性", "fn": quality_trend_stability, "category": "质量稳定性型", "params": ["closes"]},
    "quality_earnings_stability": {"name": "收益稳定性", "fn": quality_earnings_stability, "category": "质量稳定性型", "params": ["closes"]},
    "quality_serial_correlation": {"name": "序列自相关", "fn": quality_serial_correlation, "category": "质量稳定性型", "params": ["closes"]},
    "quality_drawdown_ratio": {"name": "收益回撤比", "fn": quality_drawdown_ratio, "category": "质量稳定性型", "params": ["closes"]},
    # 3. 成长加速度型
    "growth_price_acceleration": {"name": "价格加速度", "fn": growth_price_acceleration, "category": "成长加速度型", "params": ["closes"]},
    "growth_volume_trend": {"name": "成交量增长趋势", "fn": growth_volume_trend, "category": "成长加速度型", "params": ["volumes"]},
    "growth_momentum_ratio": {"name": "动量比", "fn": growth_momentum_ratio, "category": "成长加速度型", "params": ["closes"]},
    "growth_high_low_ratio": {"name": "高低点扩张比", "fn": growth_high_low_ratio, "category": "成长加速度型", "params": ["closes", "highs", "lows"]},
    # 4. 相关性因子
    "correlation_beta": {"name": "Beta系数", "fn": correlation_beta, "category": "相关性因子", "params": ["closes", "market_closes"]},
    "correlation_market_corr": {"name": "市场相关性", "fn": correlation_market_corr, "category": "相关性因子", "params": ["closes", "market_closes"]},
    "correlation_idiosyncratic_vol": {"name": "特质波动率", "fn": correlation_idiosyncratic_vol, "category": "相关性因子", "params": ["closes", "market_closes"]},
    # 5. 流动性因子
    "liquidity_dollar_volume": {"name": "成交金额因子", "fn": liquidity_dollar_volume, "category": "流动性因子", "params": ["volumes", "closes"]},
    "liquidity_turnover_ratio": {"name": "换手率因子", "fn": liquidity_turnover_ratio, "category": "流动性因子", "params": ["volumes"]},
    "liquidity_amihud": {"name": "Amihud流动性", "fn": liquidity_amihud_illiquidity, "category": "流动性因子", "params": ["closes", "volumes"]},
    "liquidity_volume_consistency": {"name": "成交量一致性", "fn": liquidity_volume_consistency, "category": "流动性因子", "params": ["volumes"]},
    # 6. 技术形态因子
    "pattern_candlestick_bullish": {"name": "看涨K线形态", "fn": pattern_candlestick_bullish, "category": "技术形态因子", "params": ["closes", "opens", "highs", "lows"]},
    "pattern_candlestick_bearish": {"name": "看跌K线形态", "fn": pattern_candlestick_bearish, "category": "技术形态因子", "params": ["closes", "opens", "highs", "lows"]},
    "pattern_support_resistance": {"name": "支撑阻力位", "fn": pattern_support_resistance, "category": "技术形态因子", "params": ["closes", "highs", "lows"]},
    "pattern_volume_breakout": {"name": "量能突破形态", "fn": pattern_volume_breakout, "category": "技术形态因子", "params": ["volumes", "closes"]},
    # 7. 市场微观结构
    "microstructure_vol_price_corr": {"name": "量价相关性", "fn": microstructure_volume_price_corr, "category": "市场微观结构", "params": ["closes", "volumes"]},
    "microstructure_vw_ret": {"name": "量加权收益", "fn": microstructure_volume_weighted_ret, "category": "市场微观结构", "params": ["closes", "volumes"]},
    "microstructure_price_reversal_1d": {"name": "日内反转信号", "fn": microstructure_price_reversal_1d, "category": "市场微观结构", "params": ["closes", "volumes"]},
    "microstructure_intraday_vol": {"name": "日内波动率", "fn": microstructure_intraday_volatility, "category": "市场微观结构", "params": ["highs", "lows"]},
    # 8. 季节效应因子
    "seasonality_day_of_week": {"name": "周几效应", "fn": seasonality_day_of_week, "category": "季节效应因子", "params": []},
    "seasonality_month_effect": {"name": "月份效应", "fn": seasonality_month_effect, "category": "季节效应因子", "params": []},
    "seasonality_turn_of_month": {"name": "月末月初效应", "fn": seasonality_turn_of_month, "category": "季节效应因子", "params": []},
    # 9. WorldQuant Alpha 风格因子
    "wq_alpha_001": {"name": "Alpha#001 动量强度", "fn": wq_alpha_001, "category": "WorldQuant Alpha", "params": ["closes"]},
    "wq_alpha_002": {"name": "Alpha#002 量价背离", "fn": wq_alpha_002, "category": "WorldQuant Alpha", "params": ["closes", "volumes", "opens"]},
    "wq_alpha_003": {"name": "Alpha#003 开盘量价", "fn": wq_alpha_003, "category": "WorldQuant Alpha", "params": ["closes", "volumes", "opens"]},
    "wq_alpha_005": {"name": "Alpha#005 高价量价", "fn": wq_alpha_005, "category": "WorldQuant Alpha", "params": ["closes", "volumes", "highs"]},
    "wq_alpha_006": {"name": "Alpha#006 开盘量价2", "fn": wq_alpha_006, "category": "WorldQuant Alpha", "params": ["closes", "volumes", "lows"]},
    "wq_alpha_049": {"name": "Alpha#049 放量下跌", "fn": wq_alpha_049, "category": "WorldQuant Alpha", "params": ["closes", "volumes"]},
    "wq_alpha_061": {"name": "Alpha#061 量价共振", "fn": wq_alpha_061, "category": "WorldQuant Alpha", "params": ["closes", "volumes", "opens"]},
    "wq_alpha_098": {"name": "Alpha#098 复杂量价", "fn": wq_alpha_098, "category": "WorldQuant Alpha", "params": ["closes", "volumes", "highs", "lows"]},
    # 10. BARRA 风格因子
    "barra_size": {"name": "BARRA 规模因子", "fn": barra_size, "category": "BARRA风格", "params": ["closes", "volumes"]},
    "barra_book_to_price": {"name": "BARRA 账面市值比", "fn": barra_book_to_price, "category": "BARRA风格", "params": ["closes", "volumes"]},
    "barra_earnings_yield": {"name": "BARRA 盈利收益率", "fn": barra_earnings_yield, "category": "BARRA风格", "params": ["closes", "volumes"]},
    "barra_growth": {"name": "BARRA 成长因子", "fn": barra_growth, "category": "BARRA风格", "params": ["closes", "volumes"]},
    "barra_leverage": {"name": "BARRA 杠杆因子", "fn": barra_leverage, "category": "BARRA风格", "params": ["closes", "volumes"]},
    "barra_dividend_yield": {"name": "BARRA 股息率因子", "fn": barra_dividend_yield, "category": "BARRA风格", "params": ["closes"]},
    # 11. 高级统计因子
    "stat_return_skewness": {"name": "收益率偏度", "fn": stat_return_skewness, "category": "高级统计", "params": ["closes"]},
    "stat_return_kurtosis": {"name": "收益率峰度", "fn": stat_return_kurtosis, "category": "高级统计", "params": ["closes"]},
    "stat_tail_risk": {"name": "尾风险VaR", "fn": stat_tail_risk, "category": "高级统计", "params": ["closes"]},
    "stat_calmar_ratio": {"name": "Calmar比率", "fn": stat_calmar_ratio, "category": "高级统计", "params": ["closes"]},
    "stat_recovery_factor": {"name": "恢复因子", "fn": stat_recovery_factor, "category": "高级统计", "params": ["closes"]},
    # 12. 市场微观结构增强
    "mi_price_impact": {"name": "价格冲击因子", "fn": mi_price_impact, "category": "微观结构增强", "params": ["closes", "volumes"]},
    "mi_volume_imbalance": {"name": "成交量不平衡", "fn": mi_volume_imbalance, "category": "微观结构增强", "params": ["volumes"]},
    "mi_tick_rule_proxy": {"name": "Tick Rule代理", "fn": mi_tick_rule_proxy, "category": "微观结构增强", "params": ["closes"]},
    "mi_high_low_vol_enhanced": {"name": "增强高低波动", "fn": mi_high_low_volatility_enhanced, "category": "微观结构增强", "params": ["highs", "lows"]},
    "mi_gap_analysis": {"name": "跳空分析因子", "fn": mi_gap_analysis, "category": "微观结构增强", "params": ["closes", "opens"]},
    # 13. 截面/相对因子
    "cs_relative_strength": {"name": "相对强度", "fn": cs_relative_strength, "category": "截面相对", "params": ["closes", "market_closes"]},
    "cs_industry_momentum": {"name": "行业动量代理", "fn": cs_industry_momentum, "category": "截面相对", "params": ["closes", "market_closes"]},
    "cs_percentile_rank": {"name": "价格百分位", "fn": cs_percentile_rank, "category": "截面相对", "params": ["closes"]},
    "cs_zscore_value": {"name": "Z-Score标准化", "fn": cs_zscore_value, "category": "截面相对", "params": ["closes"]},
    # 14. 技术指标因子
    "tech_kdj": {"name": "KDJ随机指标", "fn": tech_kdj, "category": "技术指标因子", "params": ["closes", "highs", "lows"]},
    "tech_willr": {"name": "威廉指标%R", "fn": tech_willr, "category": "技术指标因子", "params": ["highs", "lows", "closes"]},
    "tech_adx": {"name": "ADX趋势强度", "fn": tech_adx, "category": "技术指标因子", "params": ["closes", "highs", "lows"]},
    "tech_cci": {"name": "CCI商品通道", "fn": tech_cci, "category": "技术指标因子", "params": ["closes", "highs", "lows"]},
    "tech_aroon": {"name": "阿隆趋势指标", "fn": tech_aroon, "category": "技术指标因子", "params": ["highs", "lows"]},
    "tech_dmi_plus": {"name": "DMI+趋向指标", "fn": tech_dmi_plus, "category": "技术指标因子", "params": ["highs", "lows", "closes"]},
    "tech_chaikin_osc": {"name": "Chaikin摆动", "fn": tech_chaikin_osc, "category": "技术指标因子", "params": ["closes", "highs", "lows", "volumes"]},
    # 15. 高级风险因子
    "risk_semi_variance": {"name": "下半方差风险", "fn": risk_semi_variance, "category": "高级风险因子", "params": ["closes"]},
    "risk_cvar": {"name": "CVaR尾部风险", "fn": risk_cvar, "category": "高级风险因子", "params": ["closes"]},
    "risk_ulcer_index": {"name": "溃疡指数", "fn": risk_ulcer_index, "category": "高级风险因子", "params": ["closes"]},
    "risk_downside_volatility": {"name": "下行波动率", "fn": risk_downside_volatility, "category": "高级风险因子", "params": ["closes"]},
    "risk_sharpe_ratio": {"name": "夏普比率", "fn": risk_sharpe_ratio, "category": "高级风险因子", "params": ["closes"]},
    "risk_sortino_ratio": {"name": "索提诺比率", "fn": risk_sortino_ratio, "category": "高级风险因子", "params": ["closes"]},
    # 16. 趋势与成交量因子
    "trend_ease_of_movement": {"name": "运动轻松度", "fn": trend_ease_of_movement, "category": "趋势与成交量", "params": ["highs", "lows", "volumes"]},
    "trend_accumulation_distribution": {"name": "累积分配线", "fn": trend_accumulation_distribution, "category": "趋势与成交量", "params": ["closes", "highs", "lows", "volumes"]},
    "trend_volume_price_confirmation": {"name": "量价确认因子", "fn": trend_volume_price_confirmation, "category": "趋势与成交量", "params": ["closes", "volumes"]},
    "trend_volume_trend_intensity": {"name": "量能趋势强度", "fn": trend_volume_trend_intensity, "category": "趋势与成交量", "params": ["volumes"]},
    "trend_price_channel_position": {"name": "价格通道位置", "fn": trend_price_channel_position, "category": "趋势与成交量", "params": ["closes", "highs", "lows"]},
    "trend_money_flow_ratio": {"name": "资金流比率", "fn": trend_money_flow_ratio, "category": "趋势与成交量", "params": ["closes", "highs", "lows", "volumes"]},
}


# 18. Qlib Alpha158 批量注册（KBAR 9 + 归一化价格 3 + Rolling 20族×3窗口 = 72 个）

def _qlib_make(name: str, label: str, fn, params: list, window=None):
    if window is None:
        def _f(*args):
            return fn(*args)
    else:
        def _f(*args):
            return fn(*args, window)
    _f.__name__ = name
    return {"name": label, "fn": _f, "category": "Qlib Alpha158", "params": params}


_QLIB_EXTRA = {}
# K线形态
_QLIB_EXTRA["KMID"] = _qlib_make("KMID", "Qlib K线 日内涨跌", qlib_kmid, ["closes", "opens"])
_QLIB_EXTRA["KLEN"] = _qlib_make("KLEN", "Qlib K线 日内振幅", qlib_klen, ["highs", "lows", "opens"])
_QLIB_EXTRA["KMID2"] = _qlib_make("KMID2", "Qlib K线 收盘位置", qlib_kmid2, ["closes", "opens", "highs", "lows"])
_QLIB_EXTRA["KUP"] = _qlib_make("KUP", "Qlib K线 上影线", qlib_kup, ["closes", "opens", "highs"])
_QLIB_EXTRA["KUP2"] = _qlib_make("KUP2", "Qlib K线 上影占比", qlib_kup2, ["closes", "opens", "highs", "lows"])
_QLIB_EXTRA["KLOW"] = _qlib_make("KLOW", "Qlib K线 下影线", qlib_klow, ["closes", "opens", "lows"])
_QLIB_EXTRA["KLOW2"] = _qlib_make("KLOW2", "Qlib K线 下影占比", qlib_klow2, ["closes", "opens", "highs", "lows"])
_QLIB_EXTRA["KSFT"] = _qlib_make("KSFT", "Qlib K线 收盘偏移", qlib_ksft, ["closes", "opens", "highs", "lows"])
_QLIB_EXTRA["KSFT2"] = _qlib_make("KSFT2", "Qlib K线 偏移占比", qlib_ksft2, ["closes", "opens", "highs", "lows"])
# 归一化价格
_QLIB_EXTRA["OPEN0"] = _qlib_make("OPEN0", "Qlib 开盘相对收盘", qlib_open0, ["closes", "opens"])
_QLIB_EXTRA["HIGH0"] = _qlib_make("HIGH0", "Qlib 高点相对收盘", qlib_high0, ["closes", "highs"])
_QLIB_EXTRA["LOW0"] = _qlib_make("LOW0", "Qlib 低点相对收盘", qlib_low0, ["closes", "lows"])
# Rolling 族 × [5, 20, 60]
_QLIB_ROLLING = [
    ("ROC", "Qlib 价格变化率", qlib_roc, ["closes"]),
    ("MA", "Qlib 均线偏离", qlib_ma, ["closes"]),
    ("STD", "Qlib 波动率", qlib_std, ["closes"]),
    ("BETA", "Qlib 趋势斜率", qlib_beta, ["closes"]),
    ("RSQR", "Qlib 趋势线性度", qlib_rsqr, ["closes"]),
    ("RESI", "Qlib 回归残差", qlib_resi, ["closes"]),
    ("MAX", "Qlib 高点距离", qlib_max, ["highs", "closes"]),
    ("MIN", "Qlib 低点距离", qlib_min, ["lows", "closes"]),
    ("RSV", "Qlib 随机指标", qlib_rsv, ["closes", "highs", "lows"]),
    ("RANK", "Qlib 价格分位", qlib_rank, ["closes"]),
    ("IMAX", "Qlib 新高时间", qlib_imax, ["highs"]),
    ("IMIN", "Qlib 新低时间", qlib_imin, ["lows"]),
    ("CORR", "Qlib 量价相关", qlib_corr, ["closes", "volumes"]),
    ("CNTP", "Qlib 上涨天数占比", qlib_cntp, ["closes"]),
    ("CNTD", "Qlib 涨跌净占比", qlib_cntd, ["closes"]),
    ("SUMP", "Qlib RSI涨幅占比", qlib_sump, ["closes"]),
    ("VMA", "Qlib 量均线偏离", qlib_vma, ["volumes"]),
    ("VSTD", "Qlib 量能波动", qlib_vstd, ["volumes"]),
    ("WVMA", "Qlib 量加权波动", qlib_wvma, ["closes", "volumes"]),
    ("VSUMP", "Qlib 放量占比", qlib_vsump, ["volumes"]),
]
for _qname, _qlabel, _qfn, _qparams in _QLIB_ROLLING:
    for _qw in (5, 20, 60):
        _QLIB_EXTRA[f"{_qname}{_qw}"] = _qlib_make(f"{_qname}{_qw}", f"{_qlabel}({_qw})", _qfn, _qparams, _qw)
# ========== 18. WorldQuant 101 Alphas 补全（论文: Kakushadze, 101 Formulaic Alphas, arXiv:1601.00991） ==========
# 101 个公式化 Alpha 中的多数依赖截面算子（rank/scale/adv20/行业中性化），
# 本系统为单股时序计算架构，此处补全其中【纯时序可算】的因子：
#   - 直接实现：只含 ts_* 时序算子与条件表达式的因子
#   - adv20（20 日均成交额）用 sma(volume,20) 近似（截面近似，注释标注）
#   - vwap 用典型价 (high+low+close)/3 代理（与项目现有惯例一致）
# 公式均对照论文原文 Appendix A.1。


def _wq_delta(x: list[float], n: int):
    """delta(x,n) = x[t] - x[t-n]"""
    if len(x) < n + 1 or n <= 0:
        return 0.0
    return x[-1] - x[-1 - n]


def _wq_delay(x: list[float], n: int):
    """delay(x,n) = x[t-n]"""
    if len(x) < n + 1 or n < 0:
        return None
    return x[-1 - n]


def _wq_sign(x: float) -> float:
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def _wq_signedpower(x: float, e: float) -> float:
    """SignedPower：保留符号的幂运算"""
    if x == 0:
        return 0.0
    return math.copysign(abs(x) ** e, x)


def _wq_corr_series(x: list[float], y: list[float], n: int) -> list[float]:
    """逐日计算过去 n 天 Pearson 相关系数序列（论文 correlation(x,y,n)）"""
    out = []
    for i in range(len(x)):
        if i < n - 1:
            out.append(0.0)
            continue
        segx = x[i - n + 1:i + 1]
        segy = y[i - n + 1:i + 1]
        mx = sum(segx) / n
        my = sum(segy) / n
        num = sum((a - mx) * (b - my) for a, b in zip(segx, segy))
        dx = math.sqrt(sum((a - mx) ** 2 for a in segx))
        dy = math.sqrt(sum((b - my) ** 2 for b in segy))
        if dx == 0 or dy == 0:
            out.append(0.0)
        else:
            out.append(num / (dx * dy))
    return out


def _wq_corr(x: list[float], y: list[float], n: int) -> float:
    """correlation(x,y,n) 当前值"""
    s = _wq_corr_series(x, y, n)
    return s[-1] if s else 0.0


def _wq_decay_linear_series(x: list[float], n: int) -> list[float]:
    """decay_linear(x,n)：线性加权移动平均（权重 1..n 归一化）序列"""
    wsum = n * (n + 1) / 2.0
    out = []
    for i in range(len(x)):
        if i < n - 1:
            out.append(0.0)
            continue
        seg = x[i - n + 1:i + 1]
        out.append(sum((j + 1) * v for j, v in enumerate(seg)) / wsum)
    return out


def _wq_ts_rank_series(x: list[float], n: int) -> list[float]:
    """ts_rank(x,n)：逐日计算当日值在过去 n 天窗口内的分位 [0,1] 序列"""
    out = []
    for i in range(len(x)):
        if i < n - 1:
            out.append(0.5)
            continue
        seg = x[i - n + 1:i + 1]
        below = sum(1 for v in seg if v <= seg[-1])
        out.append(below / n)
    return out


def _wq_adv20(volumes: list[float]) -> list[float]:
    """adv20 近似：20 日平均成交量序列（论文为 20 日平均成交额，量纲近似）"""
    out = []
    for i in range(len(volumes)):
        if i < 19:
            out.append(0.0)
        else:
            out.append(sum(volumes[i - 19:i + 1]) / 20.0)
    return out


def _wq_vwap(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    """vwap 代理：典型价 (h+l+c)/3（项目现有惯例）"""
    return [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]


# ---- 纯时序 Alpha（无截面算子，忠实论文公式） ----

def wq_alpha_006(closes, highs, lows, opens, volumes):
    """Alpha#006: -1 * correlation(open, volume, 10)
    开盘价与成交量的负相关，捕捉高开低量/低开高量的反转信号
    """
    if len(opens) < 10 or len(volumes) < 10:
        return 0.0
    return -1.0 * _wq_corr(opens, volumes, 10)


def wq_alpha_009(closes, highs, lows, opens, volumes):
    """Alpha#009: 近5日无持续下跌则取当日涨跌，否则反转
    条件：(0 < ts_min(delta(close,1),5)) ? delta : (ts_max(delta(close,1),5) < 0 ? delta : -delta)
    """
    if len(closes) < 6:
        return 0.0
    d = _wq_delta(closes, 1)
    seg = [closes[i] - closes[i - 1] for i in range(-4, 0)]
    if len(seg) < 5:
        return d
    if min(seg) > 0:
        return d
    if max(seg) < 0:
        return d
    return -1.0 * d


def wq_alpha_012(closes, highs, lows, opens, volumes):
    """Alpha#012: sign(delta(volume,1)) * (-1 * delta(close,1))
    量增价跌为正（放量下跌后的反转做多信号）
    """
    if len(volumes) < 2 or len(closes) < 2:
        return 0.0
    return _wq_sign(_wq_delta(volumes, 1)) * (-1.0 * _wq_delta(closes, 1))


def wq_alpha_023(closes, highs, lows, opens, volumes):
    """Alpha#023: (sum(high,20)/20 < high) ? (-1*delta(high,2)) : 0
    突破20日高点后的高位回落信号
    """
    if len(highs) < 21:
        return 0.0
    if sum(highs[-20:]) / 20.0 < highs[-1]:
        return -1.0 * _wq_delta(highs, 2)
    return 0.0


def wq_alpha_024(closes, highs, lows, opens, volumes):
    """Alpha#024: 100日均线走平则取100日反转，否则3日反转
    (delta(sma(close,100),100)/delay(close,100)) <= 0.05 ? -(close-delay(close,100)) : -delta(close,3)
    """
    if len(closes) < 101:
        return 0.0
    sma100 = sum(closes[-100:]) / 100.0
    sma100_prev = sum(closes[-200:-100]) / 100.0 if len(closes) >= 200 else sma100
    rate = (sma100 - sma100_prev) / sma100_prev if sma100_prev > 0 else 0.0
    if rate <= 0.05:
        return -1.0 * (closes[-1] - _wq_delay(closes, 100))
    return -1.0 * _wq_delta(closes, 3)


def wq_alpha_026(closes, highs, lows, opens, volumes):
    """Alpha#026: -1 * ts_max(correlation(ts_rank(volume,5), ts_rank(high,5), 5), 3)
    量价排名相关性近3日峰值的反向信号
    """
    if len(highs) < 8 or len(volumes) < 8:
        return 0.0
    trv = _wq_ts_rank_series(volumes, 5)
    trh = _wq_ts_rank_series(highs, 5)
    corrs = _wq_corr_series(trv, trh, 5)
    if len(corrs) < 3:
        return 0.0
    return -1.0 * max(corrs[-3:])


def wq_alpha_035(closes, highs, lows, opens, volumes):
    """Alpha#035: Ts_Rank(volume,32) * (1-Ts_Rank(((high+low)/2)-close,16)) * (1-Ts_Rank(returns,32))
    高量+价格接近区间中轴+低动量三者共振
    """
    if len(closes) < 33 or len(volumes) < 33:
        return 0.0
    returns = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        returns.append((closes[i] - prev) / prev if prev > 0 else 0.0)
    mid = [(h + l) / 2.0 - c for h, l, c in zip(highs[-33:], lows[-33:], closes[-33:])]
    rv = _wq_ts_rank_series(volumes, 32)[-1]
    rm = _wq_ts_rank_series(mid, 16)[-1]
    rr = _wq_ts_rank_series(returns[-32:], 32)[-1] if len(returns) >= 32 else 0.5
    return rv * (1.0 - rm) * (1.0 - rr)


def wq_alpha_041(closes, highs, lows, opens, volumes):
    """Alpha#041: ((high*low)^0.5) - vwap
    高低几何中值与典型价的偏离（vwap 用典型价代理）
    """
    if not highs or not lows:
        return 0.0
    vwap = _wq_vwap(highs, lows, closes)
    return math.sqrt(highs[-1] * lows[-1]) - vwap[-1]


def wq_alpha_046(closes, highs, lows, opens, volumes):
    """Alpha#046: 20日与10日均线斜率差的条件信号
    ((delay(close,20)-delay(close,10))/10 - (delay(close,10)-close)/10) 判定涨跌节奏
    """
    if len(closes) < 21:
        return 0.0
    r1 = (_wq_delay(closes, 20) - _wq_delay(closes, 10)) / 10.0
    r2 = (_wq_delay(closes, 10) - closes[-1]) / 10.0
    slope = r1 - r2
    if slope > 0.25:
        return -1.0
    if slope < 0.0:
        return 1.0
    return -1.0 * _wq_delta(closes, 1)


def wq_alpha_053(closes, highs, lows, opens, volumes):
    """Alpha#053: -1 * delta(((close-low)-(high-close))/(close-low), 9)
    收盘位置在日内区间中占比的9日变化（上下影线动能切换）
    """
    if len(closes) < 10:
        return 0.0
    ratios = []
    for i in range(len(closes)):
        rng = closes[i] - lows[i]
        ratios.append(((closes[i] - lows[i]) - (highs[i] - closes[i])) / rng if rng > 0 else 0.0)
    return -1.0 * _wq_delta(ratios, 9)


def wq_alpha_054(closes, highs, lows, opens, volumes):
    """Alpha#054: (-1*((low-close)*(open^5))) / ((low-high)*(close^5))
    收盘相对低点位置与开盘加权的高阶量价信号
    """
    if not closes or not opens:
        return 0.0
    c = closes[-1]
    o = opens[-1]
    l = lows[-1]
    h = highs[-1]
    denom = (l - h) * (c ** 5)
    if denom == 0:
        return 0.0
    return (-1.0 * (l - c) * (o ** 5)) / denom


def wq_alpha_058(closes, highs, lows, opens, volumes):
    """Alpha#058: -1 * Ts_Rank(decay_linear(correlation(Ts_Rank(volume,5), Ts_Rank(high,5), 5), 3), 3)
    量价排名相关性的衰减加权趋势
    """
    if len(highs) < 10 or len(volumes) < 10:
        return 0.0
    trv = _wq_ts_rank_series(volumes, 5)
    trh = _wq_ts_rank_series(highs, 5)
    corrs = _wq_corr_series(trv, trh, 5)
    dec = _wq_decay_linear_series(corrs, 3)
    ranks = _wq_ts_rank_series(dec, 3)
    return -1.0 * ranks[-1]


def wq_alpha_059(closes, highs, lows, opens, volumes):
    """Alpha#059: -1 * Ts_Rank(decay_linear(correlation(Ts_Rank(volume,5), Ts_Rank(close,5), 5), 3), 3)
    同 058，但用收盘价排名
    """
    if len(closes) < 10 or len(volumes) < 10:
        return 0.0
    trv = _wq_ts_rank_series(volumes, 5)
    trc = _wq_ts_rank_series(closes, 5)
    corrs = _wq_corr_series(trv, trc, 5)
    dec = _wq_decay_linear_series(corrs, 3)
    ranks = _wq_ts_rank_series(dec, 3)
    return -1.0 * ranks[-1]


def wq_alpha_084(closes, highs, lows, opens, volumes):
    """Alpha#084: SignedPower(Ts_Rank((vwap - max(vwap,15)), 21), delta(close,5))
    价格相对15日高点位置的21日排名，以5日涨跌为幂（vwap 用典型价代理）
    """
    if len(closes) < 22 or len(highs) < 22:
        return 0.0
    vwap = _wq_vwap(highs, lows, closes)
    if len(vwap) < 22:
        return 0.0
    vals = [vwap[i] - max(vwap[max(0, i - 14):i + 1]) for i in range(len(vwap))]
    r = _wq_ts_rank_series(vals, 21)[-1]
    e = _wq_delta(closes, 5)
    return _wq_signedpower(r, e)


def wq_alpha_093(closes, highs, lows, opens, volumes):
    """Alpha#093: -1 * Ts_Rank(close,20) * Ts_Rank(correlation(Ts_Rank(close,5), Ts_Rank(volume,5), 6), 4)
    收盘排名与量价排名相关性的复合反转信号（论文主干，纯时序可算部分）
    """
    if len(closes) < 10 or len(volumes) < 10:
        return 0.0
    trc = _wq_ts_rank_series(closes, 5)
    trv = _wq_ts_rank_series(volumes, 5)
    corrs = _wq_corr_series(trc, trv, 6)
    r1 = _wq_ts_rank_series(closes, 20)[-1]
    r2 = _wq_ts_rank_series(corrs, 4)[-1]
    return -1.0 * r1 * r2


def wq_alpha_101(closes, highs, lows, opens, volumes):
    """Alpha#101: (close - open) / ((high - low) + 0.001)
    日内收盘相对开盘的涨跌占振幅比，标准日内动量因子
    """
    if not closes or not opens:
        return 0.0
    return (closes[-1] - opens[-1]) / ((highs[-1] - lows[-1]) + 0.001)


# ---- adv20 近似的 Alpha（论文用全市场20日均成交额，此处以个股20日均量近似） ----

def wq_alpha_007(closes, highs, lows, opens, volumes):
    """Alpha#007: (adv20 < volume) ? (-ts_rank(abs(delta(close,7)),60)*sign(delta(close,7))) : -1
    放量且短期急跌则做多（量能确认的7日反转）
    """
    if len(closes) < 61 or len(volumes) < 21:
        return 0.0
    adv = _wq_adv20(volumes)
    if adv[-1] < volumes[-1]:
        absd = [abs(closes[i] - closes[i - 7]) for i in range(7, len(closes))]
        r = _wq_ts_rank_series(absd, 60)[-1] if len(absd) >= 60 else 0.5
        return -1.0 * r * _wq_sign(_wq_delta(closes, 7))
    return -1.0


def wq_alpha_021(closes, highs, lows, opens, volumes):
    """Alpha#021: 8日均线±标准差包络 vs 2日均线的三态信号
    (sma(close,8)+std(close,8) < sma(close,2)) ? -1 : (sma(close,2) < sma(close,8)-std ? 1 : (volume/adv20 >= 1 ? 1 : -1))
    """
    if len(closes) < 9 or len(volumes) < 21:
        return 0.0
    sma8 = sum(closes[-8:]) / 8.0
    sma2 = sum(closes[-2:]) / 2.0
    std8 = _ts_std(closes, 8) or 0.0
    adv = _wq_adv20(volumes)[-1]
    if sma8 + std8 < sma2:
        return -1.0
    if sma2 < sma8 - std8:
        return 1.0
    if adv > 0 and volumes[-1] / adv >= 1.0:
        return 1.0
    return -1.0


def wq_alpha_043(closes, highs, lows, opens, volumes):
    """Alpha#043: ts_rank(volume/adv20, 20) * ts_rank(-delta(close,7), 8)
    相对量能排名 × 7日下跌排名（放量回调做多）
    """
    if len(closes) < 9 or len(volumes) < 21:
        return 0.0
    adv = _wq_adv20(volumes)
    ratio = [volumes[i] / adv[i] if adv[i] > 0 else 1.0 for i in range(len(volumes))]
    r1 = _wq_ts_rank_series(ratio, 20)[-1] if len(ratio) >= 20 else 0.5
    negd = [-1.0 * (closes[i] - closes[i - 7]) for i in range(7, len(closes))]
    r2 = _wq_ts_rank_series(negd, 8)[-1] if len(negd) >= 8 else 0.5
    return r1 * r2


_WQ_EXTRA = {
    "wq_alpha_006": {"name": "WQ Alpha#006 开量负相关", "fn": wq_alpha_006, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_007": {"name": "WQ Alpha#007 放量急跌反转", "fn": wq_alpha_007, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_009": {"name": "WQ Alpha#009 涨跌节奏反转", "fn": wq_alpha_009, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_012": {"name": "WQ Alpha#012 量价背离", "fn": wq_alpha_012, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_021": {"name": "WQ Alpha#021 均线包络三态", "fn": wq_alpha_021, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_023": {"name": "WQ Alpha#023 20日高点回落", "fn": wq_alpha_023, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_024": {"name": "WQ Alpha#024 100日均线择时", "fn": wq_alpha_024, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_026": {"name": "WQ Alpha#026 量价排名相关", "fn": wq_alpha_026, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_035": {"name": "WQ Alpha#035 量价中轴共振", "fn": wq_alpha_035, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_041": {"name": "WQ Alpha#041 几何中值偏离", "fn": wq_alpha_041, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_043": {"name": "WQ Alpha#043 量能回调排名", "fn": wq_alpha_043, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_046": {"name": "WQ Alpha#046 均线斜率择时", "fn": wq_alpha_046, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_053": {"name": "WQ Alpha#053 收盘位置动量", "fn": wq_alpha_053, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_054": {"name": "WQ Alpha#054 高低收加权", "fn": wq_alpha_054, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_058": {"name": "WQ Alpha#058 量高相关衰减", "fn": wq_alpha_058, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_059": {"name": "WQ Alpha#059 量收相关衰减", "fn": wq_alpha_059, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_084": {"name": "WQ Alpha#084 高位排名幂", "fn": wq_alpha_084, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_093": {"name": "WQ Alpha#093 量价相关复合", "fn": wq_alpha_093, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "wq_alpha_101": {"name": "WQ Alpha#101 日内动量", "fn": wq_alpha_101, "category": "WorldQuant Alpha", "params": ["closes", "highs", "lows", "opens", "volumes"]},
}
FACTOR_REGISTRY.update(_WQ_EXTRA)


# ========== 19. Qlib Alpha360 归一化量价特征（Microsoft Qlib, ~17k stars） ==========
# 来源: https://github.com/microsoft/qlib （qlib/contrib/data/loader.py, Alpha360DL）
# Alpha360 = 过去 60 个交易日 × 6 个量价字段（OPEN/HIGH/LOW/CLOSE/VWAP/VOLUME）= 360 维。
# 官方设计：价格类字段以当日收盘价归一化，成交量以当日成交量归一化，
# 为深度学习模型提供无量纲的原始时空特征序列（此处供规则评分体系直接引用）。
# 注：官方 vwap 为美元成交额/成交量，本系统无成交额数据，沿用项目惯例用典型价代理。


def _a360_feature(field: str, lag: int):
    """构造单个 Alpha360 特征：field 在 lag 个交易日前 的值 / 当日基准"""
    def _f(closes, highs, lows, opens=None, volumes=None):
        if field == "OPEN":
            src = opens or []
        elif field == "HIGH":
            src = highs or []
        elif field == "LOW":
            src = lows or []
        elif field == "VOLUME":
            src = volumes or []
        elif field == "VWAP":
            src = [(h + l + c) / 3.0 for h, l, c in zip(highs or [], lows or [], closes or [])]
        else:  # CLOSE
            src = closes or []
        if not src or not closes:
            return 0.0
        if lag >= len(src):
            return 0.0
        base = closes[-1] if closes[-1] else 0.0
        if field == "VOLUME":
            base = volumes[-1] if volumes and volumes[-1] else 0.0
        if base == 0:
            return 0.0
        return src[-1 - lag] / base
    return _f


_A360_EXTRA = {}
for _fld in ("OPEN", "HIGH", "LOW", "CLOSE", "VWAP", "VOLUME"):
    for _lag in range(60):
        _key = f"A360_{_fld}{_lag}"
        _A360_EXTRA[_key] = {
            "name": f"Qlib Alpha360 {_fld} 滞后{_lag}日",
            "fn": _a360_feature(_fld, _lag),
            "category": "Qlib Alpha360",
            "params": ["closes", "highs", "lows", "opens", "volumes"],
        }
FACTOR_REGISTRY.update(_A360_EXTRA)


# ========== 20. TA-Lib 经典技术指标（TA-Lib, ~5k stars） ==========
# 来源: https://github.com/TA-Lib/ta-lib-python （经典技术分析库 150+ 指标）
# 选择与现有因子库不重叠的常用指标，纯 Python 实现（不依赖 C 扩展）。


def _talib_sma(x: list[float], n: int):
    if len(x) < n or n <= 0:
        return None
    return sum(x[-n:]) / n


def _talib_true_range(highs: list[float], lows: list[float], closes: list[float], i: int) -> float:
    """TR: max(high-low, |high-prev_close|, |low-prev_close|)"""
    h, l = highs[i], lows[i]
    pc = closes[i - 1] if i > 0 else closes[i]
    return max(h - l, abs(h - pc), abs(l - pc))


def talib_atr14(closes, highs, lows, opens, volumes):
    """ATR14: 14日平均真实波幅（波动率基准指标）"""
    if len(closes) < 15:
        return 0.0
    trs = [_talib_true_range(highs, lows, closes, i) for i in range(-14, 0)]
    return sum(trs) / 14.0


def talib_natr14(closes, highs, lows, opens, volumes):
    """NATR14: 归一化 ATR = ATR/close（波动率无量纲化）"""
    if len(closes) < 15 or not closes[-1]:
        return 0.0
    trs = [_talib_true_range(highs, lows, closes, i) for i in range(-14, 0)]
    return (sum(trs) / 14.0) / closes[-1]


def talib_mfi14(closes, highs, lows, opens, volumes):
    """MFI14: 资金流量指标（0-100，>80 超买 <20 超卖）"""
    if len(closes) < 15 or not volumes:
        return 50.0
    pos = neg = 0.0
    for i in range(-14, 0):
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        tp_prev = (highs[i - 1] + lows[i - 1] + closes[i - 1]) / 3.0
        mf = tp * volumes[i]
        if tp > tp_prev:
            pos += mf
        elif tp < tp_prev:
            neg += mf
    if neg == 0:
        return 100.0 if pos > 0 else 50.0
    ratio = pos / neg
    return 100.0 - (100.0 / (1.0 + ratio))


def talib_obv_slope5(closes, highs, lows, opens, volumes):
    """OBV 5日斜率: 能量潮累计量的近期线性斜率（资金流入/流出趋势）"""
    if len(closes) < 7 or not volumes:
        return 0.0
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    seg = obv[-5:]
    mx = 2.0
    my = sum(seg) / 5.0
    num = sum((i - mx) * (v - my) for i, v in enumerate(seg))
    den = sum((i - mx) ** 2 for i in range(5))
    return (num / den) if den else 0.0


def _talib_ema_series(x: list[float], n: int) -> list[float]:
    """EMA 序列"""
    if not x:
        return []
    k = 2.0 / (n + 1)
    out = [x[0]]
    for v in x[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def talib_trix30(closes, highs, lows, opens, volumes):
    """TRIX30: 三重指数平滑的1日变化率（长期趋势动能）"""
    if len(closes) < 40:
        return 0.0
    e1 = _talib_ema_series(closes, 30)
    e2 = _talib_ema_series(e1, 30)
    e3 = _talib_ema_series(e2, 30)
    if len(e3) < 2 or e3[-2] == 0:
        return 0.0
    return (e3[-1] - e3[-2]) / e3[-2]


def talib_dpo20(closes, highs, lows, opens, volumes):
    """DPO20: 去势价格振荡器 = close - sma(close,20) 移位11日（中周期循环）"""
    if len(closes) < 32:
        return 0.0
    sma20 = _talib_sma(closes[:-11], 20)
    if sma20 is None:
        return 0.0
    return closes[-1] - sma20


def talib_bop(closes, highs, lows, opens, volumes):
    """BOP: 平衡量力 = (close-open)/(high-low)（日内买卖压力）"""
    if not closes or not opens:
        return 0.0
    rng = highs[-1] - lows[-1]
    return (closes[-1] - opens[-1]) / rng if rng != 0 else 0.0


def talib_ultosc(closes, highs, lows, opens, volumes):
    """ULTOSC: 终极振荡器（7/14/28 三周期加权买压）"""
    if len(closes) < 29:
        return 50.0
    def _bp(i): return closes[i] - min(lows[i], closes[i - 1])
    def _tr(i): return max(highs[i], closes[i - 1]) - min(lows[i], closes[i - 1])
    def _avg(n):
        b = sum(_bp(i) for i in range(-n, 0))
        t = sum(_tr(i) for i in range(-n, 0))
        return (b / t) if t else 0.5
    a7, a14, a28 = _avg(7), _avg(14), _avg(28)
    return 100.0 * (4 * a7 + 2 * a14 + a28) / 7.0


def talib_ppo12_26(closes, highs, lows, opens, volumes):
    """PPO: 百分比价格振荡器 = (EMA12-EMA26)/EMA26*100（趋势强度）"""
    if len(closes) < 27:
        return 0.0
    e12 = _talib_ema_series(closes, 12)[-1]
    e26 = _talib_ema_series(closes, 26)[-1]
    return ((e12 - e26) / e26 * 100.0) if e26 else 0.0


def talib_stochrsi14(closes, highs, lows, opens, volumes):
    """STOCHRSI14: RSI 的随机振荡（0-1，>0.8 超买 <0.2 超卖）"""
    if len(closes) < 30:
        return 0.5
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    rsi_vals = []
    for i in range(14, len(gains)):
        ag = sum(gains[i - 14:i]) / 14.0
        al = sum(losses[i - 14:i]) / 14.0
        rs = (ag / al) if al > 0 else float('inf')
        rsi_vals.append(100.0 - 100.0 / (1.0 + rs))
    if len(rsi_vals) < 15:
        return 0.5
    seg = rsi_vals[-14:]
    hi, lo = max(seg), min(seg)
    return (seg[-1] - lo) / (hi - lo) if hi > lo else 0.5


def talib_mass27(closes, highs, lows, opens, volumes):
    """MASS27: 质量指数（27日波幅扩张/收缩的 U 型反转信号）"""
    if len(closes) < 27:
        return 25.0
    sums = []
    for i in range(len(closes) - 26, len(closes)):
        trs = [_talib_true_range(highs, lows, closes, j) for j in range(i - 8, i + 1)]
        e = _talib_ema_series(trs, 9)
        e2 = _talib_ema_series(e, 9)
        if e2 and e2[-1]:
            sums.append(e[-1] / e2[-1])
    return sum(sums) if sums else 25.0


def talib_apo12_26(closes, highs, lows, opens, volumes):
    """APO: 绝对价格振荡器 = EMA12 - EMA26（动量强弱）"""
    if len(closes) < 27:
        return 0.0
    e12 = _talib_ema_series(closes, 12)[-1]
    e26 = _talib_ema_series(closes, 26)[-1]
    return e12 - e26


def talib_linearreg20(closes, highs, lows, opens, volumes):
    """LINEARREG20: 20日线性回归拟合值（与现价的偏离即回归残差信号）"""
    if len(closes) < 20:
        return closes[-1] if closes else 0.0
    seg = closes[-20:]
    mx = 9.5
    my = sum(seg) / 20.0
    num = sum((i - mx) * (v - my) for i, v in enumerate(seg))
    den = sum((i - mx) ** 2 for i in range(20))
    slope = num / den if den else 0.0
    return my + slope * (19 - mx)


def talib_tsf20(closes, highs, lows, opens, volumes):
    """TSF20: 时间序列预测 = 20日线性回归外推 1 日（趋势外推值）"""
    if len(closes) < 21:
        return closes[-1] if closes else 0.0
    seg = closes[-20:]
    mx = 9.5
    my = sum(seg) / 20.0
    num = sum((i - mx) * (v - my) for i, v in enumerate(seg))
    den = sum((i - mx) ** 2 for i in range(20))
    slope = num / den if den else 0.0
    return my + slope * 10.5


_TALIB_EXTRA = {
    "talib_atr14": {"name": "TA-Lib ATR14 平均真实波幅", "fn": talib_atr14, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_natr14": {"name": "TA-Lib NATR14 归一化波幅", "fn": talib_natr14, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_mfi14": {"name": "TA-Lib MFI14 资金流量", "fn": talib_mfi14, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_obv_slope5": {"name": "TA-Lib OBV 5日斜率", "fn": talib_obv_slope5, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_trix30": {"name": "TA-Lib TRIX30 三重平滑", "fn": talib_trix30, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_dpo20": {"name": "TA-Lib DPO20 去势价格", "fn": talib_dpo20, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_bop": {"name": "TA-Lib BOP 平衡量力", "fn": talib_bop, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_ultosc": {"name": "TA-Lib ULTOSC 终极振荡", "fn": talib_ultosc, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_ppo12_26": {"name": "TA-Lib PPO 百分比振荡", "fn": talib_ppo12_26, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_stochrsi14": {"name": "TA-Lib STOCHRSI 随机RSI", "fn": talib_stochrsi14, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_mass27": {"name": "TA-Lib MASS27 质量指数", "fn": talib_mass27, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_apo12_26": {"name": "TA-Lib APO 绝对振荡", "fn": talib_apo12_26, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_linearreg20": {"name": "TA-Lib LINEARREG20 回归值", "fn": talib_linearreg20, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
    "talib_tsf20": {"name": "TA-Lib TSF20 趋势外推", "fn": talib_tsf20, "category": "TA-Lib 技术指标", "params": ["closes", "highs", "lows", "opens", "volumes"]},
}
FACTOR_REGISTRY.update(_TALIB_EXTRA)


FACTOR_REGISTRY.update(_QLIB_EXTRA)


def compute_all_factors(closes, highs, lows, opens=None, volumes=None, market_closes=None):
    """计算所有因子值"""
    result = {}
    opens = opens or []
    volumes = volumes or []
    for key, meta in FACTOR_REGISTRY.items():
        try:
            fn = meta["fn"]
            params = meta["params"]
            args = []
            for p in params:
                if p == "closes":
                    args.append(closes)
                elif p == "highs":
                    args.append(highs)
                elif p == "lows":
                    args.append(lows)
                elif p == "opens":
                    args.append(opens or [])
                elif p == "volumes":
                    args.append(volumes or [])
                elif p == "highs":
                    args.append(highs or [])
                elif p == "lows":
                    args.append(lows or [])
                elif p == "market_closes":
                    args.append(market_closes or closes)
                else:
                    args.append(None)
            result[key] = fn(*args)
        except Exception:
            result[key] = 0.0
    return result

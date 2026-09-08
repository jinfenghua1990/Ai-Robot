"""技术指标计算服务
MA / RSI / MACD / KDJ / ATR / SuperTrend 等
统一一个地方，所有模块共用。
"""
from typing import List, Optional


def calc_ma(closes: List[float], period: int) -> List[Optional[float]]:
    """计算简单移动平均线"""
    ma = []
    for i in range(len(closes)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(closes[i - period + 1:i + 1]) / period)
    return ma


def calc_ema(values: List[float], period: int) -> List[Optional[float]]:
    """计算指数移动平均（SMA 种子 + EMA 公式）"""
    if not values:
        return []
    ema = []
    multiplier = 2 / (period + 1)
    if len(values) >= period:
        for i in range(period - 1):
            ema.append(None)
        sma_seed = sum(values[:period]) / period
        ema.append(sma_seed)
        for i in range(period, len(values)):
            ema.append(values[i] * multiplier + ema[-1] * (1 - multiplier))
    else:
        ema.append(values[0])
        for i in range(1, len(values)):
            ema.append(values[i] * multiplier + ema[-1] * (1 - multiplier))
    return ema


def calc_macd(closes: List[float], fast=12, slow=26, signal_period=9):
    """计算 MACD
    Returns: (dif, dea, macd)
    """
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    dif = []
    for ef, es in zip(ema_fast, ema_slow):
        if ef is None or es is None:
            dif.append(None)
        else:
            dif.append(ef - es)
    dif_valid_start = next((i for i, v in enumerate(dif) if v is not None), 0)
    dif_valid = dif[dif_valid_start:]
    dea_valid = calc_ema(dif_valid, signal_period)
    dea = [None] * dif_valid_start + dea_valid
    macd = []
    for d, e in zip(dif, dea):
        if d is None or e is None:
            macd.append(None)
        else:
            macd.append((d - e) * 2)
    return dif, dea, macd


def calc_rsi(closes: List[float], period: int = 14) -> List[Optional[float]]:
    """计算 RSI（相对强弱指标）"""
    if len(closes) < period + 1:
        return [None] * len(closes)
    rsi = [None] * period
    gains, losses = [], []
    for i in range(1, period + 1):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0))
        losses.append(max(-chg, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        rsi.append(100.0)
    else:
        rsi.append(100 - 100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, len(closes)):
        chg = closes[i] - closes[i - 1]
        gain = max(chg, 0)
        loss = max(-chg, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rsi.append(100 - 100 / (1 + avg_gain / avg_loss))
    return rsi


def calc_kdj(highs: List[float], lows: List[float], closes: List[float],
             n: int = 9, m1: int = 3, m2: int = 3):
    """计算 KDJ
    Returns: (k, d, j)
    """
    k_values, d_values, j_values = [], [], []
    k_prev = d_prev = 50.0
    for i in range(len(closes)):
        if i < n - 1:
            k_values.append(None)
            d_values.append(None)
            j_values.append(None)
            continue
        start = i - n + 1
        highest = max(highs[start:i + 1])
        lowest = min(lows[start:i + 1])
        if highest == lowest:
            rsv = 50.0
        else:
            rsv = (closes[i] - lowest) / (highest - lowest) * 100
        k = (m1 - 1) / m1 * k_prev + 1 / m1 * rsv
        d = (m2 - 1) / m2 * d_prev + 1 / m2 * k
        j = 3 * k - 2 * d
        k_values.append(k)
        d_values.append(d)
        j_values.append(j)
        k_prev, d_prev = k, d
    return k_values, d_values, j_values


def calc_atr(highs: List[float], lows: List[float], closes: List[float],
             period: int = 10) -> List[Optional[float]]:
    """计算 ATR（真实波幅）"""
    if not highs:
        return []
    tr = []
    for i in range(len(highs)):
        if i == 0:
            tr.append(highs[i] - lows[i])
        else:
            tr.append(max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            ))
    atr = []
    for i in range(len(tr)):
        if i < period - 1:
            atr.append(None)
        else:
            atr.append(sum(tr[i - period + 1:i + 1]) / period)
    return atr


def calc_supertrend(highs, lows, closes, period=10, multiplier=3.0):
    """计算 SuperTrend
    Returns: (support, resistance, trend, atr)
    """
    atr = calc_atr(highs, lows, closes, period)
    support, resistance, trend = [], [], []
    for i in range(len(closes)):
        hl2 = (highs[i] + lows[i]) / 2
        if atr[i] is None:
            support.append(None)
            resistance.append(None)
            trend.append(1)
            continue
        base_support = hl2 - multiplier * atr[i]
        base_resistance = hl2 + multiplier * atr[i]
        if i == 0 or support[i - 1] is None:
            support.append(base_support)
            resistance.append(base_resistance)
            trend.append(1)
            continue
        prev_close = closes[i - 1]
        # 支撑线(下轨)：多头时只上移
        if prev_close > support[i - 1]:
            support.append(max(base_support, support[i - 1]))
        else:
            support.append(base_support)
        # 阻力线(上轨)：空头时只下移
        if prev_close < resistance[i - 1]:
            resistance.append(min(base_resistance, resistance[i - 1]))
        else:
            resistance.append(base_resistance)
        # 趋势变轨
        prev_trend = trend[i - 1]
        if prev_trend == 1:
            if closes[i] < support[i - 1]:
                trend.append(-1)
            else:
                trend.append(1)
        else:
            if closes[i] > resistance[i - 1]:
                trend.append(1)
            else:
                trend.append(-1)
    return support, resistance, trend, atr

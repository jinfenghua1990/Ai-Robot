"""US Quant System — 技术指标计算

基于日线/分钟线计算常用技术指标。
yfinance 返回的 OHLC 数据格式: {symbol: [{Date, Open, High, Low, Close, Volume}, ...]}
"""

from __future__ import annotations

from typing import Optional


def ema(values: list[float], period: int) -> list[float]:
    """指数移动平均"""
    if len(values) < period:
        return []
    multiplier = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append((v - result[-1]) * multiplier + result[-1])
    return result


def sma(values: list[float], period: int) -> list[float]:
    """简单移动平均"""
    if len(values) < period:
        return []
    result = []
    for i in range(len(values) - period + 1):
        result.append(sum(values[i:i + period]) / period)
    return result


def rsi(values: list[float], period: int = 14) -> Optional[float]:
    """相对强弱指标 — 返回最新值"""
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD 指标 — 返回最新值"""
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    if not ema_fast or not ema_slow:
        return {"dif": None, "dea": None, "hist": None, "status": "N/A"}
    dif = ema_fast[-1] - ema_slow[-1]
    # 计算 DEA (signal line)
    dif_line = [ema_fast[i] - ema_slow[i] for i in range(min(len(ema_fast), len(ema_slow)))]
    if len(dif_line) < signal:
        return {"dif": dif, "dea": None, "hist": None, "status": "N/A"}
    dea_vals = ema(dif_line, signal)
    if not dea_vals:
        return {"dif": dif, "dea": None, "hist": None, "status": "N/A"}
    dea = dea_vals[-1]
    hist = dif - dea
    status = "多头" if dif > dea and hist > 0 else "空头" if dif < dea and hist < 0 else "中性"
    return {"dif": round(dif, 4), "dea": round(dea, 4), "hist": round(hist, 4), "status": status}


def kdj(values: list[float], period: int = 9, k_smooth: int = 3, d_smooth: int = 3) -> dict:
    """KDJ 指标 — 返回最新值"""
    if len(values) < period:
        return {"k": None, "d": None, "j": None, "status": "N/A"}
    recent = values[-period:]
    hh = max(recent)
    ll = min(recent)
    if hh == ll:
        return {"k": 50.0, "d": 50.0, "j": 50.0, "status": "中性"}
    rsv = (recent[-1] - ll) / (hh - ll) * 100
    k_values = [rsv]
    for _ in range(1, k_smooth):
        k_values.append((2 / 3) * k_values[-1] + (1 / 3) * rsv)
    k = k_values[-1]
    d = (2 / 3) * (k if len(k_values) == 1 else k) + (1 / 3) * k
    j = 3 * k - 2 * d
    if k > 80 and d > 80:
        status = "超买"
    elif k < 20 and d < 20:
        status = "超卖"
    elif k > d:
        status = "多头"
    elif k < d:
        status = "空头"
    else:
        status = "中性"
    return {"k": round(k, 2), "d": round(d, 2), "j": round(j, 2), "status": status}


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    """平均真实波幅 — 返回最新值"""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        trs.append(max(hl, hc, lc))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def ma_bias(price: float, ma_value: float) -> float:
    """乖离率"""
    if ma_value == 0:
        return 0.0
    return (price - ma_value) / ma_value * 100


def vwap(highs: list[float], lows: list[float], closes: list[float], volumes: list[float]) -> Optional[float]:
    """成交量加权平均价格"""
    if not volumes:
        return None
    tp_sum = sum((h + l + c) / 3 * v for h, l, c, v in zip(highs, lows, closes, volumes))
    vol_sum = sum(volumes)
    if vol_sum == 0:
        return None
    return tp_sum / vol_sum
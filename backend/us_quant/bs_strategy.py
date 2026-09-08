"""美股强 B/S 策略的唯一规则源。"""
from __future__ import annotations

from typing import Optional


STRATEGY_META = {
    "key": "strategy_us_bs_strong",
    "name": "美股强 B/S 策略",
    "version": "strong-v1",
    "route": "/us-bs-strategy",
    "description": "盘后强B确认，下一交易日开盘进入，达到8%止盈或持有30个交易日退出。",
    "validation": {
        "start": "2025-08-07",
        "end": "2026-08-07",
        "samples": 121,
        "win_rate": 0.7025,
        "avg_return": 0.0266,
        "transaction_cost": 0.003,
        "time_holdout_win_rate": 0.7667,
        "symbol_holdout_win_rate": 0.8261,
    },
    "entry_rules": [
        "MA5/MA20 当日金叉且收盘价站上 MA20",
        "KDJ 当日金叉",
        "MACD 柱体 > 0 且 DIF > 0",
        "收盘价站上 MA60，RSI14 位于 45–70",
        "股价 ≥ 5 美元且20日平均成交额 ≥ 2,000万美元",
    ],
    "exit_rules": ["相对下一交易日开盘价收益达到 8%", "持有满 30 个交易日"],
}


def _sma(values: list[float], period: int) -> list[Optional[float]]:
    result: list[Optional[float]] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= period:
            total -= values[index - period]
        result.append(total / period if index >= period - 1 else None)
    return result


def _ema(values: list[float], period: int) -> list[Optional[float]]:
    result: list[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result
    current = sum(values[:period]) / period
    result[period - 1] = current
    alpha = 2 / (period + 1)
    for index in range(period, len(values)):
        current = values[index] * alpha + current * (1 - alpha)
        result[index] = current
    return result


def _macd(closes: list[float]) -> dict[str, list[Optional[float]]]:
    fast, slow = _ema(closes, 12), _ema(closes, 26)
    dif = [f - s if f is not None and s is not None else None for f, s in zip(fast, slow)]
    dea: list[Optional[float]] = [None] * len(closes)
    valid = [value for value in dif if value is not None]
    if len(valid) >= 9:
        current = sum(valid[:9]) / 9
        first = next(index for index, value in enumerate(dif) if value is not None) + 8
        dea[first] = current
        for index in range(first + 1, len(closes)):
            if dif[index] is not None:
                current = dif[index] * 0.2 + current * 0.8
                dea[index] = current
    hist = [d - e if d is not None and e is not None else None for d, e in zip(dif, dea)]
    return {"dif": dif, "dea": dea, "hist": hist}


def _kdj(highs: list[float], lows: list[float], closes: list[float], period: int = 9):
    k: list[Optional[float]] = [None] * len(closes)
    d: list[Optional[float]] = [None] * len(closes)
    kv = dv = 50.0
    for index in range(period - 1, len(closes)):
        high = max(highs[index - period + 1:index + 1])
        low = min(lows[index - period + 1:index + 1])
        rsv = 50.0 if high == low else (closes[index] - low) / (high - low) * 100
        kv = (2 * kv + rsv) / 3
        dv = (2 * dv + kv) / 3
        k[index], d[index] = kv, dv
    return {"k": k, "d": d}


def _rsi(closes: list[float], period: int = 14) -> list[Optional[float]]:
    result: list[Optional[float]] = [None] * len(closes)
    if len(closes) <= period:
        return result
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, period + 1)]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, period + 1)]
    avg_gain, avg_loss = sum(gains) / period, sum(losses) / period
    result[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for index in range(period + 1, len(closes)):
        change = closes[index] - closes[index - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
        result[index] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return result


def generate_signals_from_indicators(
    opens, closes, volumes, ma5, ma20, ma60, macd, kdj, rsi,
) -> list[dict]:
    """从对齐指标序列生成成对 B/S 事件。"""
    signals: list[dict] = []
    volume20 = _sma(volumes, 20)
    entry_index: Optional[int] = None
    entry_price: Optional[float] = None
    for index in range(1, len(closes)):
        if entry_index is not None and entry_price is not None and index >= entry_index:
            held = index - entry_index + 1
            hit_target = closes[index] >= entry_price * 1.08
            if hit_target or held >= 30:
                signals.append({
                    "i": index,
                    "side": "S",
                    "reason": "达到 +8% 止盈" if hit_target else "持有满 30 个交易日退出",
                    "exit_type": "take_profit" if hit_target else "time_exit",
                })
                entry_index = None
                entry_price = None
                continue
        if entry_index is not None:
            continue
        values = (
            ma5[index - 1], ma20[index - 1], ma5[index], ma20[index], ma60[index],
            kdj["k"][index - 1], kdj["d"][index - 1], kdj["k"][index], kdj["d"][index],
            macd["hist"][index], macd["dif"][index], rsi[index], volume20[index],
        )
        if any(value is None for value in values):
            continue
        p5, p20, m5, m20, m60, pk, pd, k, d, hist, dif, rsi14, avg_volume = values
        strong_buy = (
            closes[index] > m20
            and p5 <= p20 and m5 > m20
            and pk <= pd and k > d
            and hist > 0 and dif > 0
            and closes[index] > m60 and 45 <= rsi14 <= 70
            and closes[index] >= 5 and closes[index] * avg_volume >= 20_000_000
        )
        if strong_buy:
            signals.append({
                "i": index,
                "side": "B",
                "strength": "strong",
                "reason": "强B：均线/KDJ金叉 + MACD双确认 + MA60趋势 + RSI/流动性过滤",
            })
            if index + 1 < len(opens) and opens[index + 1] > 0:
                entry_index = index + 1
                entry_price = opens[index + 1]
    return signals[-30:]


def calculate_indicators(highs, lows, closes):
    return {
        "ma5": _sma(closes, 5),
        "ma20": _sma(closes, 20),
        "ma60": _sma(closes, 60),
        "macd": _macd(closes),
        "kdj": _kdj(highs, lows, closes),
        "rsi": _rsi(closes),
    }


def generate_strong_bs_signals(opens, highs, lows, closes, volumes):
    indicators = calculate_indicators(highs, lows, closes)
    return generate_signals_from_indicators(
        opens, closes, volumes, indicators["ma5"], indicators["ma20"], indicators["ma60"],
        indicators["macd"], indicators["kdj"], indicators["rsi"],
    )


def evaluate_strong_bs(opens, highs, lows, closes, volumes, dates=None):
    indicators = calculate_indicators(highs, lows, closes)
    signals = generate_signals_from_indicators(
        opens, closes, volumes, indicators["ma5"], indicators["ma20"], indicators["ma60"],
        indicators["macd"], indicators["kdj"], indicators["rsi"],
    )
    last_index = len(closes) - 1
    volume20 = _sma(volumes, 20)
    latest_signal = signals[-1] if signals else None
    active = bool(latest_signal and latest_signal["side"] == "B")
    event_today = bool(latest_signal and latest_signal["i"] == last_index)
    factor_value = -1.0 if event_today and latest_signal["side"] == "S" else 1.0 if active else 0.0
    entry = None
    if active:
        entry_i = latest_signal["i"] + 1
        if entry_i < len(opens):
            entry_price = opens[entry_i]
            entry = {
                "signal_date": dates[latest_signal["i"]] if dates else latest_signal["i"],
                "entry_date": dates[entry_i] if dates else entry_i,
                "entry_price": round(entry_price, 4),
                "target_price": round(entry_price * 1.08, 4),
                "held_sessions": len(closes) - entry_i,
                "return_pct": round((closes[-1] / entry_price - 1) * 100, 2),
            }
    index = last_index
    values = {
        "close": closes[index],
        "ma20": indicators["ma20"][index],
        "ma60": indicators["ma60"][index],
        "rsi14": indicators["rsi"][index],
        "macd_hist": indicators["macd"]["hist"][index],
        "macd_dif": indicators["macd"]["dif"][index],
        "avg_dollar_volume_20d": closes[index] * volume20[index] if volume20[index] is not None else None,
    }
    checks = {
        "ma_cross": bool(index > 0 and indicators["ma5"][index - 1] is not None and indicators["ma20"][index - 1] is not None and indicators["ma5"][index - 1] <= indicators["ma20"][index - 1] and indicators["ma5"][index] > indicators["ma20"][index]),
        "kdj_cross": bool(index > 0 and indicators["kdj"]["k"][index - 1] is not None and indicators["kdj"]["d"][index - 1] is not None and indicators["kdj"]["k"][index - 1] <= indicators["kdj"]["d"][index - 1] and indicators["kdj"]["k"][index] > indicators["kdj"]["d"][index]),
        "macd_double_positive": bool(values["macd_hist"] is not None and values["macd_dif"] is not None and values["macd_hist"] > 0 and values["macd_dif"] > 0),
        "above_ma60": bool(values["ma60"] is not None and values["close"] > values["ma60"]),
        "rsi_range": bool(values["rsi14"] is not None and 45 <= values["rsi14"] <= 70),
        "liquidity": bool(values["close"] >= 5 and values["avg_dollar_volume_20d"] is not None and values["avg_dollar_volume_20d"] >= 20_000_000),
    }
    status = "strong_buy" if event_today and latest_signal["side"] == "B" else "sell" if factor_value < 0 else "holding" if active else "watch"
    return {
        "factor_value": factor_value,
        "status": status,
        "entry": entry,
        "latest_values": values,
        "checks": checks,
        "signals": [dict(signal, date=dates[signal["i"]] if dates else signal["i"]) for signal in signals[-10:]],
    }


def strong_bs_factor(closes, highs, lows, opens, volumes) -> Optional[float]:
    if min(len(closes), len(highs), len(lows), len(opens), len(volumes)) < 60:
        return None
    return evaluate_strong_bs(opens, highs, lows, closes, volumes)["factor_value"]

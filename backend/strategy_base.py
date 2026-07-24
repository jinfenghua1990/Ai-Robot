"""
strategy_base.py — 技术指标工具集（calc_rsi / calc_ma / calc_atr / calc_donchian）

原实现位于 Hermes 运行时目录 /Users/gino/.hermes/database/strategy_base.py，
在 Hermes 子系统彻底移除（迁移到 AIROBOT 主后端）后，该路径已不再存在。
此处为等价重新实现，作为仓库内的一等模块，供 api/hermes_native/screener.py
通过 `from strategy_base import ...` 直接导入，消除对 /Users/gino/.hermes 的依赖。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple


def calc_ma(closes: Sequence[float], n: int) -> Optional[float]:
    """简单移动平均。返回最近 n 根收盘价的均值；数据不足 n 根时取现有数据均值；
    空序列返回 None（供调用方 `or current_close` 之类的兜底逻辑使用）。"""
    if not closes:
        return None
    window = list(closes)[-n:]
    if not window:
        return None
    return sum(window) / len(window)


def _avg(xs: Sequence[float]) -> float:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def calc_rsi(closes: Sequence[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI。数据不足以计算时返回 50.0（中性值）。"""
    if closes is None or len(closes) < 2:
        return 50.0 if closes else None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    if len(deltas) < period:
        # 数据不足一个完整周期：用全部涨跌幅近似
        gains = [d for d in deltas if d > 0]
        losses = [-d for d in deltas if d < 0]
        avg_gain = _avg(gains) if gains else 0.0
        avg_loss = _avg(losses) if losses else 0.0
    else:
        gains = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> Optional[float]:
    """Wilder's ATR（真实波幅均值）。数据不足返回 None。"""
    if not (highs and lows and closes) or len(closes) < 2:
        return None
    trs: List[float] = []
    for i in range(1, len(closes)):
        h = highs[i] if i < len(highs) else closes[i]
        l = lows[i] if i < len(lows) else closes[i]
        prev_close = closes[i - 1]
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
    if not trs:
        return None
    if len(trs) < period:
        return _avg(trs)
    atr = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
    return atr


def calc_donchian(
    highs: Sequence[float],
    lows: Sequence[float],
    period: int = 20,
    breakout: int = 10,
) -> Tuple[Optional[float], Optional[float]]:
    """Donchian 通道。返回 (通道上轨, 通道下轨)。
    period: 回顾窗口；breakout: 预留参数（当前实现上/下轨均基于 period 窗口）。
    数据不足返回 (None, None)。"""
    if not highs or not lows:
        return (None, None)
    hi_win = list(highs)[-period:]
    lo_win = list(lows)[-period:]
    upper = max(hi_win) if hi_win else None
    lower = min(lo_win) if lo_win else None
    return (upper, lower)

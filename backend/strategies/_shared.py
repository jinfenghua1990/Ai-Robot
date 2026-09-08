#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股策略共享指标层。

注意：这里的是 **SMA 语义版** 指标，与 services/indicators.py 的
Wilder 平滑版实现不同（选股结果会因此有差异），请勿混用。
原先 calc_rsi 散落在 baihu_v30 / liangjia_report 两份完全相同副本、
calc_ema / calc_macd 仅存在于 macd_golden_cross，现统一收敛至此，改一处全生效。
"""
import logging
import numpy as np

logger = logging.getLogger(__name__)


def calc_rsi(closes, period=14):
    """计算 RSI（SMA 语义：用固定窗口均值，非 Wilder 平滑）。"""
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_ema(series, period):
    """计算 EMA（指数移动平均），返回与 series 等长列表。"""
    if len(series) < period:
        return []
    ema = [sum(series[:period]) / period]
    multiplier = 2 / (period + 1)
    for price in series[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def calc_macd(closes, short=12, long_=26, signal=9):
    """计算 MACD，返回 (dif, dea, hist) 三元组（长度已对齐到最长序列）。"""
    if len(closes) < long_ + signal:
        return None, None, None
    ema_short = calc_ema(closes, short)
    ema_long = calc_ema(closes, long_)
    # 对齐到 ema_long 的索引
    offset = len(ema_short) - len(ema_long)
    dif = [ema_short[i + offset] - ema_long[i] for i in range(len(ema_long))]
    dea = calc_ema(dif, signal)
    offset2 = len(dif) - len(dea)
    hist = [(dif[i + offset2] - dea[i]) * 2 for i in range(len(dea))]
    return dif, dea, hist

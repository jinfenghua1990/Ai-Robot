# -*- coding: utf-8 -*-
"""横盘蓄势：箱体识别 + 量价健康

箱体参数（首版默认）：
  横盘周期 20—60 交易日 | 箱体振幅 ≤15% | 窗口内 MA20 变化 ≤8%
  MA60 走平或向上 | 收盘位于箱体中上部 | 最近 20 日最低不创新低 | ATR14/close ≤4%

量价健康（不显示"吸筹"，只显示客观数字）：
  阳线均量/阴线均量 ≥1.15 | 近5日均量/20日均量 0.8—1.5 | 价格重心抬高
  回调日量 < 上涨日量 | 无连续放量长阴
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 参数
BOX_WINDOWS = [60, 50, 40, 30, 25, 20]   # 从长到短找最优箱体
MAX_AMPLITUDE = 0.15                     # 箱体振幅上限
MAX_MA20_DRIFT = 0.08                    # 窗口内 MA20 最大变化
MAX_ATR_RATIO = 0.04                     # ATR14/收盘 上限
BOX_END_MAX_GAP = 8                      # 箱体结束距今最多 N 个交易日（允许刚突破）
MIN_BOX_DAYS = 20
HIGHER_LOW_LOOKBACK = 20                 # 不创新低回看窗口


def _atr(close: pd.Series, high: pd.Series, low: pd.Series, n: int = 14) -> float:
    if len(close) < n + 1:
        return float("nan")
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


def find_box(df: pd.DataFrame) -> Optional[Dict]:
    """在单只股票日线上找最优横盘箱体

    df 按 trade_date 升序，至少 90 行。返回箱体信息或 None。
    """
    if len(df) < 90:
        return None
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    vol = df["volume"].to_numpy(dtype=float)
    n = len(df)

    ma20 = pd.Series(close).rolling(20).mean().to_numpy()
    ma60 = pd.Series(close).rolling(60).mean().to_numpy()
    atr14 = _atr(df["close"], df["high"], df["low"])
    if atr14 != atr14:  # NaN
        return None
    atr_ratio = atr14 / close[-1] if close[-1] else 999
    if atr_ratio > MAX_ATR_RATIO:
        return None

    last_low_20 = low[-HIGHER_LOW_LOOKBACK:].min()

    for L in BOX_WINDOWS:
        if n < L + 20:
            continue
        # 遍历所有可能结束位置（最后 BOX_END_MAX_GAP 个位置优先从后往前）
        start_max = n - L
        for end in range(n - 1, n - BOX_END_MAX_GAP - 2, -1):
            start = end - L + 1
            if start < 0:
                continue
            seg_high = high[start:end + 1].max()
            seg_low = low[start:end + 1].min()
            if seg_low <= 0:
                continue
            amp = seg_high / seg_low - 1
            if amp > MAX_AMPLITUDE:
                continue
            # MA20 稳定性
            if not (ma20[start] == ma20[start] and ma20[end] == ma20[end]):
                continue
            drift = abs(ma20[end] / ma20[start] - 1)
            if drift > MAX_MA20_DRIFT:
                continue
            # MA60 走平或向上
            if not (ma60[end] == ma60[end] and ma60[end - 60] == ma60[end - 60]):
                continue
            if ma60[end] < ma60[end - 60] * 0.99:
                continue
            # 最近 20 日最低不创新低（箱体低点 vs 更早 20 日最低）
            if start >= HIGHER_LOW_LOOKBACK:
                earlier_low = low[start - HIGHER_LOW_LOOKBACK:start].min()
                if seg_low < earlier_low * 0.97:
                    continue
            # 成交量健康：20 日均量 > 0
            vol20 = float(pd.Series(vol[start:end + 1]).mean())
            if vol20 <= 0:
                continue
            # 收盘位置（0=贴箱体低，1=贴箱体高）
            pos = (close[-1] - seg_low) / (seg_high - seg_low) if seg_high > seg_low else 0.5
            return {
                "box_high": round(float(seg_high), 2),
                "box_low": round(float(seg_low), 2),
                "box_days": L,
                "box_end_offset": n - 1 - end,          # 0=箱体至今仍在
                "amplitude": round(amp * 100, 2),
                "ma20_drift": round(drift * 100, 2),
                "atr_ratio": round(atr_ratio * 100, 2),
                "close_pos_in_box": round(pos * 100, 0),
                "vol_20": round(vol20, 0),
            }
    return None


def volume_price(df: pd.DataFrame, box: Dict) -> Dict:
    """量价健康指标（基于箱体窗口内数据 + 近 5 日）"""
    end = len(df) - 1 - box["box_end_offset"]
    start = end - box["box_days"] + 1
    seg = df.iloc[start:end + 1]
    if len(seg) < 20:
        return {}

    up = seg[seg["close"] >= seg["open"]]
    dn = seg[seg["close"] < seg["open"]]
    up_vol = float(up["volume"].mean()) if len(up) else 0.0
    dn_vol = float(dn["volume"].mean()) if len(dn) else 0.0
    up_dn_ratio = round(up_vol / dn_vol, 2) if dn_vol > 0 else None

    recent5 = df["volume"].iloc[-5:].mean()
    vol20 = float(seg["volume"].mean())
    vol_ratio_5_20 = round(float(recent5 / vol20), 2) if vol20 > 0 else None

    # 价格重心：箱体前半 vs 后半 收盘均值
    half = len(seg) // 2
    g1 = float(seg["close"].iloc[:half].mean())
    g2 = float(seg["close"].iloc[half:].mean())
    gravity = round((g2 / g1 - 1) * 100, 2) if g1 > 0 else 0.0

    # 回调日量 < 上涨日量（近 10 日）
    last10 = df.iloc[-10:]
    up10 = last10[last10["close"] >= last10["open"]]["volume"].mean()
    dn10 = last10[last10["close"] < last10["open"]]["volume"].mean()
    pullback_lighter = bool((dn10 or 0) < (up10 or 0)) if len(last10) else False

    # 连续放量长阴：2 日连跌且量 > 1.5×20日均量 且跌幅 > 3%
    big_dn = 0
    last5 = df.iloc[-5:]
    for i in range(1, len(last5)):
        r = last5.iloc[i]
        prev = last5.iloc[i - 1]
        if (
            r["close"] < r["open"]
            and r["close"] < prev["close"]
            and r["volume"] > 1.5 * vol20
            and (prev["close"] - r["close"]) / prev["close"] > 0.03
        ):
            big_dn += 1
    no_heavy_bear = big_dn < 2

    return {
        "up_dn_vol_ratio": up_dn_ratio,
        "vol_ratio_5_20": vol_ratio_5_20,
        "price_gravity": gravity,           # % 正=重心抬高
        "pullback_lighter": pullback_lighter,
        "no_heavy_bear": no_heavy_bear,
        "up_vol_avg": round(up_vol, 0),
        "dn_vol_avg": round(dn_vol, 0),
    }

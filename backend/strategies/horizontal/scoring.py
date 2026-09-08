# -*- coding: utf-8 -*-
"""横盘蓄势：100 分评分

模块：大盘环境10 + 板块趋势20 + 横盘质量20 + 量价结构15 + 业绩与风险10 + 突破强度15 + 盈亏比10

状态分档：85+ 核心候选 | 75—84 重点观察 | 65—74 普通观察 | <65 不显示
注意：评分高 ≠ 立刻买入，必须同时出现买点触发（runner 中结合信号与 market/sector 过滤）。
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def score_stock(
    *,
    market_score: int,            # 0-10
    sector_metrics: Optional[Dict],  # 板块指标
    box: Dict,
    vp: Dict,                     # volume_price 输出
    close: float,
    vol20: float,
    amt20: float,                 # 20 日均成交额（元）
    is_st: bool = False,
) -> Dict:
    """返回 {score, detail: {模块: 得分/满分}, grade}"""
    d: Dict[str, float] = {}

    # 1. 大盘环境 10
    d["大盘环境"] = float(min(market_score, 10))

    # 2. 板块趋势 20
    d["板块趋势"] = float((sector_metrics or {}).get("score", 0))

    # 3. 横盘质量 20
    amp = box["amplitude"]
    q = 0.0
    if amp <= 8:
        q += 8
    elif amp <= 12:
        q += 6
    else:
        q += 4
    days = box["box_days"]
    q += 5 if 30 <= days <= 45 else 3
    drift = box["ma20_drift"]
    q += 3 if drift <= 3 else (2 if drift <= 5 else 1)
    pos = box["close_pos_in_box"]
    q += 4 if pos >= 60 else (2 if pos >= 40 else 0)
    d["横盘质量"] = min(q, 20)

    # 4. 量价结构 15
    v = 0.0
    r = vp.get("up_dn_vol_ratio")
    v += 4 if r is not None and r >= 1.15 else (2 if r is not None and r >= 1.0 else 0)
    vr = vp.get("vol_ratio_5_20")
    v += 3 if vr is not None and 0.8 <= vr <= 1.5 else 0
    g = vp.get("price_gravity", 0)
    v += 4 if g is not None and g > 0 else (1 if g is not None and g > -1 else 0)
    v += 2 if vp.get("pullback_lighter") else 0
    v += 2 if vp.get("no_heavy_bear") else 0
    d["量价结构"] = min(v, 15)

    # 5. 业绩与风险 10（无财务数据，用波动率/流动性/ST 代理）
    ar = box["atr_ratio"]
    r5 = 0.0
    r5 += 4 if ar <= 2.5 else (2 if ar <= 4 else 0)
    r5 += 3 if amt20 >= 1e8 else (1 if amt20 >= 5e7 else 0)
    r5 += 0 if is_st else 3
    d["业绩与风险"] = min(r5, 10)

    # 6. 突破强度 15
    b = 0.0
    dist = (box["box_high"] - close) / box["box_high"] * 100 if box["box_high"] else 999
    b += 6 if dist <= 1 else (4 if dist <= 3 else (2 if dist <= 5 else 0))
    vr6 = vp.get("vol_ratio_5_20")
    b += 3 if vr6 is not None and 1.0 <= vr6 <= 1.5 else 0
    b += 3 if (sector_metrics or {}).get("ok") else 0
    b += 3 if pos >= 70 else 0
    d["突破强度"] = min(b, 15)

    # 7. 盈亏比 10（目标=箱体上沿+量度，止损=箱体下沿）
    rr = 0.0
    box_high, box_low = box["box_high"], box["box_low"]
    width = box_high - box_low
    if width > 0 and box_low < close < box_high + width:
        target = box_high + width
        stop = box_low
        rr = (target - close) / (close - stop) if close > stop else 0
    d["盈亏比"] = min(max(rr / 2.5 * 10, 0), 10) if rr > 0 else 0

    total = round(sum(d.values()), 1)
    grade = (
        "核心候选" if total >= 85 else
        "重点观察" if total >= 75 else
        "普通观察" if total >= 65 else
        "不显示"
    )
    return {
        "score": total,
        "grade": grade,
        "detail": d,
        "risk_reward": round(rr, 2) if rr > 0 else None,
        "dist_to_break": round(dist, 2),
    }

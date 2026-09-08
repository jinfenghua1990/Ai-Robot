# -*- coding: utf-8 -*-
"""横盘蓄势：买点信号分类

信号A 接近突破：距箱体上沿 ≤3% 且收盘在箱体上部30% 且近5日量能温和放大
信号B 放量突破：收盘 > 箱体上沿×1.01 且当日量/20日均量 ≥1.5 且收盘在当日振幅上部30% 且涨幅 ≤9%
信号C 回踩确认：突破后 2—5 日未跌回箱体，回踩量 ≤ 突破日量 70%，出现止跌阳线
信号D 突破失败：突破后 1—3 日跌回箱体（跌破上沿 2% 以上）且下跌放量
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 参数
DIST_APPROACH = 0.03        # 接近突破：距上沿 ≤3%
BREAK_VOL_RATIO = 1.5       # 放量阈值：量/20日均量
BREAK_CONFIRM = 1.01        # 有效突破：收盘 > 上沿×1.01
MAX_DAILY_CHG = 9.0         # 突破日涨幅上限（排除涨停一字）
PULLBACK_DAY_CAP = 5        # 回踩窗口：突破后 N 日内
PULLBACK_VOL_LIMIT = 0.70   # 回踩量 ≤ 突破日量 × 70%
FAIL_DROP = 0.98            # 跌破上沿 2% = 失败（close < 上沿×0.98）


def _is_bearish(r) -> bool:
    return bool(r["close"] < r["open"])


def classify_signal(df: pd.DataFrame, box: Dict) -> Dict:
    """根据箱体与最新日线判定信号

    返回 {code, state, detail}
      code: A/B/C/D/None | state: 接近突破/突破启动/回踩确认/突破失败/横盘观察
    """
    n = len(df)
    close = float(df["close"].iloc[-1])
    box_high = box["box_high"]
    box_low = box["box_low"]
    dist = (box_high - close) / box_high * 100 if box_high else 999
    offset = box["box_end_offset"]  # 0=箱体至今
    vol20 = box.get("vol_20") or 0.0
    vol_ratio_5_20 = box.get("vol_ratio_5_20")

    # 板块强弱在 runner 层注入（此处仅做个股侧）
    if offset <= 1 and close < box_high * BREAK_CONFIRM:
        # 仍在箱体内：接近突破（信号A）或横盘观察
        if (
            dist <= DIST_APPROACH * 100
            and box.get("close_pos_in_box", 0) >= 70
            and (vol_ratio_5_20 or 1) >= 1.0
        ):
            return {"code": "A", "state": "接近突破", "detail": f"距箱体上沿 {dist:.1f}%，收盘位于箱体上部，量能温和放大"}
        return {"code": None, "state": "横盘观察", "detail": f"箱体振幅 {box['amplitude']}%，距上沿 {dist:.1f}%"}

    # 突破已发生（offset >= 1）：定位突破日 = end+1
    end = n - 1 - offset
    bd = end + 1  # 突破日索引
    if bd >= n:
        return {"code": None, "state": "横盘观察", "detail": "数据边界"}
    br = df.iloc[bd]
    b_close = float(br["close"])
    b_vol = float(br["volume"])
    b_open = float(br["open"])
    b_high = float(br["high"])
    b_low = float(br["low"])
    day_range = b_high - b_low
    close_pos_day = (b_close - b_low) / day_range if day_range > 0 else 0.5
    b_chg = (b_close / box["prev_close"] - 1) * 100 if box.get("prev_close") else None

    is_valid_break = (
        b_close > box_high * BREAK_CONFIRM
        and (b_vol / vol20 >= BREAK_VOL_RATIO if vol20 > 0 else False)
        and close_pos_day >= 0.30
        and (b_chg is None or b_chg <= MAX_DAILY_CHG)
        and (b_chg is None or b_chg >= -1.0)  # 非巨阴
    )

    days_since = n - 1 - bd  # 突破后经过的交易日数

    # 突破后走势检查
    post = df.iloc[bd + 1:] if bd + 1 < n else pd.DataFrame()
    if len(post) == 0:
        # 昨天刚突破，今天直接判定（若今日仍在上方 → 启动）
        if is_valid_break:
            return {"code": "B", "state": "突破启动", "detail": f"放量突破箱体上沿 {box_high:.2f}（量比 {b_vol / vol20:.1f}）"}
        return {"code": None, "state": "横盘观察", "detail": "突破未确认"}

    post_close = post["close"].to_numpy(dtype=float)
    post_low = post["low"].to_numpy(dtype=float)
    post_vol = post["volume"].to_numpy(dtype=float)

    # 是否已跌回箱体：以"最新收盘"是否跌破上沿 2% 为准，避免把"突破后短暂回踩
    # 又收复"的历史低点误判为失败（优化2：突破确认更及时，减少误判 D）
    broke_back = bool(post_close[-1] < box_high * FAIL_DROP)
    if not is_valid_break:
        # 突破日本身不成立：若当前仍在箱体上方视为观察，跌回则失败
        if broke_back:
            return {"code": "D", "state": "突破失败", "detail": "突破后重新跌回箱体"}
        return {"code": None, "state": "横盘观察", "detail": "突破未放量确认"}

    if broke_back:
        return {"code": "D", "state": "突破失败", "detail": f"突破后 {days_since} 日跌回箱体（跌破上沿 2%）"}

    # 回踩确认：突破后未跌回箱体，且出现止跌阳线，回踩量收敛
    if 2 <= days_since <= PULLBACK_DAY_CAP + 2:
        # 回踩量：突破后最低量（典型回踩缩量）≤ 突破日量×70%
        min_post_vol = float(post_vol.min())
        vol_ok = min_post_vol <= b_vol * PULLBACK_VOL_LIMIT if b_vol > 0 else True
        last = df.iloc[-1]
        stop_yang = bool(last["close"] > last["open"])  # 止跌阳线
        if vol_ok and stop_yang:
            return {
                "code": "C", "state": "回踩确认",
                "detail": f"突破后回踩缩量（量 {min_post_vol / b_vol:.0%}）并出现止跌阳线",
            }
        return {"code": "B", "state": "突破启动", "detail": f"突破箱体后第 {days_since} 日，回踩尚未确认"}

    # 突破超过窗口：仍在箱体上方视为启动延续
    return {"code": "B", "state": "突破启动", "detail": f"突破后 {days_since} 日维持箱体上方"}

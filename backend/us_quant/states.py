"""US Quant System — 7状态体系

状态不等于信号：
  状态 = 股票所处阶段
  信号 = 是否允许交易

状态：
  FOLLOW        — 跟随观察
  WATCH         — 重点关注
  ACCUMULATION  — 吸筹阶段
  LAUNCH        — 启动阶段
  EXPANSION     — 发酵阶段
  MARKUP        — 主升阶段
  DISTRIBUTION  — 退潮阶段
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class StockState:
    """股票状态"""
    state: str
    label: str
    signal: str  # 当前是否可以交易的建议


def determine_stock_state(
    price: Optional[float] = None,
    ma20: Optional[float] = None,
    ma50: Optional[float] = None,
    ma200: Optional[float] = None,
    high_52w: Optional[float] = None,
    volume_ratio: Optional[float] = None,  # 当前量/均量
    rsi: Optional[float] = None,
    consecutive_up_days: Optional[int] = None,
    consecutive_down_days: Optional[int] = None,
    change_pct_5d: Optional[float] = None,
    change_pct_20d: Optional[float] = None,
) -> StockState:
    """根据技术指标判断股票所处阶段"""

    if not price or not ma50:
        return StockState(state="FOLLOW", label="跟随", signal="数据不足，继续观察")

    # DISTRIBUTION: 退潮
    if (ma20 and price < ma20 and ma20 < ma50) or (consecutive_down_days and consecutive_down_days >= 5):
        return StockState(
            state="DISTRIBUTION",
            label="退潮",
            signal="趋势走弱，不建议新开仓，持仓考虑减仓或退出",
        )

    # MARKUP: 主升
    if (price > ma20 and ma20 > ma50 and price > ma50) and \
       (consecutive_up_days and consecutive_up_days >= 3) and \
       (rsi and rsi > 60):
        return StockState(
            state="MARKUP",
            label="主升",
            signal="处于主升阶段，持仓可继续持有，但不宜追高加仓",
        )

    # EXPANSION: 发酵
    if (price > ma20 and ma20 > ma50) and \
       (volume_ratio and volume_ratio > 1.2) and \
       (change_pct_5d and change_pct_5d > 5):
        return StockState(
            state="EXPANSION",
            label="发酵",
            signal="趋势向好，量价配合，可考虑建仓或加仓",
        )

    # LAUNCH: 启动
    if (price > ma20 and ma20 > ma50) and \
       (volume_ratio and volume_ratio > 1.5) and \
       (change_pct_5d and change_pct_5d > 3):
        return StockState(
            state="LAUNCH",
            label="启动",
            signal="放量突破，初步启动，可考虑入场",
        )

    # ACCUMULATION: 吸筹
    if (ma50 and price > ma50) and \
       (ma20 and price < ma20 * 1.05) and \
       (volume_ratio is None or volume_ratio < 1.2):
        return StockState(
            state="ACCUMULATION",
            label="吸筹",
            signal="价格在均线附近整理，量能平稳，观察等待信号",
        )

    # WATCH: 关注
    if ma200 and price > ma200:
        return StockState(
            state="WATCH",
            label="关注",
            signal="价格在MA200之上，中期趋势尚可，但短线信号不明",
        )

    # FOLLOW: 跟随
    return StockState(
        state="FOLLOW",
        label="跟随",
        signal="继续观察，等待更明确的信号",
    )
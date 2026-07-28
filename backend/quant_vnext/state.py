from __future__ import annotations

from typing import Mapping

from .contracts import DimensionScore


LIFECYCLE = ("跟随", "关注", "吸筹", "启动", "发酵", "主升", "退潮")
TRADING = ("WATCH", "READY", "TRIGGERED", "HOLD", "NO_CHASE", "INVALID")


def lifecycle_state(dimensions: Mapping[str, DimensionScore]) -> str:
    trend = dimensions.get("trend")
    strength = dimensions.get("strength")
    position = dimensions.get("position")
    if not trend or not trend.valid:
        return "关注"
    if strength and strength.valid and strength.score is not None and strength.score < 35:
        return "退潮"
    if trend.score is not None and trend.score >= 80 and strength and strength.score is not None and strength.score >= 70:
        return "主升"
    if trend.score is not None and trend.score >= 65:
        return "启动" if not position or position.score is None or position.score >= 45 else "发酵"
    return "吸筹"


def trading_state(dimensions: Mapping[str, DimensionScore], resonance_eligible: bool) -> str:
    risk = dimensions.get("risk")
    position = dimensions.get("position")
    trend = dimensions.get("trend")
    if not all(d and d.valid for d in (risk, position, trend)):
        return "INVALID"
    if risk.score is not None and risk.score < 40:
        return "INVALID"
    if position.score is not None and position.score >= 85:
        return "NO_CHASE"
    if resonance_eligible and trend.score is not None and trend.score >= 70:
        return "TRIGGERED"
    if trend.score is not None and trend.score >= 60:
        return "READY"
    return "WATCH"

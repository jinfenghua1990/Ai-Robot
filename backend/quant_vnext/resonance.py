from __future__ import annotations

from typing import Mapping

from .contracts import DimensionScore, ResonanceSnapshot


class ResonanceEngine:
    # 生产触发门槛：宁可减少候选，也不把单一维度共振当成交易信号。
    MIN_OPPORTUNITY_DIMENSIONS = 5
    MIN_RISK_SCORE = 50
    # 风险不是机会证据，不能因为风险分高就增加共振数量；它只负责否决。
    OPPORTUNITY_DIMENSIONS = ("market", "sector", "strength", "trend", "volume_price", "position")
    REQUIRED = OPPORTUNITY_DIMENSIONS + ("risk",)

    def evaluate(self, dimensions: Mapping[str, DimensionScore]) -> ResonanceSnapshot:
        valid = [
            name for name in self.OPPORTUNITY_DIMENSIONS
            if dimensions.get(name)
            and dimensions[name].valid
            and (dimensions[name].score or 0) >= 60
        ]
        failed = [name for name in self.OPPORTUNITY_DIMENSIONS if name not in valid]
        trend_ok = "trend" in valid
        strength_ok = "strength" in valid or "sector" in valid
        risk = dimensions.get("risk")
        risk_ok = bool(risk and risk.valid and risk.score is not None and risk.score >= self.MIN_RISK_SCORE)
        if not risk_ok:
            failed.append("risk")
        eligible = len(valid) >= self.MIN_OPPORTUNITY_DIMENSIONS and trend_ok and strength_ok and risk_ok
        reason = "eligible" if eligible else ";".join([
            item for item in (
                f"less_than_{self.MIN_OPPORTUNITY_DIMENSIONS}_dimensions" if len(valid) < self.MIN_OPPORTUNITY_DIMENSIONS else "",
                "trend_not_confirmed" if not trend_ok else "",
                "strength_or_sector_not_confirmed" if not strength_ok else "",
                "risk_not_acceptable" if not risk_ok else "",
            ) if item
        ])
        return ResonanceSnapshot(len(valid), valid, failed, eligible, reason)

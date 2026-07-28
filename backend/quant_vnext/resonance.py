from __future__ import annotations

from typing import Mapping

from .contracts import DimensionScore, ResonanceSnapshot


class ResonanceEngine:
    REQUIRED = ("trend", "strength", "sector", "volume_price", "position", "risk")

    def evaluate(self, dimensions: Mapping[str, DimensionScore]) -> ResonanceSnapshot:
        valid = [name for name in self.REQUIRED if dimensions.get(name) and dimensions[name].valid and (dimensions[name].score or 0) >= 60]
        failed = [name for name in self.REQUIRED if name not in valid]
        trend_ok = "trend" in valid
        strength_ok = "strength" in valid or "sector" in valid
        risk_ok = "risk" in valid and (dimensions["risk"].score or 0) >= 40
        eligible = len(valid) >= 4 and trend_ok and strength_ok and risk_ok
        reason = "eligible" if eligible else ";".join([
            item for item in (
                "less_than_4_dimensions" if len(valid) < 4 else "",
                "trend_not_confirmed" if not trend_ok else "",
                "strength_or_sector_not_confirmed" if not strength_ok else "",
                "risk_not_acceptable" if not risk_ok else "",
            ) if item
        ])
        return ResonanceSnapshot(len(valid), valid, failed, eligible, reason)

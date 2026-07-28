from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev
from typing import Dict, Iterable, Mapping

from .contracts import DimensionScore, FactorValue
from .registry import FactorRegistry


def _percentile(values: list[float], value: float) -> float:
    if len(values) < 2:
        return 50.0
    ordered = sorted(values)
    below = sum(v < value for v in ordered)
    equal = sum(v == value for v in ordered)
    return 100.0 * (below + equal / 2) / len(ordered)


class CrossSectionScorer:
    DIMENSION_MAP = {
        "momentum": "strength",
        "trend": "trend",
        "volume_price": "volume_price",
        "volatility": "risk",
        "position": "position",
        "sector": "sector",
        "risk": "risk",
    }

    def score(self, values: Iterable[FactorValue], registry: FactorRegistry) -> dict[str, dict[str, DimensionScore]]:
        rows = list(values)
        by_factor: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row.valid and row.raw_value is not None:
                by_factor[row.name].append(row.raw_value)
        by_stock: dict[str, list[FactorValue]] = defaultdict(list)
        for row in rows:
            by_stock[row.ts_code].append(row)
        result = {}
        for ts_code, stock_rows in by_stock.items():
            dimensions: dict[str, list[float]] = defaultdict(list)
            factor_names: dict[str, list[str]] = defaultdict(list)
            for row in stock_rows:
                if not row.valid or row.raw_value is None:
                    continue
                definition = registry.get(row.name)
                normalized = _percentile(by_factor[row.name], row.raw_value)
                if definition.direction < 0:
                    normalized = 100.0 - normalized
                row.normalized = round(normalized, 4)
                dimension = self.DIMENSION_MAP[definition.category]
                dimensions[dimension].append(normalized)
                factor_names[dimension].append(row.name)
            result[ts_code] = {
                name: DimensionScore(name, round(mean(scores), 2), True, factor_names[name])
                for name, scores in dimensions.items()
            }
            for name in {"strength", "trend", "volume_price", "risk", "position", "sector"} - set(result[ts_code]):
                result[ts_code][name] = DimensionScore(name, None, False, [], "missing_factor")
        return result

    @staticmethod
    def factor_score(dimensions: Mapping[str, DimensionScore]) -> float | None:
        usable = [d.score for d in dimensions.values() if d.valid and d.score is not None and d.name != "risk"]
        if not usable:
            return None
        risk = dimensions.get("risk")
        penalty = (100 - risk.score) * 0.15 if risk and risk.valid and risk.score is not None else 0.0
        return round(max(0.0, min(100.0, mean(usable) * 0.85 + penalty)), 2)

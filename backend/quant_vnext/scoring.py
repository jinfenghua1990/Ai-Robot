from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Iterable, Mapping

from .contracts import DimensionScore, FactorValue
from .registry import FactorRegistry


GROUP_WEIGHTS = {
    "market": 0.10,
    "sector": 0.20,
    "strength": 0.20,
    "trend": 0.15,
    "volume_price": 0.15,
    "position": 0.15,
    "risk_penalty": 0.05,
}


def _percentile(values: list[float], value: float) -> float:
    if len(values) < 2:
        return 50.0
    ordered = sorted(values)
    below = sum(v < value for v in ordered)
    equal = sum(v == value for v in ordered)
    return 100.0 * (below + equal / 2) / len(ordered)


def _market_score(name: str, value: float) -> float:
    """Map global context factors to 0-100 without turning equal values into 50."""
    if name == "market_up_ratio":
        return max(0.0, min(100.0, value * 100.0))
    if name == "market_limit_pressure":
        return max(0.0, min(100.0, (value + 1.0) * 50.0))
    if name == "market_index_trend":
        return max(0.0, min(100.0, 50.0 + value * 1000.0))
    return max(0.0, min(100.0, value))


class CrossSectionScorer:
    """Normalize individual factors, then aggregate the seven factor groups."""

    DIMENSION_MAP = {
        "market": "market",
        "momentum": "strength",
        "trend": "trend",
        "volume_price": "volume_price",
        "volatility": "risk",
        "position": "position",
        "sector": "sector",
        "risk": "risk",
    }

    DIMENSIONS = ("market", "sector", "strength", "trend", "volume_price", "position", "risk")

    def score(self, values: Iterable[FactorValue], registry: FactorRegistry) -> dict[str, dict[str, DimensionScore]]:
        rows = list(values)
        by_factor: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if row.valid and row.raw_value is not None:
                by_factor[row.name].append(row.raw_value)
        by_stock: dict[str, list[FactorValue]] = defaultdict(list)
        for row in rows:
            by_stock[row.ts_code].append(row)
        result: dict[str, dict[str, DimensionScore]] = {}
        for ts_code, stock_rows in by_stock.items():
            dimensions: dict[str, list[float]] = defaultdict(list)
            factor_names: dict[str, list[str]] = defaultdict(list)
            for row in stock_rows:
                if not row.valid or row.raw_value is None:
                    continue
                definition = registry.get(row.name)
                if definition.category == "market":
                    normalized = _market_score(row.name, row.raw_value)
                else:
                    normalized = _percentile(by_factor[row.name], row.raw_value)
                    if definition.direction < 0:
                        normalized = 100.0 - normalized
                row.normalized = round(normalized, 4)
                dimension = self.DIMENSION_MAP[definition.category]
                dimensions[dimension].append(normalized)
                factor_names[dimension].append(row.name)
            result[ts_code] = {
                name: DimensionScore(name, round(mean(dimensions[name]), 2), True, factor_names[name])
                for name in dimensions
            }
            for name in self.DIMENSIONS:
                if name not in result[ts_code]:
                    result[ts_code][name] = DimensionScore(name, None, False, [], "missing_factor")
        return result

    @staticmethod
    def factor_score(dimensions: Mapping[str, DimensionScore], weights: Mapping[str, float] | None = None) -> float | None:
        active_weights = dict(GROUP_WEIGHTS)
        if weights:
            active_weights.update(weights)
        usable = []
        for name in ("market", "sector", "strength", "trend", "volume_price", "position"):
            item = dimensions.get(name)
            if item and item.valid and item.score is not None:
                usable.append(item.score * active_weights.get(name, 0.0))
        risk = dimensions.get("risk")
        if not usable and not (risk and risk.valid and risk.score is not None):
            return None
        score = sum(usable)
        if risk and risk.valid and risk.score is not None:
            score -= (100.0 - risk.score) * active_weights.get("risk_penalty", 0.05)
        return round(max(0.0, min(100.0, score)), 2)

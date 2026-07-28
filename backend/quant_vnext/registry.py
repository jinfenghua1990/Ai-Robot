from __future__ import annotations

from dataclasses import asdict
from typing import Dict, Iterable

from .contracts import FactorDefinition


class FactorRegistry:
    def __init__(self, definitions: Iterable[FactorDefinition] = ()) -> None:
        self._items: Dict[str, FactorDefinition] = {}
        for item in definitions:
            self.register(item)

    def register(self, definition: FactorDefinition) -> None:
        if definition.name in self._items:
            raise ValueError(f"duplicate factor: {definition.name}")
        if definition.direction not in (-1, 1):
            raise ValueError(f"direction must be -1 or 1: {definition.name}")
        self._items[definition.name] = definition

    def get(self, name: str) -> FactorDefinition:
        return self._items[name]

    def all(self) -> list[FactorDefinition]:
        return list(self._items.values())

    def production(self) -> list[FactorDefinition]:
        return [item for item in self._items.values() if item.production]

    def export(self) -> list[dict]:
        return [asdict(item) for item in self._items.values()]


def default_registry() -> FactorRegistry:
    definitions = [
        FactorDefinition("return_5d", "momentum", "daily_bar", "close[t]/close[t-5]-1", ("close",), 5, 1, production=True),
        FactorDefinition("return_20d", "momentum", "daily_bar", "close[t]/close[t-20]-1", ("close",), 20, 1, production=True),
        FactorDefinition("ma20_slope", "trend", "daily_bar", "slope(MA20, 5)", ("close",), 25, 1, production=True),
        FactorDefinition("trend_alignment", "trend", "daily_bar", "close>MA20>MA60", ("close",), 60, 1, production=True),
        FactorDefinition("breakout_strength", "trend", "daily_bar", "close/max(high[-20:])-1", ("high", "close"), 20, 1, production=True),
        FactorDefinition("volume_ratio_20d", "volume_price", "daily_bar", "volume/mean(volume[-20:])", ("volume",), 20, 1, production=True),
        FactorDefinition("up_volume_ratio", "volume_price", "daily_bar", "up_volume/total_volume", ("close", "volume"), 20, 1, production=True),
        FactorDefinition("atr_pct_14d", "volatility", "daily_bar", "ATR14/close", ("high", "low", "close"), 14, -1, production=True),
        FactorDefinition("distance_high_60d", "position", "daily_bar", "close/max(high[-60:])-1", ("high", "close"), 60, 1, production=True),
        FactorDefinition("pullback_depth_20d", "position", "daily_bar", "close/max(high[-20:])-1", ("high", "close"), 20, -1, production=True),
        FactorDefinition("sector_relative_20d", "sector", "sector_context", "stock_return_20d-sector_return_20d", ("close", "sector"), 20, 1, production=True),
        FactorDefinition("liquidity_amount_20d", "risk", "daily_bar", "mean(amount[-20:])", ("amount",), 20, 1, production=True),
    ]
    return FactorRegistry(definitions)

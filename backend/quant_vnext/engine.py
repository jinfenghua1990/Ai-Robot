from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from statistics import mean, pstdev
from typing import Dict, Iterable, Mapping, Sequence

from .contracts import DailyBar, FactorValue
from .registry import FactorRegistry


def _mean(values: Sequence[float]) -> float:
    return mean(values) if values else 0.0


def _slope(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    x_bar = (len(values) - 1) / 2
    y_bar = _mean(values)
    den = sum((i - x_bar) ** 2 for i in range(len(values)))
    return sum((i - x_bar) * (v - y_bar) for i, v in enumerate(values)) / den if den else 0.0


def _atr_pct(bars: Sequence[DailyBar], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    trs = []
    for previous, current in zip(bars[-period - 1:-1], bars[-period:]):
        trs.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    return _mean(trs) / bars[-1].close if bars[-1].close else None


class FactorEngine:
    def __init__(self, registry: FactorRegistry) -> None:
        self.registry = registry

    def calculate(self, history: Mapping[str, Sequence[DailyBar]], trade_date: date) -> list[FactorValue]:
        raw: list[FactorValue] = []
        sector_returns: dict[str, list[float]] = defaultdict(list)
        for bars in history.values():
            visible = sorted((b for b in bars if b.trade_date <= trade_date), key=lambda b: b.trade_date)
            if visible and visible[-1].trade_date == trade_date and len(visible) >= 21 and visible[-21].close:
                sector_returns[visible[-1].sector].append(visible[-1].close / visible[-21].close - 1)
        sector_mean = {sector: _mean(values) for sector, values in sector_returns.items()}
        for ts_code, bars in history.items():
            bars = sorted((b for b in bars if b.trade_date <= trade_date), key=lambda b: b.trade_date)
            if not bars or bars[-1].trade_date != trade_date:
                continue
            latest = bars[-1]
            closes = [b.close for b in bars]
            highs = [b.high for b in bars]
            volumes = [b.volume for b in bars]
            amounts = [b.amount for b in bars]
            values = {
                "return_5d": closes[-1] / closes[-6] - 1 if len(closes) >= 6 and closes[-6] else None,
                "return_20d": closes[-1] / closes[-21] - 1 if len(closes) >= 21 and closes[-21] else None,
                "ma20_slope": _slope([_mean(closes[i-19:i+1]) for i in range(max(19, len(closes)-6), len(closes))]) if len(closes) >= 25 else None,
                "trend_alignment": 1.0 if len(closes) >= 60 and closes[-1] > _mean(closes[-20:]) > _mean(closes[-60:]) else 0.0 if len(closes) >= 60 else None,
                "breakout_strength": closes[-1] / max(highs[-20:]) - 1 if len(closes) >= 20 and max(highs[-20:]) else None,
                "volume_ratio_20d": volumes[-1] / _mean(volumes[-20:]) if len(volumes) >= 20 and _mean(volumes[-20:]) else None,
                "up_volume_ratio": _mean([b.volume for a, b in zip(bars[-20:-1], bars[-19:]) if b.close > a.close]) / _mean(volumes[-20:]) if len(bars) >= 20 and _mean(volumes[-20:]) else None,
                "atr_pct_14d": _atr_pct(bars),
                "distance_high_60d": closes[-1] / max(highs[-60:]) - 1 if len(closes) >= 60 and max(highs[-60:]) else None,
                "pullback_depth_20d": closes[-1] / max(highs[-20:]) - 1 if len(closes) >= 20 and max(highs[-20:]) else None,
                "sector_relative_20d": (
                    (closes[-1] / closes[-21] - 1) - sector_mean.get(latest.sector, 0.0)
                    if len(closes) >= 21 and closes[-21] and latest.sector else None
                ),
                "liquidity_amount_20d": _mean(amounts[-20:]) if len(amounts) >= 20 else None,
            }
            for definition in self.registry.production():
                value = values.get(definition.name)
                valid = value is not None and math.isfinite(float(value))
                raw.append(FactorValue(ts_code, trade_date, definition.name, definition.category, float(value) if valid else None, None, valid, "" if valid else "insufficient_history"))
        return raw

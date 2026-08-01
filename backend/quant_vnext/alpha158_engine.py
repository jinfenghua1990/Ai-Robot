"""Small, dependency-free evaluator for the local Alpha158 research subset."""

from __future__ import annotations

import math
from datetime import date
from statistics import mean, pstdev
from typing import Mapping, Sequence

from .alpha158_catalog import ALPHA158_RESEARCH_FACTORS
from .contracts import DailyBar, FactorValue


def _corr(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean, right_mean = mean(left), mean(right)
    left_dev = sum((value - left_mean) ** 2 for value in left) ** 0.5
    right_dev = sum((value - right_mean) ** 2 for value in right) ** 0.5
    if not left_dev or not right_dev:
        return None
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / (left_dev * right_dev)


def _slope(values: Sequence[float]) -> float:
    x_mean = (len(values) - 1) / 2
    y_mean = mean(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    return sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values)) / denominator if denominator else 0.0


def _rsquare(values: Sequence[float]) -> float:
    correlation = _corr(list(range(len(values))), values)
    return correlation * correlation if correlation is not None else 0.0


def _value(name: str, category: str, ts_code: str, trade_date: date, raw: float | None, reason: str = "") -> FactorValue:
    valid = raw is not None and math.isfinite(float(raw))
    return FactorValue(ts_code, trade_date, name, category, float(raw) if valid else None, None, valid, reason if not valid else "")


class Alpha158ResearchEngine:
    """Evaluate only the explicitly approved research subset, never production factors."""

    def calculate(self, history: Mapping[str, Sequence[DailyBar]], trade_date: date, market=None) -> list[FactorValue]:
        definitions = {item.name: item for item in ALPHA158_RESEARCH_FACTORS}
        result: list[FactorValue] = []
        for ts_code, source_bars in history.items():
            bars = sorted((bar for bar in source_bars if bar.trade_date <= trade_date), key=lambda bar: bar.trade_date)
            if not bars or bars[-1].trade_date != trade_date:
                continue
            closes = [bar.close for bar in bars]
            highs = [bar.high for bar in bars]
            lows = [bar.low for bar in bars]
            volumes = [bar.volume for bar in bars]
            window = 20
            recent_close = closes[-window:]
            recent_high = highs[-window:]
            recent_low = lows[-window:]
            recent_volume = volumes[-window:]
            changes = [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes)) if closes[index - 1]]
            recent_changes = changes[-window:]
            values = {
                "qlib_roc_5d": closes[-6] / closes[-1] if len(closes) >= 6 and closes[-1] else None,
                "qlib_roc_20d": closes[-21] / closes[-1] if len(closes) >= 21 and closes[-1] else None,
                "qlib_ma_gap_20d": mean(recent_close) / closes[-1] if len(recent_close) == window and closes[-1] else None,
                "qlib_beta_20d": _slope(recent_close) / closes[-1] if len(recent_close) == window and closes[-1] else None,
                "qlib_rsqr_20d": _rsquare(recent_close) if len(recent_close) == window else None,
                "qlib_rsv_20d": (closes[-1] - min(recent_low)) / (max(recent_high) - min(recent_low) + 1e-12) if len(recent_close) == window else None,
                "qlib_std_20d": pstdev(recent_close) / closes[-1] if len(recent_close) == window and closes[-1] else None,
                "qlib_corr_price_volume_20d": _corr(recent_close, [math.log(volume + 1) for volume in recent_volume]) if len(recent_close) == window else None,
                "qlib_cntd_20d": (sum(change > 0 for change in recent_changes) - sum(change < 0 for change in recent_changes)) / window if len(recent_changes) == window else None,
                "qlib_sump_20d": sum(max(change, 0) for change in recent_changes) / (sum(abs(change) for change in recent_changes) + 1e-12) if len(recent_changes) == window else None,
                "qlib_vma_20d": mean(recent_volume) / (volumes[-1] + 1e-12) if len(recent_volume) == window else None,
                "qlib_vstd_20d": pstdev(recent_volume) / (volumes[-1] + 1e-12) if len(recent_volume) == window else None,
                "qlib_wvma_20d": (
                    pstdev([abs(change) * volume for change, volume in zip(recent_changes, volumes[-window:])])
                    / (mean([abs(change) * volume for change, volume in zip(recent_changes, volumes[-window:])]) + 1e-12)
                    if len(recent_changes) == window else None
                ),
            }
            for name, definition in definitions.items():
                result.append(_value(name, definition.category, ts_code, trade_date, values[name], "insufficient_history"))
        return result

from __future__ import annotations

from statistics import mean
from typing import Iterable, Sequence


def forward_return(closes: Sequence[float], horizon: int) -> float | None:
    if len(closes) <= horizon or not closes[0]:
        return None
    return closes[horizon] / closes[0] - 1


def evaluate_forward_returns(samples: Iterable[Sequence[float]], horizons=(1, 3, 5, 10, 20)) -> dict:
    result = {}
    for horizon in horizons:
        values = [value for sample in samples if (value := forward_return(sample, horizon)) is not None]
        result[str(horizon)] = {
            "count": len(values),
            "mean": round(mean(values), 6) if values else None,
            "win_rate": round(sum(v > 0 for v in values) / len(values), 6) if values else None,
            "max_profit": max(values) if values else None,
            "max_loss": min(values) if values else None,
        }
    return result

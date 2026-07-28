from __future__ import annotations

from math import isnan
from statistics import mean
from typing import Iterable, Sequence


def _rank(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        rank = (i + j + 2) / 2
        for k in range(i, j + 1):
            result[ordered[k][0]] = rank
        i = j + 1
    return result


def correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    pairs = [(float(a), float(b)) for a, b in zip(left, right) if not isnan(float(a)) and not isnan(float(b))]
    if len(pairs) < 3:
        return None
    ax, bx = mean(a for a, _ in pairs), mean(b for _, b in pairs)
    numerator = sum((a - ax) * (b - bx) for a, b in pairs)
    den_a = sum((a - ax) ** 2 for a, _ in pairs) ** .5
    den_b = sum((b - bx) ** 2 for _, b in pairs) ** .5
    return numerator / (den_a * den_b) if den_a and den_b else None


def factor_ic(factor_values: Sequence[float], forward_returns: Sequence[float]) -> float | None:
    return correlation(factor_values, forward_returns)


def rank_ic(factor_values: Sequence[float], forward_returns: Sequence[float]) -> float | None:
    return correlation(_rank(factor_values), _rank(forward_returns))


def factor_correlation_matrix(columns: dict[str, Sequence[float]]) -> dict[str, dict[str, float | None]]:
    names = list(columns)
    return {a: {b: correlation(columns[a], columns[b]) for b in names} for a in names}


def rolling_factor_validation(engine, history, dates, horizon: int = 5) -> list[dict]:
    """按交易日滚动计算横截面 IC / Rank IC，因子只使用当日以前数据。"""
    observations: dict[str, list[tuple[float, float]]] = {}
    for trade_date in sorted(set(dates)):
        visible = {
            code: [bar for bar in bars if bar.trade_date <= trade_date]
            for code, bars in history.items()
        }
        visible = {code: bars for code, bars in visible.items() if bars and bars[-1].trade_date == trade_date}
        if not visible:
            continue
        values = engine.calculate(visible, trade_date)
        future = {}
        for code, bars in history.items():
            ordered = sorted(bars, key=lambda item: item.trade_date)
            indexes = {bar.trade_date: index for index, bar in enumerate(ordered)}
            index = indexes.get(trade_date)
            if index is not None and index + horizon < len(ordered) and ordered[index].close:
                future[code] = ordered[index + horizon].close / ordered[index].close - 1
        for value in values:
            if value.valid and value.raw_value is not None and value.ts_code in future:
                observations.setdefault(value.name, []).append((value.raw_value, future[value.ts_code]))
    result = []
    for name, pairs in observations.items():
        factors = [pair[0] for pair in pairs]
        returns = [pair[1] for pair in pairs]
        result.append({
            "factor_name": name,
            "period_days": horizon,
            "sample_count": len(pairs),
            "ic": factor_ic(factors, returns),
            "rank_ic": rank_ic(factors, returns),
            "mean_forward_return": mean(returns) if returns else None,
        })
    return result

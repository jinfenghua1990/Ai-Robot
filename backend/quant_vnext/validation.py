from __future__ import annotations

from math import isnan
from statistics import mean
from typing import Iterable, Sequence

from .contracts import MarketContext


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
        values = engine.calculate(visible, trade_date, _derived_market_context(visible, trade_date))
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


def factor_correlation_from_history(engine, history, dates) -> dict[str, dict[str, float | None]]:
    """Compute factor correlations on aligned stock/date observations.

    Correlations must compare the same stock on the same signal date.  A
    simple zip of independently filtered factor lists can silently compare
    different securities when one factor has missing history, so this helper
    aligns observations by ``(trade_date, ts_code)`` first.
    """

    observations: dict[tuple[object, str], dict[str, float]] = {}
    for trade_date in sorted(set(dates)):
        visible = {
            code: [bar for bar in bars if bar.trade_date <= trade_date]
            for code, bars in history.items()
        }
        visible = {
            code: bars for code, bars in visible.items()
            if bars and bars[-1].trade_date == trade_date
        }
        if not visible:
            continue
        values = engine.calculate(visible, trade_date, _derived_market_context(visible, trade_date))
        for value in values:
            if value.valid and value.raw_value is not None:
                observations.setdefault((trade_date, value.ts_code), {})[value.name] = float(value.raw_value)

    names = sorted({name for row in observations.values() for name in row})
    result: dict[str, dict[str, float | None]] = {name: {} for name in names}
    for left in names:
        for right in names:
            pairs = [
                (row[left], row[right])
                for row in observations.values()
                if left in row and right in row
            ]
            result[left][right] = correlation(
                [pair[0] for pair in pairs],
                [pair[1] for pair in pairs],
            )
    return result


def _derived_market_context(visible, trade_date) -> MarketContext:
    """Build only from bars visible on the validation date."""
    latest = [bars[-1] for bars in visible.values() if bars]
    breadth = sum(
        1 for bars in visible.values()
        if len(bars) >= 2 and bars[-1].close > bars[-2].close
    ) / len(latest) if latest else 0.0
    returns = []
    for bars in visible.values():
        if len(bars) >= 21 and bars[-21].close:
            returns.append(bars[-1].close / bars[-21].close - 1)
    return MarketContext(
        trade_date=trade_date,
        breadth=breadth,
        limit_up_count=sum(1 for bars in visible.values() if bars and abs(float(bars[-1].pct_chg or 0)) >= 9.5 and float(bars[-1].pct_chg or 0) > 0),
        limit_down_count=sum(1 for bars in visible.values() if bars and abs(float(bars[-1].pct_chg or 0)) >= 9.5 and float(bars[-1].pct_chg or 0) < 0),
        market_return_20d=mean(returns) if returns else None,
        market_data_available=True,
    )

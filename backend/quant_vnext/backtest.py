from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

from .contracts import DailyBar, MarketContext
from .pipeline import QuantPipeline
from .research import forward_return


def _market(history: Mapping[str, Sequence[DailyBar]], trade_date: date) -> MarketContext:
    latest = [bars[-1].pct_chg for bars in history.values() if bars and bars[-1].trade_date == trade_date]
    return MarketContext(trade_date, sum(x > 0 for x in latest) / len(latest) if latest else 0.0)


def _forward_excursion(bars: Sequence[DailyBar], horizon: int) -> dict[str, float | None]:
    """Measure post-signal path risk using only the next ``horizon`` bars.

    ``max_profit`` and ``max_loss`` are intraperiod excursions from the
    signal-day close.  ``max_drawdown`` is the worst fall from a running high
    in that same forward window, represented as a negative return.
    """

    window = list(bars[:horizon + 1])
    if not window or not window[0].close:
        return {"max_profit": None, "max_loss": None, "max_drawdown": None}
    entry = float(window[0].close)
    highs = [float(bar.high or bar.close) for bar in window]
    lows = [float(bar.low or bar.close) for bar in window]
    max_profit = max(high / entry - 1 for high in highs)
    max_loss = min(low / entry - 1 for low in lows)
    running_high = highs[0]
    max_drawdown = 0.0
    for high, low in zip(highs, lows):
        running_high = max(running_high, high)
        max_drawdown = min(max_drawdown, low / running_high - 1 if running_high else 0.0)
    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "max_drawdown": max_drawdown,
    }


def walk_forward(history: Mapping[str, Sequence[DailyBar]], dates: Sequence[date], horizons=(1, 3, 5, 10, 20), include_records: bool = False) -> dict:
    """严格按日期截断历史，避免把未来 K 线带入信号。"""
    pipeline = QuantPipeline()
    outcomes = []
    max_horizon = max(horizons)
    for trade_date in sorted(set(dates)):
        visible = {
            code: [bar for bar in bars if bar.trade_date <= trade_date]
            for code, bars in history.items()
        }
        visible = {code: bars for code, bars in visible.items() if bars and bars[-1].trade_date == trade_date}
        if not visible:
            continue
        snapshots = pipeline.run(visible, trade_date, _market(visible, trade_date))
        for snapshot in snapshots:
            bars = history[snapshot.ts_code]
            future_bars = [bar for bar in bars if bar.trade_date >= trade_date]
            closes = [bar.close for bar in future_bars]
            outcome = {str(h): forward_return(closes, h) for h in horizons}
            excursions = {str(h): _forward_excursion(future_bars, h) for h in horizons}
            if any(value is not None for value in outcome.values()):
                outcomes.append({"snapshot": snapshot, "outcome": outcome, "excursions": excursions})
    summary = {}
    for horizon in horizons:
        values = [item["outcome"][str(horizon)] for item in outcomes if item["outcome"][str(horizon)] is not None]
        excursions = [
            item["excursions"][str(horizon)]
            for item in outcomes
            if item["outcome"][str(horizon)] is not None
        ]
        summary[str(horizon)] = {
            "count": len(values),
            "mean": sum(values) / len(values) if values else None,
            "win_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "max_profit": max(values) if values else None,
            "max_loss": min(values) if values else None,
            "max_favorable_excursion": max(
                (item["max_profit"] for item in excursions if item["max_profit"] is not None),
                default=None,
            ),
            "max_adverse_excursion": min(
                (item["max_loss"] for item in excursions if item["max_loss"] is not None),
                default=None,
            ),
            "max_drawdown": min(
                (item["max_drawdown"] for item in excursions if item["max_drawdown"] is not None),
                default=None,
            ),
        }
    result = {"sample_count": len(outcomes), "horizons": summary}
    if include_records:
        record_horizon = str(max(horizons))
        result["records"] = [
            {
                "ts_code": item["snapshot"].ts_code,
                "signal_date": item["snapshot"].trade_date,
                "trading_state": item["snapshot"].trading_state,
                "returns": item["outcome"],
                **item["excursions"].get(record_horizon, {}),
            }
            for item in outcomes
        ]
    return result

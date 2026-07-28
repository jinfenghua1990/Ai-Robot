from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

from .contracts import DailyBar, MarketContext
from .pipeline import QuantPipeline
from .research import forward_return


def _market(history: Mapping[str, Sequence[DailyBar]], trade_date: date) -> MarketContext:
    latest = [bars[-1].pct_chg for bars in history.values() if bars and bars[-1].trade_date == trade_date]
    return MarketContext(trade_date, sum(x > 0 for x in latest) / len(latest) if latest else 0.0)


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
            closes = [bar.close for bar in bars if bar.trade_date >= trade_date]
            outcome = {str(h): forward_return(closes, h) for h in horizons}
            if any(value is not None for value in outcome.values()):
                outcomes.append({"snapshot": snapshot, "outcome": outcome})
    summary = {}
    for horizon in horizons:
        values = [item["outcome"][str(horizon)] for item in outcomes if item["outcome"][str(horizon)] is not None]
        summary[str(horizon)] = {
            "count": len(values),
            "mean": sum(values) / len(values) if values else None,
            "win_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "max_profit": max(values) if values else None,
            "max_loss": min(values) if values else None,
        }
    result = {"sample_count": len(outcomes), "horizons": summary}
    if include_records:
        result["records"] = [
            {
                "ts_code": item["snapshot"].ts_code,
                "signal_date": item["snapshot"].trade_date,
                "trading_state": item["snapshot"].trading_state,
                "returns": item["outcome"],
            }
            for item in outcomes
        ]
    return result

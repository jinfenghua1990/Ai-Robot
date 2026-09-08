"""Production-facing helpers for the V2 right-side factor engine.

This module is deliberately independent from the legacy strategy tables.  It
owns the completed-daily-bar date, the tradable universe, bulk history loading,
cross-sectional ranking, and the payload consumed by the execution layer.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Iterable, Mapping, Optional

from sqlalchemy import func

from db.models import StockDailyKline, StockFlow
from .contracts import DailyBar, MarketContext, SignalSnapshot
from .pipeline import QuantPipeline


def _clean_name(value: object) -> str:
    return str(value or "").upper().replace(" ", "").replace("　", "")


def is_st_name(name: object) -> bool:
    """Return True for ST/*ST names after whitespace normalization."""

    normalized = _clean_name(name)
    return normalized.startswith("ST") or normalized.startswith("*ST")


def resolve_trade_date(db, requested: Optional[date] = None) -> Optional[date]:
    """Resolve a signal date to the latest completed daily-bar date.

    Intraday callers commonly pass today's calendar date while the latest
    completed daily bar is yesterday's date.  Falling back to a date <= the
    requested date prevents the execution layer from labelling stale signals
    as today's signals.
    """

    query = db.query(func.max(StockDailyKline.trade_date))
    if requested is not None:
        query = query.filter(StockDailyKline.trade_date <= requested)
    return query.scalar()


def _metadata_for_date(db, trade_date: date) -> dict[str, dict[str, str]]:
    """Load one name/sector record per symbol for a completed trade date."""

    result: dict[str, dict[str, str]] = {}
    rows = db.query(
        StockFlow.ts_code, StockFlow.name, StockFlow.sector
    ).filter(StockFlow.trade_date == trade_date).all()
    for code, name, sector in rows:
        result.setdefault(code, {"name": name or "", "sector": sector or ""})
    return result


def latest_codes(db, trade_date: date, limit: Optional[int] = None) -> list[str]:
    """Build the eligible V2 universe from all symbols with a latest bar.

    ``limit`` is only a safety cap for callers that explicitly request one;
    it is never used as the ranking mechanism.  The production API scores the
    full eligible universe first and applies the display limit afterwards.
    """

    metadata = _metadata_for_date(db, trade_date)
    rows = db.query(
        StockDailyKline.ts_code,
        StockDailyKline.close,
        StockDailyKline.volume,
    ).filter(
        StockDailyKline.trade_date == trade_date,
        StockDailyKline.close > 0,
        StockDailyKline.volume > 0,
    ).distinct().all()

    codes = []
    for code, close, volume in rows:
        meta = metadata.get(code, {})
        if is_st_name(meta.get("name")):
            continue
        codes.append(code)
    codes.sort()
    return codes[:limit] if limit else codes


def load_history(
    db,
    codes: Iterable[str],
    trade_date: date,
    lookback: int = 120,
) -> dict[str, list[DailyBar]]:
    """Bulk-load bounded history instead of issuing one query per symbol."""

    code_list = list(dict.fromkeys(codes))
    if not code_list:
        return {}

    metadata = _metadata_for_date(db, trade_date)
    grouped: dict[str, list[DailyBar]] = {code: [] for code in code_list}
    rows = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code.in_(code_list),
        StockDailyKline.trade_date <= trade_date,
    ).order_by(
        StockDailyKline.ts_code,
        StockDailyKline.trade_date.desc(),
    ).all()

    seen: dict[str, int] = {}
    for row in rows:
        count = seen.get(row.ts_code, 0)
        if count >= lookback:
            continue
        meta = metadata.get(row.ts_code, {})
        grouped[row.ts_code].append(DailyBar(
            ts_code=row.ts_code,
            trade_date=row.trade_date,
            open=float(row.open or 0),
            high=float(row.high or 0),
            low=float(row.low or 0),
            close=float(row.close or 0),
            volume=float(row.volume or 0),
            amount=float(row.amount or 0),
            pct_chg=float(row.pct_chg or 0),
            sector=row.sector or meta.get("sector", ""),
            is_st=is_st_name(meta.get("name")),
        ))
        seen[row.ts_code] = count + 1

    for code in grouped:
        grouped[code].reverse()
    return grouped


def market_context(db, trade_date: date) -> MarketContext:
    """Build market breadth and limit structure from the whole daily universe."""

    rows = db.query(
        StockDailyKline.ts_code,
        StockDailyKline.close,
        StockDailyKline.pct_chg,
    ).filter(StockDailyKline.trade_date == trade_date).all()
    changes = [float(row[2]) for row in rows if row[2] is not None]
    breadth = sum(value > 0 for value in changes) / len(changes) if changes else 0.0
    normalized = [value * 100 if abs(value) <= 1 else value for value in changes]
    limit_up = sum(value >= 9.5 for value in normalized)
    limit_down = sum(value <= -9.5 for value in normalized)

    prior_dates = [row[0] for row in db.query(
        StockDailyKline.trade_date
    ).distinct().filter(
        StockDailyKline.trade_date <= trade_date
    ).order_by(StockDailyKline.trade_date.desc()).limit(21).all()]
    market_return = None
    if len(prior_dates) >= 21:
        prior_date = prior_dates[-1]
        latest_close = {code: float(close) for code, close, _ in rows if close}
        prior_rows = db.query(
            StockDailyKline.ts_code, StockDailyKline.close
        ).filter(
            StockDailyKline.trade_date == prior_date,
            StockDailyKline.ts_code.in_(list(latest_close)),
        ).all()
        returns = [
            latest_close[code] / float(close) - 1
            for code, close in prior_rows
            if close and latest_close.get(code)
        ]
        market_return = sum(returns) / len(returns) if returns else None

    return MarketContext(
        trade_date=trade_date,
        breadth=breadth,
        limit_up_count=limit_up,
        limit_down_count=limit_down,
        market_return_20d=market_return,
        market_data_available=bool(rows),
    )


def run_production(
    db,
    requested_date: Optional[date] = None,
    display_limit: Optional[int] = 50,
    codes: Optional[Iterable[str]] = None,
    lookback: int = 120,
) -> dict:
    """Run the V2 production engine and return ranked, explainable signals."""

    trade_date = resolve_trade_date(db, requested_date)
    if not trade_date:
        return {"trade_date": None, "universe_count": 0, "market": None, "signals": [], "values": []}

    selected = list(codes) if codes is not None else latest_codes(db, trade_date)
    history = load_history(db, selected, trade_date, lookback=lookback)
    history = {
        code: bars for code, bars in history.items()
        if bars and bars[-1].trade_date == trade_date
    }
    context = market_context(db, trade_date)
    pipeline = QuantPipeline()
    values, snapshots = pipeline.run_with_values(history, trade_date, context)
    metadata = _metadata_for_date(db, trade_date)

    ranked = []
    for rank, snapshot in enumerate(snapshots, start=1):
        item = asdict(snapshot)
        item.update(metadata.get(snapshot.ts_code, {}))
        item["rank"] = rank
        item["eligible"] = snapshot.resonance.eligible
        ranked.append(item)

    if display_limit is not None:
        ranked = ranked[:display_limit]
    return {
        "trade_date": trade_date,
        "universe_count": len(history),
        "market": context,
        "signals": ranked,
        "values": values,
        "snapshots": snapshots,
    }

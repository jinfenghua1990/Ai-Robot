"""Persist post-signal outcomes from already stored market daily bars.

This module deliberately has no market-data provider dependency.  It turns a
persisted post-market trigger into an auditable historical outcome only after
subsequent *stored* sessions exist, so the daily decision page never fetches
history or fills missing horizons with neutral values.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.session import get_db_session

from .identity import normalize_market
from .repository import MarketDailyBar, MarketScanRun, MarketSignalOutcome
from .universe import universe_code


HORIZONS = (1, 3, 5, 10, 20)


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def calculate_signal_outcome(signal_date: date, bars: Iterable[object]) -> dict | None:
    """Calculate mature returns and excursions for one saved signal.

    ``signal_date`` is the close at which the post-market signal became known.
    Horizon 1 is therefore the next completed trading session, never the same
    day.  A horizon with insufficient future bars remains ``None``.
    """
    ordered = sorted(
        (row for row in bars if getattr(row, "trade_date", None) is not None),
        key=lambda row: row.trade_date,
    )
    entry = next(
        (
            row for row in ordered
            if row.trade_date == signal_date and _number(getattr(row, "close", None)) not in (None, 0)
        ),
        None,
    )
    if entry is None:
        return None

    entry_price = _number(entry.close)
    if entry_price is None or entry_price <= 0:
        return None
    future = [row for row in ordered if row.trade_date > signal_date]
    result = {f"return_{horizon}d": None for horizon in HORIZONS}
    for horizon in HORIZONS:
        if len(future) < horizon:
            continue
        close = _number(getattr(future[horizon - 1], "close", None))
        if close is not None:
            result[f"return_{horizon}d"] = close / entry_price - 1

    window = future[:20]
    if not window:
        result.update({"max_profit": None, "max_loss": None, "max_drawdown": None})
        return result

    highs = [_number(getattr(row, "high", None)) for row in window]
    lows = [_number(getattr(row, "low", None)) for row in window]
    valid_highs = [value for value in highs if value is not None]
    valid_lows = [value for value in lows if value is not None]
    result["max_profit"] = max(valid_highs) / entry_price - 1 if valid_highs else None
    result["max_loss"] = min(valid_lows) / entry_price - 1 if valid_lows else None

    peak = entry_price
    drawdowns = []
    for row in window:
        high = _number(getattr(row, "high", None))
        low = _number(getattr(row, "low", None))
        if high is not None:
            peak = max(peak, high)
        if low is not None and peak > 0:
            drawdowns.append(low / peak - 1)
    result["max_drawdown"] = min(drawdowns) if drawdowns else None
    return result


def _triggered_signals(runs: Iterable[MarketScanRun]) -> list[dict]:
    """Read only production-triggered, non-vetoed rows from saved snapshots."""
    items = []
    for run in runs:
        payload = run.payload if isinstance(run.payload, dict) else {}
        for signal in payload.get("signals") or []:
            symbol = signal.get("symbol") or signal.get("ts_code")
            if not symbol or signal.get("trading_state") != "TRIGGERED" or signal.get("risk_veto"):
                continue
            items.append({
                "symbol": str(symbol).upper(),
                "signal_date": run.trade_date,
                "trading_state": "TRIGGERED",
            })
    return items


def refresh_market_signal_outcomes(
    market: str,
    requested_universe: str = "CORE",
    days: int = 60,
) -> dict:
    """Upsert post-market trigger outcomes using only daily bars in the DB.

    This function is called after a persisted daily snapshot, not from a read
    endpoint.  Reprocessing the recent window is intentional: newly matured
    3/5/10/20-session outcomes overwrite the prior incomplete row.
    """
    market = normalize_market(market)
    code = universe_code(market, requested_universe)
    days = max(1, int(days))
    with get_db_session() as db:
        latest_bar_date = db.query(func.max(MarketDailyBar.trade_date)).filter(
            MarketDailyBar.market == market,
            MarketDailyBar.quality_status == "VALID",
        ).scalar()
        if latest_bar_date is None:
            return {"market": market, "status": "NO_HISTORY", "scanned": 0, "upserted": 0}

        start_date = latest_bar_date - timedelta(days=days)
        runs = db.query(MarketScanRun).filter(
            MarketScanRun.market == market,
            MarketScanRun.universe_code == code,
            MarketScanRun.status == "SUCCESS",
            MarketScanRun.trade_date >= start_date,
        ).order_by(MarketScanRun.trade_date.desc(), MarketScanRun.completed_at.desc()).all()
        signals = _triggered_signals(runs)
        if not signals:
            return {
                "market": market, "status": "NO_TRIGGERED_SIGNALS", "from": start_date.isoformat(),
                "latest_bar_date": latest_bar_date.isoformat(), "scanned": 0, "upserted": 0,
            }

        symbols = sorted({item["symbol"] for item in signals})
        earliest_signal = min(item["signal_date"] for item in signals)
        bars = db.query(MarketDailyBar).filter(
            MarketDailyBar.market == market,
            MarketDailyBar.symbol.in_(symbols),
            MarketDailyBar.trade_date >= earliest_signal,
            MarketDailyBar.trade_date <= latest_bar_date,
            MarketDailyBar.quality_status == "VALID",
        ).order_by(MarketDailyBar.symbol, MarketDailyBar.trade_date).all()
        by_symbol = defaultdict(list)
        for bar in bars:
            by_symbol[bar.symbol].append(bar)

        rows = []
        for signal in signals:
            outcome = calculate_signal_outcome(signal["signal_date"], by_symbol.get(signal["symbol"], []))
            if outcome is None:
                continue
            rows.append({
                "market": market,
                "symbol": signal["symbol"],
                "signal_date": signal["signal_date"],
                "trading_state": signal["trading_state"],
                **outcome,
            })
        if rows:
            stmt = pg_insert(MarketSignalOutcome.__table__).values(rows)
            excluded = stmt.excluded
            db.execute(stmt.on_conflict_do_update(
                index_elements=["market", "symbol", "signal_date"],
                set_={
                    "trading_state": excluded.trading_state,
                    "return_1d": excluded.return_1d,
                    "return_3d": excluded.return_3d,
                    "return_5d": excluded.return_5d,
                    "return_10d": excluded.return_10d,
                    "return_20d": excluded.return_20d,
                    "max_profit": excluded.max_profit,
                    "max_loss": excluded.max_loss,
                    "max_drawdown": excluded.max_drawdown,
                },
            ))
            db.commit()
    return {
        "market": market,
        "status": "SUCCESS",
        "from": start_date.isoformat(),
        "latest_bar_date": latest_bar_date.isoformat(),
        "scanned": len(signals),
        "upserted": len(rows),
    }

"""Market-independent factor scoring and snapshot persistence."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.session import get_db_session
from quant_vnext.pipeline import QuantPipeline

from .history import MIN_CROSS_SECTION, MIN_HISTORY_DAYS, load_history, market_context
from .identity import normalize_market
from .repository import (
    MarketDataQualityRun,
    MarketFactorValue,
    MarketInstrument,
    MarketResonanceSnapshot,
    MarketScanRun,
)
from .universe import get_members, universe_code

logger = logging.getLogger(__name__)


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _snapshot_payload(
    snapshot,
    instrument: MarketInstrument | None,
    rank: int,
    history_rows: int,
    current_price: float | None = None,
) -> dict:
    payload = _json_value(asdict(snapshot))
    dimensions = payload.get("dimensions") or {}
    payload.update({
        "market": instrument.market if instrument else "",
        "symbol": snapshot.ts_code,
        "name": instrument.name if instrument else snapshot.ts_code,
        "exchange": instrument.exchange if instrument else "",
        "currency": instrument.currency if instrument else "",
        "sector": instrument.sector if instrument else "",
        "industry": instrument.industry if instrument else "",
        # The latest persisted daily bar is the source of truth for a
        # snapshot.  Instrument.price is only a discovery-cache fallback.
        "current_price": current_price if current_price is not None else (
            float(instrument.price) if instrument and instrument.price is not None else None
        ),
        "rank": rank,
        "history_coverage": history_rows,
        "data_quality": "VALID" if history_rows >= MIN_HISTORY_DAYS else "INSUFFICIENT_HISTORY",
        "dimension_scores": {
            key: {
                "name": value.get("name", key),
                "score": value.get("score"),
                "valid": bool(value.get("valid")),
                "factors": value.get("factors", []),
                "reason": value.get("reason", ""),
            }
            for key, value in dimensions.items()
        },
        "resonance_count": snapshot.resonance.count,
        "resonance_dimensions": list(snapshot.resonance.dimensions),
        "failed_dimensions": list(snapshot.resonance.failed_dimensions),
        "risk_veto": "risk" in snapshot.resonance.failed_dimensions,
        "updated_at": datetime.now().isoformat(),
    })
    return payload


def _instrument_map(market: str, symbols: list[str]) -> dict[str, MarketInstrument]:
    with get_db_session() as db:
        rows = db.query(MarketInstrument).filter(
            MarketInstrument.market == market,
            MarketInstrument.symbol.in_(symbols),
        ).all()
    return {row.symbol: row for row in rows}


def _persist_run(
    market: str,
    code: str,
    trade_date: date,
    started_at: datetime,
    payload: dict,
    values,
    snapshot_rows,
    pool_total: int,
    valid_count: int,
) -> None:
    now = datetime.now()
    with get_db_session() as db:
        factor_rows = []
        for value in values:
            factor_rows.append({
                "market": market,
                "symbol": value.ts_code,
                "trade_date": trade_date,
                "factor_name": value.name,
                "category": value.category,
                "raw_value": value.raw_value,
                "normalized": value.normalized,
                "valid": value.valid,
                "reason": value.reason,
            })
        if factor_rows:
            db.execute(pg_insert(MarketFactorValue.__table__).values(factor_rows).on_conflict_do_update(
                index_elements=["market", "symbol", "trade_date", "factor_name"],
                set_={
                    "category": pg_insert(MarketFactorValue.__table__).excluded.category,
                    "raw_value": pg_insert(MarketFactorValue.__table__).excluded.raw_value,
                    "normalized": pg_insert(MarketFactorValue.__table__).excluded.normalized,
                    "valid": pg_insert(MarketFactorValue.__table__).excluded.valid,
                    "reason": pg_insert(MarketFactorValue.__table__).excluded.reason,
                },
            ))

        resonance_rows = []
        for item in snapshot_rows or payload["signals"]:
            resonance_rows.append({
                "market": market,
                "symbol": item["symbol"],
                "trade_date": trade_date,
                "factor_score": item.get("factor_score"),
                "resonance_count": item.get("resonance_count", 0),
                "dimensions_json": json.dumps(item.get("resonance_dimensions", []), ensure_ascii=False),
                "failed_dimensions_json": json.dumps(item.get("failed_dimensions", []), ensure_ascii=False),
                "lifecycle": item.get("lifecycle"),
                "trading_state": item.get("trading_state"),
                "eligible": bool(item.get("resonance", {}).get("eligible")),
                "risk_veto": bool(item.get("risk_veto")),
                "reason": ";".join(item.get("reasons", [])),
                "payload": item,
            })
        if resonance_rows:
            db.execute(pg_insert(MarketResonanceSnapshot.__table__).values(resonance_rows).on_conflict_do_update(
                index_elements=["market", "symbol", "trade_date"],
                set_={
                    "factor_score": pg_insert(MarketResonanceSnapshot.__table__).excluded.factor_score,
                    "resonance_count": pg_insert(MarketResonanceSnapshot.__table__).excluded.resonance_count,
                    "dimensions_json": pg_insert(MarketResonanceSnapshot.__table__).excluded.dimensions_json,
                    "failed_dimensions_json": pg_insert(MarketResonanceSnapshot.__table__).excluded.failed_dimensions_json,
                    "lifecycle": pg_insert(MarketResonanceSnapshot.__table__).excluded.lifecycle,
                    "trading_state": pg_insert(MarketResonanceSnapshot.__table__).excluded.trading_state,
                    "eligible": pg_insert(MarketResonanceSnapshot.__table__).excluded.eligible,
                    "risk_veto": pg_insert(MarketResonanceSnapshot.__table__).excluded.risk_veto,
                    "reason": pg_insert(MarketResonanceSnapshot.__table__).excluded.reason,
                    "payload": pg_insert(MarketResonanceSnapshot.__table__).excluded.payload,
                },
            ))

        quality = payload["data_quality"]
        db.execute(pg_insert(MarketDataQualityRun.__table__).values(
            market=market,
            universe_code=code,
            trade_date=trade_date,
            expected_count=pool_total,
            valid_count=valid_count,
            missing_count=max(pool_total - valid_count, 0),
            min_history_days=payload["history"].get("min_rows", 0),
            max_history_days=payload["history"].get("max_rows", 0),
            status=quality["status"],
            details=quality,
        ))

        run = db.query(MarketScanRun).filter_by(
            market=market, universe_code=code, trade_date=trade_date,
        ).first()
        if run is None:
            run = MarketScanRun(market=market, universe_code=code, trade_date=trade_date, started_at=started_at)
            db.add(run)
        run.status = payload.get("status", "SUCCESS")
        run.pool_total = pool_total
        run.history_valid_count = valid_count
        run.candidate_count = payload["candidate_count"]
        run.triggered_count = payload["triggered_count"]
        run.data_trade_date = (
            date.fromisoformat(str(payload["trade_date"]))
            if payload.get("trade_date") else None
        )
        run.started_at = started_at
        run.completed_at = now
        run.error = None
        run.payload = payload
        db.commit()


def run_market_snapshot(
    market: str,
    requested_universe: str = "CORE",
    display_limit: int = 100,
    persist: bool = True,
    target_date=None,
) -> dict:
    """Run the same seven-dimension pipeline for a non-A-share market.

    This function reads only bars already stored in ``market_daily_bars``.
    Collection is deliberately separate so opening a page never fans out to
    hundreds of remote requests.
    """

    market = normalize_market(market)
    if market == "A":
        raise ValueError("market_quant is only for HK/US")
    code = universe_code(market, requested_universe)
    members = get_members(market, code)
    started_at = datetime.now()
    if not members:
        return {
            "market": market,
            "universe": code,
            "status": "NO_UNIVERSE",
            "pool_total": 0,
            "valid_count": 0,
            "signals": [],
            "data_quality": {"status": "NO_UNIVERSE"},
            "updated_at": datetime.now().isoformat(),
        }

    from .history import latest_trade_date, history_status

    target = target_date or latest_trade_date(market, members)
    status = history_status(market, members)
    if target is None:
        payload = {
            "market": market,
            "trade_date": None,
            "universe": code,
            "status": "NO_HISTORY",
            "pool_total": len(members),
            "valid_count": 0,
            "candidate_count": 0,
            "triggered_count": 0,
            "signals": [],
            "history": status,
            "data_quality": {"status": "NO_HISTORY", "message": "尚未完成真实历史日线入库"},
            "updated_at": datetime.now().isoformat(),
        }
        if persist:
            _persist_run(market, code, date.today(), started_at, payload, [], [], len(members), 0)
        return payload

    history = load_history(market, members, target)
    valid_history = {
        symbol: bars for symbol, bars in history.items()
        if len(bars) >= MIN_HISTORY_DAYS and bars[-1].trade_date == target
    }
    quality_status = "VALID" if valid_history else "INSUFFICIENT_HISTORY"
    quality = {
        "status": quality_status,
        "message": "真实历史日线覆盖足够" if valid_history else "没有标的同时满足最新交易日和最低历史长度",
        "market": market,
        "target_trade_date": target.isoformat(),
    }
    if not valid_history:
        payload = {
            "market": market,
            "trade_date": target.isoformat(),
            "universe": code,
            "status": "INSUFFICIENT_HISTORY",
            "pool_total": len(members),
            "valid_count": 0,
            "candidate_count": 0,
            "triggered_count": 0,
            "signals": [],
            "history": status,
            "data_quality": quality,
            "updated_at": datetime.now().isoformat(),
        }
        if persist:
            _persist_run(market, code, target, started_at, payload, [], [], len(members), 0)
        return payload

    if len(valid_history) < MIN_CROSS_SECTION:
        payload = {
            "market": market,
            "trade_date": target.isoformat(),
            "universe": code,
            "status": "INSUFFICIENT_DATA",
            "pool_total": len(members),
            "valid_count": len(valid_history),
            "candidate_count": 0,
            "triggered_count": 0,
            "signals": [],
            "history": status,
            "data_quality": {
                "status": "INSUFFICIENT_DATA",
                "message": f"有效标的仅 {len(valid_history)} 只，横截面至少需要 {MIN_CROSS_SECTION} 只；不生成中性默认分数",
                "market": market,
                "target_trade_date": target.isoformat(),
            },
            "updated_at": datetime.now().isoformat(),
        }
        if persist:
            _persist_run(market, code, target, started_at, payload, [], [], len(members), len(valid_history))
        return payload

    context = market_context(valid_history, target, market)
    pipeline = QuantPipeline()
    values, snapshots = pipeline.run_with_values(valid_history, target, context)
    instruments = _instrument_map(market, [item.ts_code for item in snapshots])
    snapshots_by_score = sorted(snapshots, key=lambda item: item.factor_score if item.factor_score is not None else -1, reverse=True)
    rows = [
        _snapshot_payload(
            item,
            instruments.get(item.ts_code),
            rank,
            len(valid_history[item.ts_code]),
            current_price=valid_history[item.ts_code][-1].close,
        )
        for rank, item in enumerate(snapshots_by_score, start=1)
    ]
    for row in rows:
        row["market"] = market
    triggered = sum(item.get("trading_state") == "TRIGGERED" for item in rows)
    candidates = sum(bool(item.get("resonance", {}).get("eligible")) for item in rows)
    payload = {
        "market": market,
        "trade_date": target.isoformat(),
        "universe": code,
        "status": "SUCCESS",
        "pool_total": len(members),
        "valid_count": len(valid_history),
        "candidate_count": candidates,
        "triggered_count": triggered,
        "signals": rows[: max(1, min(int(display_limit), 500))],
        "data_quality": quality,
        "history": status,
        "updated_at": datetime.now().isoformat(),
    }
    if persist:
        _persist_run(market, code, target, started_at, payload, values, rows, len(members), len(valid_history))
    return payload


def get_latest_snapshot(market: str, requested_universe: str = "CORE", limit: int = 100) -> dict:
    market = normalize_market(market)
    code = universe_code(market, requested_universe)
    with get_db_session() as db:
        run = db.query(MarketScanRun).filter_by(
            market=market,
            universe_code=code,
        ).order_by(MarketScanRun.trade_date.desc(), MarketScanRun.completed_at.desc()).first()
        if run is None:
            return {
                "market": market,
                "universe": code,
                "status": "NOT_READY",
                "signals": [],
                "updated_at": None,
            }
        payload = dict(run.payload or {})
    payload["signals"] = list(payload.get("signals") or [])[: max(1, min(int(limit), 500))]
    payload["source"] = "market_scan_snapshot"
    return payload


def get_history_status(market: str, requested_universe: str = "CORE") -> dict:
    from .history import history_status

    market = normalize_market(market)
    code = universe_code(market, requested_universe)
    members = get_members(market, code)
    return {"market": market, "universe": code, **history_status(market, members)}

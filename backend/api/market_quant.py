"""Unified HK/US universe, history, factor and snapshot APIs.

The old HK/US endpoints remain untouched for compatibility.  New strategy
pages can read this market-aware snapshot without triggering remote collection
when the browser opens.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from market_quant.history import backfill_market
from market_quant.identity import normalize_market
from market_quant.repository import MarketResearchRecord
from market_quant.service import get_history_status, get_latest_snapshot, run_market_snapshot
from market_quant.universe import get_members, list_universes, sync_market_universe, universe_code
from db.session import get_db_session

router = APIRouter(prefix="/api/market-quant", tags=["market-quant"])


def _str_param(value, default: str) -> str:
    return value if isinstance(value, str) else getattr(value, "default", default)


def _int_param(value, default: int) -> int:
    return value if isinstance(value, int) else getattr(value, "default", default)


def _market(value: str) -> str:
    try:
        normalized = normalize_market(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if normalized not in {"HK", "US"}:
        raise HTTPException(status_code=400, detail="统一港美股服务只接受 HK 或 US")
    return normalized


@router.get("/{market}/universes")
def universes(market: str):
    return jsonable_encoder({"market": _market(market), "universes": list_universes(_market(market))})


@router.post("/{market}/universes/refresh")
async def refresh_universes(market: str, remote: bool = Query(False)):
    normalized = _market(market)
    result = await asyncio.to_thread(sync_market_universe, normalized, remote)
    return jsonable_encoder(result)


@router.get("/{market}/history/status")
def history_status(market: str, universe: str = Query("CORE")):
    normalized = _market(market)
    return jsonable_encoder(get_history_status(normalized, _str_param(universe, "CORE")))


@router.post("/{market}/history/backfill")
async def history_backfill(
    market: str,
    universe: str = Query("CORE"),
    days: int = Query(1260, ge=120, le=1260),
    limit: int = Query(50, ge=1, le=300),
    remote: bool = Query(False),
):
    normalized = _market(market)
    universe = _str_param(universe, "CORE")
    days = _int_param(days, 1260)
    limit = _int_param(limit, 50)
    code = universe_code(normalized, universe)
    members = get_members(normalized, code)
    if not members:
        await asyncio.to_thread(sync_market_universe, normalized, remote)
        members = get_members(normalized, code)
    result = await asyncio.to_thread(backfill_market, normalized, members[:limit], days)
    return jsonable_encoder({"universe": code, **result})


@router.get("/{market}/snapshot")
def snapshot(market: str, universe: str = Query("CORE"), limit: int = Query(100, ge=1, le=500)):
    normalized = _market(market)
    universe = _str_param(universe, "CORE")
    limit = _int_param(limit, 100)
    return jsonable_encoder(get_latest_snapshot(normalized, universe, limit))


@router.post("/{market}/scan")
async def scan(
    market: str,
    universe: str = Query("CORE"),
    limit: int = Query(100, ge=1, le=500),
):
    normalized = _market(market)
    universe = _str_param(universe, "CORE")
    limit = _int_param(limit, 100)
    result = await asyncio.to_thread(run_market_snapshot, normalized, universe, limit, True)
    return jsonable_encoder(result)


@router.post("/{market}/research")
async def research(
    market: str,
    universe: str = Query("CORE"),
    limit: int = Query(50, ge=1, le=50),
):
    normalized = _market(market)
    universe = _str_param(universe, "CORE")
    limit = _int_param(limit, 50)
    from market_quant.research import run_market_research

    result = await run_market_research(normalized, universe, limit)
    return jsonable_encoder(result)


@router.get("/{market}/research/status")
def research_status(market: str, limit: int = Query(100, ge=1, le=500)):
    normalized = _market(market)
    with get_db_session() as db:
        rows = db.query(
            MarketResearchRecord.symbol,
            MarketResearchRecord.name,
            MarketResearchRecord.query_type,
            MarketResearchRecord.status,
            MarketResearchRecord.received_at,
            MarketResearchRecord.data_asof,
            MarketResearchRecord.error,
        ).filter(
            MarketResearchRecord.market == normalized,
        ).order_by(MarketResearchRecord.received_at.desc()).limit(limit).all()
    return jsonable_encoder({
        "market": normalized,
        "count": len(rows),
        "items": [
            {
                "symbol": row.symbol,
                "name": row.name,
                "query_type": row.query_type,
                "status": row.status,
                "received_at": row.received_at,
                "data_asof": row.data_asof,
                "error": row.error,
            }
            for row in rows
        ],
    })


@router.get("/{market}/health")
def health(market: str, universe: str = Query("CORE")):
    normalized = _market(market)
    universe = _str_param(universe, "CORE")
    code = universe_code(normalized, universe)
    members = get_members(normalized, code)
    latest = get_latest_snapshot(normalized, universe, 1)
    return jsonable_encoder({
        "market": normalized,
        "universe": code,
        "pool_count": len(members),
        "latest_trade_date": latest.get("trade_date"),
        "latest_status": latest.get("status"),
        "updated_at": latest.get("updated_at"),
        "checked_at": datetime.now().isoformat(),
    })

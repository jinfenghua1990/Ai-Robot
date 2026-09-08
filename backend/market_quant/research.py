"""Market-aware Miaoxiang research adapter.

Research is an explanation layer.  It never fills missing OHLCV values and
never changes a factor score or risk veto.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime

from db.session import get_db_session

from .identity import normalize_market
from .repository import MarketInstrument, MarketResearchRecord
from .service import get_latest_snapshot
from .universe import universe_code

logger = logging.getLogger(__name__)


def _json_text(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _extract_news(raw: dict) -> str:
    try:
        from mx_search import MXSearch
        return MXSearch.extract_content(raw)
    except Exception:
        return ""


def _extract_data(raw: dict) -> dict:
    try:
        from mx_data import MXData
        tables, conditions, total_rows, error = MXData.parse_result(raw)
        return {
            "tables": tables,
            "condition": " ".join(conditions),
            "total_rows": total_rows,
            "error": error,
        }
    except Exception as exc:
        return {"tables": [], "condition": "", "total_rows": 0, "error": str(exc)}


def _save_record(
    market: str,
    instrument: MarketInstrument,
    query_type: str,
    query: str,
    raw,
    normalized,
    status: str = "SUCCESS",
    error: str | None = None,
    data_asof: date | None = None,
) -> None:
    with get_db_session() as db:
        db.add(MarketResearchRecord(
            market=market,
            symbol=instrument.symbol,
            name=instrument.name,
            exchange=instrument.exchange,
            query_type=query_type,
            query=query,
            provider="miaoxiang",
            status=status,
            raw_response=_json_text(raw),
            normalized_result=normalized,
            data_asof=data_asof,
            received_at=datetime.now(),
            error=error,
        ))
        db.commit()


async def run_market_research(market: str, requested_universe: str = "CORE", limit: int = 50) -> dict:
    market = normalize_market(market)
    if market == "A":
        raise ValueError("market research adapter is only for HK/US")
    snapshot = get_latest_snapshot(market, requested_universe, limit=max(1, min(limit, 50)))
    signals = snapshot.get("signals") or []
    if not signals:
        return {
            "market": market,
            "universe": universe_code(market, requested_universe),
            "status": "NO_SNAPSHOT",
            "selected": 0,
            "success": 0,
            "failed": 0,
        }

    symbols = [str(item.get("symbol") or item.get("ts_code") or "") for item in signals]
    with get_db_session() as db:
        instruments = db.query(MarketInstrument).filter(
            MarketInstrument.market == market,
            MarketInstrument.symbol.in_(symbols),
        ).all()
    by_symbol = {item.symbol: item for item in instruments}
    selected = [item for item in signals if item.get("symbol") in by_symbol]
    if not selected:
        return {"market": market, "status": "NO_INSTRUMENTS", "selected": 0, "success": 0, "failed": 0}

    from api.mx_skills import _mx_post

    trade_date = None
    try:
        trade_date = date.fromisoformat(str(snapshot.get("trade_date")))
    except (TypeError, ValueError):
        pass
    success = 0
    failed = 0
    for item in selected:
        instrument = by_symbol[item["symbol"]]
        exchange_name = "NASDAQ/NYSE" if market == "US" else "HKEX"
        identity = f"{market} {exchange_name} {instrument.symbol} {instrument.name or ''}".strip()
        queries = [
            ("NEWS", f"{identity} 最新公告 近期新闻 行业催化 风险事件"),
            ("FUNDAMENTAL", f"{identity} 近一年营收 净利润 毛利率 估值 机构评级 目标价"),
        ]
        for query_type, query in queries:
            endpoint = "/api/claw/news-search" if query_type == "NEWS" else "/api/claw/query"
            payload = {"query": query} if query_type == "NEWS" else {"toolQuery": query}
            try:
                raw = await _mx_post(endpoint, payload, timeout=30)
                normalized = _extract_news(raw) if query_type == "NEWS" else _extract_data(raw)
                _save_record(market, instrument, query_type, query, raw, normalized, data_asof=trade_date)
                success += 1
            except Exception as exc:
                _save_record(
                    market, instrument, query_type, query, {}, {},
                    status="FAILED", error=str(exc)[:500], data_asof=trade_date,
                )
                failed += 1
            await asyncio.sleep(0.2)
    return {
        "market": market,
        "universe": universe_code(market, requested_universe),
        "status": "COMPLETED_WITH_ERRORS" if failed else "SUCCESS",
        "selected": len(selected),
        "success": success,
        "failed": failed,
        "snapshot_trade_date": snapshot.get("trade_date"),
        "updated_at": datetime.now().isoformat(),
    }


def run_market_research_sync(market: str, requested_universe: str = "CORE", limit: int = 50) -> dict:
    return asyncio.run(run_market_research(market, requested_universe, limit))

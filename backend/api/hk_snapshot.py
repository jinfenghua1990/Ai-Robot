"""港股盘后快照。

港股页面默认读取这里保存的最近一次成功结果，避免每个标签页打开时重复请求外部行情。
这里只保存真实行情与技术计算结果；缺失的数据由前端明确标记为估算或不可用。
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Column, Date, DateTime, Integer, JSON, String, Text, func

from db.connection import Base, engine
from db.session import get_db_session

from .global_market import DEFAULT_WATCHLIST, get_indices, _fetch_enhanced_for_stock
from .hk_strategy import RULES, _scan_item

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/hk-market", tags=["hk-market"])


class HKScanRun(Base):
    """港股盘后扫描运行记录与页面快照。"""

    __tablename__ = "hk_scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, unique=True, index=True)
    data_trade_date = Column(Date)
    status = Column(String(16), nullable=False, default="RUNNING")
    source = Column(String(32), default="postmarket")
    pool_source = Column(String(64), default="HK_WATCHLIST")
    pool_total = Column(Integer, default=0)
    scanned_count = Column(Integer, default=0)
    valid_count = Column(Integer, default=0)
    candidate_count = Column(Integer, default=0)
    signal_count = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    error = Column(Text)
    payload = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())


def ensure_schema() -> None:
    """启动时创建港股快照表，不改动既有表。"""

    HKScanRun.__table__.create(bind=engine, checkfirst=True)


def _run_meta(run: HKScanRun | None) -> dict | None:
    if not run:
        return None
    return {
        "status": run.status,
        "trade_date": run.trade_date.isoformat() if run.trade_date else None,
        "data_trade_date": run.data_trade_date.isoformat() if run.data_trade_date else None,
        "source": run.source,
        "pool_source": run.pool_source,
        "pool_total": run.pool_total or 0,
        "scanned_count": run.scanned_count or 0,
        "valid_count": run.valid_count or 0,
        "candidate_count": run.candidate_count or 0,
        "signal_count": run.signal_count or 0,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error": run.error,
    }


def _latest_completed(db):
    return db.query(HKScanRun).filter(
        HKScanRun.status == "COMPLETED"
    ).order_by(HKScanRun.trade_date.desc(), HKScanRun.completed_at.desc()).first()


def _empty_snapshot(error: str | None = None) -> dict:
    return {
        "market": "HK",
        "available": False,
        "indices": [],
        "items": [],
        "quotes": [],
        "stats": {"total": 0, "up": 0, "down": 0, "flat": 0},
        "strategy": {"items": [], "total": 0, "scanned": 0, "rules": [], "signal_type": "ALL"},
        "trade_date": None,
        "data_trade_date": None,
        "updated_at": None,
        "scan_run": None,
        "error": error,
    }


def _unified_to_legacy_snapshot(snapshot: dict) -> dict:
    """Keep the old HK page shape while sourcing results from seven dimensions."""
    rows = []
    for item in snapshot.get("signals") or []:
        rows.append({
            "code": item.get("symbol"),
            "name": item.get("name") or item.get("symbol"),
            "price": item.get("current_price"),
            "factor_score": item.get("factor_score"),
            "dimension_scores": item.get("dimension_scores") or item.get("dimensions") or {},
            "trading_state": item.get("trading_state"),
            "lifecycle": item.get("lifecycle"),
            "resonance_count": item.get("resonance_count", 0),
            "resonance_dimensions": item.get("resonance_dimensions", []),
            "failed_dimensions": item.get("failed_dimensions", []),
            "risk_veto": item.get("risk_veto", False),
            "data_quality": item.get("data_quality"),
            "history_coverage": item.get("history_coverage"),
            "exchange": item.get("exchange"),
            "currency": item.get("currency"),
            "signal": "B" if item.get("trading_state") in {"READY", "TRIGGERED"} else "—",
            "hits": [
                {"key": dimension, "name": dimension, "signal": "B"}
                for dimension in item.get("resonance_dimensions", [])
            ],
            "source": "market_scan_snapshot",
        })
    return {
        "market": "HK",
        "available": bool(rows),
        "indices": [],
        "items": rows,
        "quotes": rows,
        "stats": {"total": len(rows), "up": 0, "down": 0, "flat": len(rows)},
        "strategy": {
            "items": rows,
            "total": len(rows),
            "scanned": snapshot.get("valid_count", 0),
            "rules": ["market", "sector", "strength", "trend", "volume_price", "position", "risk"],
            "signal_type": "ALL",
            "source": "market_scan_snapshot",
        },
        "factor_snapshot": snapshot,
        "trade_date": snapshot.get("trade_date"),
        "data_trade_date": snapshot.get("trade_date"),
        "updated_at": snapshot.get("updated_at"),
        "scan_run": {
            "status": snapshot.get("status"),
            "trade_date": snapshot.get("trade_date"),
            "pool_total": snapshot.get("pool_total", 0),
            "valid_count": snapshot.get("valid_count", 0),
            "candidate_count": snapshot.get("candidate_count", 0),
        },
        "data_quality": snapshot.get("data_quality"),
    }


def _snapshot_from_run(run: HKScanRun | None) -> dict:
    if not run or not run.payload:
        return _empty_snapshot(run.error if run else None)
    payload = dict(run.payload)
    payload.update({
        "market": "HK",
        "available": True,
        "trade_date": run.trade_date.isoformat() if run.trade_date else None,
        "data_trade_date": run.data_trade_date.isoformat() if run.data_trade_date else None,
        "updated_at": run.completed_at.isoformat() if run.completed_at else None,
        "scan_run": _run_meta(run),
    })
    return payload


def get_latest_snapshot() -> dict:
    try:
        from market_quant.service import get_latest_snapshot as get_market_snapshot
        unified = get_market_snapshot("HK", "CORE", 100)
        if unified.get("status") not in {None, "NOT_READY"}:
            return _unified_to_legacy_snapshot(unified)
    except Exception as exc:
        logger.debug("[hk-market] unified snapshot read failed: %s", exc)
    with get_db_session() as db:
        return _snapshot_from_run(_latest_completed(db))


def run_hk_postmarket_scan(trade_date: str | None = None, force: bool = False) -> dict:
    """采集港股关注池并保存技术/策略快照；同一执行日默认幂等。"""

    if os.getenv("MARKET_QUANT_LEGACY_FALLBACK", "0").lower() not in {"1", "true", "yes"}:
        from market_quant.service import run_market_snapshot
        unified = run_market_snapshot("HK", "CORE", 100, True)
        if unified.get("status") != "SUCCESS":
            return _unified_to_legacy_snapshot(unified)
        return _unified_to_legacy_snapshot(unified)

    symbols = DEFAULT_WATCHLIST.get("HK", [])
    scan_day = date.fromisoformat(trade_date) if trade_date else datetime.now().date()
    started_at = datetime.now()

    with get_db_session() as db:
        run = db.query(HKScanRun).filter(HKScanRun.trade_date == scan_day).first()
        if run and run.status == "COMPLETED" and not force:
            return _snapshot_from_run(run)
        if not run:
            run = HKScanRun(trade_date=scan_day, started_at=started_at)
            db.add(run)
        run.status = "RUNNING"
        run.source = "postmarket"
        run.pool_source = "HK_WATCHLIST"
        run.pool_total = len(symbols)
        run.scanned_count = 0
        run.valid_count = 0
        run.candidate_count = 0
        run.signal_count = 0
        run.started_at = started_at
        run.completed_at = None
        run.error = None
        db.commit()

    results: list[dict | None] = [None] * len(symbols)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_fetch_enhanced_for_stock, "HK", stock): i
            for i, stock in enumerate(symbols)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                logger.warning("[hk-market] snapshot fetch failed %s: %s", symbols[index]["code"], exc)
                results[index] = {
                    "code": symbols[index]["code"],
                    "name": symbols[index]["name"],
                    "price": None,
                    "source": "error",
                    "error": str(exc),
                }

    items = [item for item in results if item and item.get("price") is not None]
    if not items:
        error = "没有获取到可用港股日线数据"
        with get_db_session() as db:
            run = db.query(HKScanRun).filter(HKScanRun.trade_date == scan_day).first()
            if run:
                run.status = "FAILED"
                run.error = error
                run.completed_at = datetime.now()
                db.commit()
        raise RuntimeError(error)

    items = [dict(item) for item in items]
    data_dates = [item.get("trade_date") for item in items if item.get("trade_date")]
    data_trade_date = max((date.fromisoformat(value) for value in data_dates), default=None)

    quotes = [{
        key: item.get(key)
        for key in ("code", "name", "price", "change_pct", "change_amount", "volume", "high", "low", "open", "prev_close", "trade_date")
    } for item in items]
    up = sum(1 for item in items if (item.get("change_pct") or 0) > 0)
    down = sum(1 for item in items if (item.get("change_pct") or 0) < 0)
    indices = get_indices("HK").get("indices", [])

    enabled_rules = [rule["key"] for rule in RULES]
    scanned = [_scan_item(item, enabled_rules, "ALL") for item in items]
    strategy_items = [item for item in scanned if item.get("hits")]
    signal_count = sum(1 for item in strategy_items if item.get("signal") in ("B", "S"))
    completed_at = datetime.now()
    payload = {
        "indices": indices,
        "items": items,
        "quotes": quotes,
        "stats": {"total": len(items), "up": up, "down": down, "flat": len(items) - up - down},
        "strategy": {
            "items": strategy_items,
            "total": len(strategy_items),
            "scanned": len(items),
            "rules": enabled_rules,
            "signal_type": "ALL",
            "updated_at": completed_at.isoformat(),
        },
        "data_quality": {
            "pool_total": len(symbols),
            "valid_count": len(items),
            "missing_count": len(symbols) - len(items),
            "sources": sorted({item.get("source") or "unknown" for item in items}),
            "data_trade_date": data_trade_date.isoformat() if data_trade_date else None,
        },
    }

    with get_db_session() as db:
        run = db.query(HKScanRun).filter(HKScanRun.trade_date == scan_day).first()
        if run:
            run.status = "COMPLETED"
            run.data_trade_date = data_trade_date
            run.scanned_count = len(symbols)
            run.valid_count = len(items)
            run.candidate_count = len(strategy_items)
            run.signal_count = signal_count
            run.completed_at = completed_at
            run.payload = payload
            db.commit()
            db.refresh(run)
            return _snapshot_from_run(run)
    return _empty_snapshot("港股快照保存失败")


@router.get("/snapshot")
def get_snapshot():
    """页面读取最近一次成功港股盘后快照。"""

    try:
        return jsonable_encoder(get_latest_snapshot())
    except Exception as exc:
        logger.exception("[hk-market] read snapshot failed")
        return jsonable_encoder(_empty_snapshot(str(exc)))


@router.post("/scan")
async def trigger_scan(force: bool = False):
    """手动触发港股快照；重任务放到线程池，不阻塞页面/API。"""

    try:
        result = await asyncio.to_thread(run_hk_postmarket_scan, force=force)
        return jsonable_encoder({"status": "ok", "result": result})
    except Exception as exc:
        return jsonable_encoder({"status": "error", "error": str(exc)})

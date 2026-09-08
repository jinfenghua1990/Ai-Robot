"""美股强 B/S 独立策略页 API。"""
from __future__ import annotations

import re
from sqlalchemy import func

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder

from db.session import get_db_session
from us_quant.bs_strategy import STRATEGY_META, evaluate_strong_bs
from us_quant.repository import USStockDaily, USFactorScore, USInstrument
from market_quant.repository import MarketInstrument

router = APIRouter(prefix="/api/us-bs-strategy", tags=["us-bs-strategy"])
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


@router.get("/metadata")
def metadata():
    return jsonable_encoder({"ok": True, "strategy": STRATEGY_META})


@router.get("/evaluate")
def evaluate(symbol: str = Query(..., description="美股代码，如 AAPL")):
    normalized = symbol.strip().upper()
    if not _SYMBOL_RE.match(normalized):
        return {"ok": False, "error": "股票代码格式不正确"}
    with get_db_session() as db:
        rows = (
            db.query(USStockDaily)
            .filter(
                USStockDaily.symbol == normalized,
                USStockDaily.open.isnot(None),
                USStockDaily.high.isnot(None),
                USStockDaily.low.isnot(None),
                USStockDaily.close.isnot(None),
            )
            .order_by(USStockDaily.trade_date.desc())
            .limit(500)
            .all()
        )
    rows.reverse()
    if len(rows) < 60:
        return {"ok": False, "error": f"{normalized} 数据不足60个交易日，无法计算强 B/S"}
    dates = [row.trade_date.isoformat() for row in rows]
    opens = [float(row.open) for row in rows]
    highs = [float(row.high) for row in rows]
    lows = [float(row.low) for row in rows]
    closes = [float(row.close) for row in rows]
    volumes = [float(row.volume or 0) for row in rows]
    result = evaluate_strong_bs(opens, highs, lows, closes, volumes, dates)
    return jsonable_encoder({
        "ok": True,
        "source": "database",
        "symbol": normalized,
        "trade_date": dates[-1],
        "strategy": STRATEGY_META,
        **result,
    })


@router.get("/daily")
def daily(limit: int = Query(300, ge=1, le=1000)):
    """读取最近交易日已落库的强 B/S 盘后选股结果。"""
    with get_db_session() as db:
        trade_date = db.query(func.max(USFactorScore.trade_date)).filter(
            USFactorScore.factor_name == STRATEGY_META["key"],
            USFactorScore.factor_value != 0,
        ).scalar()
        if trade_date is None:
            return {"ok": True, "source": "database", "trade_date": None, "items": []}

        factors = db.query(USFactorScore).filter(
            USFactorScore.factor_name == STRATEGY_META["key"],
            USFactorScore.trade_date == trade_date,
            USFactorScore.factor_value != 0,
        ).order_by(USFactorScore.factor_value.desc(), USFactorScore.symbol.asc()).limit(limit).all()
        symbols = [row.symbol for row in factors]
        bars = db.query(USStockDaily).filter(
            USStockDaily.symbol.in_(symbols),
            USStockDaily.trade_date <= trade_date,
        ).order_by(USStockDaily.symbol, USStockDaily.trade_date.asc()).all() if symbols else []
        instruments = db.query(USInstrument).filter(USInstrument.symbol.in_(symbols)).all() if symbols else []
        market_instruments = db.query(MarketInstrument).filter(
            MarketInstrument.market == "US",
            MarketInstrument.symbol.in_(symbols),
        ).all() if symbols else []

    grouped_bars = {}
    for row in bars:
        grouped_bars.setdefault(row.symbol, []).append(row)
    instrument_map = {row.symbol: row for row in instruments}
    market_instrument_map = {row.symbol: row for row in market_instruments}
    items = []
    for factor in factors:
        history = grouped_bars.get(factor.symbol, [])[-500:]
        bar = history[-1] if history else None
        instrument = instrument_map.get(factor.symbol)
        market_instrument = market_instrument_map.get(factor.symbol)
        value = float(factor.factor_value)
        checks = {}
        if len(history) >= 60:
            evaluated = evaluate_strong_bs(
                [float(row.open) for row in history], [float(row.high) for row in history],
                [float(row.low) for row in history], [float(row.close) for row in history],
                [float(row.volume or 0) for row in history],
            )
            checks = evaluated.get("checks") or {}
        items.append({
            "symbol": factor.symbol,
            "name": (instrument.name if instrument and instrument.name else market_instrument.name if market_instrument else factor.symbol),
            "sector": (instrument.sector if instrument and instrument.sector else instrument.industry if instrument and instrument.industry else market_instrument.sector if market_instrument and market_instrument.sector else market_instrument.industry if market_instrument and market_instrument.industry else None),
            "side": "B" if value > 0 else "S",
            "status": "持有中" if value > 0 else "今日退出",
            "factor_value": value,
            "checks": checks,
            "close": float(bar.close) if bar and bar.close is not None else None,
            "change_pct": float(bar.change_pct) if bar and bar.change_pct is not None else None,
            "volume": int(bar.volume) if bar and bar.volume is not None else None,
        })
    return jsonable_encoder({
        "ok": True, "source": "database", "trade_date": trade_date,
        "strategy": STRATEGY_META, "count": len(items), "items": items,
    })

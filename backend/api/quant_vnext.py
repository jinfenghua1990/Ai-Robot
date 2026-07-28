"""Read-only API for the greenfield quant_vnext engine."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func

from db.models import StockDailyKline, StockFlow
from db.session import get_db_session
from quant_vnext.contracts import DailyBar, MarketContext
from quant_vnext.pipeline import QuantPipeline
from quant_vnext.registry import default_registry
from quant_vnext.research import evaluate_forward_returns
from quant_vnext.backtest import walk_forward
from quant_vnext.repository import ensure_schema, save_factor_values, save_resonance
from quant_vnext.repository import save_factor_validation, save_signal_outcomes
from quant_vnext.validation import rolling_factor_validation
from db.connection import engine

router = APIRouter(prefix="/api/vnext", tags=["quant_vnext"])


def _load_history(db, codes: list[str], trade_date: date, lookback: int = 120) -> dict[str, list[DailyBar]]:
    history: dict[str, list[DailyBar]] = {}
    for code in codes:
        rows = (
            db.query(StockDailyKline)
            .filter(StockDailyKline.ts_code == code, StockDailyKline.trade_date <= trade_date)
            .order_by(StockDailyKline.trade_date.desc())
            .limit(lookback)
            .all()
        )
        rows.reverse()
        history[code] = [DailyBar(
            ts_code=row.ts_code,
            trade_date=row.trade_date,
            open=float(row.open or 0),
            high=float(row.high or 0),
            low=float(row.low or 0),
            close=float(row.close or 0),
            volume=float(row.volume or 0),
            amount=float(row.amount or 0),
            pct_chg=float(row.pct_chg or 0),
            sector=row.sector or "",
        ) for row in rows]
    return history


def _latest_codes(db, trade_date: date, limit: int) -> list[str]:
    rows = (
        db.query(StockDailyKline.ts_code)
        .filter(StockDailyKline.trade_date == trade_date)
        .order_by(StockDailyKline.ts_code)
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def _market_context(db, trade_date: date) -> MarketContext:
    rows = db.query(StockDailyKline.pct_chg).filter(StockDailyKline.trade_date == trade_date).all()
    changes = [float(row[0]) for row in rows if row[0] is not None]
    breadth = sum(value > 0 for value in changes) / len(changes) if changes else 0.0
    return MarketContext(trade_date=trade_date, breadth=breadth)


def _stock_meta(db, codes: list[str], trade_date: date) -> dict[str, dict[str, str]]:
    rows = db.query(StockFlow.ts_code, StockFlow.name, StockFlow.sector).filter(
        StockFlow.trade_date <= trade_date, StockFlow.ts_code.in_(codes)
    ).order_by(StockFlow.trade_date.desc()).all()
    result = {}
    for code, name, sector in rows:
        result.setdefault(code, {"name": name or "", "sector": sector or ""})
    return result


@router.get("/snapshots")
def get_snapshots(
    trade_date: Optional[date] = Query(None),
    codes: Optional[str] = Query(None, description="逗号分隔的 ts_code；不传则读取最新日期前 N 只"),
    limit: int = Query(50, ge=1, le=500),
):
    """运行新引擎并返回快照；只读，不写旧表。"""
    # 兼容 FastAPI 注入和本地直接调用验证。
    requested_date = trade_date if isinstance(trade_date, date) else None
    requested_codes = codes if isinstance(codes, str) else None
    requested_limit = limit if isinstance(limit, int) else 50
    with get_db_session() as db:
        target = requested_date or db.query(func.max(StockDailyKline.trade_date)).scalar()
        if not target:
            return {"trade_date": None, "snapshots": [], "message": "no daily kline"}
        selected = [item.strip() for item in requested_codes.split(",") if item.strip()] if requested_codes else _latest_codes(db, target, requested_limit)
        history = _load_history(db, selected, target)
        context = _market_context(db, target)
        snapshots = QuantPipeline().run(history, target, context)
        metadata = _stock_meta(db, selected, target)
        payload = []
        for snapshot in snapshots[:requested_limit]:
            item = jsonable_encoder(snapshot)
            item.update(metadata.get(snapshot.ts_code, {}))
            payload.append(item)
        return jsonable_encoder({
            "trade_date": target,
            "universe_count": len(history),
            "market": context,
            "snapshots": payload,
        })


@router.get("/registry")
def get_registry():
    """返回新系统当前注册的生产因子定义。"""
    registry = default_registry()
    return {"count": len(registry.production()), "factors": registry.export()}


@router.get("/health")
def get_health():
    """新系统健康状态，不依赖旧策略运行状态。"""
    registry = default_registry()
    return {
        "service": "quant_vnext",
        "status": "ok",
        "production_factor_count": len(registry.production()),
        "read_only": False,
        "legacy_strategy_dependency": False,
    }


@router.post("/snapshots/persist")
def persist_snapshots(
    trade_date: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """运行新引擎并写入新表；不触碰旧策略结果表。"""
    requested_date = trade_date if isinstance(trade_date, date) else None
    requested_limit = limit if isinstance(limit, int) else 100
    with get_db_session() as db:
        target = requested_date or db.query(func.max(StockDailyKline.trade_date)).scalar()
        if not target:
            return {"trade_date": None, "saved_factors": 0, "saved_snapshots": 0}
        codes = _latest_codes(db, target, requested_limit)
        history = _load_history(db, codes, target)
        context = _market_context(db, target)
        values, snapshots = QuantPipeline().run_with_values(history, target, context)
    with engine.begin() as connection:
        ensure_schema(connection)
        save_factor_values(connection, values)
        for snapshot in snapshots:
            save_resonance(connection, snapshot)
    return {"trade_date": target, "saved_factors": len(values), "saved_snapshots": len(snapshots)}


@router.get("/research")
def research(
    trade_date: Optional[date] = Query(None),
    days: int = Query(20, ge=1, le=120),
    limit: int = Query(20, ge=1, le=100),
):
    """使用真实日 K 线运行严格日期截断的样本外收益统计。"""
    requested_date = trade_date if isinstance(trade_date, date) else None
    requested_days = days if isinstance(days, int) else 20
    requested_limit = limit if isinstance(limit, int) else 20
    with get_db_session() as db:
        target = requested_date or db.query(func.max(StockDailyKline.trade_date)).scalar()
        if not target:
            return {"trade_date": None, "sample_count": 0, "horizons": {}}
        all_dates = [row[0] for row in db.query(StockDailyKline.trade_date).distinct().order_by(StockDailyKline.trade_date.desc()).limit(requested_days + 80).all()]
        all_dates = sorted(all_dates)
        codes = _latest_codes(db, target, requested_limit)
        history = _load_history(db, codes, target, lookback=max(120, requested_days + 80))
        result = walk_forward(history, all_dates, horizons=(1, 3, 5, 10, 20))
        return jsonable_encoder({"trade_date": target, "codes": codes, **result})


@router.post("/research/factors/persist")
def persist_factor_validation(
    days: int = Query(20, ge=5, le=120),
    limit: int = Query(50, ge=3, le=100),
    horizon: int = Query(5, ge=1, le=20),
):
    """计算并保存滚动因子 IC / Rank IC；仅写入 quant_vnext 新表。"""
    requested_days = days if isinstance(days, int) else 20
    requested_limit = limit if isinstance(limit, int) else 50
    requested_horizon = horizon if isinstance(horizon, int) else 5
    with get_db_session() as db:
        target = db.query(func.max(StockDailyKline.trade_date)).scalar()
        if not target:
            return {"trade_date": None, "validated": 0}
        dates = [row[0] for row in db.query(StockDailyKline.trade_date).distinct().order_by(StockDailyKline.trade_date.desc()).limit(requested_days + 80).all()]
        codes = _latest_codes(db, target, requested_limit)
        history = _load_history(db, codes, target, lookback=max(120, requested_days + requested_horizon + 80))
    pipeline = QuantPipeline()
    rows = rolling_factor_validation(pipeline.factors, history, dates, requested_horizon)
    with engine.begin() as connection:
        ensure_schema(connection)
        saved = save_factor_validation(connection, rows)
    return {"trade_date": target, "horizon": requested_horizon, "validated": saved, "rows": rows}


@router.post("/research/outcomes/persist")
def persist_signal_outcomes(
    days: int = Query(20, ge=5, le=120),
    limit: int = Query(50, ge=3, le=100),
):
    """保存严格日期截断的信号后续收益到 signal_outcome。"""
    requested_days = days if isinstance(days, int) else 20
    requested_limit = limit if isinstance(limit, int) else 50
    with get_db_session() as db:
        target = db.query(func.max(StockDailyKline.trade_date)).scalar()
        if not target:
            return {"trade_date": None, "saved": 0}
        dates = [row[0] for row in db.query(StockDailyKline.trade_date).distinct().order_by(StockDailyKline.trade_date.desc()).limit(requested_days + 80).all()]
        codes = _latest_codes(db, target, requested_limit)
        history = _load_history(db, codes, target, lookback=max(120, requested_days + 80))
    result = walk_forward(history, dates, horizons=(1, 3, 5, 10, 20), include_records=True)
    with engine.begin() as connection:
        ensure_schema(connection)
        saved = save_signal_outcomes(connection, result["records"])
    return {"trade_date": target, "saved": saved, "sample_count": result["sample_count"]}

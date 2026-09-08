"""Read-only API for the greenfield quant_vnext engine."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_

from db.models import StockDailyKline, StockFlow
from db.session import get_db_session
from quant_vnext.contracts import DailyBar, MarketContext
from quant_vnext.alpha158_catalog import alpha158_research_registry
from quant_vnext.alpha158_engine import Alpha158ResearchEngine
from quant_vnext.market_regime import MarketRegimeEngine
from quant_vnext.scoring import GROUP_WEIGHTS
from quant_vnext.pipeline import QuantPipeline
from quant_vnext.registry import default_registry
from quant_vnext.research import evaluate_forward_returns
from quant_vnext.backtest import walk_forward
from quant_vnext.repository import ensure_schema, save_factor_values, save_resonance
from quant_vnext.repository import save_factor_validation, save_signal_outcomes
from quant_vnext.validation import rolling_factor_validation, factor_correlation_from_history
from db.connection import engine
from quant_vnext.production import (
    latest_codes as production_latest_codes,
    load_history as production_load_history,
    market_context as production_market_context,
    resolve_trade_date as production_resolve_trade_date,
    run_production,
)

router = APIRouter(prefix="/api/vnext", tags=["quant_vnext"])


def _load_history(db, codes: list[str], trade_date: date, lookback: int = 120) -> dict[str, list[DailyBar]]:
    return production_load_history(db, codes, trade_date, lookback=lookback)


def _latest_codes(db, trade_date: date, limit: int) -> list[str]:
    return production_latest_codes(db, trade_date, limit=limit)


def _market_context(db, trade_date: date) -> MarketContext:
    return production_market_context(db, trade_date)


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
        selected = [item.strip() for item in requested_codes.split(",") if item.strip()] if requested_codes else None
        result = run_production(
            db,
            requested_date=requested_date,
            display_limit=requested_limit,
            codes=selected,
        )
        if not result.get("trade_date"):
            return {"trade_date": None, "snapshots": [], "message": "no daily kline"}
        return jsonable_encoder({
            "trade_date": result["trade_date"],
            "universe_count": result["universe_count"],
            "market": result["market"],
            "snapshots": result["signals"],
        })


@router.get("/registry")
def get_registry():
    """返回新系统当前注册的生产因子定义。"""
    registry = default_registry()
    return {
        "count": len(registry.production()),
        "factor_groups": ["market", "sector", "strength", "trend", "volume_price", "position", "risk"],
        "base_weights": GROUP_WEIGHTS,
        "factors": registry.export(),
    }


@router.get("/research/alpha158")
def get_alpha158_research_catalog():
    """返回 Qlib Alpha158 的本地研究候选，不参与生产评分。"""
    return {
        "count": len(alpha158_research_registry()),
        "production_enabled": False,
        "factors": [item.__dict__ for item in alpha158_research_registry()],
    }


@router.get("/research/factors/validate")
def validate_production_factors(
    days: int = Query(20, ge=5, le=120),
    limit: int = Query(200, ge=30, le=1000),
    horizon: int = Query(5, ge=1, le=20),
):
    """Validate production factors with date-bounded real daily bars.

    The endpoint is research-only: its result never changes production
    weights.  ``limit`` controls research cost and is reported explicitly so
    a small sample cannot be mistaken for a full-market validation.
    """
    requested_days = days if isinstance(days, int) else 20
    requested_limit = limit if isinstance(limit, int) else 200
    requested_horizon = horizon if isinstance(horizon, int) else 5
    with get_db_session() as db:
        target = production_resolve_trade_date(db)
        if not target:
            return {"trade_date": None, "sample_count": 0, "rows": [], "correlation": {}}
        dates = [
            row[0]
            for row in db.query(StockDailyKline.trade_date)
            .distinct()
            .filter(StockDailyKline.trade_date <= target)
            .order_by(StockDailyKline.trade_date.desc())
            .limit(requested_days + 80)
            .all()
        ]
        dates = sorted(dates)
        codes = production_latest_codes(db, target, requested_limit)
        history = production_load_history(
            db, codes, target,
            lookback=max(120, requested_days + requested_horizon + 80),
        )
    pipeline = QuantPipeline()
    rows = rolling_factor_validation(pipeline.factors, history, dates, requested_horizon)
    return jsonable_encoder({
        "trade_date": target,
        "horizon": requested_horizon,
        "research_days": requested_days,
        "research_universe_count": len(history),
        "production_enabled": True,
        "sample_count": sum(row["sample_count"] for row in rows),
        "rows": rows,
        "correlation": factor_correlation_from_history(pipeline.factors, history, dates),
    })


@router.get("/research/alpha158/validate")
def validate_alpha158(
    days: int = Query(20, ge=5, le=120),
    limit: int = Query(50, ge=3, le=200),
    horizon: int = Query(5, ge=1, le=20),
):
    """用真实历史 K 线验证 Alpha158 候选；不进入生产评分。"""
    requested_days = days if isinstance(days, int) else 20
    requested_limit = limit if isinstance(limit, int) else 50
    requested_horizon = horizon if isinstance(horizon, int) else 5
    with get_db_session() as db:
        target = db.query(func.max(StockDailyKline.trade_date)).scalar()
        if not target:
            return {"trade_date": None, "sample_count": 0, "rows": []}
        dates = [row[0] for row in db.query(StockDailyKline.trade_date).distinct().order_by(StockDailyKline.trade_date.desc()).limit(requested_days + 80).all()]
        codes = _latest_codes(db, target, requested_limit)
        history = _load_history(db, codes, target, lookback=max(120, requested_days + requested_horizon + 80))
    rows = rolling_factor_validation(Alpha158ResearchEngine(), history, dates, requested_horizon)
    return jsonable_encoder({
        "trade_date": target,
        "horizon": requested_horizon,
        "production_enabled": False,
        "sample_count": sum(row["sample_count"] for row in rows),
        "rows": rows,
    })


@router.get("/health")
def get_health():
    """新系统健康状态，不依赖旧策略运行状态。"""
    registry = default_registry()
    return {
        "service": "quant_vnext",
        "status": "ok",
        "production_factor_count": len(registry.production()),
        "factor_groups": ["market", "sector", "strength", "trend", "volume_price", "position", "risk"],
        "market_regime_engine": MarketRegimeEngine.__name__,
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
        result = run_production(
            db,
            requested_date=requested_date,
            display_limit=None,
        )
        target = result.get("trade_date")
        if not target:
            return {"trade_date": None, "saved_factors": 0, "saved_snapshots": 0}
        values = result["values"]
        snapshots = result["snapshots"]
    with engine.begin() as connection:
        ensure_schema(connection)
        save_factor_values(connection, values)
        for snapshot in snapshots:
            save_resonance(connection, snapshot)
    return {"trade_date": target, "universe_count": len(snapshots), "saved_factors": len(values), "saved_snapshots": len(snapshots)}


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

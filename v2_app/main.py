from __future__ import annotations

import json
import importlib.util
import logging
import subprocess
from urllib.request import urlopen
import os
from datetime import date, datetime
from statistics import mean
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from .account import MiaoxiangClient, cached_account
from .config import V2_TRADING_ENABLED
from .engine import serialize_market, serialize_signal
from .factors import DIMENSION_LABELS, FACTOR_BY_NAME
from .repository import (
    active_factor_names,
    factor_registry,
    get_config,
    latest_factor_reviews,
    list_audits,
    save_audit,
    ensure_schema,
    update_config,
)
from .service import V2Service
from .db import engine


# Keep imports readable on Python versions where conditional import syntax is
# not supported by static tooling: action key is resolved from the environment.
ACTION_KEY = os.getenv("V2_ACTION_KEY", "")

app = FastAPI(title="Ai-Robot V2 右侧多因子决策系统", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
)

service = V2Service()
STATIC = Path(__file__).resolve().parent / "static"
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
logger = logging.getLogger(__name__)


def _sync_legacy_watchlist(action: str, code: str, name: str = "", note: str = "", group: str = "默认") -> None:
    """同步旧系统的 watchlist.json，避免 9000 与 9001 各自维护一份自选。"""
    path = Path(__file__).resolve().parents[1] / "backend" / "api" / "watchlist" / "watchlist_local.py"
    try:
        spec = importlib.util.spec_from_file_location("airobot_legacy_watchlist_local", path)
        if not spec or not spec.loader:
            raise RuntimeError(f"无法加载旧自选同步模块: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if action == "add":
            module.add_stock(code, name, note, group)
        elif action == "remove":
            module.remove_stock(code)
    except Exception as exc:
        # DB 已经完成主操作；同步失败必须可见，但不能让 V2 页面整体不可用。
        logger.warning("旧自选 JSON 同步失败 (%s %s): %s", action, code, exc)


class ConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    account_source: Optional[str] = Field(default=None, pattern="^(displayed|dedicated)$")
    max_positions: Optional[int] = Field(default=None, ge=1, le=100)
    max_buy_count: Optional[int] = Field(default=None, ge=1, le=50)
    single_position_pct: Optional[float] = Field(default=None, gt=0, le=100)
    stop_loss_pct: Optional[float] = Field(default=None, ge=-50, lt=0)
    take_profit_pct: Optional[float] = Field(default=None, gt=0, le=200)


class TradeRequest(BaseModel):
    action: str = Field(pattern="^(buy|sell)$")
    code: str = Field(min_length=6, max_length=20)
    quantity: int = Field(gt=0)
    confirm: bool = False
    price: Optional[float] = Field(default=None, gt=0)


class WatchlistRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)
    name: str = ""
    note: str = ""
    group: str = "默认"


@app.on_event("startup")
def startup() -> None:
    ensure_schema()


@app.get("/api/v2/health")
def health():
    try:
        target = service.data.resolve_date()
        # 健康页是首屏信息，不能为了显示股票池数量而重新扫描 5,000+
        # 条元数据。优先读取当天已验证的信号快照；没有快照时显示 0，
        # 并由显式“刷新计算”完成全市场计算。
        snapshot_signals = service._persisted_signals(target) if target else []
        active_names, score_mode, status_summary = active_factor_names()
        return {
            "service": "v2_app",
            "status": "ok",
            "trade_date": target,
            "eligible_universe": len(snapshot_signals),
            "factor_catalog_count": len(FACTOR_BY_NAME),
            "production_factor_count": status_summary.get("production", 0),
            "observation_factor_count": status_summary.get("observation", 0),
            "active_factor_count": len(active_names),
            "factor_status_summary": status_summary,
            "score_mode": score_mode,
            "production_ready": score_mode == "PRODUCTION",
            "dimensions": list(DIMENSION_LABELS),
            "trading_enabled": bool(get_config().get("enabled")),
            "external_order_default": False,
            "legacy_strategy_dependency": False,
            "database_source": "existing Ai-Robot PostgreSQL tables",
        }
    except Exception as exc:
        return {"service": "v2_app", "status": "degraded", "error": str(exc)}


def _legacy_json(path: str, timeout: float = 3.0) -> dict:
    """读取 9000 的采集状态；不在 9001 重启或复制旧采集器。"""
    try:
        with urlopen(f"http://127.0.0.1:9000{path}", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"available": False, "error": str(exc)[:160]}


def _legacy_path(request: Request, path: str) -> str:
    query = request.url.query
    return f"{path}?{query}" if query else path


# 9000 原生 React 前端的只读兼容层。页面代码保持原样，数据仍由 9000
# 采集/质量服务提供；9001 不重复采集，也不直接改动旧质量库。
@app.get("/api/services/status")
def migrated_services_status():
    return _legacy_json("/api/services/status")


@app.get("/api/quality/overview")
def migrated_quality_overview():
    return _legacy_json("/api/quality/overview")


@app.get("/api/quality/sources")
def migrated_quality_sources(request: Request):
    return _legacy_json(_legacy_path(request, "/api/quality/sources"))


@app.get("/api/quality/data-sources")
def migrated_quality_data_sources(request: Request):
    return _legacy_json(_legacy_path(request, "/api/quality/data-sources"))


@app.get("/api/quality/anomalies")
def migrated_quality_anomalies(request: Request):
    return _legacy_json(_legacy_path(request, "/api/quality/anomalies"))


@app.get("/api/quality/review-queue")
def migrated_quality_review_queue(request: Request):
    return _legacy_json(_legacy_path(request, "/api/quality/review-queue"))


@app.get("/api/quality/logs")
def migrated_quality_logs(request: Request):
    return _legacy_json(_legacy_path(request, "/api/quality/logs"))


@app.get("/api/quality/error-stats")
def migrated_quality_error_stats(request: Request):
    return _legacy_json(_legacy_path(request, "/api/quality/error-stats"))


@app.get("/api/quality/data-freshness")
def migrated_quality_data_freshness(request: Request):
    return _legacy_json(_legacy_path(request, "/api/quality/data-freshness"))


@app.get("/api/v2/collection/status")
def collection_status():
    """统一展示旧采集器状态，明确唯一执行者仍是 9000 scheduler。"""
    jobs = _legacy_json("/api/scheduler/jobs")
    freshness = _legacy_json("/api/scheduler/freshness")
    research = _legacy_json("/api/scheduler/research-status")
    return {
        "collector_owner": "9000 legacy scheduler",
        "collector_mode": "single-writer",
        "scheduler": jobs,
        "freshness": freshness,
        "research": research,
        "v2_read_only": True,
        "message": "9001 只读取采集状态和结果，避免重复采集、重复写库。",
    }


@app.get("/api/v2/system/quality")
def system_quality():
    """把旧系统中仍有价值的数据质量信息以精简格式接入 V2。"""
    sources = _legacy_json("/api/quality/sources")
    anomalies = _legacy_json("/api/quality/anomalies")
    review = _legacy_json("/api/quality/review-queue")
    source_rows = []
    for item in (sources.get("sources") or []):
        source_rows.append({
            "source": item.get("source"),
            "score": item.get("avg_score"),
            "outlier_rate": item.get("outlier_rate"),
            "total_count": item.get("total_count"),
        })
    return {
        "trade_date": anomalies.get("trade_date"),
        "source_count": len(source_rows),
        "sources": source_rows,
        "anomaly_count": anomalies.get("count", len(anomalies.get("anomalies") or [])),
        "anomalies": (anomalies.get("anomalies") or [])[:10],
        "pending_review_count": review.get("count", len(review.get("items") or [])),
        "reviews": (review.get("items") or [])[:10],
        "source": "9000 quality APIs",
    }


@app.get("/api/v2/system/quality-dashboard")
def quality_dashboard():
    """迁移 9000 质量页的只读数据面板；9001 不在此端点修改旧库。"""
    overview = _legacy_json("/api/quality/overview")
    sources = _legacy_json("/api/quality/sources?days=7")
    anomalies = _legacy_json("/api/quality/anomalies?limit=30")
    reviews = _legacy_json("/api/quality/review-queue?status=pending")
    freshness = _legacy_json("/api/quality/data-freshness")
    services = _legacy_json("/api/services/status")
    return {
        "overview": overview,
        "sources": sources.get("sources") or [],
        "anomalies": anomalies.get("anomalies") or [],
        "review_queue": reviews,
        "freshness": freshness,
        "services": services.get("services") or [],
        "source": "9000 quality APIs (read-only)",
    }


@app.post("/api/v2/system/check")
def system_check():
    """执行只读系统体检，供系统状态页的一键检查使用。"""
    checks = []

    def add(name: str, status: str, detail: str, value=None):
        item = {"name": name, "status": status, "detail": detail}
        if value is not None:
            item["value"] = value
        checks.append(item)

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        add("数据库连接", "ok", "PostgreSQL 连接正常")
    except Exception as exc:
        add("数据库连接", "error", str(exc)[:180])

    v2_health = globals()["health"]()
    add("V2 服务", "ok" if v2_health.get("status") == "ok" else "error", v2_health.get("status", "未知"), v2_health)
    legacy_health = _legacy_json("/api/health")
    add("9000 主服务", "ok" if legacy_health.get("status") == "ok" else "warning", legacy_health.get("status", legacy_health.get("error", "未知")), legacy_health)

    freshness = _legacy_json("/api/scheduler/freshness")
    stale = freshness.get("stale_count")
    if stale is None:
        add("数据新鲜度", "warning", freshness.get("error", "无法读取采集新鲜度"), freshness)
    else:
        add("数据新鲜度", "ok" if stale == 0 else "warning", f"滞后数据表 {stale} 张", freshness)

    jobs = _legacy_json("/api/scheduler/jobs")
    running = jobs.get("scheduler_running")
    add("采集调度器", "ok" if running is True else "warning", f"任务 {jobs.get('job_count', '—')} 个，运行状态 {running}", jobs)

    def run_check(name: str, command: list[str], env=None, timeout: int = 30):
        try:
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=timeout)
            detail = (result.stdout or result.stderr or "通过").strip().splitlines()[-1][:240]
            add(name, "ok" if result.returncode == 0 else "error", detail or "通过")
        except subprocess.TimeoutExpired:
            add(name, "warning", f"检查超过 {timeout} 秒，已停止")
        except Exception as exc:
            add(name, "error", str(exc)[:180])

    test_env = os.environ.copy()
    test_env["PYTHONPATH"] = "backend"
    run_check("后端测试", ["python3", "-m", "pytest", "-q", "backend/tests", "backend/quant_vnext/tests"], test_env, 30)
    run_check("V2 测试", ["python3", "-m", "pytest", "-q", "v2_app/tests"], os.environ.copy(), 30)
    run_check("Python 编译", ["python3", "-m", "compileall", "-q", "backend/collectors", "backend/api", "backend/services", "v2_app"], os.environ.copy(), 20)
    run_check("JavaScript 检查", ["/opt/homebrew/bin/node", "--check", "v2_app/static/app.js"], os.environ.copy(), 20)

    errors = sum(item["status"] == "error" for item in checks)
    warnings = sum(item["status"] == "warning" for item in checks)
    overall = "error" if errors else "warning" if warnings else "ok"
    return {"status": overall, "checked_at": datetime.now().isoformat(), "summary": {"total": len(checks), "errors": errors, "warnings": warnings}, "checks": checks}


@app.get("/api/v2/dashboard")
def dashboard():
    return service.dashboard()


@app.get("/api/v2/candidates")
def candidates(
    trade_date: Optional[date] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    state: Optional[str] = Query(default=None),
):
    return service.candidates(trade_date, limit, state)


@app.get("/api/v2/stock/{code}")
def stock(code: str, trade_date: Optional[date] = Query(default=None)):
    item = service.stock(code, trade_date)
    if not item:
        raise HTTPException(status_code=404, detail="新 V2 股票池中没有这只股票")
    return item


@app.get("/api/v2/stock/{code}/history")
def stock_history(code: str, limit: int = Query(default=60, ge=10, le=240)):
    """读取真实日线，供个股分析页核对价格和交易位置。"""
    raw = code.strip().upper()
    plain = raw.split(".", 1)[0]
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ts_code, trade_date, open, high, low, close, volume, amount, pct_chg
            FROM stock_daily_kline
            WHERE ts_code = :code OR ts_code LIKE :prefix
            ORDER BY trade_date DESC LIMIT :limit
        """), {"code": raw, "prefix": f"{plain}.%", "limit": limit}).mappings().all()
    rows = list(reversed(rows))
    return {"code": plain, "count": len(rows), "bars": [
        {key: (value.isoformat() if hasattr(value, "isoformat") else float(value) if hasattr(value, "__float__") and key not in ("ts_code",) else value)
         for key, value in dict(row).items()}
        for row in rows
    ], "source": "stock_daily_kline"}


@app.get("/api/v2/stock/{code}/research")
def stock_research(code: str):
    """统一个股研究数据：真实行情/资金与 V2 因子结论分层返回。"""
    raw = code.strip().upper()
    plain = raw.split(".", 1)[0]
    signal = service.stock(raw)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ts_code, trade_date, open, high, low, close, volume, amount, pct_chg
            FROM stock_daily_kline
            WHERE ts_code = :code OR ts_code LIKE :prefix
            ORDER BY trade_date DESC LIMIT 80
        """), {"code": raw, "prefix": f"{plain}.%"}).mappings().all()
        flow = conn.execute(text("""
            SELECT name, sector, price, price_chg, main_force_inflow, trade_date
            FROM stock_flow
            WHERE ts_code = :code OR ts_code LIKE :prefix
            ORDER BY trade_date DESC, id DESC LIMIT 1
        """), {"code": raw, "prefix": f"{plain}.%"}).mappings().first()
    bars = [dict(row) for row in reversed(rows)]
    closes = [float(row["close"] or 0) for row in bars]
    volumes = [float(row["volume"] or 0) for row in bars]
    highs = [float(row["high"] or 0) for row in bars]
    lows = [float(row["low"] or 0) for row in bars]
    latest = bars[-1] if bars else {}

    def change(days: int):
        if len(closes) <= days or closes[-days - 1] <= 0:
            return None
        return (closes[-1] / closes[-days - 1] - 1) * 100

    def ma(days: int):
        return round(mean(closes[-days:]), 3) if len(closes) >= days else None

    peak = max(highs) if highs else 0
    trough = min(lows[-20:]) if lows else 0
    drawdowns = [close / max(closes[:i + 1]) - 1 for i, close in enumerate(closes) if max(closes[:i + 1]) > 0]
    profile = {
        "code": (signal or {}).get("code") or (bars[-1].get("ts_code") if bars else raw),
        "name": (signal or {}).get("name") or (dict(flow or {}).get("name") if flow else plain),
        "sector": (signal or {}).get("sector") or (dict(flow or {}).get("sector") if flow else "未分类"),
        "trade_date": str(latest.get("trade_date") or ""),
        "price": float(latest.get("close") or 0) if latest else None,
        "price_change": float(latest.get("pct_chg") or 0) if latest else None,
        "returns": {"d1": change(1), "d5": change(5), "d20": change(20), "d60": change(60)},
        "trend": {"ma5": ma(5), "ma10": ma(10), "ma20": ma(20), "ma60": ma(60), "recent_high": peak or None, "distance_to_high": ((closes[-1] / peak - 1) * 100) if peak and closes else None, "support_20d": trough or None},
        "volume": {"today": volumes[-1] if volumes else None, "avg5": mean(volumes[-5:]) if len(volumes) >= 5 else None, "avg20": mean(volumes[-20:]) if len(volumes) >= 20 else None, "ratio_to_5d": (volumes[-1] / mean(volumes[-5:-1])) if len(volumes) >= 6 and mean(volumes[-5:-1]) else None},
        "risk": {"max_drawdown_80d": min(drawdowns) * 100 if drawdowns else None, "range_20d": ((max(highs[-20:]) / min(lows[-20:]) - 1) * 100) if len(highs) >= 20 and min(lows[-20:]) else None},
        "money_flow": {"main_force_inflow": float(dict(flow or {}).get("main_force_inflow") or 0) if flow else None, "source_date": str(dict(flow or {}).get("trade_date") or "") if flow else None},
        "factor_decision": signal,
        "source": {"market_data": "stock_daily_kline / stock_flow", "factor_data": "v2_signal_snapshots" if signal else "暂无 V2 快照"},
    }
    return profile


@app.get("/api/v2/market")
def market():
    result = service.snapshot()
    return {"trade_date": result.get("trade_date"), "market": serialize_market(result.get("market"))}


@app.get("/api/v2/sectors")
def sectors(limit: int = Query(default=30, ge=1, le=100)):
    result = service.snapshot()
    flow_by_sector = {}
    with engine.connect() as conn:
        flow_date = conn.execute(text("SELECT MAX(trade_date) FROM sector_flow WHERE trade_date <= :d"), {"d": result.get("trade_date")}).scalar()
        if flow_date:
            flow_rows = conn.execute(text("""
                SELECT sector, net_flow, heat_score, rise_ratio, avg_chg
                FROM sector_flow WHERE trade_date = :d
            """), {"d": flow_date}).mappings().all()
            flow_by_sector = {row["sector"]: dict(row) for row in flow_rows}
    groups = {}
    for signal in result.get("all_signals", []):
        item = groups.setdefault(signal.sector, {"sector": signal.sector, "count": 0, "score_sum": 0.0, "triggered": 0, "eligible": 0})
        item["count"] += 1
        item["score_sum"] += signal.factor_score or 0
        item["triggered"] += signal.trading_state == "TRIGGERED"
        item["eligible"] += signal.resonance_eligible
    rows = []
    for item in groups.values():
        item["avg_score"] = round(item.pop("score_sum") / item["count"], 2) if item["count"] else 0
        flow = flow_by_sector.get(item["sector"], {})
        item["flow_date"] = flow_date
        item["net_flow"] = float(flow["net_flow"]) if flow.get("net_flow") is not None else None
        item["heat_score"] = float(flow["heat_score"]) if flow.get("heat_score") is not None else None
        item["rise_ratio"] = float(flow["rise_ratio"]) if flow.get("rise_ratio") is not None else None
        item["avg_chg"] = float(flow["avg_chg"]) if flow.get("avg_chg") is not None else None
        rows.append(item)
    rows.sort(key=lambda item: (item["avg_score"], item["eligible"]), reverse=True)
    return {"trade_date": result.get("trade_date"), "sectors": rows[:limit]}


@app.get("/api/v2/watchlist")
def watchlist():
    """读取旧库自选，但展示统一使用 V2 信号；不复制旧策略评分。"""
    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(text("""
            SELECT stock_code AS code, COALESCE(stock_name, '') AS name,
                   COALESCE(note, '') AS note, COALESCE(group_name, '默认') AS group_name,
                   COALESCE(quality_status, '普通') AS quality_status,
                   sort_order, created_at
              FROM watchlist
             ORDER BY sort_order, id
        """)).mappings().all()]
    signal_map = {item.code: item for item in service.snapshot().get("all_signals", [])}
    for row in rows:
        signal = signal_map.get(row["code"]) or signal_map.get(f'{row["code"]}.SH') or signal_map.get(f'{row["code"]}.SZ')
        row["signal"] = serialize_signal(signal) if signal else None
        if row.get("created_at"):
            row["created_at"] = row["created_at"].isoformat()
    return {"count": len(rows), "watchlist": rows, "source": "existing watchlist + V2 signal"}


@app.post("/api/v2/watchlist")
def add_watchlist(payload: WatchlistRequest):
    code = payload.code.strip().upper()
    if "." in code:
        code = code.split(".", 1)[0]
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO watchlist (stock_code, stock_name, note, group_name)
            VALUES (:code, :name, :note, :group_name)
            ON CONFLICT (stock_code) DO UPDATE SET
              stock_name = CASE WHEN :name <> '' THEN :name ELSE watchlist.stock_name END,
              note = CASE WHEN :note <> '' THEN :note ELSE watchlist.note END,
              group_name = CASE WHEN :group_name <> '默认' THEN :group_name ELSE COALESCE(watchlist.group_name, '默认') END
        """), {"code": code, "name": payload.name[:20], "note": payload.note[:200], "group_name": payload.group[:50] or "默认"})
    _sync_legacy_watchlist("add", code, payload.name[:20], payload.note[:200], payload.group[:50] or "默认")
    return {"success": True, "code": code}


@app.delete("/api/v2/watchlist/{code}")
def remove_watchlist(code: str):
    code = code.strip().upper().split(".", 1)[0]
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM watchlist WHERE stock_code = :code"), {"code": code})
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="自选股不存在")
    _sync_legacy_watchlist("remove", code)
    return {"success": True, "code": code}


@app.get("/api/v2/yuzi")
def yuzi(limit: int = Query(default=100, ge=1, le=500)):
    """读取最新龙虎榜量化聚合，作为 V2 的外部证据维度展示。"""
    with engine.connect() as conn:
        latest = conn.execute(text("SELECT MAX(trade_date) FROM yuzi_quant_signals")).scalar()
        rows = []
        if latest:
            rows = [dict(row) for row in conn.execute(text("""
                SELECT trade_date, ts_code AS code, stock_name AS name, sector,
                       total_net_buy, resonance_count, boss_list, quant_score,
                       change_pct, limit_up_flag, list_reason, list_tag
                  FROM yuzi_quant_signals
                 WHERE trade_date = :trade_date
                 ORDER BY quant_score DESC NULLS LAST, total_net_buy DESC NULLS LAST
                 LIMIT :limit
            """), {"trade_date": latest, "limit": limit}).mappings().all()]
    for row in rows:
        for key in ("total_net_buy", "quant_score", "change_pct"):
            if row.get(key) is not None:
                row[key] = float(row[key])
    return {"trade_date": latest, "count": len(rows), "signals": rows, "source": "yuzi_quant_signals"}


@app.get("/api/v2/actions")
def actions(limit: int = Query(default=30, ge=1, le=100)):
    result = service.snapshot()
    signals = result.get("all_signals", [])
    return {
        "trade_date": result.get("trade_date"),
        "market": serialize_market(result.get("market")),
        "triggered": [serialize_signal(item) for item in signals if item.trading_state == "TRIGGERED"][:limit],
        "ready": [serialize_signal(item) for item in signals if item.trading_state == "READY"][:limit],
        "no_chase": [serialize_signal(item) for item in signals if item.trading_state == "NO_CHASE"][:limit],
        "invalid": [serialize_signal(item) for item in signals if item.trading_state == "INVALID"][:limit],
    }


@app.get("/api/v2/registry")
def registry():
    rows = factor_registry()
    _, score_mode, status_summary = active_factor_names()
    return {
        "factor_count": len(rows),
        "factor_status_summary": status_summary,
        "score_mode": score_mode,
        "production_ready": score_mode == "PRODUCTION",
        "dimensions": [{"key": key, "label": label} for key, label in DIMENSION_LABELS.items()],
        "weights": {"market": 0.10, "sector": 0.20, "strength": 0.20, "trend": 0.15, "volume_price": 0.15, "position": 0.15, "risk_penalty": 0.05},
        "factors": rows,
    }


@app.get("/api/v2/factor-lifecycle")
def factor_lifecycle(limit: int = Query(default=500, ge=1, le=1000)):
    _, score_mode, status_summary = active_factor_names()
    return {
        "factor_catalog_count": len(FACTOR_BY_NAME),
        "factor_status_summary": status_summary,
        "score_mode": score_mode,
        "production_ready": score_mode == "PRODUCTION",
        "factors": latest_factor_reviews(limit),
    }


@app.post("/api/v2/snapshot/persist")
def persist_snapshot():
    result = service.snapshot(persist=True)
    return {
        "trade_date": result.get("trade_date"),
        "universe_count": result.get("universe_count", 0),
        "message": "V2 因子值与信号快照已写入独立 v2_* 表",
    }


@app.post("/api/v2/research/snapshot/persist")
def persist_research_snapshot():
    """保存全因子研究值；不改变当前评分启用集合。"""
    return service.persist_research_snapshot()


@app.get("/api/v2/validation")
def validation(
    # 20 日用于快速观察；120/240 日用于正式样本外准入评估。
    days: int = Query(default=20, ge=5, le=240),
    limit: int = Query(default=300, ge=30, le=1000),
    persist: bool = Query(default=False),
):
    return service.validation(days, limit, persist)


@app.get("/api/v2/config")
def config():
    row = get_config()
    for key in ("updated_at",):
        if row.get(key):
            row[key] = row[key].isoformat() if hasattr(row[key], "isoformat") else str(row[key])
    return row


@app.post("/api/v2/config")
def set_config(payload: ConfigUpdate):
    data = payload.dict(exclude_none=True)
    # The new program never enables external trading silently.
    if data.get("enabled") is True and not V2_TRADING_ENABLED:
        raise HTTPException(status_code=400, detail="环境变量 V2_TRADING_ENABLED 未开启，当前只能研究/预览")
    return update_config(data)


@app.get("/api/v2/holdings")
async def holdings(live: bool = Query(default=False)):
    if not live:
        return service.enrich_account(cached_account())
    try:
        return service.enrich_account(await MiaoxiangClient().account())
    except Exception as exc:
        data = service.enrich_account(cached_account())
        data["data_quality"] = "fallback"
        data["limitations"] = data.get("limitations", []) + [f"实时账户失败：{exc}"]
        return data


@app.get("/api/v2/orders")
async def orders(live: bool = Query(default=False)):
    if not live:
        return {"source": "新 V2 本地审计", "orders": list_audits()}
    try:
        return {"source": "妙想实时委托", "orders": await MiaoxiangClient().orders()}
    except Exception as exc:
        return {"source": "新 V2 本地审计", "orders": list_audits(), "error": str(exc)}


@app.get("/api/v2/audit")
def audit(limit: int = Query(default=100, ge=1, le=500)):
    return {"orders": list_audits(limit)}


@app.post("/api/v2/trade/preview")
def trade_preview(payload: TradeRequest):
    signal = service.stock(payload.code)
    if not signal:
        raise HTTPException(status_code=404, detail="股票不在 V2 生产股票池")
    if payload.action == "buy" and signal["trading_state"] != "TRIGGERED":
        return {"allowed": False, "reason": f"买入只允许 TRIGGERED，当前为 {signal['trading_state']}", "signal": signal}
    return {
        "allowed": payload.action == "sell" or signal["trading_state"] == "TRIGGERED",
        "external_order": False,
        "reason": "仅预览，不会发出订单",
        "signal": signal,
        "requested": payload.dict(),
    }


@app.post("/api/v2/trade/execute")
async def trade_execute(payload: TradeRequest, x_v2_action_key: Optional[str] = Header(default=None)):
    cfg = get_config()
    if not cfg.get("enabled") or not V2_TRADING_ENABLED:
        raise HTTPException(status_code=403, detail="新 V2 实盘/模拟下单开关未开启；当前只能预览")
    if not ACTION_KEY or x_v2_action_key != ACTION_KEY:
        raise HTTPException(status_code=403, detail="缺少有效的 V2 操作密钥")
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="必须明确 confirm=true 才能提交订单")
    signal = service.stock(payload.code)
    if payload.action == "buy" and (not signal or signal["trading_state"] != "TRIGGERED"):
        raise HTTPException(status_code=400, detail="买入信号不是 TRIGGERED")
    try:
        result = await MiaoxiangClient().place(payload.action, payload.code.split(".")[0], payload.quantity, price=payload.price)
        order_id = str(result.get("orderId") or result.get("order_id") or result.get("id") or "") if isinstance(result, dict) else ""
        audit_id = save_audit({
            "trade_date": date.today(), "signal_date": signal.get("trade_date") if signal else None,
            "account_source": cfg.get("account_source", "displayed"), "code": payload.code,
            "name": signal.get("name", "") if signal else "", "action": payload.action,
            "reason": "V2明确确认后提交", "factor_score": signal.get("factor_score") if signal else None,
            "resonance_count": signal.get("resonance_count") if signal else None,
            "trading_state": signal.get("trading_state") if signal else None,
            "quantity": payload.quantity, "requested_price": payload.price,
            "filled_quantity": 0, "filled_price": None, "order_id": order_id,
            "status": "submitted", "fill_status": "submitted",
            "raw_result": json.dumps(result, ensure_ascii=False),
        })
        return {"ok": True, "audit_id": audit_id, "status": "submitted", "order_id": order_id, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"订单提交失败：{exc}")


@app.get("/", include_in_schema=False)
def index():
    # 9001 主入口保留原 V2 功能框架（顶部市场切换 + 左侧功能导航）。
    # React 迁移产物仅作为 UI 参考，不得替换或删减 V2 模块。
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/v2", include_in_schema=False)
@app.get("/v2/{path:path}", include_in_schema=False)
def legacy_v2_frontend(path: str = ""):
    """保留原 V2 页面作为回退入口，主入口使用迁移后的紧凑 React UI。"""
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

# 9000 React 前端已作为 9001 主入口；保留 /migrated 兼容旧书签。
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")
    app.mount("/migrated/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="migrated-assets")

    @app.get("/migrated", include_in_schema=False)
    @app.get("/migrated/{path:path}", include_in_schema=False)
    def migrated_frontend(path: str = ""):
        return FileResponse(FRONTEND_DIST / "index.html")


@app.get("/{frontend_path:path}", include_in_schema=False)
def frontend_spa_fallback(frontend_path: str):
    """让 React Router 的 /quality、/stock-analysis 等深链接可直接刷新。"""
    if frontend_path.startswith(("api/", "assets/", "static/", "migrated/")):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(FRONTEND_DIST / "index.html")

"""9000 内的 V2 候选因子研究入口。

生产评分继续由 backend.quant_vnext 唯一负责；本路由只把原 9001 的
候选因子目录、生命周期和验证记录纳入 9000，避免两套评分同时运行。
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from typing import Optional

from v2_app.factors import DIMENSION_LABELS, FACTOR_CATALOG, FACTOR_STATUS_LABELS
from v2_app.repository import factor_registry, factor_status_summary, latest_factor_reviews


router = APIRouter(prefix="/api/vnext/research-v2", tags=["v2 research migration"])


@router.get("/dashboard")
def dashboard():
    # 不在普通页面请求里触发 V2 全市场扫描；扫描由显式研究任务执行。
    return {
        "trade_date": None, "universe_count": 0, "market": None,
        "signals": [], "state_counts": {}, "triggered": 0,
        "resonance_eligible": 0, "score_mode": "NOT_COMPUTED",
        "production_ready": False,
        "message": "V2 快照尚未刷新；页面读取不会自动启动全市场计算。",
    }


@router.get("/candidates")
def candidates(limit: int = Query(default=50, ge=1, le=500), state: Optional[str] = Query(default=None)):
    return {"trade_date": None, "universe_count": 0, "signals": [], "score_mode": "NOT_COMPUTED", "message": "请先执行 V2 快照刷新。"}


@router.get("/catalog")
def catalog():
    rows = factor_registry()
    return {
        "candidate_catalog_count": len(FACTOR_CATALOG),
        "registry_count": len(rows),
        "status_summary": factor_status_summary(),
        "dimensions": [{"key": key, "label": label} for key, label in DIMENSION_LABELS.items()],
        "status_labels": FACTOR_STATUS_LABELS,
        "factors": rows,
        "note": "候选/观察库；不参与 9000 的生产评分，生产评分唯一来源是 /api/vnext。",
    }


@router.get("/registry")
def registry():
    """9000 本地因子注册表；替代原先经 9001 反向代理的因子页面。"""
    rows = factor_registry()
    summary = factor_status_summary()
    return {
        "total": len(rows),
        "factor_count": len(rows),
        "status_summary": summary,
        "dimensions": [{"key": key, "label": label} for key, label in DIMENSION_LABELS.items()],
        "factors": rows,
        "source": "9000.local.v2_research",
        "production_scoring_source": "/api/vnext/registry",
    }


@router.get("/lifecycle")
def lifecycle(limit: int = Query(default=300, ge=1, le=1000)):
    reviews = latest_factor_reviews(limit)
    return {
        "status_summary": factor_status_summary(),
        "total": len(reviews),
        "reviews": reviews,
        "note": "生命周期记录仅用于研究准入与淘汰，不会自动修改生产因子。",
    }

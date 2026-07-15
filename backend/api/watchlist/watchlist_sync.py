"""watchlist 实时资金流采集触发 API（拆分自 core.py）

原 watchlist/core.py 末尾的 collection trigger 三件套：
  - POST /api/watchlist/realtime-flow/trigger
  - GET  /api/watchlist/realtime-flow/trigger/status
  - GET  /api/watchlist/market-capital-ranking

将它们抽到本模块以降低 core.py 体积（1213 行 → ~1100 行），并按职责分组：
core.py 负责 CRUD / 列表 / 标签 / 信号；sync.py 负责外部触发采集与进度上报。
"""
import threading
import logging
from datetime import datetime

from fastapi import APIRouter, Query

from db.session import get_db_session
from db.models import Watchlist

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 手动触发实时资金流采集（带进度，后台线程不阻塞请求）=====
_COLLECT_STATE = {
    "running": False,
    "done": 0,
    "total": 0,
    "started_at": None,
    "finished_at": None,
    "last_error": None,
}


def _run_collection_job():
    """后台线程：采集全部自选股实时资金流，并上报进度。"""
    from collectors.emdatah5_collector import batch_save_realtime
    try:
        with get_db_session() as db:
            codes = [r.stock_code for r in db.query(Watchlist).all() if r.stock_code]
        _COLLECT_STATE["total"] = len(codes)
        _COLLECT_STATE["done"] = 0

        def _on_progress(done, total):
            _COLLECT_STATE["done"] = done

        batch_save_realtime(codes, on_progress=_on_progress)
    except Exception as e:
        _COLLECT_STATE["last_error"] = str(e)
        logger.error(f"[trigger] 手动采集异常: {e}", exc_info=True)
    finally:
        _COLLECT_STATE["running"] = False
        _COLLECT_STATE["finished_at"] = datetime.now().isoformat()


@router.post("/api/watchlist/realtime-flow/trigger")
async def trigger_realtime_collection():
    """立即触发一次全量自选股实时资金流采集（后台异步，约 60-90s）。"""
    if _COLLECT_STATE["running"]:
        return {
            "status": "running",
            "done": _COLLECT_STATE["done"],
            "total": _COLLECT_STATE["total"],
            "started_at": _COLLECT_STATE["started_at"],
        }
    # 先取总数，让前端立即知道进度上限
    try:
        with get_db_session() as db:
            _COLLECT_STATE["total"] = db.query(Watchlist).count()
    except Exception:
        _COLLECT_STATE["total"] = 0
    _COLLECT_STATE["running"] = True
    _COLLECT_STATE["started_at"] = datetime.now().isoformat()
    _COLLECT_STATE["finished_at"] = None
    _COLLECT_STATE["last_error"] = None
    _COLLECT_STATE["done"] = 0
    t = threading.Thread(target=_run_collection_job, daemon=True)
    t.start()
    return {"status": "started", "total": _COLLECT_STATE["total"]}


@router.get("/api/watchlist/realtime-flow/trigger/status")
async def trigger_collection_status():
    """查询手动采集进度。"""
    return {
        "running": _COLLECT_STATE["running"],
        "done": _COLLECT_STATE["done"],
        "total": _COLLECT_STATE["total"],
        "started_at": _COLLECT_STATE["started_at"],
        "finished_at": _COLLECT_STATE["finished_at"],
        "last_error": _COLLECT_STATE["last_error"],
    }


@router.get("/api/watchlist/market-capital-ranking")
async def market_capital_ranking(
    rtype: str = Query("inflow", description="inflow=主力净流入前N, outflow=主力净流出前N"),
    top: int = Query(100, description="返回条数(10-200)"),
):
    """全市场资金流排行（东财批量排行榜接口，1 次请求，轻量）。"""
    from collectors.emdatah5_collector import fetch_market_capital_ranking
    rank_type = "outflow" if str(rtype).lower() == "outflow" else "inflow"
    top_n = max(10, min(200, int(top)))
    return fetch_market_capital_ranking(rank_type=rank_type, top_n=top_n)

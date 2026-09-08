"""同步 REST API 端点"""
import logging
from fastapi import APIRouter, Query
from sqlalchemy import distinct

from db.session import get_db_session
from db.models import StockNewsSearch, Watchlist
from .ths import sync_from_ths, sync_to_ths
from .mx import sync_to_mx, sync_from_mx
from .dispatcher import full_sync

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/api/sync/status")
async def sync_status(force: bool = Query(False, description="保留兼容；GET 始终只读数据库")):
    """返回数据库中的同步/采集状态，不在页面加载时探测外部平台。"""
    del force
    from api.stock_info import _search_error

    status = {"source": "database", "platforms": {}}
    with get_db_session() as db:
        local_count = db.query(Watchlist).count()
        groups = [r[0] for r in db.query(distinct(Watchlist.group_name)).all()]
        status["platforms"]["local"] = {"count": local_count, "groups": groups}
        latest_mx = db.query(StockNewsSearch).order_by(
            StockNewsSearch.search_time.desc(), StockNewsSearch.id.desc()
        ).first()

    latest_error = _search_error(latest_mx.result_raw) if latest_mx else None
    status["platforms"]["mx"] = {
        "connected": None,
        "status": latest_error or ("READY" if latest_mx else "UNKNOWN"),
        "last_collected_at": latest_mx.search_time.isoformat() if latest_mx else None,
        "message": (
            "最近一次妙想采集已触发额度限制"
            if latest_error == "UPSTREAM_LIMIT"
            else "连接状态未实时探测；请以手动同步结果为准"
        ),
    }
    status["platforms"]["ths"] = {
        "connected": None,
        "status": "UNKNOWN",
        "message": "连接状态未实时探测；请以手动同步结果为准",
    }
    return status


@router.get("/api/sync/ths/list")
async def get_ths_list():
    """返回已同步入库的自选快照，不在 GET 中调用同花顺。"""
    with get_db_session() as db:
        rows = db.query(Watchlist).order_by(Watchlist.sort_order, Watchlist.id).all()
        return [{"code": row.stock_code, "name": row.stock_name or row.stock_code} for row in rows]


@router.post("/api/sync/ths/pull")
async def pull_from_ths(dry_run: bool = Query(False), mirror: bool = Query(False)):
    """从同花顺拉取到本地。默认 mirror=False = 增量模式（只加不删，保留本地独有自选）"""
    return await sync_from_ths(dry_run, mirror)


@router.post("/api/sync/ths/push")
async def push_to_ths(dry_run: bool = Query(False), mirror: bool = Query(False)):
    """本地推送到同花顺。默认 mirror=False = 增量模式（只加不删，保留云端独有自选）"""
    return await sync_to_ths(dry_run, mirror)


@router.post("/api/sync/mx/push")
async def push_to_mx(dry_run: bool = Query(False), mirror: bool = Query(False)):
    return await sync_to_mx(dry_run, mirror)


@router.post("/api/sync/mx/pull")
async def pull_from_mx(dry_run: bool = Query(False), mirror: bool = Query(False)):
    return await sync_from_mx(dry_run, mirror)


@router.post("/api/sync/all")
async def sync_all():
    return await full_sync()

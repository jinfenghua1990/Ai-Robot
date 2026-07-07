"""同步 REST API 端点"""
import logging
from datetime import datetime
from fastapi import APIRouter, Query
from sqlalchemy import distinct

from db.connection import get_db
from db.session import get_db_session
from db.models import Watchlist
from .ths import ths_get_self_stock, sync_from_ths, sync_to_ths
from .mx import sync_to_mx, sync_from_mx
from .dispatcher import full_sync

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/sync/status")
async def sync_status():
    """获取各平台同步状态"""
    status = {"platforms": {}}
    try:
        ths_list = await ths_get_self_stock()
        from .ths import THS_COOKIE_FILE
        status["platforms"]["ths"] = {
            "connected": True,
            "count": len(ths_list),
            "cookie_file_exists": THS_COOKIE_FILE.exists() if THS_COOKIE_FILE else False,
        }
    except Exception as e:
        status["platforms"]["ths"] = {"connected": False, "error": str(e)}
    try:
        from api.mx_skills import _parse_zixuan_list
        from .mx import _mx_post
        raw = await _mx_post("/api/claw/self-select/get", {})
        if isinstance(raw, dict) and raw.get('status') == 112:
            status["platforms"]["mx"] = {"connected": False, "error": "妙想API限流，稍后再试"}
        else:
            mx_list = _parse_zixuan_list(raw)
            status["platforms"]["mx"] = {"connected": True, "count": len(mx_list)}
    except Exception as e:
        status["platforms"]["mx"] = {"connected": False, "error": str(e)}
    with get_db_session() as db:
        local_count = db.query(Watchlist).count()
        groups = [r[0] for r in db.query(distinct(Watchlist.group_name)).all()]
        status["platforms"]["local"] = {"count": local_count, "groups": groups}
    try:
        from api.sina_sync import _sina_available, sina_get_self_stock
        if not _sina_available():
            status["platforms"]["sina"] = {"connected": False, "note": "未配置 SINA_COOKIE，新浪同步未启用"}
        else:
            try:
                sina_list = await sina_get_self_stock()
                status["platforms"]["sina"] = {"connected": True, "count": len(sina_list)}
            except Exception as e:
                status["platforms"]["sina"] = {"connected": False, "error": str(e)}
    except ImportError:
        status["platforms"]["sina"] = {"connected": False, "note": "新浪同步模块未加载"}
    return status


@router.get("/api/sync/ths/list")
async def get_ths_list():
    return await ths_get_self_stock()


@router.post("/api/sync/ths/pull")
async def pull_from_ths(dry_run: bool = Query(False), mirror: bool = Query(True)):
    return await sync_from_ths(dry_run, mirror)


@router.post("/api/sync/ths/push")
async def push_to_ths(dry_run: bool = Query(False), mirror: bool = Query(True)):
    return await sync_to_ths(dry_run, mirror)


@router.post("/api/sync/mx/push")
async def push_to_mx(dry_run: bool = Query(False), mirror: bool = Query(True)):
    return await sync_to_mx(dry_run, mirror)


@router.post("/api/sync/mx/pull")
async def pull_from_mx(dry_run: bool = Query(False), mirror: bool = Query(True)):
    return await sync_from_mx(dry_run, mirror)


@router.post("/api/sync/all")
async def sync_all():
    return await full_sync()

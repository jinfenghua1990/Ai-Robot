"""同步包：本地自选股 ↔ 同花顺/妙想/新浪 三向同步

将原 backend/api/external_sync.py（776行）拆为：
- ths.py        同花顺 cookie 提取 + 云端 API + sync_from/sync_to
- mx.py         妙想云端 sync_from/sync_to
- dispatcher.py 防抖触发（本地变化→推送/删除云端）
- api.py        REST 端点 /api/sync/*
"""
from fastapi import APIRouter
import api.sync_pkg.ths  # noqa: F401  加载 router
import api.sync_pkg.mx  # noqa: F401
import api.sync_pkg.dispatcher  # noqa: F401
from .api import router as api_router

router = APIRouter()
router.include_router(api_router)


def trigger_cloud_sync(reason: str = "watchlist change"):
    """本地自选股变化后调用：防抖 3 秒后推送到所有云端。
    重新导出供 api/watchlist/core.py 调用。
    """
    from .dispatcher import trigger_cloud_sync as _impl
    return _impl(reason)


def trigger_cloud_delete(code: str, name: str = ""):
    """本地删除自选股后调用：防抖 3 秒后从所有云端删除。
    重新导出供 api/watchlist/core.py 调用。
    """
    from .dispatcher import trigger_cloud_delete as _impl
    return _impl(code, name)


async def full_sync(mirror_push: bool = True) -> dict:
    """全量双向同步（供 collector/scheduler.py 调用）"""
    from .dispatcher import full_sync as _impl
    return await _impl(mirror_push)


__all__ = ["router", "trigger_cloud_sync", "trigger_cloud_delete", "full_sync"]

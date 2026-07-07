"""watchlist 包入口

将原 backend/api/watchlist.py（844行）拆为以下子模块：
- _shared.py   共享缓存 + 内部工具
- core.py      核心 CRUD + 列表构建（get/add/remove/note/quality/pin/move-group/sync-quality）
- groups.py    分组管理
- batch.py     批量操作（delete/move/export）
- sync_mx.py   从妙想同步到本地

main.py 仍可通过 `from api import watchlist` 然后 `app.include_router(watchlist.router)` 加载。
同时保持向后兼容：`from api.watchlist import _watchlist_cache, _refresh_watchlist_cache` 仍可用
（这两个符号在 main.py startup 里被引用）。
"""
from fastapi import APIRouter
from fastapi.routing import APIRouter as _APIRouter

from ._shared import _watchlist_cache
from .core import build_watchlist, refresh_watchlist_cache, get_quote, fetch_kline_cached


# 合并子模块 router
router = APIRouter()
for _mod in ("core", "groups", "batch", "sync_mx"):
    _sub = __import__(f"api.watchlist.{_mod}", fromlist=["router"])
    router.include_router(_sub.router)


# === 向后兼容：旧模块曾导出这些符号 ===
_watchlist_refreshing = False
WATCHLIST_CACHE_TTL = 300
QUOTE_CACHE_TTL = 30
KLINE_CACHE_TTL = 3600


def _refresh_watchlist_cache():
    """同步入口：供 main.py 启动时调用"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.create_task(refresh_watchlist_cache())


__all__ = [
    "router",
    "build_watchlist",
    "refresh_watchlist_cache",
    "get_quote",
    "fetch_kline_cached",
    "_watchlist_cache",
    "_refresh_watchlist_cache",
]

"""老虎证券(Tiger Trade)自选同步 API

- POST /api/tiger-sync/sync    触发同步（美股→US_WATCHLIST，港股→HK_WATCHLIST）
- GET  /api/tiger-sync/status  查看上次同步状态
"""
from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, Query

from services.tiger_watchlist_sync import get_last_status, run_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tiger-sync", tags=["tiger-sync"])


@router.post("/sync")
async def api_tiger_sync(markets: str = Query("US,HK", description="同步市场，逗号分隔：US/HK")):
    """同步 Tiger Trade 客户端自选股到 9000 服务股票池（本地 plist 读取）"""
    try:
        result = await asyncio.to_thread(run_sync, markets)
        return result
    except Exception as exc:
        logger.exception("[tiger-sync] 同步异常")
        return {"ok": False, "error": str(exc)}


@router.get("/status")
def api_tiger_sync_status():
    """查看最近一次 Tiger Trade 自选同步状态"""
    return get_last_status()

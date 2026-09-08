"""盈立(uSMART)自选同步 API

- POST /api/usmart-sync/sync      触发同步（美股→US_WATCHLIST 池，港股→HK_WATCHLIST 池）
- GET  /api/usmart-sync/status    查看上次同步状态
- POST /api/usmart-sync/positions 触发盈立真实持仓同步（只读）
- GET  /api/usmart-sync/positions 查看已同步的盈立真实持仓
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query
from sqlalchemy import desc

from db.session import get_db_session
from services.usmart_watchlist_sync import (
    _check_login_state,
    _discover_page_ws,
    discover_cdp_status,
    get_last_status,
    run_sync,
)
from services.usmart_positions_sync import get_last_status as get_pos_status
from services.usmart_positions_sync import run_sync as run_pos_sync
from us_quant.repository import USRealPosition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/usmart-sync", tags=["usmart-sync"])


@router.post("/sync")
async def api_usmart_sync(markets: str = Query("US,HK", description="同步市场，逗号分隔：US/HK")):
    """同步盈立客户端自选股到 9000 服务股票池（需本地盈立客户端已登录）"""
    try:
        result = await asyncio.to_thread(run_sync, markets)
        return result
    except Exception as exc:
        logger.exception("[usmart-sync] 同步异常")
        return {"ok": False, "error": str(exc)}


@router.get("/status")
def api_usmart_sync_status():
    """查看最近一次盈立自选同步状态"""
    status = get_last_status()
    # 同步页面同时展示只读持仓同步的最近状态，便于区分“客户端掉线”
    # 与“触发了新设备短信验证”，避免只看到旧的自选同步成功记录。
    status["positions_status"] = get_pos_status()
    try:
        cdp = discover_cdp_status()
        ws_url = _discover_page_ws() if cdp["available"] else None
        status["cdp_available"] = cdp["available"]
        status["cdp_reason"] = cdp["reason"]
        status["cdp_page_count"] = cdp["page_count"]
        status["client_login"] = _check_login_state(ws_url) if ws_url else "offline"
    except Exception as exc:
        logger.warning("[usmart-sync] 读取客户端状态失败: %s", exc)
        status["cdp_available"] = False
        status["client_login"] = "offline"
        status["cdp_reason"] = "读取盈立调试状态失败，请确认客户端仍在运行。"
    return status


@router.post("/positions")
async def api_usmart_positions_sync():
    """同步盈立客户端真实持仓（需本地盈立客户端已登录，同步时客户端页面会刷新一次）"""
    try:
        result = await asyncio.to_thread(run_pos_sync)
        # 同步成功后自动触发持仓技术指标计算（异步执行，不阻塞响应）
        if isinstance(result, dict) and result.get("ok") and result.get("count", 0) > 0:
            async def _compute_indicators():
                try:
                    from api.us_quant import compute_position_indicators
                    with get_db_session() as db:
                        rows = db.query(USRealPosition).filter(
                            USRealPosition.status == "ACTIVE"
                        ).all()
                        symbols = [r.symbol for r in rows if r.symbol]
                    if symbols:
                        await asyncio.to_thread(compute_position_indicators, symbols)
                        logger.info(f"[usmart-pos] auto-computed indicators for {len(symbols)} positions")
                except Exception as exc:
                    logger.warning(f"[usmart-pos] auto indicator compute failed: {exc}")
            asyncio.create_task(_compute_indicators())
        return result
    except Exception as exc:
        logger.exception("[usmart-pos] 同步异常")
        return {"ok": False, "error": str(exc)}


@router.get("/positions")
def api_usmart_positions(include_history: bool = Query(False, description="同时返回已关闭的历史持仓")):
    """查看已同步的盈立真实美股持仓；按需附带数据库中的已关闭记录"""
    try:
        with get_db_session() as db:
            rows = (db.query(USRealPosition)
                    .filter(USRealPosition.status == "ACTIVE")
                    .order_by(desc(USRealPosition.market_value))
                    .all())
            history_rows = []
            if include_history:
                history_rows = (db.query(USRealPosition)
                                .filter(USRealPosition.status == "CLOSED")
                                .order_by(desc(USRealPosition.synced_at), desc(USRealPosition.id))
                                .all())

            def serialize(row: USRealPosition) -> dict:
                return {
                    "symbol": row.symbol,
                    "name": row.name,
                    "exchange_type": row.exchange_type,
                    "fund_account": row.fund_account,
                    "quantity": float(row.quantity) if row.quantity is not None else None,
                    "cost_price": float(row.cost_price) if row.cost_price is not None else None,
                    "last_price": float(row.last_price) if row.last_price is not None else None,
                    "pre_close": float(row.pre_close) if row.pre_close is not None else None,
                    "market_value": float(row.market_value) if row.market_value is not None else None,
                    "hold_profit": float(row.hold_profit) if row.hold_profit is not None else None,
                    "hold_profit_pct": float(row.hold_profit_pct) if row.hold_profit_pct is not None else None,
                    "today_profit": float(row.today_profit) if row.today_profit is not None else None,
                    "status": row.status,
                    "synced_at": row.synced_at.isoformat() if row.synced_at else None,
                    "closed_at": row.synced_at.isoformat() if row.status == "CLOSED" and row.synced_at else None,
                }

            return {
                "ok": True,
                "count": len(rows),
                "positions": [serialize(r) for r in rows],
                "history_count": len(history_rows),
                "history": [serialize(r) for r in history_rows],
                "last_status": get_pos_status(),
            }
    except Exception as exc:
        logger.exception("[usmart-pos] 查询异常")
        return {"ok": False, "error": str(exc)}

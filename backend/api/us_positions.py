"""内置美股持仓管理 API（已脱离盈立客户端 CDP 同步）

数据流：
  手动录入（新增/编辑/平仓） → us_real_positions 表
  现价/市值/盈亏 → 腾讯实时行情（_tx_quote）自动刷新（15 秒节流）

- GET    /api/us-positions                 查询持仓（?include_history=true 附带已平仓；?refresh=1 先刷行情再返回）
- POST   /api/us-positions                 新增持仓 {symbol, quantity, cost_price, name?}
- PATCH  /api/us-positions/{symbol}        修改数量 / 成本价 / 名称
- POST   /api/us-positions/{symbol}/close  平仓（快照盈亏后标记 CLOSED）
- DELETE /api/us-positions/{symbol}        彻底删除记录（含历史）
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc

from db.session import get_db_session
from us_quant.repository import USRealPosition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/us-positions", tags=["us-positions"])

# 行情刷新节流：GET ?refresh=1 的最小间隔，避免前端 30s 轮询打爆外部行情接口
REFRESH_THROTTLE_S = 15
_REFRESH_LOCK = threading.Lock()
_last_refresh_ts = 0.0


# ─── 行情刷新 ────────────────────────────────────────────────────────────

def _refresh_quotes() -> int:
    """用腾讯实时行情刷新所有 ACTIVE 持仓的现价 / 市值 / 盈亏（带节流）"""
    global _last_refresh_ts
    with _REFRESH_LOCK:
        now = time.time()
        if now - _last_refresh_ts < REFRESH_THROTTLE_S:
            return -1  # 节流期内跳过
        _last_refresh_ts = now

    from api.us_stock_analysis import _tx_quote

    with get_db_session() as db:
        rows = db.query(USRealPosition).filter(USRealPosition.status == "ACTIVE").all()
        updated = 0
        for row in rows:
            try:
                quote = _tx_quote(row.symbol)
            except Exception:
                quote = None
            if not quote or quote.get("price") in (None, 0):
                continue
            price = float(quote["price"])
            row.last_price = price
            row.pre_close = quote.get("prev_close")
            if row.quantity is not None:
                qty = float(row.quantity)
                row.market_value = price * qty
                if row.cost_price:
                    row.hold_profit = (price - float(row.cost_price)) * qty
                    row.hold_profit_pct = (price / float(row.cost_price) - 1) * 100
                if quote.get("prev_close"):
                    row.today_profit = (price - float(quote["prev_close"])) * qty
            row.synced_at = datetime.now()
            updated += 1
        db.commit()
    if updated:
        logger.info("[us-positions] 行情刷新完成: %d 只", updated)
    return updated


def _recompute(row: USRealPosition) -> None:
    """按已存的 last_price 重算市值 / 盈亏（编辑数量或成本后调用）"""
    if row.last_price is None or row.quantity is None:
        return
    price, qty = float(row.last_price), float(row.quantity)
    row.market_value = price * qty
    if row.cost_price:
        row.hold_profit = (price - float(row.cost_price)) * qty
        row.hold_profit_pct = (price / float(row.cost_price) - 1) * 100
    if row.pre_close:
        row.today_profit = (price - float(row.pre_close)) * qty


# ─── 序列化 ──────────────────────────────────────────────────────────────

def _serialize(row: USRealPosition) -> dict:
    def f(v) -> Optional[float]:
        return float(v) if v is not None else None

    return {
        "symbol": row.symbol,
        "name": row.name,
        "exchange_type": row.exchange_type,
        "fund_account": row.fund_account,
        "quantity": f(row.quantity),
        "cost_price": f(row.cost_price),
        "last_price": f(row.last_price),
        "pre_close": f(row.pre_close),
        "market_value": f(row.market_value),
        "hold_profit": f(row.hold_profit),
        "hold_profit_pct": f(row.hold_profit_pct),
        "today_profit": f(row.today_profit),
        "status": row.status,
        "synced_at": row.synced_at.isoformat() if row.synced_at else None,
        "closed_at": row.synced_at.isoformat() if row.status == "CLOSED" and row.synced_at else None,
    }


# ─── 查询 ────────────────────────────────────────────────────────────────

@router.get("")
def list_positions(
    include_history: bool = Query(False, description="同时返回已平仓的历史持仓"),
    refresh: bool = Query(False, description="先刷新实时行情再返回（15 秒节流）"),
):
    try:
        if refresh:
            _refresh_quotes()
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
            latest = rows[0].synced_at if rows else None
            return {
                "ok": True,
                "count": len(rows),
                "positions": [_serialize(r) for r in rows],
                "history_count": len(history_rows),
                "history": [_serialize(r) for r in history_rows],
                "last_status": {"ok": True, "source": "builtin", "synced_at": latest.isoformat() if latest else None},
            }
    except Exception as exc:
        logger.exception("[us-positions] 查询异常")
        return {"ok": False, "error": str(exc)}


# ─── 新增 ────────────────────────────────────────────────────────────────

class PositionIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    quantity: float = Field(gt=0)
    cost_price: float = Field(gt=0)
    name: Optional[str] = None


@router.post("")
def add_position(body: PositionIn):
    symbol = body.symbol.strip().upper()
    try:
        with get_db_session() as db:
            exists = db.query(USRealPosition).filter(USRealPosition.symbol == symbol).first()
            if exists and exists.status == "ACTIVE":
                return {"ok": False, "error": f"{symbol} 已在持仓中，请直接编辑"}
            row = exists or USRealPosition(symbol=symbol)
            row.name = body.name or row.name
            row.exchange_type = 5
            row.quantity = body.quantity
            row.cost_price = body.cost_price
            row.status = "ACTIVE"
            row.hold_info_id = None
            row.synced_at = datetime.now()
            # 名称 / 现价缺失时尝试拉一次实时行情补齐
            if not row.name or row.last_price is None:
                try:
                    from api.us_stock_analysis import _tx_quote
                    quote = _tx_quote(symbol)
                    if quote:
                        row.name = row.name or quote.get("name")
                        row.last_price = quote.get("price") or row.last_price
                        row.pre_close = quote.get("prev_close") or row.pre_close
                except Exception:
                    pass
            _recompute(row)
            db.add(row)
            db.commit()
            db.refresh(row)
        return {"ok": True, "position": _serialize(row)}
    except Exception as exc:
        logger.exception("[us-positions] 新增异常")
        return {"ok": False, "error": str(exc)}


# ─── 修改 ────────────────────────────────────────────────────────────────

class PositionPatch(BaseModel):
    quantity: Optional[float] = Field(default=None, gt=0)
    cost_price: Optional[float] = Field(default=None, gt=0)
    name: Optional[str] = None


@router.patch("/{symbol}")
def update_position(symbol: str, body: PositionPatch):
    symbol = symbol.strip().upper()
    try:
        with get_db_session() as db:
            row = db.query(USRealPosition).filter(
                USRealPosition.symbol == symbol, USRealPosition.status == "ACTIVE").first()
            if not row:
                return {"ok": False, "error": f"未找到活跃持仓 {symbol}"}
            if body.quantity is not None:
                row.quantity = body.quantity
            if body.cost_price is not None:
                row.cost_price = body.cost_price
            if body.name is not None:
                row.name = body.name
            row.synced_at = datetime.now()
            _recompute(row)
            db.commit()
            db.refresh(row)
        return {"ok": True, "position": _serialize(row)}
    except Exception as exc:
        logger.exception("[us-positions] 修改异常")
        return {"ok": False, "error": str(exc)}


# ─── 平仓 ────────────────────────────────────────────────────────────────

@router.post("/{symbol}/close")
def close_position(symbol: str):
    """平仓：用最新行情快照盈亏后标记 CLOSED（记录保留在历史持仓）"""
    symbol = symbol.strip().upper()
    try:
        with get_db_session() as db:
            row = db.query(USRealPosition).filter(
                USRealPosition.symbol == symbol, USRealPosition.status == "ACTIVE").first()
            if not row:
                return {"ok": False, "error": f"未找到活跃持仓 {symbol}"}
            try:
                from api.us_stock_analysis import _tx_quote
                quote = _tx_quote(symbol)
                if quote and quote.get("price"):
                    row.last_price = quote["price"]
                    row.pre_close = quote.get("prev_close") or row.pre_close
                    _recompute(row)
            except Exception:
                pass
            row.status = "CLOSED"
            row.synced_at = datetime.now()
            db.commit()
            db.refresh(row)
        return {"ok": True, "position": _serialize(row)}
    except Exception as exc:
        logger.exception("[us-positions] 平仓异常")
        return {"ok": False, "error": str(exc)}


# ─── 删除 ────────────────────────────────────────────────────────────────

@router.delete("/{symbol}")
def delete_position(symbol: str):
    """彻底删除持仓记录（活跃 / 历史一并删除，不可恢复）"""
    symbol = symbol.strip().upper()
    try:
        with get_db_session() as db:
            deleted = db.query(USRealPosition).filter(USRealPosition.symbol == symbol).delete()
            db.commit()
        if not deleted:
            return {"ok": False, "error": f"未找到持仓记录 {symbol}"}
        return {"ok": True, "deleted": deleted}
    except Exception as exc:
        logger.exception("[us-positions] 删除异常")
        return {"ok": False, "error": str(exc)}

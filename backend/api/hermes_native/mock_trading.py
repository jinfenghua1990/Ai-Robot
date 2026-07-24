"""
from typing import Optional
模拟盘 API —— 数据层统一走 AIROBOT 共享 portfolio.json
from typing import Optional
- 读取：优先从 /api/shared/portfolio 获取，同时调用 /api/trading/balance 补全账户资金
- 写入：交易成功后刷新 /api/shared/portfolio/refresh，确保顶部共享指示器实时一致
- 降级：AIROBOT 不可达时回退到直接调用妙想 API，避免页面空白
"""
from __future__ import annotations

import sys
import json
import logging
import threading
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException

_TRACKING = Path(__file__).resolve().parent.parent
if str(_TRACKING) not in sys.path:
    sys.path.insert(0, str(_TRACKING))

logger = logging.getLogger("mock_trading")

from api.hermes_native.services.monitor_pool import ensure_monitor_schema, queue_trade_action, sync_broker_positions, update_trade_action_result

try:
    from api.hermes_native.services.miaoxiang_service import mock_positions, mock_balance, mock_trade  # noqa: F401
    _MIAOXIANG_OK = True
except Exception as e:
    _MIAOXIANG_OK = False
    logger.warning(f"miaoxiang_service 不可用,mock-trading 路由将返回占位: {e}")

router = APIRouter(prefix="/api/mock-trading", tags=["mock-trading"])

_AIROBOT_BASE = "http://127.0.0.1:9000"


def _airobot_request(method: str, path: str, payload: Optional[dict] = None, timeout: float = 15.0) -> dict:
    """向 AIROBOT 后端发起同步 HTTP 请求（同步端点运行在线程池，阻塞是可接受的）。"""
    url = f"{_AIROBOT_BASE}{path}"
    headers = {"User-Agent": "Hermes/1.0"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _refresh_shared_portfolio() -> bool:
    """触发 AIROBOT 共享 portfolio 刷新。失败返回 False，不影响主流程。"""
    try:
        _airobot_request("POST", "/api/shared/portfolio/refresh", timeout=15.0)
        return True
    except Exception as e:
        logger.warning(f"刷新共享 portfolio 失败: {e}")
        return False


def _get_shared_portfolio() -> Optional[dict]:
    """读取 AIROBOT 共享 portfolio。"""
    try:
        return _airobot_request("GET", "/api/shared/portfolio", timeout=10.0)
    except Exception as e:
        logger.warning(f"读取共享 portfolio 失败: {e}")
        return None


def _get_shared_balance() -> Optional[dict]:
    """读取 AIROBOT 共享模拟盘资金（/api/trading/balance 与共享 portfolio 同源）。"""
    try:
        return _airobot_request("GET", "/api/trading/balance?force=1", timeout=10.0)
    except Exception as e:
        logger.warning(f"读取共享 balance 失败: {e}")
        return None


def _shared_to_hermes(shared_pf: dict, balance: Optional[dict]) -> dict:
    """把 AIROBOT 共享 portfolio 格式转成 Hermes 前端格式（价格为浮点元）。"""
    positions = shared_pf.get("positions", []) if shared_pf else []
    pos_list = []
    for p in positions:
        qty = int(p.get("quantity", 0) or 0)
        price = float(p.get("last_price", 0) or 0)
        cost = float(p.get("avg_cost", 0) or 0)
        profit = float(p.get("unrealized_pnl", 0) or 0)
        profit_pct = float(p.get("profit_ratio", 0) or 0)
        if profit_pct == 0 and cost > 0:
            profit_pct = round((price - cost) / cost * 100, 2)
        pos_list.append({
            "secCode": str(p.get("symbol", "")),
            "secName": str(p.get("name", "")),
            "count": qty,
            "availCount": qty,  # 共享层不区分可用/持仓，按全部可用处理
            "price": round(price, 2),
            "priceDec": 2,
            "costPrice": round(cost, 2),
            "costPriceDec": 2,
            "profit": profit,
            "profitPct": profit_pct,
            "dayProfit": 0.0,
            "dayProfitPct": 0.0,
        })

    active_pos_list = [p for p in pos_list if (p.get("count") or 0) > 0]
    closed_pos_list = [p for p in pos_list if (p.get("count") or 0) <= 0]
    total_mv = float((shared_pf or {}).get("total_market_value", 0) or 0)
    total_pnl = float((shared_pf or {}).get("total_unrealized_pnl", 0) or 0)

    bal = (balance or {}).get("data", balance or {})
    avail_balance = float(bal.get("availBalance", 0) or 0)
    total_assets = float(bal.get("totalAssets", 0) or 0)
    init_money = float(bal.get("initMoney", 0) or 0)
    account_profit = (total_assets - init_money) if init_money else total_pnl
    account_profit_pct = (account_profit / init_money * 100) if init_money else 0

    return {
        "posList": pos_list,
        "totalAssets": total_assets or (total_mv + avail_balance),
        "totalPosValue": total_mv,
        "availBalance": avail_balance,
        "totalProfit": total_pnl,
        "profitPct": 0.0,
        "posCount": len(pos_list),
        "activePosCount": len(active_pos_list),
        "closedPosCount": len(closed_pos_list),
        "accName": bal.get("accName", ""),
        "accID": bal.get("accID", ""),
        "initMoney": init_money,
        "nav": bal.get("nav", 0) or 0,
        "totalPosPct": bal.get("totalPosPct", 0) or 0,
        "frozenMoney": bal.get("frozenMoney", 0) or 0,
        "balanceActual": bal.get("balanceActual", avail_balance) or avail_balance,
        "accountProfit": account_profit,
        "accountProfitPct": account_profit_pct,
        "sourceLabel": "AIROBOT 共享模拟盘",
        "updatedAt": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }


def _normalize_trade_code(code: Optional[str]) -> str:
    text = str(code or "").strip().upper()
    for prefix in ("SH", "SZ", "BJ", "HK", "US"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    for suffix in (".SH", ".SZ", ".BJ", ".HK", ".US"):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
            break
    return text


def _get_position_qty_from_shared(code: str) -> int:
    """从 AIROBOT 共享 portfolio 读取指定代码的持仓数量，失败返回 0。"""
    try:
        shared = _get_shared_portfolio()
        if not shared:
            return 0
        target = _normalize_trade_code(code)
        for p in shared.get("positions", []):
            if _normalize_trade_code(p.get("symbol", "")) == target:
                return int(p.get("quantity", 0) or 0)
    except Exception as e:
        logger.warning(f"从共享 portfolio 读取持仓数量失败: {e}")
    return 0


def _resolve_trade_qty(payload: dict, action_type: str) -> int:
    qty = int(payload.get("count") or payload.get("amount") or payload.get("quantity") or 0)
    if qty > 0:
        return qty
    if action_type == "close_position":
        target = _normalize_trade_code(payload.get("secCode") or payload.get("stockCode") or payload.get("code"))
        shared_qty = _get_position_qty_from_shared(payload.get("secCode") or payload.get("stockCode") or payload.get("code"))
        if shared_qty > 0:
            return shared_qty
        # 降级：直接读妙想
        try:
            positions = mock_positions()
            data = positions.get("data", positions)
            for pos in data.get("posList", []):
                if _normalize_trade_code(pos.get("secCode")) == target:
                    return int(pos.get("count") or 0)
        except Exception as e:
            logger.warning(f"close_position 自动补数量失败: {e}")
    return qty


def _trade_action_type(action_type: str) -> str:
    return "buy" if action_type in {"buy", "add_position"} else "sell"


def _execute_trade(action_type: str, payload: dict, *, fallback_msg: str) -> dict:
    code = payload.get("secCode") or payload.get("stockCode") or payload.get("code")
    qty = _resolve_trade_qty(payload, action_type)
    if qty <= 0:
        raise HTTPException(status_code=400, detail=f"{fallback_msg}: 数量无效")
    queue = queue_trade_action(
        code=code,
        name=payload.get("secName") or payload.get("name"),
        market=payload.get("market") or "",
        action_type=action_type,
        qty=qty,
        price_hint=payload.get("price"),
        request_source="stock_monitor",
        payload=payload,
    )
    queue_id = queue.get("id")
    try:
        trade_price = payload.get("price")
        use_market_price = bool(payload.get("useMarketPrice") or payload.get("marketPrice"))
        if trade_price in (None, "", 0, "0"):
            use_market_price = True
            trade_price = 0
        result = mock_trade(
            trade_type=_trade_action_type(action_type),
            stock_code=str(code or ""),
            price=trade_price,
            quantity=qty,
            use_market_price=use_market_price,
        )
        update_trade_action_result(
            int(queue_id),
            status="submitted",
            broker_response=result,
            error_message=None,
        )
        # 交易成功后后台刷新共享 portfolio，避免阻塞前端响应
        threading.Thread(target=_refresh_shared_portfolio, daemon=True).start()
        return {
            "success": True,
            "code": 200,
            "msg": result.get("message") or result.get("msg") or fallback_msg,
            "queue_id": queue_id,
            "broker_response": result,
        }
    except Exception as e:
        update_trade_action_result(
            int(queue_id),
            status="failed",
            broker_response={"error": str(e)},
            error_message=str(e),
        )
        raise HTTPException(status_code=503, detail=f"妙想 API 不可达: {e}")


def _convert_positions(raw_positions: dict, raw_balance: Optional[dict] = None) -> dict:
    """将妙想模拟盘数据转成前端格式（价格为浮点元）。降级时使用。"""
    data = raw_positions.get("data", raw_positions)
    balance = (raw_balance or {}).get("data", raw_balance or {})
    pos_list = []
    for p in data.get("posList", []):
        price_dec = int(p.get("priceDec", 2) or 2)
        cost_dec = int(p.get("costPriceDec", 2) or 2)

        def _to_yuan(v, dec):
            if v is None or v == "":
                return 0.0
            try:
                return round(float(v), dec)
            except Exception:
                return 0.0

        price_yuan = _to_yuan(p.get("price", 0), price_dec)
        cost_yuan = _to_yuan(p.get("costPrice", p.get("price", 0)), cost_dec)
        profit_pct = p.get("profitPct", 0) or 0
        if (not profit_pct) and cost_yuan > 0:
            profit_pct = round((price_yuan - cost_yuan) / cost_yuan * 100, 2)
        pos_list.append({
            "secCode": p.get("secCode", ""),
            "secName": p.get("secName", ""),
            "count": p.get("count", 0),
            "availCount": p.get("availCount", 0),
            "price": price_yuan,
            "priceDec": price_dec,
            "costPrice": cost_yuan,
            "costPriceDec": cost_dec,
            "profit": p.get("profit", 0) or 0,
            "profitPct": profit_pct,
            "dayProfit": p.get("dayProfit", 0) or 0,
            "dayProfitPct": p.get("dayProfitPct", 0) or 0,
        })

    active_pos_list = [p for p in pos_list if (p.get("count") or 0) > 0]
    closed_pos_list = [p for p in pos_list if (p.get("count") or 0) <= 0]
    total_assets = data.get("totalAssets", 0) or 0
    total_pos_value = data.get("totalPosValue", 0) or 0
    avail_balance = data.get("availBalance", 0) or 0
    init_money = balance.get("initMoney", 0) or 0
    account_profit = (total_assets - init_money) if init_money else (total_assets - total_pos_value - avail_balance)
    account_profit_pct = (account_profit / init_money * 100) if init_money else 0

    return {
        "posList": pos_list,
        "totalAssets": total_assets,
        "totalPosValue": total_pos_value,
        "availBalance": avail_balance,
        "totalProfit": data.get("totalProfit", 0) or 0,
        "profitPct": data.get("profitPct", 0) or 0,
        "posCount": len(pos_list),
        "activePosCount": len(active_pos_list),
        "closedPosCount": len(closed_pos_list),
        "accName": balance.get("accName", ""),
        "accID": balance.get("accID", ""),
        "initMoney": init_money,
        "nav": balance.get("nav", 0) or 0,
        "totalPosPct": balance.get("totalPosPct", 0) or 0,
        "frozenMoney": balance.get("frozenMoney", 0) or 0,
        "balanceActual": balance.get("balanceActual", avail_balance) or avail_balance,
        "accountProfit": account_profit,
        "accountProfitPct": account_profit_pct,
        "sourceLabel": "妙想原始账户数据（降级）",
        "updatedAt": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }


def _mock_positions_fallback() -> dict:
    """妙想 key 失效 / 网络不通时,返回占位数据让前端能渲染(空持仓)"""
    return {
        "posList": [],
        "totalAssets": 0.0,
        "totalPosValue": 0.0,
        "availBalance": 0.0,
        "totalProfit": 0.0,
        "profitPct": 0.0,
        "posCount": 0,
        "updatedAt": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "warning": "妙想 API 不可达,显示空持仓 (key 失效或网络问题)",
    }


@router.get("/positions")
def get_positions():
    # 优先走 AIROBOT 共享 portfolio
    try:
        _refresh_shared_portfolio()
        shared_pf = _get_shared_portfolio()
        if shared_pf:
            shared_balance = _get_shared_balance()
            hermes_data = _shared_to_hermes(shared_pf, shared_balance)
            try:
                ensure_monitor_schema()
                # 同步持仓到 monitor pool：把共享 portfolio 数据包装成妙想格式
                raw_positions = {"data": {"posList": hermes_data["posList"]}}
                sync_broker_positions(raw_positions, shared_balance)
            except Exception as sync_err:
                logger.warning(f"monitor pool 同步持仓失败: {sync_err}")
            return hermes_data
    except Exception as e:
        logger.warning(f"共享 portfolio 路径失败，降级到妙想直连: {e}")

    # 降级：直接调用妙想 API
    try:
        raw_positions = mock_positions()
        raw_balance = None
        try:
            raw_balance = mock_balance()
        except Exception as balance_err:
            logger.warning(f"mock_balance() 调用失败,仍返回持仓原始数据: {balance_err}")
        try:
            ensure_monitor_schema()
            sync_broker_positions(raw_positions, raw_balance)
        except Exception as sync_err:
            logger.warning(f"monitor pool 同步持仓失败: {sync_err}")
        return _convert_positions(raw_positions, raw_balance)
    except Exception as e:
        logger.warning(f"mock_positions() 调用失败,返回占位: {e}")
        return _mock_positions_fallback()


@router.get("/balance")
def get_balance():
    # 优先走 AIROBOT 共享 balance
    try:
        shared_balance = _get_shared_balance()
        if shared_balance:
            return shared_balance
    except Exception as e:
        logger.warning(f"共享 balance 路径失败，降级到妙想直连: {e}")

    try:
        return mock_balance()
    except Exception as e:
        logger.warning(f"mock_balance() 调用失败: {e}")
        return {"data": {"balance": 0, "available": 0}, "warning": "妙想 API 不可达"}


@router.post("/buy")
def buy_stock(payload: dict):
    return _execute_trade("buy", payload, fallback_msg="买入成功")


@router.post("/sell")
def sell_stock(payload: dict):
    return _execute_trade("sell", payload, fallback_msg="卖出成功")


@router.post("/add-position")
def add_position(payload: dict):
    return _execute_trade("add_position", payload, fallback_msg="加仓成功")


@router.post("/reduce-position")
def reduce_position(payload: dict):
    return _execute_trade("reduce_position", payload, fallback_msg="减仓成功")


@router.post("/close-position")
def close_position(payload: dict):
    return _execute_trade("close_position", payload, fallback_msg="清仓成功")

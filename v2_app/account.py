from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from .config import MX_API_URL, ROOT, V2_TRADING_APIKEY


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _scaled_number(row: dict, key: str, fallback_key: str | None = None) -> float:
    """Normalize 妙想接口的整数价格字段 without guessing on other values.

    妙想持仓接口可能返回 ``price=4751, priceDec=2``，而本地缓存已经是
    ``47.51``。只有明确存在对应的 ``*Dec`` 字段时才缩放，避免误处理市值
    和盈亏等已经是金额单位的字段。
    """
    actual_key = key
    raw = row.get(actual_key)
    if raw is None and fallback_key:
        actual_key = fallback_key
        raw = row.get(actual_key)
    if raw is None:
        return 0.0
    value = _number(raw)
    decimals = row.get(f"{actual_key}Dec")
    if decimals not in (None, "", 0, "0"):
        try:
            return value / (10 ** int(decimals))
        except (TypeError, ValueError, OverflowError):
            return value
    return value


def _normalize_positions(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows or []:
        result.append({
            "code": row.get("secCode") or row.get("symbol") or row.get("code") or "",
            "name": row.get("secName") or row.get("name") or row.get("stock_name") or "",
            "quantity": int(row.get("count") or row.get("quantity") or 0),
            "available_quantity": int(row.get("availCount") or row.get("available_quantity") or row.get("quantity") or 0),
            "avg_cost": _scaled_number(row, "costPrice", "avg_cost"),
            "last_price": _scaled_number(row, "price", "last_price"),
            "market_value": _number(row.get("value") or row.get("market_value")),
            "unrealized_pnl": _number(row.get("profit") or row.get("unrealized_pnl")),
            "unrealized_pnl_pct": _number(row.get("profitPct") or row.get("profit_ratio")),
            "source": row.get("source") or "portfolio_cache",
        })
    return result


def cached_account() -> dict:
    path = ROOT / "portfolio.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    positions = _normalize_positions(data.get("positions") or [])
    market_value = _number(data.get("total_market_value")) or sum(item["market_value"] for item in positions)
    cash = _number(data.get("available_cash"))
    assets = _number(data.get("total_assets")) or market_value + cash
    return {
        "source": "portfolio.json缓存",
        "as_of": data.get("as_of"),
        "cash": cash,
        "market_value": market_value,
        "total_assets": assets,
        "unrealized_pnl": _number(data.get("total_unrealized_pnl")) or sum(item["unrealized_pnl"] for item in positions),
        "positions": positions,
        "data_quality": "cached",
        "limitations": ["当前为只读缓存；点击刷新才会请求账户接口", "已实现盈亏/费用未由缓存提供"],
    }


class MiaoxiangClient:
    def __init__(self, api_key: str = V2_TRADING_APIKEY, base_url: str = MX_API_URL):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def request(self, endpoint: str, payload: dict | None = None) -> dict:
        if not self.api_key:
            raise RuntimeError("未配置 V2_TRADING_APIKEY")
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                f"{self.base_url}{endpoint}",
                json=payload or {"moneyUnit": 1},
                headers={"apikey": self.api_key, "Content-Type": "application/json; charset=UTF-8"},
            )
        data = response.json()
        if str(data.get("code", "")) not in {"0", "200"}:
            raise RuntimeError(data.get("message") or f"账户接口错误：{data.get('code')}")
        return data.get("data") or {}

    async def account(self) -> dict:
        balance = await self.request("/api/claw/mockTrading/balance")
        positions = await self.request("/api/claw/mockTrading/positions")
        rows = positions.get("posList") or positions.get("positions") or []
        normalized = _normalize_positions(rows)
        return {
            "source": "妙想实时账户",
            "as_of": None,
            "cash": _number(balance.get("availBalance")),
            "market_value": _number(balance.get("totalPosValue")) or sum(item["market_value"] for item in normalized),
            "total_assets": _number(balance.get("totalAssets")),
            "unrealized_pnl": sum(item["unrealized_pnl"] for item in normalized),
            "positions": normalized,
            "data_quality": "live",
            "limitations": ["已实现盈亏、费用需通过委托成交记录另行核算"],
        }

    async def orders(self) -> list[dict]:
        data = await self.request("/api/claw/mockTrading/orders", {
            "moneyUnit": 1, "beginDate": "", "endDate": "", "beginTime": 0, "endTime": 0,
            "count": 200, "offset": 0,
        })
        result = []
        for row in data.get("orders") or data.get("orderList") or []:
            result.append({
                "id": str(row.get("id") or row.get("orderId") or ""),
                "code": row.get("secCode") or "",
                "name": row.get("secName") or "",
                "direction": "买入" if row.get("drt") == 1 else "卖出",
                "quantity": int(row.get("count") or 0),
                "filled_quantity": int(row.get("tradeCount") or 0),
                "price": _number(row.get("price")),
                "filled_price": _number(row.get("tradePrice")),
                "status_code": row.get("status"),
            })
        return result

    async def place(self, action: str, code: str, quantity: int, use_market_price: bool = True, price: float | None = None) -> dict:
        payload = {"type": action, "stockCode": code, "quantity": quantity, "useMarketPrice": use_market_price}
        if price is not None:
            payload["price"] = price
        return await self.request("/api/claw/mockTrading/trade", payload)

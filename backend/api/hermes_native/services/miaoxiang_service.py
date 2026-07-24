"""
妙想 API 服务模块 — 封装东方财富妙想 API 的通用数据查询
"""
from __future__ import annotations

import os
import json
from typing import Any, Optional, Optional, Union

import requests

BASE_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"


def _api_key() -> str:
    key = os.getenv("MX_APIKEY", "")
    if not key:
        raise ValueError("MX_APIKEY 未设置")
    return key


def query(tool_query: str) -> dict[str, Any]:
    """调用妙想 API 查询数据"""
    headers = {"apikey": _api_key(), "Content-Type": "application/json"}
    resp = requests.post(BASE_URL, headers=headers, json={"toolQuery": tool_query}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _parse_tables(result: dict) -> list[dict]:
    """从妙想 API 响应中提取 dataTableDTOList 并解析成统一格式"""
    # 妙想 API 有双层 data 嵌套
    inner = result.get("data")
    if inner is None:
        # API 返回空数据（可能是调用限制或非交易时段）
        return []
    if isinstance(inner, dict) and "data" in inner and "searchDataResultDTO" in inner.get("data", {}):
        inner = inner["data"]
    if not isinstance(inner, dict):
        return []
    data = inner.get("data", inner)
    if not isinstance(data, dict):
        return []
    search = data.get("searchDataResultDTO") or data
    tables = search.get("dataTableDTOList", [])
    items = []
    for t in tables:
        table = t.get("table", {})
        name_map = t.get("nameMap", {})
        raw = t.get("rawTable", {})
        code = t.get("code", "")
        entity = t.get("entityName", "")
        item = {"code": code, "name": entity}
        for api_field, values in raw.items():
            label = name_map.get(api_field, api_field)
            if values and len(values) > 0:
                item[label] = str(values[0])
        # 也尝试从 table 取 f2/f3 这类标准字段
        for api_field, values in table.items():
            label = name_map.get(api_field, api_field)
            if api_field not in ("headName", "headNameSub") and values and len(values) > 0:
                if api_field not in raw:
                    item[label] = str(values[0])
        items.append(item)
    return items


def realtime_quote(codes: list[str]) -> list[dict[str, Any]]:
    """
    查询多只股票的实时行情
    妙想 API 对个股查询支持有限,走通用查询
    """
    return _parse_tables(query(f"最新行情{' '.join(codes)}"))


def index_quote() -> list[dict[str, Any]]:
    """查询主要指数行情"""
    return _parse_tables(query("沪深300指数 上证指数 最新点位 涨跌幅"))


def smart_select(tool_query: str) -> list[dict[str, Any]]:
    """智能选股"""
    return _parse_tables(query(tool_query))


def search_news(keyword: str) -> list[dict[str, Any]]:
    """搜索财经资讯"""
    return _parse_tables(query(f"搜索{keyword}最新新闻"))
    for t in tables[:10]:
        table = t.get("table", {})
        entity = t.get("entityName", "")
        raw = t.get("rawTable", {})
        item = {"title": entity}
        for api_field, values in raw.items():
            if values and len(values) > 0:
                item[api_field] = values[0]
        news.append(item)
    return news
API_BASE = "https://mkapi2.dfcfs.com/finskillshub"

def _api_post(path, payload):
    headers = {"apikey": __import__('os').environ.get("MX_APIKEY",""), "Content-Type": "application/json"}
    resp = __import__('requests').post(f"{API_BASE}{path}", headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()

def mock_positions():
    return _api_post("/api/claw/mockTrading/positions", {"moneyUnit": 1})

def mock_balance():
    return _api_post("/api/claw/mockTrading/balance", {"moneyUnit": 1})


def _normalize_trade_code(stock_code: str) -> str:
    code = str(stock_code or "").strip().upper()
    for prefix in ("SH", "SZ", "BJ", "HK", "US"):
        if code.startswith(prefix):
            code = code[len(prefix):]
            break
    for suffix in (".SH", ".SZ", ".BJ", ".HK", ".US"):
        if code.endswith(suffix):
            code = code[:-len(suffix)]
            break
    return code


def mock_trade(*, trade_type: str, stock_code: str, price: Union[float, Optional[int]]= None, quantity: int = 0, use_market_price: bool = False) -> dict[str, Any]:
    payload = {
        "type": trade_type,
        "stockCode": _normalize_trade_code(stock_code),
        "price": price,
        "quantity": int(quantity),
        "useMarketPrice": bool(use_market_price),
    }
    return _api_post("/api/claw/mockTrading/trade", payload)

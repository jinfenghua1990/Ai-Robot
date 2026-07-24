"""
资金流向独立 API

提供北向资金、行业资金流、概念/个股资金流向数据。
从 market_review.py 的 _build_fund_flow_section 提取并优化。

端点:
- GET /api/fundflow?date=YYYY-MM-DD

缓存策略:
- 内存缓存: 300 秒 (5分钟) TTL - 资金流数据更新频率较低
- 数据源: robot1 fund_flow_collector + DB 查询

注意:
- 北向资金: 盘中实时更新（约每 5 分钟）
- 行业/概念资金: 收盘后更新（19:00 左右）
"""

from __future__ import annotations

import logging
import sys
import time as _time_module
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

# 复用 market_review 中已验证的资金流数据准备逻辑
try:
    from api.hermes_native.market_review import _build_fund_flow_section
except ImportError:  # pragma: no cover - 包模式回退
    try:
        from .market_review import _build_fund_flow_section
    except ImportError:
        _build_fund_flow_section = None

# 与原 market-review 一致: 构建前触发后台自动补数 (带进程内冷却)
try:
    from api.hermes_native.auto_fill_trigger import ensure_auto_fill
except ImportError:  # pragma: no cover
    try:
        from .auto_fill_trigger import ensure_auto_fill
    except ImportError:
        ensure_auto_fill = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["fundflow"])

# 缓存配置 (资金流数据不需要高频刷新)
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS: int = 300  # 5 分钟缓存

# Robot1 数据源路径
ROBOT1_ROOT = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/robot-1")
DATA_ROOT = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/data")

# 延迟加载的客户端
_fund_flow_client: Optional[Any] = None
_db_client: Optional[dict[str, Any]] = None
_client_loaded_at: float = 0
_ERROR_TTL: float = 300


def _ensure_paths() -> None:
    for p in (DATA_ROOT, ROBOT1_ROOT):
        text = str(p)
        if text not in sys.path:
            sys.path.insert(0, text)


def _load_clients() -> tuple[Optional[Any], dict[str, Any]]:
    """加载资金流和数据库客户端"""
    global _fund_flow_client, _db_client, _client_loaded_at

    if _fund_flow_client is not None and _db_client is not None:
        if not _db_client.get("error"):
            return _fund_flow_client, _db_client

    # TTL 未过，返回错误状态
    if (_time_module.time() - _client_loaded_at) < _ERROR_TTL:
        return _fund_flow_client, _db_client

    # 重试加载
    _ensure_paths()
    _client_loaded_at = _time_module.time()
    try:
        from collectors.fund_flow_collector import collect_fund_flow
        from api.hermes_native.db_connector import execute_query

        _fund_flow_client = collect_fund_flow
        _db_client = {"execute_query": execute_query, "error": None}
    except Exception as e:
        logger.warning(f"[fundflow] 加载客户端失败: {e}")
        _db_client = {"error": str(e)}

    return _fund_flow_client, _db_client


def _normalize_date(value: Optional[str]) -> str:
    if not value:
        return datetime.now().strftime("%Y-%m-%d")
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return text


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_float(value: Any, default=None):
    if value in (None, "", []):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _money_to_yi(value: Any) -> Optional[float]:
    """转换为亿元单位"""
    if value in (None, "", []):
        return None
    try:
        return round(float(value) / 100000000.0, 2)
    except Exception:
        return None


def _north_money_to_yi(value: Any) -> Optional[float]:
    """北向资金转换为亿元（原单位可能是万元）"""
    if value in (None, "", []):
        return None
    try:
        return round(float(value) / 10000.0, 2)
    except Exception:
        return None


def _is_cache_valid(entry: dict[str, Any]) -> bool:
    if not entry:
        return False
    age = _time_module.time() - entry.get("timestamp", 0)
    return age < entry.get("ttl", CACHE_TTL_SECONDS)


def _query_rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    _, db_client = _load_clients()
    if db_client.get("error"):
        return []
    try:
        rows = db_client["execute_query"](sql, params)
        return [dict(row) for row in rows]
    except Exception:
        return []


def _load_north_money(review_date: str) -> dict[str, Any]:
    """加载北向资金数据"""
    rows = _query_rows(
        """
        SELECT trade_date, hgt, sgt, north_money, south_money,
               ggt_ss, ggt_sz, created_at
        FROM north_money_flow
        WHERE trade_date = %s
        ORDER BY trade_date DESC LIMIT 1
        """,
        (review_date,),
    )

    if not rows:
        return {}

    row = dict(rows[0])
    return {
        "trade_date": str(row.get("trade_date", "")),
        "hgt": _north_money_to_yi(row.get("hgt")),
        "sgt": _north_money_to_yi(row.get("sgt")),
        "north_money": _north_money_to_yi(row.get("north_money")),
        "south_money": _north_money_to_yi(row.get("south_money")),
        "ggt_ss": _money_to_yi(row.get("ggt_ss")),
        "ggt_sz": _money_to_yi(row.get("ggt_sz")),
        "updated_at": str(row.get("created_at", "")),
        "source": "database",
    }


def _load_industry_flow(review_date: str, limit: int = 10) -> list[dict[str, Any]]:
    """加载行业资金流向 Top N"""
    rows = _query_rows(
        """
        SELECT industry_name, industry_code,
               net_inflow, net_inflow_pct,
               main_net_inflow, retail_net_inflow,
               trade_date, created_at
        FROM industry_fund_flow_daily
        WHERE trade_date = %s
        ORDER BY ABS(net_inflow) DESC
        LIMIT %s
        """,
        (review_date, limit * 2),  # 取双倍数量，后续分流入/流出
    )

    inflow_list = []
    outflow_list = []

    for row in rows:
        r = dict(row)
        item = {
            "name": str(r.get("industry_name") or ""),
            "code": str(r.get("industry_code") or ""),
            "net_inflow": _money_to_yi(r.get("net_inflow")),
            "net_inflow_pct": _to_float(r.get("net_inflow_pct")),
            "main_net_inflow": _money_to_yi(r.get("main_net_inflow")),
            "retail_net_inflow": _money_to_yi(r.get("retail_net_inflow")),
        }

        if (item["net_inflow"] or 0) >= 0 and len(inflow_list) < limit:
            inflow_list.append(item)
        elif (item["net_inflow"] or 0) < 0 and len(outflow_list) < limit:
            outflow_list.append(item)

    return {
        "inflow_top": inflow_list,
        "outflow_top": outflow_list,
    }


def _load_concept_flow(review_date: str, limit: int = 10) -> list[dict[str, Any]]:
    """加载概念板块资金流向 Top N"""
    rows = _query_rows(
        """
        SELECT concept_name, concept_code,
               net_inflow, net_inflow_pct,
               trade_date, created_at
        FROM concept_fund_flow_daily
        WHERE trade_date = %s
        ORDER BY ABS(net_inflow) DESC
        LIMIT %s
        """,
        (review_date, limit * 2),
    )

    inflow_list = []
    outflow_list = []

    for row in rows:
        r = dict(row)
        item = {
            "name": str(r.get("concept_name") or ""),
            "code": str(r.get("concept_code") or ""),
            "net_inflow": _money_to_yi(r.get("net_inflow")),
            "net_inflow_pct": _to_float(r.get("net_inflow_pct")),
        }

        if (item["net_inflow"] or 0) >= 0 and len(inflow_list) < limit:
            inflow_list.append(item)
        elif (item["net_inflow"] or 0) < 0 and len(outflow_list) < limit:
            outflow_list.append(item)

    return {
        "inflow_top": inflow_list,
        "outflow_top": outflow_list,
    }


def _collect_realtime_fundflow(review_date: str) -> dict[str, Any]:
    """调用实时资金流采集器"""
    collector, _ = _load_clients()
    if collector is None:
        return {}

    try:
        result = collector(trade_date=review_date)
        if isinstance(result, dict):
            return result
    except Exception as e:
        logger.warning(f"[fundflow] 实时采集失败: {e}")

    return {}


def _build_fundflow_data(review_date: str) -> dict[str, Any]:
    """构建完整资金流向数据（核心逻辑）"""
    cached = _cache.get(review_date)
    if _is_cache_valid(cached):
        logger.debug(f"[fundflow] 命中缓存: {review_date}")
        return cached["data"]

    # 与原 market-review 一致: 确保后台自动补数已触发
    if ensure_auto_fill is not None:
        ensure_auto_fill(review_date)

    if _build_fund_flow_section is None:
        return {
            "date": review_date,
            "north_money": None,
            "industry_inflow_top5": [],
            "industry_outflow_top5": [],
            "concept_inflow_top5": [],
            "concept_outflow_top5": [],
            "market_moneyflow": {},
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": "error",
            "status": "error",
            "error": "market_review._build_fund_flow_section not available",
        }

    # 复用已验证的数据准备逻辑（内部负责北向/行业/概念/个股资金流加载 + 引擎调用）
    fund_flow, source, updated_at, has_real = _build_fund_flow_section(review_date)

    north_money = fund_flow.get("north_money") or {}
    industry_in = fund_flow.get("industry_inflow_top5", [])
    industry_out = fund_flow.get("industry_outflow_top5", [])

    result = {
        "date": review_date,
        **fund_flow,
        "updated_at": updated_at or datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "source": source,
        "status": "ok",
        "data_quality": {
            "north_available": bool(north_money),
            "industry_count": len(industry_in) + len(industry_out),
            "has_real": has_real,
        },
    }

    # 写入缓存
    _cache[review_date] = {
        "data": result,
        "timestamp": _time_module.time(),
        "ttl": CACHE_TTL_SECONDS,
    }

    north_total = (north_money or {}).get("north_money")
    logger.info(
        f"[fundflow] 构建完成: {review_date}, "
        f"north={north_total}亿, industries={result['data_quality']['industry_count']}条"
    )
    return result


@router.get("/fundflow")
async def get_fundflow(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取资金流向数据

    返回内容包括：
    - **north_money**: 北向资金（沪深港通）净买入
      - hgt: 沪股通净买入
      - sgt: 深股通净买入
    - **industry_inflow/outflow_top5**: 行业资金流向 Top5
    - **concept_inflow/outflow_top5**: 概念板块资金流向 Top5

    单位说明：
    - 北向资金：亿元
    - 行业/概念资金流：亿元（net_inflow）

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "north_money": {"north_money": 25.6, "hgt": 12.3, "sgt": 13.3},
      "industry_inflow_top5": [{"name": "电子", "net_inflow": 15.8}],
      "updated_at": "2026/07/18 15:30:00"
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_fundflow_data(requested_date)
    return data


@router.get("/fundflow/cache-info")
async def get_fundflow_cache_info():
    """获取资金流 API 缓存状态（调试用）"""
    now = _time_module.time()
    entries = []
    for date_str, entry in _cache.items():
        age = now - entry.get("timestamp", 0)
        valid = _is_cache_valid(entry)
        entries.append({
            "date": date_str,
            "age_seconds": round(age, 1),
            "valid": valid,
        })

    return {
        "total_cached": len(_cache),
        "ttl_seconds": CACHE_TTL_SECONDS,
        "collector_status": "loaded" if _fund_flow_client else "unavailable",
        "entries": entries,
        "server_time": datetime.now().isoformat(),
    }

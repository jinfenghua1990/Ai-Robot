"""
市场指数与行情独立 API

提供 A 股市场核心指数、涨停池统计、市场热度等数据。
从 market_review.py 的 _build_market_section 提取并优化。

端点:
- GET /api/market?date=YYYY-MM-DD

缓存策略:
- 内存缓存: 30 秒 TTL (盘中实时数据)
- 数据源: robot1 data_api (get_index_data, get_limit_up_pool, get_market_sentiment)
"""

from __future__ import annotations

import logging
import sys
import time as _time_module
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

# 复用 market_review 中已验证的市场数据准备逻辑
try:
    from api.hermes_native.market_review import _build_market_section
except ImportError:  # pragma: no cover - 包模式回退
    try:
        from .market_review import _build_market_section
    except ImportError:
        _build_market_section = None

# 与原 market-review 一致: 构建前触发后台自动补数 (带进程内冷却)
try:
    from api.hermes_native.auto_fill_trigger import ensure_auto_fill
except ImportError:  # pragma: no cover
    try:
        from .auto_fill_trigger import ensure_auto_fill
    except ImportError:
        ensure_auto_fill = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["market"])

# 缓存配置
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS: int = 30  # 30秒缓存（实时数据）


def _normalize_date(value: Optional[str]) -> str:
    if not value:
        return datetime.now().strftime("%Y-%m-%d")
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}->{text[6:8]}"
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


def _to_int(value: Any, default=None):
    if value in (None, "", []):
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _is_cache_valid(entry: dict[str, Any]) -> bool:
    if not entry:
        return False
    age = _time_module.time() - entry.get("timestamp", 0)
    return age < entry.get("ttl", CACHE_TTL_SECONDS)


def _build_market_data(review_date: str) -> dict[str, Any]:
    """构建完整的市场数据（核心逻辑）"""
    cached = _cache.get(review_date)
    if _is_cache_valid(cached):
        logger.debug(f"[market] 命中缓存: {review_date}")
        return cached["data"]

    # 与原 market-review 一致: 确保后台自动补数已触发
    if ensure_auto_fill is not None:
        ensure_auto_fill(review_date)

    if _build_market_section is None:
        return {
            "date": review_date,
            "indices": [],
            "limit_up": {},
            "heat": {},
            "breadth": {},
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": "error",
            "status": "error",
            "error": "market_review._build_market_section not available",
        }

    # 复用已验证的数据准备逻辑（指数/涨停池/情绪/热度）
    market, source, updated_at, has_real = _build_market_section(review_date)

    indices = market.get("indices", [])
    limit_stats = market.get("limit_up", {})
    result = {
        "date": review_date,
        **market,
        "resolved_date": market.get("trade_date") or review_date,
        "updated_at": updated_at or datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "source": source,
        "status": "ok",
        "data_quality": {"has_real": has_real},
    }

    # 写入缓存
    _cache[review_date] = {
        "data": result,
        "timestamp": _time_module.time(),
        "ttl": CACHE_TTL_SECONDS,
    }

    logger.info(
        f"[market] 构建完成: {review_date}, "
        f"indices={len(indices)}, limit_up={limit_stats.get('limit_up')}, source={source}"
    )
    return result


@router.get("/market")
async def get_market(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取市场指数与行情数据

    返回内容包括：
    - **indices**: 主要指数列表（上证/深证/创业板/科创板）
    - **limit_up**: 涨停池统计（涨停数/炸板率/跌停数）
    - **heat**: 市场热度指标（0-100，数值越高越活跃）
    - **sentiment**: 市场情绪（涨跌比/情绪评分）

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "indices": [{"name": "上证指数", "value": 2985.6, "change": 0.85}],
      "limit_up": {"limit_up": 45, "broken": 12.3},
      "heat": {"value": 72.5, "label": "热"},
      "updated_at": "2026/07/18 15:00:00"
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_market_data(requested_date)
    return data


@router.get("/market/cache-info")
async def get_market_cache_info():
    """获取市场 API 缓存状态（调试用）"""
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
        "robot1_status": "loaded" if _robot1_api and not _robot1_api.get("error") else "unavailable",
        "entries": entries,
        "server_time": datetime.now().isoformat(),
    }

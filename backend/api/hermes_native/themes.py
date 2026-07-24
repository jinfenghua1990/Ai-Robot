"""
主题分类独立 API

提供主线/观察/活跃三个维度的主题数据，支持按日期查询。
从 market_review.py 的 _build_themes_section 提取并优化。

端点:
- GET /api/themes?date=YYYY-MM-DD

缓存策略:
- 内存缓存: 30 秒 TTL
- 数据源: theme_engine.build_theme_sections()
"""

from __future__ import annotations

import logging
import time as _time_module
from datetime import datetime
from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

# 复用 market_review 中已验证的数据准备逻辑（负责加载行业/概念/龙头行并正确调用引擎）
try:
    from api.hermes_native.market_review import _build_themes_section
except ImportError:  # pragma: no cover - 包模式回退
    try:
        from .market_review import _build_themes_section
    except ImportError:
        _build_themes_section = None

# 与原 market-review 一致: 构建前触发后台自动补数 (带进程内冷却)
try:
    from api.hermes_native.auto_fill_trigger import ensure_auto_fill
except ImportError:  # pragma: no cover
    try:
        from .auto_fill_trigger import ensure_auto_fill
    except ImportError:
        ensure_auto_fill = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["themes"])

# 内存缓存: {date_str: {data, timestamp, ttl}}
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS: int = 30  # 30秒缓存


def _normalize_date(value: Optional[str]) -> str:
    """标准化日期格式"""
    if not value:
        return datetime.now().strftime("%Y-%m-%d")
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return text


def _is_cache_valid(cache_entry: dict[str, Any]) -> bool:
    """检查缓存是否有效"""
    if not cache_entry:
        return False
    age = _time_module.time() - cache_entry.get("timestamp", 0)
    return age < cache_entry.get("ttl", CACHE_TTL_SECONDS)


def _build_themes_data(review_date: str) -> dict[str, Any]:
    """构建主题分类数据（核心逻辑）"""
    # 尝试从缓存读取
    cached = _cache.get(review_date)
    if _is_cache_valid(cached):
        logger.debug(f"[themes] 命中缓存: {review_date}")
        return cached["data"]

    # 与原 market-review 一致: 确保后台自动补数已触发
    if ensure_auto_fill is not None:
        ensure_auto_fill(review_date)

    # 缓存未命中，重新构建数据
    try:
        if _build_themes_section is None:
            raise ImportError("market_review._build_themes_section not available")

        themes_data, source, updated_at, _is_real = _build_themes_section(review_date)

        # 标准化输出格式
        result = {
            "date": review_date,
            "mainline": themes_data.get("mainline", []),
            "watch": themes_data.get("watch", []),
            "alive": themes_data.get("alive", []),
            "signals": themes_data.get("signals", []),
            "drivers": themes_data.get("drivers", {}),
            "updated_at": updated_at or datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": source,
            "status": "ok",
        }

        # 写入缓存
        _cache[review_date] = {
            "data": result,
            "timestamp": _time_module.time(),
            "ttl": CACHE_TTL_SECONDS,
        }

        logger.info(f"[themes] 构建完成: {review_date}, mainline={len(result['mainline'])}条")
        return result

    except Exception as e:
        logger.error(f"[themes] 构建失败: {e}", exc_info=True)
        return {
            "date": review_date,
            "mainline": [],
            "watch": [],
            "alive": [],
            "signals": [],
            "drivers": {},
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": "error",
            "status": "error",
            "error": str(e),
        }


@router.get("/themes")
async def get_themes(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取主题分类数据（主线/观察/活跃）

    返回当前市场的三大主题分类：
    - mainline: 主线热点（最强、最持续）
    - watch: 观察方向（有潜力但需确认）
    - alive: 活口方向（短线机会）

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "mainline": [{"name": "AI算力", "score": 85, ...}],
      "watch": [{"name": "新能源车", "score": 72, ...}],
      "alive": [{"name": "消费电子", "score": 65, ...}],
      "updated_at": "2026/07/18 15:00:00",
      "status": "ok"
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_themes_data(requested_date)
    return data


@router.get("/themes/cache-info")
async def get_themes_cache_info():
    """获取主题 API 的缓存状态（调试用）"""
    now = _time_module.time()
    entries = []
    for date_str, entry in _cache.items():
        age = now - entry.get("timestamp", 0)
        valid = _is_cache_valid(entry)
        entries.append({
            "date": date_str,
            "age_seconds": round(age, 1),
            "valid": valid,
            "data_keys": list(entry.get("data", {}).keys()),
        })

    return {
        "total_cached": len(_cache),
        "ttl_seconds": CACHE_TTL_SECONDS,
        "entries": entries,
        "server_time": datetime.now().isoformat(),
    }

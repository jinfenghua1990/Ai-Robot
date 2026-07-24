"""
板块轮动独立 API

提供板块轮动路径、概念/行业/主题维度对比等数据。
从 market_review.py 的 _build_rotation_section 提取并优化。

端点:
- GET /api/rotation?date=YYYY-MM-DD

缓存策略:
- 内存缓存: 300 秒 (5分钟) TTL - 轮动数据更新频率较低
- 数据源: rotation_engine.build_rotation_context() + MainCentralHub
"""

from __future__ import annotations

import logging
import time as _time_module
from copy import deepcopy
from datetime import datetime
from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

# 复用 market_review 中已验证的数据准备逻辑（内部负责加载前置数据并正确调用引擎）
try:
    from api.hermes_native.market_review import (
        _build_rotation_section,
        _build_market_section,
        _build_themes_section,
        _build_emotion_section,
    )
except ImportError:  # pragma: no cover - 包模式回退
    try:
        from .market_review import (
            _build_rotation_section,
            _build_market_section,
            _build_themes_section,
            _build_emotion_section,
        )
    except ImportError:
        _build_rotation_section = None
        _build_market_section = None
        _build_themes_section = None
        _build_emotion_section = None

# MainCentralHub 用于补充轮动数据
try:
    from api.hermes_native.services.main_central_hub import MainCentralHub
except ImportError:
    MainCentralHub = None

# 与原 market-review 一致: 构建前触发后台自动补数 (带进程内冷却)
try:
    from api.hermes_native.auto_fill_trigger import ensure_auto_fill
except ImportError:  # pragma: no cover
    try:
        from .auto_fill_trigger import ensure_auto_fill
    except ImportError:
        ensure_auto_fill = None

# 复用 market_review 中已验证的数据准备逻辑（负责前置 market/themes/emotion 及正确的引擎调用）
try:
    from api.hermes_native.market_review import (
        _build_rotation_section,
        _build_market_section,
        _build_themes_section,
        _build_emotion_section,
    )
except ImportError:  # pragma: no cover - 包模式回退
    try:
        from .market_review import (
            _build_rotation_section,
            _build_market_section,
            _build_themes_section,
            _build_emotion_section,
        )
    except ImportError:
        _build_rotation_section = None
        _build_market_section = None
        _build_themes_section = None
        _build_emotion_section = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["rotation"])

# 缓存配置
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS: int = 300  # 5 分钟缓存（轮动数据不需要高频刷新）

# 默认空结构（用于 fallback）
DEFAULT_ROTATION = {
    "policy": "realtime_only_for_sector_rotation",
    "mode": "fallback",
    "session": "closed",
    "updated_at": None,
    "review_date": None,
    "realtime_allowed": False,
    "current": {"mainline": [], "watch": [], "alive": []},
    "previous_close": {"mainline": [], "watch": [], "alive": []},
    "comparison": {
        "conclusion": None,
        "basis": [],
        "realtime_allowed": False,
        "by_category": {},
    },
    "history_windows": {"mainline": {}, "watch": {}, "alive": {}},
    "concept_dimensions": {
        "timeline": [],
        "dimensions": [],
        "source": "unavailable",
        "updated_at": None,
        "window_days": 30,
        "fill_mode": "amount_share_rank_daily",
        "unit": "亿",
    },
    "theme_dimensions": {
        "timeline": [],
        "dimensions": [],
        "source": "unavailable",
        "updated_at": None,
        "window_days": 30,
        "unit": "亿",
    },
    "industry_dimensions": {
        "timeline": [],
        "dimensions": [],
        "source": "unavailable",
        "updated_at": None,
        "window_days": 30,
        "unit": "亿",
    },
    "summary": {"text": None, "source": None},
    "source": {"current": "unavailable", "previous_close": "unavailable", "policy": "board_rotation_only"},
}


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


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典"""
    result = deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _is_cache_valid(entry: dict[str, Any]) -> bool:
    if not entry:
        return False
    age = _time_module.time() - entry.get("timestamp", 0)
    return age < CACHE_TTL_SECONDS


def _build_rotation_data(
    review_date: str,
    market: dict = None,
    themes: dict = None,
    emotion: dict = None,
) -> dict[str, Any]:
    """构建板块轮动数据（核心逻辑）"""
    cache_key = f"rotation_{review_date}"
    cached = _cache.get(cache_key)
    if _is_cache_valid(cached):
        logger.debug(f"[rotation] 命中缓存: {review_date}")
        return cached["data"]

    # 与原 market-review 一致: 确保后台自动补数已触发 (rotation 依赖 market/themes/emotion)
    if ensure_auto_fill is not None:
        ensure_auto_fill(review_date)

    try:
        # 调用轮动引擎（通过 market_review 已验证的 section 构建器）
        if _build_rotation_section is None:
            raise ImportError("market_review._build_rotation_section not available")

        # 补齐前置依赖：rotation 需要 market / themes / emotion
        if market is None and _build_market_section is not None:
            market, *_ = _build_market_section(review_date)
        if themes is None and _build_themes_section is not None:
            themes, *_ = _build_themes_section(review_date)
        if emotion is None and _build_emotion_section is not None:
            emotion, *_ = _build_emotion_section(review_date, market or {}, {})

        rotation = _build_rotation_section(
            review_date,
            market or {},
            themes or {},
            emotion or {},
        )

        # 标准化输出
        result = _deep_merge(DEFAULT_ROTATION, rotation or {})
        result["date"] = review_date
        result["review_date"] = review_date
        result["updated_at"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        result["status"] = "ok"

        # 尝试从 MainCentralHub 补充数据
        if MainCentralHub is not None:
            try:
                hub = MainCentralHub()
                package = hub.load_latest_package()

                if package and package.get("market_context", {}).get("rotation"):
                    hub_rotation = package["market_context"]["rotation"]

                    # 合并 hub 数据，保留原始数据的完整性
                    merged = _deep_merge(result, hub_rotation)

                    # 如果 hub 数据的 dimensions 为空，保留原始的
                    base_concept_dims = _safe_list(
                        result.get("concept_dimensions", {}).get("dimensions")
                    )
                    merged_concept_dims = _safe_list(
                        merged.get("concept_dimensions", {}).get("dimensions")
                    )
                    if len(merged_concept_dims) < len(base_concept_dims):
                        merged["concept_dimensions"] = deepcopy(
                            result.get("concept_dimensions", {})
                        )

                    base_industry_dims = _safe_list(
                        result.get("industry_dimensions", {}).get("dimensions")
                    )
                    merged_industry_dims = _safe_list(
                        merged.get("industry_dimensions", {}).get("dimensions")
                    )
                    if len(merged_industry_dims) < len(base_industry_dims):
                        merged["industry_dimensions"] = deepcopy(
                            result.get("industry_dimensions", {})
                        )

                    result = merged
                    result["source"]["hub_merged"] = True
            except Exception as e:
                logger.warning(f"[rotation] MainCentralHub 合并失败: {e}")

        # 写入缓存
        _cache[cache_key] = {
            "data": result,
            "timestamp": _time_module.time(),
        }

        concept_count = len(_safe_list(result.get("concept_dimensions", {}).get("dimensions")))
        industry_count = len(_safe_list(result.get("industry_dimensions", {}).get("dimensions")))

        logger.info(
            f"[rotation] 构建完成: {review_date}, "
            f"mode={result['mode']}, concepts={concept_count}, industries={industry_count}"
        )
        return result

    except Exception as e:
        logger.error(f"[rotation] 构建失败: {e}", exc_info=True)
        fallback = deepcopy(DEFAULT_ROTATION)
        fallback.update({
            "date": review_date,
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "status": "error",
            "error": str(e),
        })
        return fallback


@router.get("/rotation")
async def get_rotation(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取板块轮动路径与维度对比数据

    返回内容包括：

    **核心字段：**
    - **current**: 当日主题分类（mainline/watch/alive）
    - **previous_close**: 前一交易日分类（用于对比）
    - **comparison**: 两日对比结论（持续/加强/减弱/新晋/退潮）
    - **history_windows**: 历史时间窗口数据（近30天）

    **维度分析：**
    - **concept_dimensions**: 概念板块维度资金流/热度变化
      - timeline: 时间序列
      - dimensions: 各板块详细指标
    - **theme_dimensions**: 主题维度分析
    - **industry_dimensions**: 行业维度分析

    **使用场景：**
    - ThemeBattlefield 组件展示轮动路径
    - RotationReportCard 显示对比结论
    - 判断主线是否可持续、观察方向是否值得介入

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "mode": "realtime",
      "current": {
        "mainline": [{"name": "AI算力", "score": 85}],
        "watch": [{"name": "新能源车", "score": 72}]
      },
      "previous_close": {...},
      "comparison": {
        "conclusion": "主线持续加强",
        "basis": ["AI算力连续3天居首"]
      },
      "concept_dimensions": {
        "timeline": [...],
        "dimensions": [...]
      }
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_rotation_data(requested_date)
    return data


@router.get("/rotation/cache-info")
async def get_cache_info():
    """获取轮动 API 缓存状态（调试用）"""
    now = _time_module.time()
    entries = []
    for cache_key, entry in _cache.items():
        age = now - entry.get("timestamp", 0)
        valid = _is_cache_valid(entry)
        entries.append({
            "key": cache_key,
            "age_seconds": round(age, 1),
            "valid": valid,
        })

    return {
        "total_cached": len(_cache),
        "ttl_seconds": CACHE_TTL_SECONDS,
        "engine_available": build_rotation_context is not None,
        "entries": entries,
        "server_time": datetime.now().isoformat(),
    }

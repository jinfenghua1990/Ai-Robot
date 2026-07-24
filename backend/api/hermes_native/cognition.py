"""
认知层与调度门控独立 API

提供市场认知、调度门控、仓位建议等高级决策数据。
从 market_review.py 的 cognition + main_hub 部分提取并优化。

端点:
- GET /api/cognition?date=YYYY-MM-DD
- GET /api/dispatch?date=YYYY-MM-DD

缓存策略:
- cognition: 60 秒 TTL (认知层变化较慢)
- dispatch: 60 门控数据

数据源:
- MainCentralHub (主控中心)
- market_stage_engine
- risk_engine
"""

from __future__ import annotations

import logging
import time as _time_module
from datetime import datetime
from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

# 复用 Hermes 内部引擎
try:
    from api.hermes_native.services.main_central_hub import MainCentralHub, build_main_hub_package
    from api.hermes_native.services.market_stage_engine import build_market_stage
    from api.hermes_native.services.risk_engine import build_risk_assessment
except ImportError:
    MainCentralHub = None
    build_main_hub_package = None
    build_market_stage = None
    build_risk_assessment = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["cognition", "dispatch"])

# 初始化主控中心实例
MAIN_HUB = MainCentralHub() if MainCentralHub else None

# 缓存配置
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS: int = 60  # 1 分钟缓存


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


def _is_cache_valid(entry: dict[str, Any]) -> bool:
    if not entry:
        return False
    age = _time_module.time() - entry.get("timestamp", 0)
    return age < CACHE_TTL_SECONDS


def _build_cognition_data(review_date: str, themes: dict = None, market: dict = None) -> dict[str, Any]:
    """构建认知层数据（核心逻辑）"""
    cache_key = f"cognition_{review_date}"
    cached = _cache.get(cache_key)
    if _is_cache_valid(cached):
        logger.debug(f"[cognition] 命中缓存: {review_date}")
        return cached["data"]

    try:
        # 1. 构建市场阶段认知
        stage = {}
        if build_market_stage:
            stage = build_market_stage(market or {}, themes or {})

        # 2. 构建风险评估
        risk = {}
        if build_risk_assessment:
            risk = build_risk_assessment(
                market or {},
                themes or {},
                {},  # fund_flow
                stage,
            )

        # 3. 提取主线/观察/活跃主题名称
        mainline = []
        watch = []
        alive = []

        if themes:
            for item in _safe_list(themes.get("mainline")):
                name = str(item.get("name") or "").strip()
                if name and name not in mainline:
                    mainline.append(name)

            for item in _safe_list(themes.get("watch")):
                name = str(item.get("name") or "").strip()
                if name and name not in watch:
                    watch.append(name)

            for item in _safe_list(themes.get("alive")):
                name = str(item.get("name") or "").strip()
                if name and name not in alive:
                    alive.append(name)

        # 4. 构建完整认知对象
        result = {
            "date": review_date,
            "stage": stage.get("stage"),
            "stage_score": stage.get("score"),
            "stage_description": stage.get("description"),
            "mainline": mainline[:10],
            "watch": watch[:10],
            "alive": alive[:10],
            "risk_level": risk.get("risk_level"),
            "warnings": _safe_list(risk.get("warnings", []))[:10],
            "signals": {
                "stage": _safe_list(stage.get("signals", []))[:5],
                "theme": _safe_list((themes or {}).get("signals", []))[:5],
                "risk": _safe_list(risk.get("signals", []))[:5],
            },
            "position": risk.get("position_suggestion"),
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": "cognition_engine",
            "status": "ok",
            "breakdown": {
                "stage": {
                    "score": stage.get("score"),
                    "description": stage.get("description"),
                    "drivers": _safe_list(stage.get("drivers", []))[:3],
                    "signals": _safe_list(stage.get("signals", []))[:3],
                },
                "theme": {
                    "mainline": mainline[:5],
                    "watch": watch[:5],
                    "alive": alive[:5],
                    "signals": _safe_list((themes or {}).get("signals", []))[:3],
                },
                "risk": {
                    "level": risk.get("risk_level"),
                    "score": risk.get("risk_score"),
                    "drivers": _safe_list(risk.get("drivers", []))[:3],
                    "warnings": _safe_list(risk.get("warnings", []))[:3],
                },
            },
        }

        # 写入缓存
        _cache[cache_key] = {
            "data": result,
            "timestamp": _time_module.time(),
        }

        logger.info(
            f"[cognition] 构建完成: {review_date}, "
            f"stage={result['stage']}, level={result['risk_level']}"
        )
        return result

    except Exception as e:
        logger.error(f"[cognition] 构建失败: {e}", exc_info=True)
        return {
            "date": review_date,
            "stage": None,
            "error": str(e),
            "status": "error",
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        }


def _build_dispatch_data(review_date: str) -> dict[str, Any]:
    """构建调度门控数据"""
    cache_key = f"dispatch_{review_date}"
    cached = _cache.get(cache_key)
    if _is_cache_valid(cached):
        logger.debug(f"[dispatch] 命中缓存: {review_date}")
        return cached["data"]

    try:
        if MAIN_HUB is None:
            raise ImportError("MainCentralHub not available")

        # 加载最新的 hub package
        package = MAIN_HUB.load_latest_package()

        if not package:
            if build_main_hub_package:
                package = build_main_hub_package([], {}, {}, None, None)
            else:
                raise ValueError("无法加载主控中心数据")

        dispatch = package.get("dispatch", {})
        market_context = package.get("market_context", {})

        result = {
            "date": review_date,
            "market_stage": market_context.get("market_stage") or market_context.get("stage") or "",
            "emotion_score": market_context.get("emotion_score"),
            "risk_level": market_context.get("risk_level") or "中",
            "can_open_position": dispatch.get("can_open_position", False),
            "position_suggestion": (
                dispatch.get("position_suggestion")
                or market_context.get("suggested_position")
                or market_context.get("position_suggestion")
            ),
            "mainline": _safe_list(dispatch.get("mainline", [])),
            "watch": _safe_list(dispatch.get("watch", [])),
            "alive": _safe_list(dispatch.get("alive", [])),
            "stage_score": market_context.get("stage_score"),
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": "main_central_hub",
            "hub_status": package.get("status", "unknown"),
        }

        # 写入缓存
        _cache[cache_key] = {
            "data": result,
            "timestamp": _time_module.time(),
        }

        logger.info(
            f"[dispatch] 构建完成: {review_date}, "
            f"can_open={result['can_open_position']}"
        )
        return result

    except Exception as e:
        logger.error(f"[dispatch] 构建失败: {e}", exc_info=True)
        return {
            "date": review_date,
            "can_open_position": False,
            "error": str(e),
            "status": "error",
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        }


# ==================== API 端点 ====================

@router.get("/cognition")
async def get_cognition(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取市场认知层综合数据

    这是 Hermes 指挥舱的核心决策层，整合了：
    - **stage/stage_score**: 市场阶段及评分
    - **mainline/watch/alive**: 三大主题分类（名称列表）
    - **risk_level**: 综合风险等级
    - **signals**: 多维信号汇总（stage/theme/risk）
    - **position**: 仓位建议
    - **breakdown**: 各维度详细拆解

    用途：
    - 前端 HeaderBar 显示当前市场状态
    - 调度系统决定是否开仓/加仓/减仓
    - 自动化交易策略的输入参数

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "stage": "加速",
      "stage_score": 72.5,
      "mainline": ["AI算力", "半导体"],
      "watch": ["新能源车"],
      "alive": ["消费电子"],
      "risk_level": "中",
      "position": "60%-70%",
      "breakdown": {...}
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_cognition_data(requested_date)
    return data


@router.get("/dispatch")
async def get_dispatch(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取调度门控数据

    返回交易决策的关键门控参数：
    - **can_open_position**: 是否允许开新仓（True/False）
    - **position_suggestion**: 推荐仓位比例
    - **mainline/watch/alive**: 当前可操作的方向
    - **risk_level**: 当前风险等级

    使用场景：
    ```python
    dispatch = await get_dispatch(date="today")
    if dispatch["can_open_position"]:
        execute_trade(direction=dispatch["mainline"][0])
    else:
        reduce_position(target=dispatch["position_suggestion"])
    ```

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "can_open_position": true,
      "position_suggestion": "65%",
      "market_stage": "加速",
      "risk_level": "中",
      "mainline": ["AI算力", "半导体设备"]
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_dispatch_data(requested_date)
    return data


@router.get("/cognition/cache-info")
async def get_cache_info():
    """获取认知层 API 缓存状态（调试用）"""
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
        "main_hub_available": MAIN_HUB is not None,
        "entries": entries[:10],
        "server_time": datetime.now().isoformat(),
    }

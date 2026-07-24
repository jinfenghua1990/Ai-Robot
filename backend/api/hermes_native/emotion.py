"""
市场情绪与风险独立 API

提供市场情绪指标、风险警告、明日计划等数据。
从 market_review.py 的 _build_emotion_section + risk + tomorrow_plan 提取并优化。

端点:
- GET /api/emotion?date=YYYY-MM-DD
- GET /api/risk?date=YYYY-MM-DD
- GET /api/tomorrow-plan?date=YYYY-MM-DD

缓存策略:
- emotion: 60 秒 TTL (情绪指标变化较慢)
- risk: 300 秒 TTL (风险评估不需要高频刷新)
- tomorrow_plan: 600 秒 TTL (明日计划基本不变)

数据源:
- market_stage_engine.build_market_stage()
- risk_engine.build_risk_assessment()
- tomorrow_plan_engine.build_tomorrow_plan()
"""

from __future__ import annotations

import logging
import time as _time_module
from datetime import datetime
from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

# 复用 Hermes 内部引擎
try:
    from api.hermes_native.services.market_stage_engine import build_market_stage
    from api.hermes_native.services.risk_engine import build_risk_assessment
    from api.hermes_native.services.tomorrow_plan_engine import build_tomorrow_plan
except ImportError:
    build_market_stage = None
    build_risk_assessment = None
    build_tomorrow_plan = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["emotion", "risk", "plan"])

# 独立缓存（每个维度不同 TTL）
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL: dict[str, int] = {
    "emotion": 60,
    "risk": 300,
    "tomorrow_plan": 600,
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


def _is_cache_valid(cache_key: str, entry: dict[str, Any]) -> bool:
    if not entry:
        return False
    age = _time_module.time() - entry.get("timestamp", 0)
    ttl = CACHE_TTL.get(cache_key, 60)
    return age < ttl


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_int(value: Any, default=None):
    if value in (None, "", []):
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _to_float(value: Any, default=None):
    if value in (None, "", []):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _build_emotion_data(review_date: str, market: dict = None, themes: dict = None) -> dict[str, Any]:
    """构建市场情绪数据"""
    cache_key = f"emotion_{review_date}"
    cached = _cache.get(cache_key)
    if _is_cache_valid("emotion", cached):
        logger.debug(f"[emotion] 命中缓存: {review_date}")
        return cached["data"]

    try:
        if build_market_stage is None:
            raise ImportError("market_stage_engine not available")

        stage = build_market_stage(market or {}, themes or {})

        result = {
            "date": review_date,
            "stage": stage.get("stage"),
            "display_stage": stage.get("display_label") or stage.get("stage"),
            "score": stage.get("score"),
            "description": stage.get("description"),
            "signals": _safe_list(stage.get("signals", []))[:5],
            "drivers": _safe_list(stage.get("drivers", []))[:3],
            "limit_up": None,  # 需要从外部传入或查询
            "broken": None,
            "limit_down": None,
            "explain": (
                f"{stage.get('description') or '市场结构待确认。'}；"
                + "；".join(stage.get("signals", [])[:3])
            ),
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": "market_stage_engine",
            "status": "ok",
        }

        # 写入缓存
        _cache[cache_key] = {
            "data": result,
            "timestamp": _time_module.time(),
        }
        logger.info(f"[emotion] 构建完成: {review_date}, stage={result['stage']}")
        return result

    except Exception as e:
        logger.error(f"[emotion] 构建失败: {e}", exc_info=True)
        return {
            "date": review_date,
            "stage": None,
            "score": None,
            "error": str(e),
            "status": "error",
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        }


def _build_risk_data(review_date: str, market: dict = None, themes: dict = None, fund_flow: dict = None) -> dict[str, Any]:
    """构建风险警告数据"""
    cache_key = f"risk_{review_date}"
    cached = _cache.get(cache_key)
    if _is_cache_valid("risk", cached):
        logger.debug(f"[risk] 命中缓存: {review_date}")
        return cached["data"]

    try:
        if build_risk_assessment is None:
            raise ImportError("risk_engine not available")

        # 获取情绪阶段（用于风险评估）
        stage = {}
        if build_market_stage:
            stage = build_market_stage(market or {}, themes or {})

        risk = build_risk_assessment(
            market or {},
            themes or {},
            fund_flow or {},
            stage,
        )

        result = {
            "date": review_date,
            "risk_level": risk.get("risk_level"),  # 低/中/高
            "risk_score": risk.get("risk_score"),
            "warnings": _safe_list(risk.get("warnings", []))[:10],
            "drivers": _safe_list(risk.get("drivers", []))[:5],
            "signals": _safe_list(risk.get("signals", []))[:10],
            "position_suggestion": risk.get("position_suggestion"),
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": "risk_engine",
            "status": "ok",
        }

        _cache[cache_key] = {
            "data": result,
            "timestamp": _time_module.time(),
        }
        logger.info(
            f"[risk] 构建完成: {review_date}, "
            f"level={result['risk_level']}, warnings={len(result['warnings'])}条"
        )
        return result

    except Exception as e:
        logger.error(f"[risk] 构建失败: {e}", exc_info=True)
        return {
            "date": review_date,
            "risk_level": None,
            "warnings": [],
            "error": str(e),
            "status": "error",
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        }


def _build_tomorrow_plan_data(review_date: str, market: dict = None, themes: dict = None) -> dict[str, Any]:
    """构建明日计划数据"""
    cache_key = f"tomorrow_plan_{review_date}"
    cached = _cache.get(cache_key)
    if _is_cache_valid("tomorrow_plan", cached):
        logger.debug(f"[tomorrow_plan] 命中缓存: {review_date}")
        return cached["data"]

    try:
        if build_tomorrow_plan is None:
            raise ImportError("tomorrow_plan_engine not available")

        # 获取情绪和风险（用于生成计划）
        stage = {}
        risk = {}
        if build_market_stage:
            stage = build_market_stage(market or {}, themes or {})
        if build_risk_assessment:
            risk = build_risk_assessment(market or {}, themes or {}, {}, stage)

        plan = build_tomorrow_plan(stage, themes or {}, risk, market or {})

        result = {
            "date": review_date,
            "attack": _safe_list(plan.get("attack", []))[:5],   # 攻击方向
            "secondary": _safe_list(plan.get("secondary", []))[:5],  # 备选方向
            "defense": _safe_list(plan.get("defense", []))[:5],     # 防御方向
            "position": plan.get("position"),  # 仓位建议
            "strategy_notes": plan.get("strategy_notes", ""),
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": "tomorrow_plan_engine",
            "status": "ok",
        }

        _cache[cache_key] = {
            "data": result,
            "timestamp": _time_module.time(),
        }
        logger.info(
            f"[tomorrow_plan] 构建完成: {review_date}, "
            f"attack={len(result['attack'])}, defense={len(result['defense'])}"
        )
        return result

    except Exception as e:
        logger.error(f"[tomorrow_plan] 构建失败: {e}", exc_info=True)
        return {
            "date": review_date,
            "attack": [],
            "defense": [],
            "error": str(e),
            "status": "error",
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        }


# ==================== API 端点 ====================

@router.get("/emotion")
async def get_emotion(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取市场情绪指标

    返回内容包括：
    - **stage**: 市场阶段（启动/发酵/加速/退潮/冰点）
    - **score**: 情绪评分（0-100）
    - **signals**: 情绪信号列表（驱动因素）
    - **explain**: 情绪解读文字说明

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "stage": "加速",
      "score": 72.5,
      "display_stage": "强势 · 加速",
      "signals": ["涨停数增加", "北向资金流入"],
      "explain": "市场处于强势加速阶段...",
      "updated_at": "2026/07/18 15:00:00"
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_emotion_data(requested_date)
    return data


@router.get("/risk")
async def get_risk(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取风险评估数据

    返回内容包括：
    - **risk_level**: 风险等级（低/中/高）
    - **risk_score**: 风险评分（0-100）
    - **warnings**: 风险警告列表
    - **position_suggestion**: 仓位建议（重仓/半仓/轻仓/空仓）

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "risk_level": "中",
      "risk_score": 55.0,
      "warnings": ["注意高位股回调风险"],
      "position_suggestion": "半仓",
      "updated_at": "2026/07/18 15:30:00"
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_risk_data(requested_date)
    return data


@router.get("/tomorrow-plan")
async def get_tomorrow_plan(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取明日交易计划建议

    返回内容包括：
    - **attack**: 攻击方向（推荐关注的主线/热点）
    - **secondary**: 备选方向（观察池中的潜力板块）
    - **defense**: 防御方向（需规避的风险领域）
    - **position**: 仓位建议

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "attack": ["AI算力龙头", "半导体设备"],
      "secondary": ["新能源车产业链"],
      "defense": ["高位题材股", "业绩雷区"],
      "position": "60%-70%",
      "updated_at": "2026/07/18 16:00:00"
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_tomorrow_plan_data(requested_date)
    return data


@router.get("/emotion/cache-info")
async def get_all_cache_info():
    """获取情绪/风险/计划 API 缓存状态（调试用）"""
    now = _time_module.time()
    summary = {}

    for key in ["emotion", "risk", "tomorrow_plan"]:
        entries = []
        for cache_key, entry in _cache.items():
            if cache_key.startswith(key):
                age = now - entry.get("timestamp", 0)
                valid = _is_cache_valid(key, entry)
                entries.append({
                    "key": cache_key,
                    "age_seconds": round(age, 1),
                    "valid": valid,
                })

        summary[key] = {
            "total_cached": len(entries),
            "ttl_seconds": CACHE_TTL[key],
            "entries": entries[:5],  # 只显示最近5条
        }

    return {
        **summary,
        "server_time": datetime.now().isoformat(),
    }

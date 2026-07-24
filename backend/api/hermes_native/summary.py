"""
市场复盘摘要独立 API

提供市场综合摘要、文字总结、明日要点等数据。
从 market_review.py 的 _build_summary + rotation_report 提取并优化。

端点:
- GET /api/summary?date=YYYY-MM-DD

缓存策略:
- 内存缓存: 600 秒 (10分钟) TTL - 摘要数据生成成本高，不需要高频刷新
- 数据源: summary_engine.build_summary() + market_rotation_report

注意:
- 摘要生成涉及多个引擎聚合，首次调用可能较慢（1-3秒）
- 建议前端在用户滚动到该区域时才加载
"""

from __future__ import annotations

import logging
import time as _time_module
from datetime import datetime
from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

# 复用 Hermes 内部引擎
try:
    from api.hermes_native.services.summary_engine import build_summary
    from api.hermes_native.services.market_stage_engine import build_market_stage
    from api.hermes_native.services.risk_engine import build_risk_assessment
    from api.hermes_native.services.tomorrow_plan_engine import build_tomorrow_plan
    from api.hermes_native.services.market_rotation_report import (
        build_market_rotation_report,
        write_market_rotation_report,
    )
except ImportError:
    build_summary = None
    build_market_stage = None
    build_risk_assessment = None
    build_tomorrow_plan = None
    build_market_rotation_report = None
    write_market_rotation_report = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["summary"])

# 缓存配置 (较长的 TTL，因为摘要计算成本高)
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS: int = 600  # 10 分钟缓存


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


def _build_summary_data(
    review_date: str,
    market: dict = None,
    themes: dict = None,
    fund_flow: dict = None,
    emotion: dict = None,
) -> dict[str, Any]:
    """构建市场复盘摘要数据（核心逻辑）"""
    cache_key = f"summary_{review_date}"
    cached = _cache.get(cache_key)
    if _is_cache_valid(cached):
        logger.debug(f"[summary] 命中缓存: {review_date}")
        return cached["data"]

    try:
        if build_summary is None:
            raise ImportError("summary_engine not available")

        # 构建依赖数据（如果未传入）
        stage = {}
        risk = {}

        if build_market_stage and not emotion:
            stage = build_market_stage(market or {}, themes or {})
            emotion = {
                "stage": stage.get("stage"),
                "score": stage.get("score"),
                "description": stage.get("description"),
                "signals": stage.get("signals", []),
            }

        if build_risk_assessment and not (market and themes):
            risk = build_risk_assessment(
                market or {},
                themes or {},
                fund_flow or {},
                stage,
            )

        # 调用摘要引擎
        summary = build_summary(
            stage=stage,
            themes=themes or {},
            risk=risk,
            market=market or {},
            fund_flow=fund_flow or {},
        )

        result = {
            "date": review_date,
            "text": summary.get("text") or summary.get("markdown"),
            "markdown": summary.get("markdown") or summary.get("text"),
            "key_points": _safe_list(summary.get("key_points"))[:5],
            "highlights": _safe_list(summary.get("highlights"))[:3],
            "data_sources_used": summary.get("sources", []),
            "generated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "source": "summary_engine",
            "status": "ok",
        }

        # 尝试生成轮动报告（如果可用）
        if build_market_rotation_report:
            try:
                review_context = {
                    "date": review_date,
                    "resolved_date": review_date,
                    "market": market or {},
                    "themes": themes or {},
                    "fund_flow": fund_flow or {},
                    "emotion": emotion or {},
                    "rotation": {},
                    "cognition": {},
                }
                rotation_report = build_market_rotation_report(review_context)

                if write_market_rotation_report:
                    report_paths = write_market_rotation_report(rotation_report)
                    rotation_report["paths"] = report_paths

                result["rotation_report"] = {
                    "title": rotation_report.get("title", ""),
                    "date": rotation_report.get("date", ""),
                    "summary": rotation_report.get("summary", ""),
                    "sections": rotation_report.get("sections", {}),
                    "source": rotation_report.get("source", ""),
                    "paths": rotation_report.get("paths", {}),
                }
            except Exception as e:
                logger.warning(f"[summary] 轮动报告生成失败: {e}")
                result["rotation_report_error"] = str(e)

        # 写入缓存
        _cache[cache_key] = {
            "data": result,
            "timestamp": _time_module.time(),
        }

        logger.info(
            f"[summary] 构建完成: {review_date}, "
            f"text_length={len(str(result.get('text', '')))}"
        )
        return result

    except Exception as e:
        logger.error(f"[summary] 构建失败: {e}", exc_info=True)
        return {
            "date": review_date,
            "text": None,
            "error": str(e),
            "status": "error",
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        }


@router.get("/summary")
async def get_summary(
    date: Optional[str] = Query(default=None, description="查询日期 YYYY-MM-DD，默认今天"),
):
    """
    获取市场复盘综合摘要

    这是 Hermes 盘后复盘中"最重"的接口，整合了所有维度的分析结果：

    **核心字段：**
    - **text/markdown**: 文字摘要（纯文本/Markdown格式）
      - 市场整体表现概述
      - 主线热点回顾
      - 风险提示
    - **key_points**: 关键要点列表（5条以内）
    - **highlights**: 亮点事件（3条以内）
    - **rotation_report**: 板块轮动详细报告（PDF/HTML路径）

    **性能说明：**
    - 首次调用需 1-3 秒（多引擎聚合）
    - 后续调用走缓存，响应 <50ms
    - 建议：使用懒加载或 Intersection Observer 触发

    **使用场景：**
    - 页面底部的"今日总结"卡片
    - 导出 PDF 报告的数据来源
    - 推送消息的摘要文本

    示例响应:
    ```json
    {
      "date": "2026-07-18",
      "text": "今日A股三大指数集体收涨...",
      "markdown": "# 市场复盘\\n## 概述\\n今日A股...",
      "key_points": [
        "AI算力板块领涨，涨幅超3%",
        "北向资金净流入25.6亿",
        "涨停45家，炸板率12.3%"
      ],
      "rotation_report": {
        "title": "板块轮动与主力动向收盘复盘报告",
        "paths": {"html": "/reports/2026-07-18.html"}
      }
    }
    ```
    """
    requested_date = _normalize_date(date)
    data = _build_summary_data(requested_date)
    return data


@router.get("/summary/cache-info")
async def get_cache_info():
    """获取摘要 API 缓存状态（调试用）"""
    now = _time_module.time()
    entries = []
    for cache_key, entry in _cache.items():
        age = now - entry.get("timestamp", 0)
        valid = _is_cache_valid(entry)
        data = entry.get("data", {})
        entries.append({
            "key": cache_key,
            "age_seconds": round(age, 1),
            "valid": valid,
            "text_length": len(str(data.get("text", ""))),
        })

    return {
        "total_cached": len(_cache),
        "ttl_seconds": CACHE_TTL_SECONDS,
        "engines_available": {
            "summary": build_summary is not None,
            "rotation_report": build_market_rotation_report is not None,
        },
        "entries": entries,
        "server_time": datetime.now().isoformat(),
    }

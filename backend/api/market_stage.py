"""
Market Stage API — 市场情绪 6 阶段 (迁移自 hermes-cockpit market_stage_engine)

6 阶段: 冰点 / 修复 / 发酵 / 高潮 / 分歧 / 退潮
每阶段对应仓位建议: 2-3成 / 4成 / 6成 / 7成 / 4-5成 / 3成

数据源: StockFlow 表实时统计 (涨停/跌停/涨跌家数) + ConceptSectorFlow 热度
算法: 综合热度/涨停数/涨跌广度/炸板率/跌停数 → 0-100 评分 → 6 阶段映射
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, date
from typing import Any, Optional

from fastapi import APIRouter
from sqlalchemy import func

from db.session import get_db_session
from db.models import StockFlow, ConceptSectorFlow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market-stage", tags=["market-stage"])

# ─── inline 缓存 (装饰器与 FastAPI endpoint 不兼容，改用 dict + TTL) ──────────
_MARKET_STAGE_CACHE: dict[str, dict] = {}  # key -> {data, ts, ttl}
_MS_CACHE_TTL_LATEST = 30        # 最新交易日 30s (盘中实时更新)
_MS_CACHE_TTL_HISTORICAL = 600   # 历史日期 10min (数据稳定)


# ─── 6 阶段配置 ────────────────────────────────────────────────────────────────

STAGE_DESCRIPTIONS = {
    "冰点": "短线情绪偏弱，资金仍在等待方向。",
    "修复": "市场进入试探性修复，承接开始出现。",
    "发酵": "主线扩散中，资金开始向核心方向集中。",
    "高潮": "强势主线集中爆发，赚钱效应升温。",
    "分歧": "高位分歧加剧，强弱切换明显。",
    "退潮": "短线情绪回落，风险释放阶段。",
}

POSITION_GUIDANCE = {
    "冰点": "2~3成",
    "修复": "4成",
    "发酵": "6成",
    "高潮": "7成",
    "分歧": "4~5成",
    "退潮": "3成",
}

STAGE_COLORS = {
    "冰点": "#3b82f6",    # 蓝
    "修复": "#06b6d4",    # 青
    "发酵": "#f59e0b",    # 琥珀
    "高潮": "#ef4444",    # 红
    "分歧": "#a855f7",    # 紫
    "退潮": "#6b7280",    # 灰
}


def _stage_description(stage: str) -> str:
    return STAGE_DESCRIPTIONS.get(stage, "市场结构待确认。")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ─── 6 阶段核心算法 (移植自 hermes market_stage_engine) ────────────────────────

def build_market_stage(
    limit_up: int,
    broken: int,
    limit_down: int,
    up: int,
    down: int,
    heat_value: float,
    theme_strength: float = 0.0,
    mainline_count: int = 0,
) -> dict[str, Any]:
    """根据市场广度数据计算情绪阶段

    参数:
        limit_up: 涨停家数
        broken: 炸板家数 (涨停后开板)
        limit_down: 跌停家数
        up: 上涨家数
        down: 下跌家数
        heat_value: 市场热度 0-100
        theme_strength: 主线强度 0-100 (可选)
        mainline_count: 主线数量 (可选)

    返回: {stage, score, description, position, signals, drivers, color}
    """
    broken_rate = (broken / limit_up) if limit_up > 0 else (1.0 if broken else 0.0)
    breadth_net = up - down
    breadth_total = up + down

    score = 0.0
    signals: list[str] = []
    drivers: list[dict[str, Any]] = []

    def push_driver(name: str, value: Any, impact: float, reason: str) -> None:
        drivers.append({"name": name, "value": value, "impact": impact, "reason": reason})

    # 热度评分
    if heat_value >= 70:
        score += 20
        signals.append("市场热度高位")
        push_driver("市场热度", round(heat_value, 2), 20, "热度处于高位，资金参与度强")
    elif heat_value >= 55:
        score += 15
        signals.append("市场热度偏强")
        push_driver("市场热度", round(heat_value, 2), 15, "热度偏强，情绪仍在扩散")
    elif heat_value >= 40:
        score += 8
        signals.append("市场热度温和")
        push_driver("市场热度", round(heat_value, 2), 8, "热度温和，属于试探修复区")
    elif heat_value >= 25:
        score += 3
        signals.append("市场热度仍在修复")
        push_driver("市场热度", round(heat_value, 2), 3, "热度仍在修复，但未回到强势区")
    else:
        signals.append("市场热度偏弱")
        push_driver("市场热度", round(heat_value, 2), 0, "热度偏弱，资金参与不足")

    # 涨停家数评分
    if limit_up >= 80:
        score += 20
        signals.append("涨停家数极高")
        push_driver("涨停家数", limit_up, 20, "涨停扩张明显，赚钱效应很强")
    elif limit_up >= 50:
        score += 17
        signals.append("涨停家数活跃")
        push_driver("涨停家数", limit_up, 17, "涨停家数保持活跃")
    elif limit_up >= 30:
        score += 12
        signals.append("涨停家数处于扩散")
        push_driver("涨停家数", limit_up, 12, "涨停家数进入扩散区间")
    elif limit_up >= 15:
        score += 7
        signals.append("涨停家数开始回暖")
        push_driver("涨停家数", limit_up, 7, "涨停家数回暖但仍偏中性")
    elif limit_up > 0:
        score += 3
        signals.append("仍有零散涨停")
        push_driver("涨停家数", limit_up, 3, "仍有零散活跃点，但不足以形成主升")

    # 涨跌广度评分
    if breadth_net >= 2000:
        score += 15
        signals.append("上涨家数明显占优")
        push_driver("涨跌家数", f"{up}:{down}", 15, "上涨家数明显占优，市场广度强")
    elif breadth_net >= 1000:
        score += 12
        signals.append("市场广度偏强")
        push_driver("涨跌家数", f"{up}:{down}", 12, "广度偏强，资金扩散较好")
    elif breadth_net >= 500:
        score += 8
        signals.append("市场广度温和回暖")
        push_driver("涨跌家数", f"{up}:{down}", 8, "广度温和回暖")
    elif breadth_net > 0:
        score += 4
        signals.append("广度略偏正")
        push_driver("涨跌家数", f"{up}:{down}", 4, "上涨略多于下跌")
    elif breadth_net <= -1000:
        score -= 12
        signals.append("下跌家数占优")
        push_driver("涨跌家数", f"{up}:{down}", -12, "下跌家数明显占优")
    elif breadth_net <= -500:
        score -= 8
        signals.append("市场广度偏弱")
        push_driver("涨跌家数", f"{up}:{down}", -8, "广度偏弱，承接不足")

    # 主线强度评分
    if theme_strength >= 75:
        score += 18
        signals.append("主线强度高")
        push_driver("主线强度", round(theme_strength, 2), 18, "主线强度高，方向性明确")
    elif theme_strength >= 55:
        score += 12
        signals.append("主线强度清晰")
        push_driver("主线强度", round(theme_strength, 2), 12, "主线强度清晰")
    elif theme_strength >= 35:
        score += 7
        signals.append("主线仍在扩散")
        push_driver("主线强度", round(theme_strength, 2), 7, "主线仍在扩散")
    elif theme_strength > 0:
        score += 3
        signals.append("主线尚在孕育")
        push_driver("主线强度", round(theme_strength, 2), 3, "主线尚在孕育")

    # 炸板率评分
    if broken_rate >= 0.35:
        score -= 18
        signals.append("炸板率偏高")
        push_driver("炸板率", round(broken_rate, 4), -18, "炸板率偏高，短线兑现压力加大")
    elif broken_rate >= 0.2:
        score -= 10
        signals.append("炸板率抬升")
        push_driver("炸板率", round(broken_rate, 4), -10, "炸板率开始抬升")
    elif broken_rate >= 0.1:
        score -= 5
        signals.append("炸板率略有压力")
        push_driver("炸板率", round(broken_rate, 4), -5, "炸板率略有压力")

    # 跌停数评分
    if limit_down >= 20:
        score -= 18
        signals.append("跌停扩散明显")
        push_driver("跌停数", limit_down, -18, "跌停扩散明显，尾部风险增大")
    elif limit_down >= 10:
        score -= 10
        signals.append("跌停数量偏多")
        push_driver("跌停数", limit_down, -10, "跌停数量偏多")
    elif limit_down >= 5:
        score -= 5
        signals.append("跌停仍需关注")
        push_driver("跌停数", limit_down, -5, "跌停仍需关注")

    # 主线覆盖加分
    if mainline_count >= 3 and limit_up >= 30 and broken_rate <= 0.15:
        score += 5
        signals.append("主线覆盖面较好")
        push_driver("主线覆盖", mainline_count, 5, "主线覆盖面较好，资金并未只集中单点")

    # 一致性预警
    if breadth_total and abs(breadth_net) / breadth_total < 0.1 and limit_up >= 30:
        signals.append("一致性较高")
        push_driver("一致性", round(abs(breadth_net) / breadth_total, 4), 0, "涨跌家数过于一致，后续切换风险需要注意")

    score = round(_clamp(score, 0.0, 100.0), 0)

    # 6 阶段判定
    if limit_down >= 20 or (heat_value < 20 and limit_up <= 10 and breadth_net < 0):
        stage = "退潮"
    elif broken_rate >= 0.35 and limit_up >= 30:
        stage = "分歧"
    elif limit_up >= 50 and broken_rate <= 0.18 and heat_value >= 60 and breadth_net > 0 and theme_strength >= 55:
        stage = "高潮"
    elif limit_up >= 30 and breadth_net > 0 and theme_strength >= 45 and heat_value >= 40:
        stage = "发酵"
    elif breadth_net >= 0 or heat_value >= 35 or limit_up >= 15:
        stage = "修复"
    else:
        stage = "冰点"

    if stage == "退潮":
        signals.append("短线情绪回落")
    elif stage == "分歧":
        signals.append("高位分歧显现")
    elif stage == "高潮":
        signals.append("主线集中爆发")
    elif stage == "发酵":
        signals.append("主线扩散中")
    elif stage == "修复":
        signals.append("市场试探性修复")
    else:
        signals.append("市场仍在冰点区")

    return {
        "stage": stage,
        "score": int(score),
        "description": _stage_description(stage),
        "position": POSITION_GUIDANCE.get(stage, ""),
        "color": STAGE_COLORS.get(stage, "#6b7280"),
        "signals": signals[:8],
        "drivers": drivers[:8],
        "metrics": {
            "limit_up": limit_up,
            "broken": broken,
            "limit_down": limit_down,
            "up": up,
            "down": down,
            "heat_value": round(heat_value, 2),
            "broken_rate": round(broken_rate, 4),
            "breadth_net": breadth_net,
            "theme_strength": round(theme_strength, 2),
            "mainline_count": mainline_count,
        },
    }


# ─── 从 StockFlow 实时统计市场广度 ─────────────────────────────────────────────

def _compute_heat(limit_up: int, up: int, down: int, total: int) -> float:
    """简化版热度计算: 涨停权重 40% + 涨跌比权重 30% + 涨停绝对值权重 30%"""
    if total == 0:
        return 0.0
    up_ratio = up / total
    # 涨停数映射到 0-100: 0只=0, 30只=50, 80只=100
    limit_up_score = min(100, limit_up * 1.25)
    # 涨跌比映射: 全跌=0, 平=50, 全涨=100
    breadth_score = up_ratio * 100
    heat = limit_up_score * 0.5 + breadth_score * 0.5
    return round(_clamp(heat, 0, 100), 2)


@router.get("")
def get_market_stage(date: Optional[str] = None):
    """获取当日市场情绪阶段 (从 StockFlow 实时统计)

    date: YYYYMMDD (可选, 默认最新交易日)
    返回: {stage, score, description, position, color, signals, drivers, metrics, trade_date}
    """
    cache_key = date or "__latest__"
    entry = _MARKET_STAGE_CACHE.get(cache_key)
    if entry and time.time() - entry['ts'] < entry['ttl']:
        return entry['data']

    result = _compute_market_stage(date)
    ttl = _MS_CACHE_TTL_HISTORICAL if date else _MS_CACHE_TTL_LATEST
    _MARKET_STAGE_CACHE[cache_key] = {'data': result, 'ts': time.time(), 'ttl': ttl}
    return result


def _compute_market_stage(date: Optional[str] = None) -> dict:
    with get_db_session() as db:
        # 确定查询日期
        target_date = date
        if not target_date:
            latest = db.query(func.max(StockFlow.trade_date)).scalar()
            if not latest:
                return {
                    "stage": "冰点",
                    "score": 0,
                    "description": _stage_description("冰点"),
                    "position": POSITION_GUIDANCE["冰点"],
                    "color": STAGE_COLORS["冰点"],
                    "signals": ["无数据"],
                    "drivers": [],
                    "metrics": {},
                    "trade_date": None,
                    "error": "StockFlow 表无数据",
                }
            target_date = latest

        # 统计涨跌停 + 涨跌家数
        rows = db.query(StockFlow.price_chg).filter(StockFlow.trade_date == target_date).all()
        if not rows:
            return {
                "stage": "冰点",
                "score": 0,
                "description": _stage_description("冰点"),
                "position": POSITION_GUIDANCE["冰点"],
                "color": STAGE_COLORS["冰点"],
                "signals": [f"{target_date} 无数据"],
                "drivers": [],
                "metrics": {},
                "trade_date": str(target_date),
                "error": f"{target_date} 当日无 StockFlow 数据",
            }

        limit_up = 0
        limit_down = 0
        up = 0
        down = 0
        flat = 0
        for (chg,) in rows:
            if chg is None:
                continue
            chg_f = float(chg)
            if chg_f >= 9.8:
                limit_up += 1
            elif chg_f <= -9.8:
                limit_down += 1
            if chg_f > 0:
                up += 1
            elif chg_f < 0:
                down += 1
            else:
                flat += 1

        total = up + down + flat
        # 炸板数估算 (无盘中数据，用 limit_up * 0.15 估算)
        broken = int(limit_up * 0.15)
        # 热度计算
        heat = _compute_heat(limit_up, up, down, total)

        # 主线强度: 从 ConceptSectorFlow 取热度 top 板块的平均强度
        theme_strength = 0.0
        mainline_count = 0
        try:
            sector_rows = db.query(ConceptSectorFlow).filter(
                ConceptSectorFlow.trade_date == target_date,
            ).order_by(ConceptSectorFlow.net_flow.desc()).limit(5).all()
            if sector_rows:
                # 主线 = 净流入为正的板块数
                mainline_count = sum(1 for s in sector_rows if float(s.net_flow or 0) > 0)
                # 简化: 用净流入正的板块比例 × 涨停数映射
                if mainline_count > 0:
                    theme_strength = min(100, mainline_count * 20 + limit_up * 0.5)
        except Exception as e:
            logger.warning(f"查询 ConceptSectorFlow 失败: {e}")

        result = build_market_stage(
            limit_up=limit_up,
            broken=broken,
            limit_down=limit_down,
            up=up,
            down=down,
            heat_value=heat,
            theme_strength=theme_strength,
            mainline_count=mainline_count,
        )
        result["trade_date"] = str(target_date)
        result["metrics"]["flat"] = flat
        result["metrics"]["total"] = total
        return result


@router.get("/config")
def get_stage_config():
    """返回 6 阶段配置 (供前端展示用)"""
    return {
        "stages": [
            {"key": k, "description": v, "position": POSITION_GUIDANCE[k], "color": STAGE_COLORS[k]}
            for k, v in STAGE_DESCRIPTIONS.items()
        ],
        "stage_order": ["冰点", "修复", "发酵", "高潮", "分歧", "退潮"],
    }

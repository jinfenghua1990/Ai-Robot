from __future__ import annotations

from typing import Any, Mapping, Optional

from ._utils import as_text, safe_dict, safe_list, to_float, to_int


def build_risk_assessment(
    market: Optional[Mapping[str, Any]],
    themes: Optional[Mapping[str, Any]],
    fund_flow: Optional[Mapping[str, Any]],
    stage: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    market = safe_dict(market)
    themes = safe_dict(themes)
    fund_flow = safe_dict(fund_flow)
    stage = safe_dict(stage)

    limit = safe_dict(market.get("limit_up"))
    breadth = safe_dict(market.get("breadth"))
    heat = safe_dict(market.get("heat"))

    limit_up = max(to_int(limit.get("limit_up"), 0) or 0, 0)
    broken = max(to_int(limit.get("broken"), 0) or 0, 0)
    limit_down = max(to_int(limit.get("limit_down"), 0) or 0, 0)
    up = max(to_int(breadth.get("up"), 0) or 0, 0)
    down = max(to_int(breadth.get("down"), 0) or 0, 0)
    heat_value = to_float(heat.get("value"), 0.0) or 0.0
    mainline = safe_list(themes.get("mainline"))
    watch = safe_list(themes.get("watch"))
    alive = safe_list(themes.get("alive"))
    broken_rate = (broken / limit_up) if limit_up > 0 else (1.0 if broken else 0.0)
    breadth_net = up - down
    stage_name = as_text(stage.get("stage"), default="")

    risk_score = 0
    warnings: list[str] = []
    signals: list[str] = []
    drivers: list[dict[str, Any]] = []

    def push_driver(name: str, value: Any, impact: float, reason: str) -> None:
        drivers.append(
            {
                "name": name,
                "value": value,
                "impact": impact,
                "reason": reason,
            }
        )

    if broken_rate >= 0.35:
        risk_score += 28
        warnings.append(f"炸板率偏高，{broken} / {limit_up or 0} 的短线兑现压力加大。")
        signals.append("炸板率高")
        push_driver("炸板率", round(broken_rate, 4), 28, "炸板率偏高，短线兑现压力加大")
    elif broken_rate >= 0.2:
        risk_score += 18
        warnings.append(f"炸板率升高，{broken} 家炸板需要关注分歧后的承接。")
        signals.append("炸板率抬升")
        push_driver("炸板率", round(broken_rate, 4), 18, "炸板率升高，分歧压力抬升")
    elif broken_rate >= 0.1:
        risk_score += 10
        warnings.append(f"炸板数量仍在抬头，短线节奏需要更谨慎。")
        signals.append("炸板率略有压力")
        push_driver("炸板率", round(broken_rate, 4), 10, "炸板率开始有压力")

    if limit_down >= 20:
        risk_score += 28
        warnings.append(f"跌停 {limit_down} 家，尾部风险扩散明显。")
        signals.append("跌停扩散明显")
        push_driver("跌停数", limit_down, 28, "跌停扩散明显，尾部风险增大")
    elif limit_down >= 10:
        risk_score += 18
        warnings.append(f"跌停 {limit_down} 家，防守位仍需保留。")
        signals.append("跌停数量偏多")
        push_driver("跌停数", limit_down, 18, "跌停数量偏多")
    elif limit_down >= 5:
        risk_score += 10
        warnings.append(f"跌停数量仍不低，弱势个股需要隔离。")
        signals.append("跌停仍需关注")
        push_driver("跌停数", limit_down, 10, "跌停仍需关注")

    if heat_value < 30 and limit_up < 20:
        risk_score += 14
        warnings.append("市场热度偏低且涨停不够，缩量风险抬头。")
        signals.append("缩量风险")
        push_driver("市场热度", round(heat_value, 2), 14, "热度不足且涨停偏少，缩量风险抬头")

    if breadth_net < 0:
        risk_score += 10
        warnings.append("下跌家数占优，市场广度不支持激进追高。")
        signals.append("广度偏弱")
        push_driver("涨跌家数", f"{up}:{down}", 10, "下跌家数占优，广度不支持激进追高")

    if stage_name == "退潮":
        risk_score += 18
        warnings.append("市场已进入退潮阶段，仓位要明显收缩。")
        signals.append("阶段退潮")
        push_driver("市场阶段", stage_name, 18, "阶段已进入退潮，优先防守")
    elif stage_name == "分歧":
        risk_score += 10
        warnings.append("高位分歧加剧，强弱切换会更快。")
        signals.append("高位分歧")
        push_driver("市场阶段", stage_name, 10, "阶段处于分歧，强弱切换更快")

    if len(mainline) <= 1 and limit_up >= 30:
        risk_score += 8
        warnings.append("主线数量偏少，一致性过高时要防切换。")
        signals.append("一致性偏高")
        push_driver("主线结构", len(mainline), 8, "主线数量偏少，一致性过高时要防切换")

    if len(watch) + len(alive) <= 2 and limit_up >= 30:
        signals.append("次线储备有限")

    north_money = safe_dict(fund_flow.get("north_money"))
    if north_money.get("north_money") is not None:
        north_value = to_float(north_money.get("north_money"), None)
        if north_value is not None and north_value < 10 and heat_value < 50:
            risk_score += 8
            warnings.append("北向流入偏弱，追高容错率有限。")
            signals.append("外资支撑一般")
            push_driver("北向资金", round(north_value, 2), 8, "北向流入偏弱，追高容错率有限")

    if not warnings:
        warnings.append("暂无明显风险信号，仍需遵守仓位纪律。")

    if risk_score >= 65:
        risk_level = "高"
    elif risk_score >= 35:
        risk_level = "中"
    else:
        risk_level = "低"

    if risk_score >= 80:
        risk_level = "极高"

    return {
        "risk_level": risk_level,
        "risk_score": min(risk_score, 100),
        "warnings": warnings[:6],
        "signals": signals[:8],
        "drivers": drivers[:8],
    }

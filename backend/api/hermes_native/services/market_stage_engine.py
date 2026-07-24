from __future__ import annotations

from typing import Any, Mapping, Optional

from ._utils import as_text, clamp, mean, safe_dict, safe_list, to_float, to_int


def _theme_strength(themes: Mapping[str, Any]) -> float:
    strengths: list[float] = []
    for group_name in ("mainline", "watch", "alive"):
        for item in safe_list(themes.get(group_name)):
            value = to_float(item.get("strength"), None)
            if value is None:
                value = to_float(item.get("hot"), None)
            if value is None:
                value = to_float(item.get("score"), None)
            if value is not None:
                strengths.append(clamp(value, 0.0, 100.0))
    return mean(strengths, 0.0)


def _stage_description(stage: str) -> str:
    return {
        "冰点": "短线情绪偏弱，资金仍在等待方向。",
        "修复": "情绪开始回暖，市场进入试探性修复。",
        "发酵": "主线扩散中，资金开始向核心方向集中。",
        "高潮": "强势主线集中爆发，赚钱效应升温。",
        "分歧": "高位分歧加剧，强弱切换明显。",
        "退潮": "短线情绪回落，风险释放阶段。",
    }.get(stage, "市场结构待确认。")


def build_market_stage(market: Optional[Mapping[str, Any]], themes: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    market = safe_dict(market)
    themes = safe_dict(themes)

    limit = safe_dict(market.get("limit_up"))
    breadth = safe_dict(market.get("breadth"))
    heat = safe_dict(market.get("heat"))

    limit_up = max(to_int(limit.get("limit_up"), 0) or 0, 0)
    broken = max(to_int(limit.get("broken"), 0) or 0, 0)
    limit_down = max(to_int(limit.get("limit_down"), 0) or 0, 0)
    up = max(to_int(breadth.get("up"), 0) or 0, 0)
    down = max(to_int(breadth.get("down"), 0) or 0, 0)
    heat_value = to_float(heat.get("value"), 0.0) or 0.0
    theme_strength = _theme_strength(themes)
    mainline_count = len(safe_list(themes.get("mainline")))
    broken_rate = (broken / limit_up) if limit_up > 0 else (1.0 if broken else 0.0)
    breadth_net = up - down
    breadth_total = up + down

    score = 0.0
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

    if mainline_count >= 3 and limit_up >= 30 and broken_rate <= 0.15:
        score += 5
        signals.append("主线覆盖面较好")
        push_driver("主线覆盖", mainline_count, 5, "主线覆盖面较好，资金并未只集中单点")

    if breadth_total and abs(breadth_net) / breadth_total < 0.1 and limit_up >= 30:
        signals.append("一致性较高")
        push_driver("一致性", round(abs(breadth_net) / breadth_total, 4), 0, "涨跌家数过于一致，后续切换风险需要注意")

    score = round(clamp(score, 0.0, 100.0), 0)

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
        "signals": signals[:8],
        "drivers": drivers[:8],
    }

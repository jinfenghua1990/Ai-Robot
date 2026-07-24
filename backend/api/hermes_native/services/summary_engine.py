from __future__ import annotations

from typing import Any, Mapping, Optional

from ._utils import as_text, safe_dict, safe_list, to_float, to_int


def _join_names(items: list[dict[str, Any]], limit: int = 3) -> str:
    names = [as_text(item.get("name"), default="") for item in items[:limit]]
    names = [name for name in names if name]
    return "、".join(names) if names else "暂无明显主线"


def _clean(text: str) -> str:
    return str(text or "").strip().rstrip("。.!！?？")


def build_summary(
    stage: Optional[Mapping[str, Any]],
    themes: Optional[Mapping[str, Any]],
    risk: Optional[Mapping[str, Any]],
    market: Optional[Mapping[str, Any]] = None,
    fund_flow: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    stage = safe_dict(stage)
    themes = safe_dict(themes)
    risk = safe_dict(risk)
    market = safe_dict(market)
    fund_flow = safe_dict(fund_flow)

    stage_name = as_text(stage.get("stage"), default="未知")
    stage_desc = as_text(stage.get("description"), default="")
    mainline = safe_list(themes.get("mainline"))
    watch = safe_list(themes.get("watch"))
    limit = safe_dict(market.get("limit_up"))
    broken = to_int(limit.get("broken"), 0) or 0
    limit_down = to_int(limit.get("limit_down"), 0) or 0
    limit_up = to_int(limit.get("limit_up"), 0) or 0
    risk_level = as_text(risk.get("risk_level"), default="中")
    warnings = safe_list(risk.get("warnings"))

    mainline_text = _join_names(mainline)
    watch_text = _join_names(watch, 2)

    stage_prefix = {
        "冰点": "市场仍在冰点整理，资金更偏向试探。",
        "修复": "市场进入修复窗口，承接开始出现。",
        "发酵": "市场进入发酵扩散阶段，主线正在外扩。",
        "高潮": "市场处于高潮阶段，强势方向集中爆发。",
        "分歧": "市场进入高位分歧阶段，强弱切换加快。",
        "退潮": "市场进入退潮阶段，防守优先级抬高。",
    }.get(stage_name, "市场结构仍在识别中。")

    risk_tail = {
        "低": "明日更适合围绕核心方向低吸。",
        "中": "明日更适合低吸核心，避免追高后排。",
        "高": "明日宜收缩仓位，以防守和确认新主线为主。",
        "极高": "明日以防守为先，等待风险释放完成。",
    }.get(risk_level, "明日以观察为主。")

    warning_text = _clean(as_text(warnings[0], default="暂无明显风险提示"))
    north_money = safe_dict(fund_flow.get("north_money"))
    north_text = ""
    north_value = to_float(north_money.get("north_money"), None)
    if north_value is not None:
        north_text = f"，北向资金约 {north_value:.2f} 亿"

    text = (
        f"{_clean(stage_prefix)}，{_clean(stage_desc)}。"
        f"主线聚焦 {mainline_text}，观察方向包括 {watch_text}。"
        f"涨停 {limit_up} 家、炸板 {broken} 家、跌停 {limit_down} 家{north_text}。"
        f"{warning_text}，{_clean(risk_tail)}"
    )

    markdown = (
        "### AI 一句话总览\n"
        f"{text}\n\n"
        f"- 当前阶段：{stage_name}\n"
        f"- 核心主线：{mainline_text}\n"
        f"- 风险判断：{risk_level}\n"
    )

    return {
        "text": text,
        "markdown": markdown,
    }

from __future__ import annotations

from typing import Any, Mapping, Optional

from ._utils import as_text, safe_dict, safe_list, to_float


def build_tomorrow_plan(
    stage: Optional[Mapping[str, Any]],
    themes: Optional[Mapping[str, Any]],
    risk: Optional[Mapping[str, Any]],
    market: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    stage = safe_dict(stage)
    themes = safe_dict(themes)
    risk = safe_dict(risk)
    market = safe_dict(market)

    stage_name = as_text(stage.get("stage"), default="未知")
    risk_level = as_text(risk.get("risk_level"), default="中")
    mainline = safe_list(themes.get("mainline"))
    watch = safe_list(themes.get("watch"))
    alive = safe_list(themes.get("alive"))
    warnings = safe_list(risk.get("warnings"))

    def _mk(items: list[dict[str, Any]], suffix: str, fallback: str) -> list[str]:
        if not items:
            return [fallback]
        return [f"{as_text(item.get('name'))}{suffix}" for item in items[:2]]

    if risk_level in ("高", "极高") or stage_name == "退潮":
        attack = ["等待新主线确认"]
        secondary = [f"{as_text(item.get('name'))}观察" for item in watch[:2]] or ["观察分歧后的承接"]
        defense = ["降低追高频率", "优先防守核心持仓", "回避弱势后排"]
        position = "3成"
    elif stage_name == "高潮" and risk_level == "低":
        attack = _mk(mainline, "低吸", "围绕核心方向低吸")
        secondary = _mk(watch, "分歧回封", "关注次线确认")
        defense = ["不要过度追高", "关注炸板回落后的承接"]
        position = "7成"
    elif stage_name in ("发酵", "高潮") and risk_level in ("低", "中"):
        attack = _mk(mainline, "低吸", "围绕主线核心低吸")
        secondary = _mk(watch, "分歧回封", "观察次线轮动")
        defense = ["避免后排追涨", "保留仓位等分歧"]
        position = "6成"
    elif stage_name == "分歧":
        attack = _mk(mainline, "回踩接", "等待核心分歧后的低吸")
        secondary = _mk(watch, "回封", "等待次线修复")
        defense = ["只做核心，不碰杂毛", "降低冲高兑现风险"]
        position = "4~5成"
    else:
        attack = _mk(mainline, "观察", "等待主线进一步确认")
        secondary = _mk(alive, "轮动", "等待活口方向验证")
        defense = ["仓位先轻", "控制回撤", "不做无主线追高"]
        position = "4成"

    if market.get("limit_up", {}).get("broken") not in (None, "", []):
        broken = int(to_float(market.get("limit_up", {}).get("broken"), 0) or 0)
        if broken > 0 and "炸板票隔日接力优先观察" not in defense:
            defense.append("炸板票隔日接力优先观察")

    if warnings:
        defense.append(as_text(warnings[0], default="风险提示保持关注"))

    return {
        "attack": attack[:3],
        "secondary": secondary[:3],
        "defense": defense[:4],
        "position": position,
    }


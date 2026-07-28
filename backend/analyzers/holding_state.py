"""持仓状态引擎。

watchlist 的职责是管理已有持仓和候选观察标的，不是把一个技术信号直接翻译成买入。
本模块只做纯规则计算，输入已经准备好的持仓、技术、资金和板块因子，便于单元测试和后续回测。
"""

from __future__ import annotations

from typing import Any, Dict


HOLDING_STATUS = {
    "WATCH": {"label": "观察", "color": "#64748b"},
    "READY": {"label": "等待确认", "color": "#eab308"},
    "TRIGGERED": {"label": "持仓强化", "color": "#22c55e"},
    "HOLD": {"label": "继续持有", "color": "#16a34a"},
    "NO_CHASE": {"label": "持有但不追高", "color": "#f97316"},
    "INVALID": {"label": "无效/退出", "color": "#dc2626"},
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _is_forbidden(name: str, code: str = "") -> bool:
    normalized = (name or "").strip().upper().replace(" ", "")
    code_normalized = (code or "").strip().upper()
    return (
        normalized.startswith(("ST", "*ST", "S*ST", "退"))
        or "退市" in normalized
        or code_normalized.startswith(("退",))
    )


def evaluate_holding_state(
    *,
    code: str,
    name: str,
    position: Dict[str, Any] | None,
    quote: Dict[str, Any] | None,
    market_state: Dict[str, Any] | None,
    score_dimensions: Dict[str, Any] | None,
    overall_score: Any,
    technical: Dict[str, Any] | None,
    bs_signal: str | None,
) -> Dict[str, Any]:
    """根据持仓环境输出状态、动作和可解释因子。

    设计原则：
    - 未持仓只允许输出 WATCH/INVALID，不伪装成买入建议。
    - 持仓判断优先看趋势破坏、回撤、风险和资金环境。
    - B/S 只是证据，不能单独决定状态。
    """
    pos = position or {}
    dims = score_dimensions or {}
    features = (market_state or {}).get("features") or {}
    tech = technical or {}
    held_count = _num(pos.get("count"))
    held = held_count > 0
    pnl_pct = _num(pos.get("profitPct"), 0.0)
    day_pct = _num(pos.get("dayProfitPct"), 0.0)
    trend = _num(dims.get("trend_strength"), _num(tech.get("score"), 50.0))
    strength = _num(dims.get("relative_strength"), 50.0)
    capital = _num(dims.get("capital_momentum"), 50.0)
    sector = _num(dims.get("sector_resonance"), 50.0)
    volume = _num(dims.get("volume_health"), 50.0)
    volatility = _num(dims.get("volatility_health"), 50.0)
    drawdown = _num(dims.get("drawdown_status"), 50.0)
    overall = _num(overall_score, 50.0)
    close_vs_ma20 = _num(features.get("close_vs_ma20"), 0.0)
    noise = _num(features.get("noise_ratio"), 0.0)
    stage = str(tech.get("stage") or "")
    forbidden = _is_forbidden(name, code)
    has_trend_data = dims.get("trend_strength") is not None or tech.get("score") is not None
    has_price_data = bool(quote and _num(quote.get("price")) > 0)

    factors = [
        {"key": "持仓", "label": "持仓中" if held else "未持仓", "score": 100 if held else 0,
         "detail": f"数量 {int(held_count)} 股" if held else "当前没有实际持仓"},
        {"key": "趋势", "label": "趋势健康" if trend >= 60 else "趋势转弱" if trend < 40 else "趋势中性",
         "score": round(trend, 1), "detail": f"趋势强度 {trend:.1f}"},
        {"key": "强度", "label": "相对强" if strength >= 60 else "相对弱" if strength < 40 else "相对中性",
         "score": round(strength, 1), "detail": f"相对强度 {strength:.1f}"},
        {"key": "板块", "label": "板块支持" if sector >= 60 else "板块偏弱" if sector < 40 else "板块中性",
         "score": round(sector, 1), "detail": f"板块共振 {sector:.1f}"},
        {"key": "量价资金", "label": "量价健康" if min(capital, volume) >= 60 else "量价偏弱" if max(capital, volume) < 40 else "量价中性",
         "score": round((capital + volume) / 2, 1), "detail": f"资金 {capital:.1f} / 量能 {volume:.1f}"},
        {"key": "风险", "label": "风险可控" if min(volatility, drawdown) >= 60 else "风险升高" if max(volatility, drawdown) < 40 else "风险中性",
         "score": round((volatility + drawdown) / 2, 1), "detail": f"波动健康 {volatility:.1f} / 回撤健康 {drawdown:.1f}"},
    ]
    reasons = []
    warnings = []

    if forbidden:
        reasons.append("ST/退市类标的禁止持仓策略继续管理")
    if not held:
        reasons.append("未持仓，不生成加仓或卖出结论")
    if bs_signal == "S":
        warnings.append("BS卖出信号，仅作为减仓风险证据")
    if stage in {"破位", "弱势"} or trend < 40 or close_vs_ma20 < -0.08:
        warnings.append("趋势结构已转弱")
    if pnl_pct <= -15:
        warnings.append(f"浮亏已达 {pnl_pct:.1f}%")
    if noise >= 2.0:
        warnings.append(f"价格噪声偏高({noise:.2f})")
    if sector < 40:
        warnings.append("板块环境偏弱")
    if held and not has_trend_data:
        warnings.append("缺少关键趋势数据，不能继续持仓决策")

    # 交易状态：未持仓不进入持有态；禁入标的永远无效。
    if forbidden:
        status = "INVALID"
        action = "退出/禁止持有"
    elif not held:
        status = "WATCH"
        action = "仅观察，不买入"
    elif held and not has_price_data and not has_trend_data:
        status = "INVALID"
        action = "数据不足，暂停持仓决策"
    elif not has_trend_data:
        status = "INVALID"
        action = "数据不足，暂停持仓决策"
    elif (stage in {"破位", "弱势"} and trend < 45) or (pnl_pct <= -20 and trend < 55) or (pnl_pct <= -12 and trend < 45) or (bs_signal == "S" and trend < 35):
        status = "INVALID"
        action = "退出或大幅减仓"
    elif (stage in {"顶部", "突破"} and pnl_pct >= 15) or (pnl_pct >= 25 and close_vs_ma20 >= 0.08):
        status = "NO_CHASE"
        action = "继续持有，不追高加仓"
    elif trend >= 65 and strength >= 60 and sector >= 50 and capital >= 55 and drawdown >= 55:
        status = "TRIGGERED"
        action = "趋势确认，可小幅强化"
    elif trend >= 50 and overall >= 50 and drawdown >= 45:
        status = "HOLD"
        action = "继续持有，跟踪保护位"
    else:
        status = "READY"
        action = "等待修复确认，不加仓"

    # 给前端一个稳定的状态摘要，避免把 score 当作最终交易决定。
    state_meta = HOLDING_STATUS[status]
    return {
        "status": status,
        "statusLabel": state_meta["label"],
        "statusColor": state_meta["color"],
        "action": action,
        "isHeld": held,
        "holdingCount": int(held_count),
        "profitPct": round(pnl_pct, 2),
        "factorScore": round(_clamp((trend * 0.30 + strength * 0.15 + sector * 0.15 + capital * 0.15 + volume * 0.10 + drawdown * 0.15)), 1),
        "factors": factors,
        "reasons": reasons,
        "warnings": warnings,
        "decisionRule": "持仓优先：先判断趋势破坏与风险，再判断是否强化；BS信号不单独决定买卖。",
    }

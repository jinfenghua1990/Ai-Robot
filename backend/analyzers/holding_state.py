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


def _optional_num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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
    pnl_pct = _optional_num(pos.get("profitPct"))
    if not held and pnl_pct is None:
        pnl_pct = 0.0
    trend = _optional_num(dims.get("trend_strength"))
    if trend is None:
        trend = _optional_num(tech.get("score"))
    strength = _optional_num(dims.get("relative_strength"))
    capital = _optional_num(dims.get("capital_momentum"))
    sector = _optional_num(dims.get("sector_resonance"))
    volume = _optional_num(dims.get("volume_health"))
    volatility = _optional_num(dims.get("volatility_health"))
    drawdown = _optional_num(dims.get("drawdown_status"))
    overall = _optional_num(overall_score)
    close_vs_ma20 = _optional_num(features.get("close_vs_ma20"))
    noise = _optional_num(features.get("noise_ratio"))
    stage = str(tech.get("stage") or "")
    forbidden = _is_forbidden(name, code)
    has_trend_data = trend is not None
    has_price_data = bool(quote and _num(quote.get("price")) > 0)
    decision_values = {
        "trend_strength": trend,
        "relative_strength": strength,
        "capital_momentum": capital,
        "sector_resonance": sector,
        "volume_health": volume,
        "volatility_health": volatility,
        "drawdown_status": drawdown,
        "overall_score": overall,
    }
    missing_dimensions = [key for key, value in decision_values.items() if value is None]
    if held and pnl_pct is None:
        missing_dimensions.append("position_profit_pct")

    def factor(key, value, high_label, low_label, neutral_label, detail_label):
        if value is None:
            return {"key": key, "label": "数据不足", "score": None, "detail": f"{detail_label}缺失"}
        label = high_label if value >= 60 else low_label if value < 40 else neutral_label
        return {"key": key, "label": label, "score": round(value, 1), "detail": f"{detail_label} {value:.1f}"}

    price_flow_score = (
        (capital + volume) / 2 if capital is not None and volume is not None else None
    )
    risk_score = (
        (volatility + drawdown) / 2
        if volatility is not None and drawdown is not None else None
    )

    factors = [
        {"key": "持仓", "label": "持仓中" if held else "未持仓", "score": 100 if held else 0,
         "detail": f"数量 {int(held_count)} 股" if held else "当前没有实际持仓"},
        factor("趋势", trend, "趋势健康", "趋势转弱", "趋势中性", "趋势强度"),
        factor("强度", strength, "相对强", "相对弱", "相对中性", "相对强度"),
        factor("板块", sector, "板块支持", "板块偏弱", "板块中性", "板块共振"),
        factor("量价资金", price_flow_score, "量价健康", "量价偏弱", "量价中性", "量价资金"),
        factor("风险", risk_score, "风险可控", "风险升高", "风险中性", "风险健康度"),
    ]
    reasons = []
    warnings = []

    if forbidden:
        reasons.append("ST/退市类标的禁止持仓策略继续管理")
    if not held:
        reasons.append("未持仓，不生成加仓或卖出结论")
    if bs_signal == "S":
        warnings.append("BS卖出信号，仅作为减仓风险证据")
    if stage in {"破位", "弱势"} or (trend is not None and trend < 40) or (close_vs_ma20 is not None and close_vs_ma20 < -0.08):
        warnings.append("趋势结构已转弱")
    if pnl_pct is not None and pnl_pct <= -15:
        warnings.append(f"浮亏已达 {pnl_pct:.1f}%")
    if noise is not None and noise >= 2.0:
        warnings.append(f"价格噪声偏高({noise:.2f})")
    if sector is not None and sector < 40:
        warnings.append("板块环境偏弱")
    if held and (not has_trend_data or missing_dimensions):
        warnings.append(f"数据库缺少关键决策维度：{', '.join(missing_dimensions) or 'trend_strength'}")

    # 交易状态：未持仓不进入持有态；禁入标的永远无效。
    if forbidden:
        status = "INVALID"
        action = "退出/禁止持有"
    elif not held:
        status = "WATCH"
        action = "仅观察，不买入"
    elif not has_price_data or not has_trend_data or missing_dimensions:
        status = "READY"
        action = "数据不足，暂停持仓决策"
    elif (stage in {"破位", "弱势"} and trend < 45) or (pnl_pct <= -20 and trend < 55) or (pnl_pct <= -12 and trend < 45) or (bs_signal == "S" and trend < 35):
        status = "INVALID"
        action = "退出或大幅减仓"
    elif (stage in {"顶部", "突破"} and pnl_pct >= 15) or (pnl_pct >= 25 and close_vs_ma20 is not None and close_vs_ma20 >= 0.08):
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
        "profitPct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "factorScore": (
            round(_clamp((trend * 0.30 + strength * 0.15 + sector * 0.15 + capital * 0.15 + volume * 0.10 + drawdown * 0.15)), 1)
            if not missing_dimensions else None
        ),
        "dataStatus": "READY" if has_price_data and not missing_dimensions else "PARTIAL",
        "missingDimensions": missing_dimensions,
        "factors": factors,
        "reasons": reasons,
        "warnings": warnings,
        "decisionRule": "持仓优先：先判断趋势破坏与风险，再判断是否强化；BS信号不单独决定买卖。",
    }

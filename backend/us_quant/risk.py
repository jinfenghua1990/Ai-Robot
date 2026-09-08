"""US Quant System — 风险否决与仓位管理"""

from __future__ import annotations

from typing import Optional

from .contracts import PositionSizingResult, RiskCheckResult


# ─── 风险否决 ─────────────────────────────────────────────────────────────────

def check_risk_veto(
    data_stale: bool = False,
    broker_disconnected: bool = False,
    position_reconciliation_failed: bool = False,
    spread_abnormal: bool = False,
    stop_distance_too_large: bool = False,
    expected_rr_below_min: bool = False,
    daily_loss_limit_reached: bool = False,
    weekly_loss_limit_reached: bool = False,
    sector_risk_high: bool = False,
    correlated_positions_exceeded: bool = False,
    market_risk_off: bool = False,
    stock_suspended: bool = False,
    duplicate_order: bool = False,
    unknown_earnings_risk: bool = False,
    data_delayed: bool = False,
) -> RiskCheckResult:
    """执行风险否决检查

    任一项触发则禁止开仓。
    """
    veto_reasons = []

    if data_stale:
        veto_reasons.append("行情数据过期")
    if data_delayed:
        veto_reasons.append("数据延迟")
    if broker_disconnected:
        veto_reasons.append("券商断线")
    if position_reconciliation_failed:
        veto_reasons.append("持仓核对失败")
    if spread_abnormal:
        veto_reasons.append("价差异常")
    if stop_distance_too_large:
        veto_reasons.append("止损距离过大")
    if expected_rr_below_min:
        veto_reasons.append("盈亏比不足")
    if daily_loss_limit_reached:
        veto_reasons.append("达到日亏损上限")
    if weekly_loss_limit_reached:
        veto_reasons.append("达到周亏损上限")
    if sector_risk_high:
        veto_reasons.append("行业风险过高")
    if correlated_positions_exceeded:
        veto_reasons.append("相关仓位过多")
    if market_risk_off:
        veto_reasons.append("市场 RISK_OFF")
    if stock_suspended:
        veto_reasons.append("股票停牌")
    if duplicate_order:
        veto_reasons.append("重复订单")
    if unknown_earnings_risk:
        veto_reasons.append("未知财报风险")

    risk_score = min(100, len(veto_reasons) * 20)
    passed = len(veto_reasons) == 0
    return RiskCheckResult(passed=passed, veto_reasons=veto_reasons, risk_score=risk_score)


# ─── 仓位管理 ─────────────────────────────────────────────────────────────────

def calculate_position_size(
    account_equity: float = 100_000.0,
    entry_price: float = 0.0,
    stop_price: float = 0.0,
    target_prices: Optional[list[float]] = None,
    risk_per_trade: float = 0.005,         # 单笔风险 0.5%
    max_position_pct: float = 0.10,        # 单股最高仓位 10%
    max_open_positions: int = 6,
    current_positions: int = 0,
    current_sector_exposure: float = 0.0,  # 当前行业仓位占比
    max_sector_exposure: float = 0.30,     # 行业最高仓位 30%
    min_trade_unit: int = 1,
) -> PositionSizingResult:
    """计算仓位"""
    if entry_price <= 0 or stop_price <= 0:
        return PositionSizingResult(reason="无效的入场价或止损价")

    risk_per_share = abs(entry_price - stop_price)
    if risk_per_share <= 0:
        return PositionSizingResult(reason="止损价与入场价相同")

    # 允许亏损金额
    allowed_loss = account_equity * risk_per_trade

    # 理论股数
    theoretical_shares = int(allowed_loss / risk_per_share)

    # 单股仓位上限
    max_shares_by_position = int(account_equity * max_position_pct / entry_price)

    # 行业风险上限
    remaining_sector_capacity = max_sector_exposure - current_sector_exposure
    max_shares_by_sector = int(account_equity * remaining_sector_capacity / entry_price) if remaining_sector_capacity > 0 else 0

    # 最终股数
    final_shares = min(theoretical_shares, max_shares_by_position, max_shares_by_sector)
    if max_shares_by_sector <= 0:
        final_shares = 0

    # 取整到最小交易单位
    final_shares = (final_shares // min_trade_unit) * min_trade_unit

    position_pct = (final_shares * entry_price) / account_equity if account_equity > 0 else 0
    risk_amount = final_shares * risk_per_share

    target_prices = target_prices or []
    reason_parts = []
    if final_shares == theoretical_shares:
        reason_parts.append("标准仓位")
    elif final_shares == max_shares_by_position:
        reason_parts.append("受单股仓位上限限制")
    elif final_shares == max_shares_by_sector:
        reason_parts.append("受行业风险上限限制")
    else:
        reason_parts.append("调整仓位")

    return PositionSizingResult(
        allowed_quantity=final_shares,
        position_pct=round(position_pct * 100, 2),
        risk_amount=round(risk_amount, 2),
        stop_price=stop_price,
        target_prices=target_prices,
        reason=", ".join(reason_parts),
    )


# ─── 止损止盈 ─────────────────────────────────────────────────────────────────

def calculate_stop_loss(
    entry_price: float,
    support_level: Optional[float] = None,
    platform_low: Optional[float] = None,
    ema20: Optional[float] = None,
    atr_value: Optional[float] = None,
    atr_multiple: float = 1.5,
    use_atr: bool = False,
) -> float:
    """计算止损价

    优先级：形态失效位 > 平台下沿 > EMA20 > ATR
    """
    if support_level and support_level < entry_price:
        return round(support_level, 2)
    if platform_low and platform_low < entry_price:
        return round(platform_low, 2)
    if ema20 and ema20 < entry_price:
        return round(ema20, 2)
    if use_atr and atr_value and atr_value > 0:
        return round(entry_price - atr_value * atr_multiple, 2)
    return round(entry_price * 0.95, 2)  # 默认 5% 止损


def calculate_take_profit(
    entry_price: float,
    stop_price: float,
    r_multiple: float = 2.0,
    partial_at_1r: float = 0.30,
    partial_at_2r: float = 0.30,
) -> list[float]:
    """计算止盈价

    1R：卖出30%
    2R：再卖30%
    剩余40%：跟踪
    """
    risk_r = entry_price - stop_price
    if risk_r <= 0:
        return [round(entry_price * 1.05, 2), round(entry_price * 1.10, 2)]
    tp1 = entry_price + risk_r * 1.0
    tp2 = entry_price + risk_r * r_multiple
    return [round(tp1, 2), round(tp2, 2)]
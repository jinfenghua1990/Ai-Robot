"""US Quant System — 盘前扫描、盘中触发与信号生命周期"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .contracts import Signal
from .filters import check_premarket_filters
from .market_regime import MarketRegime


# ─── 盘前扫描 ─────────────────────────────────────────────────────────────────

def scan_premarket(
    symbol: str,
    name: str,
    premarket_change_pct: float,
    premarket_dollar_volume: float,
    premarket_volume: float,
    relative_volume: float,
    spread: float,
    price: float,
    avg_dollar_volume_20d: float,
    catalyst: str = "",
    sector_aligned: bool = False,
    industry: str = "",
    sector_rank: int = 0,
    regime: Optional[MarketRegime] = None,
) -> Optional[dict]:
    """盘前扫描单只股票

    返回候选字典或 None（被过滤掉）
    """
    # 过滤
    f = check_premarket_filters(
        premarket_change_pct=premarket_change_pct,
        premarket_dollar_volume=premarket_dollar_volume,
        relative_volume=relative_volume,
        spread=spread,
        price=price,
        avg_dollar_volume_20d=avg_dollar_volume_20d,
        has_catalyst=bool(catalyst),
    )
    if not f.passed:
        return None

    # 高波动池
    high_volatility = premarket_change_pct > 10

    return {
        "symbol": symbol,
        "name": name,
        "premarket_change_pct": round(premarket_change_pct, 2),
        "premarket_volume": premarket_volume,
        "premarket_dollar_volume": premarket_dollar_volume,
        "premarket_high": price * (1 + premarket_change_pct / 100),
        "premarket_low": price,
        "spread": spread,
        "catalyst": catalyst,
        "industry": industry,
        "sector_rank": sector_rank,
        "high_volatility": high_volatility,
        "position_mult": 0.5 if high_volatility else 1.0,
        "regime": regime.regime if regime else "",
    }


# ─── 盘中触发 ─────────────────────────────────────────────────────────────────

def check_intraday_trigger(
    price: float,
    opening_range_high: float,
    opening_range_low: float,
    vwap: float,
    previous_close: float,
    relative_spy_strong: bool = False,
    sector_aligned: bool = False,
    market_aligned: bool = False,
    rel_volume: Optional[float] = None,
    upper_shadow: bool = False,
    regime: Optional[MarketRegime] = None,
) -> dict:
    """检查盘中触发条件"""
    result = {
        "triggered": False,
        "trigger_type": "",
        "reasons": [],
        "details": {},
    }

    # 市场状态检查
    if regime and not regime.allow_new_positions:
        result["reasons"].append(f"市场状态 {regime.regime} 禁止新开仓")
        return result

    # 15分钟开盘区间突破
    if price > opening_range_high:
        result["trigger_type"] = "开盘区间突破"
        result["triggered"] = True
        result["reasons"].append(f"突破15分钟开盘区间高点 {opening_range_high:.2f}")

    # VWAP 回踩承接
    if price >= vwap * 0.995 and price <= vwap * 1.005:
        result["trigger_type"] = "VWAP回踩"
        result["triggered"] = True
        result["reasons"].append(f"回踩VWAP {vwap:.2f} 后承接")

    # 假突破排除
    if upper_shadow:
        result["triggered"] = False
        result["reasons"].append("长上影，排除假突破")

    if rel_volume and rel_volume < 1.0:
        result["triggered"] = False
        result["reasons"].append("成交量不足")

    if not sector_aligned:
        result["reasons"].append("行业不同步")

    if not market_aligned:
        result["reasons"].append("指数不同步")

    result["details"] = {
        "price": price,
        "opening_range_high": opening_range_high,
        "opening_range_low": opening_range_low,
        "vwap": vwap,
        "rel_volume": rel_volume,
        "relative_spy_strong": relative_spy_strong,
        "sector_aligned": sector_aligned,
        "market_aligned": market_aligned,
    }
    return result


# ─── 信号生命周期管理 ─────────────────────────────────────────────────────────

SIGNAL_LIFECYCLE_STATES = [
    "DISCOVERED",
    "SCORED",
    "WATCHING",
    "TRIGGERED",
    "RISK_REJECTED",
    "APPROVED",
    "ORDER_CREATED",
    "ACTIVE",
    "EXIT_TRIGGERED",
    "CLOSED",
    "EXPIRED",
]

VALID_TRANSITIONS = {
    "DISCOVERED": ["SCORED", "EXPIRED"],
    "SCORED": ["WATCHING", "RISK_REJECTED", "EXPIRED"],
    "WATCHING": ["TRIGGERED", "EXPIRED"],
    "TRIGGERED": ["RISK_REJECTED", "APPROVED", "EXPIRED"],
    "RISK_REJECTED": ["EXPIRED"],
    "APPROVED": ["ORDER_CREATED", "EXPIRED"],
    "ORDER_CREATED": ["ACTIVE", "EXPIRED"],
    "ACTIVE": ["EXIT_TRIGGERED", "CLOSED"],
    "EXIT_TRIGGERED": ["CLOSED"],
    "CLOSED": [],
    "EXPIRED": [],
}


def transition_signal(signal: Signal, new_status: str) -> tuple[bool, str]:
    """尝试转换信号状态"""
    if signal.lifecycle_status not in VALID_TRANSITIONS:
        return False, f"未知状态: {signal.lifecycle_status}"

    if new_status not in VALID_TRANSITIONS[signal.lifecycle_status]:
        return False, f"不能从 {signal.lifecycle_status} 转换到 {new_status}"

    signal.lifecycle_status = new_status
    return True, f"信号已从 {signal.lifecycle_status} 转换到 {new_status}"


def create_signal(
    symbol: str,
    name: str,
    strategy: str,
    strategy_version: str,
    score: float,
    signal_time: Optional[datetime] = None,
    planned_entry: Optional[float] = None,
    planned_stop: Optional[float] = None,
    planned_target: Optional[float] = None,
    expected_rr: Optional[float] = None,
    market_regime: str = "",
    sector_rank: int = 0,
    trigger_details: Optional[dict] = None,
) -> Signal:
    """创建新信号"""
    signal_time = signal_time or datetime.utcnow()
    expires_at = signal_time + timedelta(days=3)  # 默认3天过期

    return Signal(
        symbol=symbol,
        name=name,
        strategy=strategy,
        strategy_version=strategy_version,
        signal_type="ENTRY",
        lifecycle_status="DISCOVERED",
        score=score,
        signal_time=signal_time,
        expires_at=expires_at,
        planned_entry=planned_entry,
        planned_stop=planned_stop,
        planned_target=planned_target,
        expected_rr=expected_rr,
        market_regime=market_regime,
        sector_rank=sector_rank,
        trigger_details=trigger_details or {},
    )
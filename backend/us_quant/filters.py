"""US Quant System — 股票池过滤

硬过滤条件：
  - 价格 >= $10
  - 市值 >= 20亿
  - 上市天数 >= 250
  - 20日均成交额 >= 1亿
  - 排除OTC
  - 排除杠杆ETF
  - 排除反向ETF
  - 排除SPAC
  - 要求完整数据
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FilterResult:
    """过滤结果"""
    passed: bool = False
    reasons: list[str] = field(default_factory=list)


def check_hard_filters(
    price: Optional[float] = None,
    market_cap: Optional[float] = None,
    listing_days: Optional[int] = None,
    avg_dollar_volume_20d: Optional[float] = None,
    is_otc: bool = False,
    is_leveraged_etf: bool = False,
    is_inverse_etf: bool = False,
    is_spac: bool = False,
    has_complete_data: bool = True,
    bid_ask_spread: Optional[float] = None,
    is_suspended: bool = False,
) -> FilterResult:
    """执行硬过滤检查"""
    reasons = []
    passed = True

    if price is not None and price < 10:
        reasons.append(f"价格 ${price} < $10")
        passed = False
    if market_cap is not None and market_cap < 2_000_000_000:
        reasons.append(f"市值 ${market_cap/1e9:.1f}B < $20亿")
        passed = False
    if listing_days is not None and listing_days < 250:
        reasons.append(f"上市天数 {listing_days} < 250")
        passed = False
    if avg_dollar_volume_20d is not None and avg_dollar_volume_20d < 100_000_000:
        reasons.append(f"日均成交额 ${avg_dollar_volume_20d/1e6:.0f}M < $1亿")
        passed = False
    if is_otc:
        reasons.append("OTC股票")
        passed = False
    if is_leveraged_etf:
        reasons.append("杠杆ETF")
        passed = False
    if is_inverse_etf:
        reasons.append("反向ETF")
        passed = False
    if is_spac:
        reasons.append("SPAC")
        passed = False
    if not has_complete_data:
        reasons.append("数据不完整")
        passed = False
    if bid_ask_spread is not None and bid_ask_spread > 0.002:
        reasons.append(f"价差 {bid_ask_spread*100:.2f}% > 0.20%")
        passed = False
    if is_suspended:
        reasons.append("停牌")
        passed = False

    return FilterResult(passed=passed, reasons=reasons)


def check_premarket_filters(
    premarket_change_pct: Optional[float] = None,
    premarket_volume: Optional[float] = None,
    premarket_dollar_volume: Optional[float] = None,
    relative_volume: Optional[float] = None,
    spread: Optional[float] = None,
    price: Optional[float] = None,
    avg_dollar_volume_20d: Optional[float] = None,
    has_catalyst: bool = False,
) -> FilterResult:
    """盘前过滤条件"""
    reasons = []
    passed = True

    if premarket_change_pct is not None:
        if premarket_change_pct < 2 or premarket_change_pct > 8:
            reasons.append(f"盘前涨幅 {premarket_change_pct:.1f}% 不在 2%-8% 范围")
            passed = False
    if premarket_dollar_volume is not None and premarket_dollar_volume < 5_000_000:
        reasons.append(f"盘前成交额 ${premarket_dollar_volume/1e6:.1f}M < $500万")
        passed = False
    if relative_volume is not None and relative_volume < 2:
        reasons.append(f"相对成交量 {relative_volume:.1f} < 2")
        passed = False
    if spread is not None and spread > 0.002:
        reasons.append(f"价差 {spread*100:.2f}% > 0.20%")
        passed = False
    if price is not None and price < 10:
        reasons.append(f"股价 ${price} < $10")
        passed = False
    if avg_dollar_volume_20d is not None and avg_dollar_volume_20d < 100_000_000:
        reasons.append(f"日均成交额 ${avg_dollar_volume_20d/1e6:.0f}M < $1亿")
        passed = False
    if not has_catalyst:
        reasons.append("无明确催化")
        passed = False

    return FilterResult(passed=passed, reasons=reasons)
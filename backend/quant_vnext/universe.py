from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Sequence

from .contracts import DailyBar, MarketContext


@dataclass(frozen=True)
class DataQuality:
    valid: bool
    reasons: tuple[str, ...] = ()


def quality_gate(bars: Sequence[DailyBar], trade_date: date, max_staleness_days: int = 0) -> DataQuality:
    reasons = []
    if not bars:
        reasons.append("no_bars")
    else:
        latest = max(item.trade_date for item in bars)
        if latest != trade_date:
            reasons.append("stale_or_missing_latest_bar")
        if any(item.is_suspended for item in bars if item.trade_date == trade_date):
            reasons.append("suspended")
        if any(item.is_st for item in bars if item.trade_date == trade_date):
            reasons.append("st_stock")
    return DataQuality(not reasons, tuple(reasons))


def build_universe(history: Mapping[str, Sequence[DailyBar]], trade_date: date, market: MarketContext) -> dict[str, Sequence[DailyBar]]:
    """基础股票池门禁；不以单日资金流作为唯一入池条件。"""
    if market.trade_date != trade_date:
        raise ValueError("market context date mismatch")
    return {
        code: bars
        for code, bars in history.items()
        if quality_gate(bars, trade_date).valid
        and bars[-1].close > 0
        and bars[-1].volume > 0
    }

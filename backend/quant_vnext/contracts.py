from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional


@dataclass(frozen=True)
class DailyBar:
    ts_code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0
    pct_chg: float = 0.0
    sector: str = ""
    is_st: bool = False
    is_suspended: bool = False


@dataclass(frozen=True)
class MarketContext:
    trade_date: date
    breadth: float
    limit_up_count: int = 0
    limit_down_count: int = 0
    broken_rate: float = 0.0
    market_return_20d: Optional[float] = None
    market_data_available: bool = False


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    category: str
    source: str
    formula: str
    inputs: tuple[str, ...]
    period: Optional[int]
    direction: int
    validity: str = "research"
    production: bool = False


@dataclass
class FactorValue:
    ts_code: str
    trade_date: date
    name: str
    category: str
    raw_value: Optional[float]
    normalized: Optional[float]
    valid: bool
    reason: str = ""


@dataclass
class DimensionScore:
    name: str
    score: Optional[float]
    valid: bool
    factors: List[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class ResonanceSnapshot:
    count: int
    dimensions: List[str]
    failed_dimensions: List[str]
    eligible: bool
    reason: str


@dataclass
class SignalSnapshot:
    ts_code: str
    trade_date: date
    factor_score: Optional[float]
    dimensions: Dict[str, DimensionScore]
    resonance: ResonanceSnapshot
    lifecycle: str
    trading_state: str
    reasons: List[str] = field(default_factory=list)
    market_state: str = ""
    factor_weights: Dict[str, float] = field(default_factory=dict)

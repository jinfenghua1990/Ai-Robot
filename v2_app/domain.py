from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Bar:
    code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    pct_chg: float
    name: str = ""
    sector: str = ""


@dataclass(frozen=True)
class MarketContext:
    trade_date: date
    breadth: float
    limit_up: int
    limit_down: int
    market_return_20d: Optional[float]
    sentiment: str
    state: str
    source: str


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    label: str
    category: str
    source: str
    formula: str
    inputs: tuple[str, ...]
    period: Optional[int]
    direction: int
    # Governance status is deliberately separate from whether the formula
    # exists.  Newly implemented factors start in observation and can only
    # become production after out-of-sample validation.
    status: str = "observation"
    validity: str = "research"
    allow_production: bool = False

    @property
    def production(self) -> bool:
        return self.status == "production"


@dataclass
class FactorValue:
    code: str
    trade_date: date
    name: str
    category: str
    raw: Optional[float]
    normalized: Optional[float]
    valid: bool
    reason: str = ""


@dataclass
class DimensionScore:
    key: str
    label: str
    score: Optional[float]
    valid: bool
    factors: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class Signal:
    code: str
    name: str
    sector: str
    trade_date: date
    rank: int
    factor_score: Optional[float]
    dimensions: dict[str, DimensionScore]
    resonance_count: int
    resonance_dimensions: list[str]
    failed_dimensions: list[str]
    resonance_eligible: bool
    resonance_reason: str
    patterns: list[dict]
    lifecycle: str
    trading_state: str
    signal_valid_until: Optional[date]
    market_state: str
    reasons: list[str]
    score_mode: str = "RESEARCH"

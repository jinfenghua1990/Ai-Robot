"""US Quant System — 数据合约与类型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ─── 基础数据 ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class USBar:
    """美股K线"""
    symbol: str
    ts: datetime
    timeframe: str  # 1d, 60min, 15min, 5min
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: Optional[float] = None


@dataclass(frozen=True)
class USStockInfo:
    """美股基础信息"""
    symbol: str
    name: str
    exchange: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: Optional[float] = None
    listing_date: Optional[date] = None
    is_active: bool = True


# ─── 市场环境 ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MarketRegime:
    """市场环境状态"""
    regime: str          # STRONG_BREADTH / LEADER_CONCENTRATION / HIGH_LEVEL_RANGE / WEAK_REBOUND / RISK_OFF
    score: float         # 0-100
    label: str           # 中文标签
    allow_new_positions: bool
    reason: str
    breakout_mult: float = 1.0
    pullback_mult: float = 1.0
    earnings_gap_mult: float = 1.0


@dataclass(frozen=True)
class IndexQuote:
    """指数行情"""
    symbol: str
    name: str
    price: float
    change_pct: float
    ma20: Optional[float] = None
    ma50: Optional[float] = None


# ─── 行业轮动 ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SectorScore:
    """行业评分"""
    etf_symbol: str
    etf_name: str
    industry: str
    ret_5d: float
    ret_20d: float
    ret_60d: float
    rel_strength_20d: float
    rel_strength_60d: float
    ma_trend: float       # 均线趋势评分
    volume_activity: float # 成交量活跃度
    total_score: float     # 综合评分 0-100
    rank: int = 0
    grade: str = ""        # 强势主线/重点关注/观察/不优先


# ─── 策略评分 ─────────────────────────────────────────────────────────────────

@dataclass
class StrategyScore:
    """单只股票的策略评分"""
    symbol: str
    name: str
    trade_date: date
    breakout_score: Optional[float] = None    # 平台突破评分 0-100
    pullback_score: Optional[float] = None    # 趋势回踩评分 0-100
    earnings_gap_score: Optional[float] = None  # 财报跳空评分 0-100
    primary_strategy: str = ""                # 主要策略
    hard_filter_pass: bool = False
    hard_filter_reasons: list[str] = field(default_factory=list)
    score_details: dict = field(default_factory=dict)


# ─── 7状态体系 ─────────────────────────────────────────────────────────────────

STOCK_STATES = [
    ("FOLLOW", "跟随"),
    ("WATCH", "关注"),
    ("ACCUMULATION", "吸筹"),
    ("LAUNCH", "启动"),
    ("EXPANSION", "发酵"),
    ("MARKUP", "主升"),
    ("DISTRIBUTION", "退潮"),
]

STATE_MAP = {k: v for k, v in STOCK_STATES}


# ─── 信号生命周期 ─────────────────────────────────────────────────────────────

SIGNAL_LIFECYCLE = [
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


@dataclass
class Signal:
    """交易信号"""
    id: Optional[int] = None
    symbol: str = ""
    name: str = ""
    strategy: str = ""
    strategy_version: str = "1.0.0"
    signal_type: str = ""  # ENTRY / EXIT
    lifecycle_status: str = "DISCOVERED"
    score: float = 0.0
    signal_time: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    planned_entry: Optional[float] = None
    planned_stop: Optional[float] = None
    planned_target: Optional[float] = None
    expected_rr: Optional[float] = None
    risk_veto: bool = False
    veto_reasons: list[str] = field(default_factory=list)
    trigger_details: dict = field(default_factory=dict)
    market_regime: str = ""
    sector_rank: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


# ─── 风险与仓位 ─────────────────────────────────────────────────────────────────

@dataclass
class RiskCheckResult:
    """风险检查结果"""
    passed: bool
    veto_reasons: list[str] = field(default_factory=list)
    risk_score: float = 0.0  # 0-100, 越高越危险


@dataclass
class PositionSizingResult:
    """仓位计算结果"""
    allowed_quantity: int = 0
    position_pct: float = 0.0  # 占总资产百分比
    risk_amount: float = 0.0   # 风险金额
    stop_price: float = 0.0
    target_prices: list[float] = field(default_factory=list)
    reason: str = ""
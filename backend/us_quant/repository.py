"""US Quant System — 数据仓库层（数据库模型）

使用现有 SQLAlchemy Base 和 get_db_session。
复用现有 airobot 数据库，添加 US Quant 系统专用表。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Numeric, Boolean, Text,
    UniqueConstraint, func, BigInteger, JSON, Float, Index,
)
from db.connection import Base, engine


class USInstrument(Base):
    """美股标的"""
    __tablename__ = "us_instruments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, unique=True, index=True)
    name = Column(String(128))
    exchange = Column(String(32))
    sector = Column(String(128))
    industry = Column(String(128))
    sector_etf = Column(String(32))
    market_cap = Column(Numeric(24, 4))
    listing_date = Column(Date)
    is_active = Column(Boolean, default=True)
    is_otc = Column(Boolean, default=False)
    is_leveraged = Column(Boolean, default=False)
    is_inverse = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class USMarketRegime(Base):
    """市场环境记录"""
    __tablename__ = "us_market_regime"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    regime = Column(String(32), nullable=False)
    score = Column(Numeric(6, 2))
    label = Column(String(32))
    allow_new_positions = Column(Boolean)
    reason = Column(Text)
    breakout_mult = Column(Numeric(4, 2))
    pullback_mult = Column(Numeric(4, 2))
    earnings_gap_mult = Column(Numeric(4, 2))
    spy_price = Column(Numeric(12, 2))
    qqq_price = Column(Numeric(12, 2))
    vix = Column(Numeric(8, 2))
    breadth = Column(Numeric(6, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", name="uq_us_regime_date"),)


class USSectorScore(Base):
    """行业轮动评分"""
    __tablename__ = "us_sector_scores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    etf_symbol = Column(String(16), nullable=False)
    etf_name = Column(String(32))
    industry = Column(String(64))
    total_score = Column(Numeric(6, 2))
    ret_5d = Column(Numeric(8, 2))
    ret_20d = Column(Numeric(8, 2))
    ret_60d = Column(Numeric(8, 2))
    rel_strength_20d = Column(Numeric(8, 2))
    rel_strength_60d = Column(Numeric(8, 2))
    ma_trend = Column(Numeric(6, 2))
    volume_activity = Column(Numeric(6, 2))
    rank = Column(Integer)
    grade = Column(String(16))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "etf_symbol", name="uq_us_sector_date"),)


class USStrategyScore(Base):
    """策略评分记录"""
    __tablename__ = "us_strategy_scores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    name = Column(String(64))
    breakout_score = Column(Numeric(6, 2))
    pullback_score = Column(Numeric(6, 2))
    earnings_gap_score = Column(Numeric(6, 2))
    primary_strategy = Column(String(32))
    hard_filter_pass = Column(Boolean, default=False)
    hard_filter_reasons = Column(Text)
    score_details = Column(JSON)
    strategy_version = Column(String(32), default="1.0.0")
    state = Column(String(16))  # 7状态
    state_label = Column(String(16))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "symbol", name="uq_us_strategy_score"),)


class USSignal(Base):
    """交易信号"""
    __tablename__ = "us_signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    name = Column(String(64))
    strategy = Column(String(32), nullable=False)
    strategy_version = Column(String(32))
    signal_type = Column(String(16), nullable=False)  # ENTRY / EXIT
    lifecycle_status = Column(String(32), nullable=False, default="DISCOVERED")
    score = Column(Numeric(6, 2))
    signal_time = Column(DateTime, nullable=False)
    expires_at = Column(DateTime)
    planned_entry = Column(Numeric(12, 4))
    planned_stop = Column(Numeric(12, 4))
    planned_target = Column(Numeric(12, 4))
    expected_rr = Column(Numeric(8, 4))
    risk_veto = Column(Boolean, default=False)
    veto_reasons = Column(Text)
    trigger_details = Column(JSON)
    market_regime = Column(String(32))
    sector_rank = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class USPosition(Base):
    """持仓记录"""
    __tablename__ = "us_positions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, unique=True, index=True)
    name = Column(String(64))
    strategy = Column(String(32))
    entry_price = Column(Numeric(12, 4))
    current_price = Column(Numeric(12, 4))
    quantity = Column(Integer, default=0)
    cost_basis = Column(Numeric(16, 4))
    market_value = Column(Numeric(16, 4))
    unrealized_pl = Column(Numeric(12, 4))
    unrealized_pl_pct = Column(Numeric(8, 4))
    stop_price = Column(Numeric(12, 4))
    target_prices = Column(JSON)
    entry_date = Column(Date)
    holding_days = Column(Integer, default=0)
    sector = Column(String(64))
    risk_group = Column(String(32))
    status = Column(String(16), default="ACTIVE")  # ACTIVE / CLOSED
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())




class USStockDaily(Base):
    """美股日K线存档（遵循 A 股 stock_daily_kline 模式，所有数据源统一入库）"""
    __tablename__ = "us_stock_daily"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    open = Column(Numeric(12, 4))
    high = Column(Numeric(12, 4))
    low = Column(Numeric(12, 4))
    close = Column(Numeric(12, 4))
    volume = Column(BigInteger)
    source = Column(String(32))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", name="uq_us_stock_daily"),
        Index("ix_us_stock_daily_date", "trade_date"),
    )


class USBacktestResult(Base):
    """回测结果汇总"""
    __tablename__ = 'us_backtest_results'
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(32), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    strategy = Column(String(32), nullable=False)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Numeric(8, 2))
    total_pnl = Column(Numeric(16, 2))
    total_pnl_pct = Column(Numeric(10, 2))
    avg_win = Column(Numeric(12, 2))
    avg_loss = Column(Numeric(12, 2))
    profit_factor = Column(Numeric(10, 2))
    max_drawdown_pct = Column(Numeric(8, 2))
    sharpe_ratio = Column(Numeric(8, 2))
    avg_bars_held = Column(Numeric(8, 2))
    run_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())


class USBacktestTrade(Base):
    """回测单笔交易详情"""
    __tablename__ = 'us_backtest_trades'
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(32), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    strategy = Column(String(32), nullable=False)
    entry_date = Column(String(16), nullable=False)
    entry_price = Column(Numeric(12, 4), nullable=False)
    exit_date = Column(String(16))
    exit_price = Column(Numeric(12, 4))
    direction = Column(String(8), default='LONG')
    shares = Column(Integer, default=0)
    pnl = Column(Numeric(12, 2))
    pnl_pct = Column(Numeric(8, 2))
    bars_held = Column(Integer, default=0)
    exit_reason = Column(String(32))
    created_at = Column(DateTime, server_default=func.now())


class USOrder(Base):
    """订单记录"""
    __tablename__ = "us_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_order_id = Column(String(128), unique=True)
    symbol = Column(String(32), nullable=False, index=True)
    strategy = Column(String(32))
    side = Column(String(8), nullable=False)  # BUY / SELL
    order_type = Column(String(16), default="MARKET")
    quantity = Column(Integer, nullable=False)
    filled_quantity = Column(Integer, default=0)
    price = Column(Numeric(12, 4))
    avg_fill_price = Column(Numeric(12, 4))
    status = Column(String(32), default="CREATED")
    reject_reason = Column(Text)
    signal_id = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


def ensure_schema():
    """创建所有 US Quant 表"""
    Base.metadata.create_all(bind=engine, tables=[
        USInstrument.__table__,
        USMarketRegime.__table__,
        USSectorScore.__table__,
        USStrategyScore.__table__,
        USSignal.__table__,
        USPosition.__table__,
        USOrder.__table__,
        USStockDaily.__table__,
        USBacktestResult.__table__,
        USBacktestTrade.__table__,
    ])
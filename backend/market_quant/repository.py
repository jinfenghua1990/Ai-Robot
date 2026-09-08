"""SQLAlchemy models for the multi-market research/production layer."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)

from db.connection import Base, engine


class MarketInstrument(Base):
    __tablename__ = "market_instruments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    provider_symbol = Column(String(48), nullable=False)
    exchange = Column(String(16), nullable=False)
    name = Column(String(128))
    sector = Column(String(128))
    industry = Column(String(128))
    security_type = Column(String(32), default="COMMON_STOCK")
    currency = Column(String(8))
    market_cap = Column(Numeric(24, 4))
    avg_turnover_20d = Column(Numeric(24, 4))
    price = Column(Numeric(16, 6))
    listing_date = Column(Date)
    is_active = Column(Boolean, default=True, index=True)
    is_etf = Column(Boolean, default=False)
    is_otc = Column(Boolean, default=False)
    is_leveraged = Column(Boolean, default=False)
    is_inverse = Column(Boolean, default=False)
    source = Column(String(32))
    data_updated_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("market", "symbol", name="uq_market_instrument"),
        Index("ix_market_instrument_active", "market", "is_active"),
    )


class MarketUniverseMembership(Base):
    __tablename__ = "market_universe_memberships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    universe_code = Column(String(64), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    tier = Column(String(16))
    rank = Column(Integer)
    universe_score = Column(Float)
    effective_from = Column(DateTime, nullable=False)
    effective_to = Column(DateTime)
    inclusion_reason = Column(Text)
    exclusion_reason = Column(Text)
    source = Column(String(64))
    config_version = Column(String(64))
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_market_membership_active", "market", "universe_code", "effective_to"),
        Index("ix_market_membership_symbol", "market", "symbol", "universe_code"),
    )


class MarketDailyBar(Base):
    __tablename__ = "market_daily_bars"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    open = Column(Numeric(16, 6))
    high = Column(Numeric(16, 6))
    low = Column(Numeric(16, 6))
    close = Column(Numeric(16, 6))
    adjusted_close = Column(Numeric(16, 6))
    volume = Column(BigInteger)
    amount = Column(Numeric(28, 6))
    source = Column(String(32))
    source_timestamp = Column(DateTime)
    is_adjusted = Column(Boolean, default=False)
    quality_status = Column(String(20), nullable=False, default="VALID")
    quality_reason = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("market", "symbol", "trade_date", name="uq_market_daily_bar"),
        Index("ix_market_daily_bar_lookup", "market", "trade_date", "symbol"),
    )


class MarketDataQualityRun(Base):
    __tablename__ = "market_data_quality_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    universe_code = Column(String(64), nullable=False)
    trade_date = Column(Date)
    expected_count = Column(Integer, default=0)
    valid_count = Column(Integer, default=0)
    missing_count = Column(Integer, default=0)
    min_history_days = Column(Integer, default=0)
    max_history_days = Column(Integer, default=0)
    status = Column(String(20), nullable=False)
    details = Column(JSON)
    checked_at = Column(DateTime, server_default=func.now())


class MarketFactorValue(Base):
    __tablename__ = "market_factor_values"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    factor_name = Column(String(80), nullable=False)
    category = Column(String(40), nullable=False)
    raw_value = Column(Float)
    normalized = Column(Float)
    valid = Column(Boolean, nullable=False)
    reason = Column(String(240))
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("market", "symbol", "trade_date", "factor_name", name="uq_market_factor_value"),
    )


class MarketResonanceSnapshot(Base):
    __tablename__ = "market_resonance_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    factor_score = Column(Float)
    resonance_count = Column(Integer, default=0)
    dimensions_json = Column(Text)
    failed_dimensions_json = Column(Text)
    lifecycle = Column(String(20))
    trading_state = Column(String(20))
    eligible = Column(Boolean, default=False)
    risk_veto = Column(Boolean, default=False)
    reason = Column(Text)
    payload = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("market", "symbol", "trade_date", name="uq_market_resonance_snapshot"),
    )


class MarketSignalOutcome(Base):
    __tablename__ = "market_signal_outcomes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    signal_date = Column(Date, nullable=False, index=True)
    trading_state = Column(String(20), nullable=False)
    return_1d = Column(Float)
    return_3d = Column(Float)
    return_5d = Column(Float)
    return_10d = Column(Float)
    return_20d = Column(Float)
    max_profit = Column(Float)
    max_loss = Column(Float)
    max_drawdown = Column(Float)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("market", "symbol", "signal_date", name="uq_market_signal_outcome"),
    )


class MarketScanRun(Base):
    __tablename__ = "market_scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    universe_code = Column(String(64), nullable=False)
    trade_date = Column(Date, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="RUNNING")
    pool_total = Column(Integer, default=0)
    history_valid_count = Column(Integer, default=0)
    candidate_count = Column(Integer, default=0)
    triggered_count = Column(Integer, default=0)
    data_trade_date = Column(Date)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    error = Column(Text)
    payload = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("market", "universe_code", "trade_date", name="uq_market_scan_run"),
    )


class MarketResearchRecord(Base):
    __tablename__ = "market_research_records"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    name = Column(String(128))
    exchange = Column(String(16))
    query_type = Column(String(20), nullable=False)
    query = Column(Text, nullable=False)
    provider = Column(String(32), nullable=False, default="miaoxiang")
    status = Column(String(20), nullable=False, default="SUCCESS")
    raw_response = Column(Text)
    normalized_result = Column(JSON)
    data_asof = Column(Date)
    received_at = Column(DateTime, server_default=func.now())
    error = Column(Text)

    __table_args__ = (
        Index("ix_market_research_symbol_time", "market", "symbol", "received_at"),
    )


TABLES = [
    MarketInstrument.__table__,
    MarketUniverseMembership.__table__,
    MarketDailyBar.__table__,
    MarketDataQualityRun.__table__,
    MarketFactorValue.__table__,
    MarketResonanceSnapshot.__table__,
    MarketSignalOutcome.__table__,
    MarketScanRun.__table__,
    MarketResearchRecord.__table__,
]


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine, tables=TABLES)

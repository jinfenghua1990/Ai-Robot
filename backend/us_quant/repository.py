"""US Quant System — 数据仓库层（数据库模型）

使用现有 SQLAlchemy Base 和 get_db_session。
复用现有 airobot 数据库，添加 US Quant 系统专用表。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Numeric, Boolean, Text,
    UniqueConstraint, func, BigInteger, JSON, Float, Index, text,
)
from db.connection import Base, engine


class USInstrument(Base):
    """美股标的（类似 A 股 stock_universe，全市场基础信息表）

    作为量化选股/覆盖池的基础表：从东财动态拉取 + 筛选入库。
    支持分层股票池：全量研究池 \u2192 核心 A 池 \u2192 核心 B 池。
    """
    __tablename__ = "us_instruments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, unique=True, index=True)
    name = Column(String(128))
    exchange = Column(String(32))
    sector = Column(String(128))
    industry = Column(String(128))
    sector_etf = Column(String(32))
    security_type = Column(String(32), default='Common Stock')
    market_cap = Column(Numeric(24, 4))
    price = Column(Numeric(12, 4))
    volume = Column(BigInteger)
    avg_dollar_volume_20d = Column(Numeric(20, 2))
    spread_pct = Column(Numeric(8, 4))
    listing_date = Column(Date)
    is_active = Column(Boolean, default=True, index=True)
    is_otc = Column(Boolean, default=False)
    is_leveraged = Column(Boolean, default=False)
    is_inverse = Column(Boolean, default=False)
    is_etf = Column(Boolean, default=False)
    universe_source = Column(String(32))
    data_updated_at = Column(DateTime)
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


class USSectorRotationSnapshot(Base):
    """美股行业龙头池盘后快照，避免页面切换行业时重复扫描日线。"""
    __tablename__ = "us_sector_rotation_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, unique=True, index=True)
    snapshot_json = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


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


class USScanRun(Base):
    """美股盘后扫描运行记录，保证页面读取最近一次成功快照。"""
    __tablename__ = "us_scan_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, unique=True, index=True)
    status = Column(String(16), nullable=False, default="RUNNING")  # RUNNING / COMPLETED / FAILED
    source = Column(String(32), default="postmarket")
    pool_source = Column(String(64))
    pool_total = Column(Integer, default=0)
    scanned_count = Column(Integer, default=0)
    candidate_count = Column(Integer, default=0)
    signal_count = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    error = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


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


class USUniverseMembership(Base):
    """股票池成员历史（类似 A 股 Watchlist 的 DB 化版本）

    记录每只股票在各个股票池中的归属、排名、有效时间。
    支持历史追溯（回测读取当时快照）。
    """
    __tablename__ = "us_universe_memberships"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    universe_code = Column(String(64), nullable=False, index=True)
    tier = Column(String(16))
    rank = Column(Integer)
    universe_score = Column(Numeric(10, 4))
    effective_from = Column(DateTime, nullable=False)
    effective_to = Column(DateTime)
    inclusion_reason = Column(Text)
    exclusion_reason = Column(Text)
    source = Column(String(64))
    config_version = Column(String(64))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        Index("idx_us_uni_membership_active", "universe_code", "effective_to"),
        Index("idx_us_uni_membership_symbol", "symbol", "universe_code"),
    )


class USWatchlistSectorPreference(Base):
    """单用户本地系统的板块偏好；替代仅存在浏览器 localStorage 的热门标记。"""
    __tablename__ = "us_watchlist_sector_preferences"
    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(8), nullable=False, default="US")
    sector = Column(String(128), nullable=False)
    is_hot = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("market", "sector", name="uq_us_watchlist_sector_preference"),
    )


class USUniverseRebalanceRun(Base):
    """重平衡运行记录"""
    __tablename__ = "us_universe_rebalance_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    universe_code = Column(String(64), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    status = Column(String(32), nullable=False)
    input_count = Column(Integer)
    eligible_count = Column(Integer)
    selected_count = Column(Integer)
    added_count = Column(Integer)
    removed_count = Column(Integer)
    config_version = Column(String(64))
    metrics = Column(JSON, default={})
    errors = Column(JSON, default=[])
    created_at = Column(DateTime, server_default=func.now())


class USStockDaily(Base):
    """美股日K线存档（遵循 A 股 stock_daily_kline 模式，所有数据源统一入库）

    字段说明：
    - open/high/low/close/volume: 基础 OHLCV
    - amount: 成交额（元）
    - vwap: 加权均价（VWAP）
    - adj_close: 复权收盘价（拆股/股息调整）
    - change_pct: 涨跌幅（%）
    - amplitude: 振幅（%）
    - turnover: 换手率（%）
    """
    __tablename__ = "us_stock_daily"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    open = Column(Numeric(12, 4))
    high = Column(Numeric(12, 4))
    low = Column(Numeric(12, 4))
    close = Column(Numeric(12, 4))
    volume = Column(BigInteger)
    # -- 扩展字段 --
    amount = Column(Numeric(20, 2), comment="成交额（元）")
    vwap = Column(Numeric(12, 4), comment="加权均价 VWAP")
    adj_close = Column(Numeric(12, 4), comment="复权收盘价")
    change_pct = Column(Numeric(8, 4), comment="涨跌幅%")
    amplitude = Column(Numeric(8, 4), comment="振幅%")
    turnover = Column(Numeric(12, 4), comment="换手率%")
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
    pool_source = Column(String(64), nullable=True, default='')     # 回测使用的股票池来源
    pool_snapshot = Column(JSON, nullable=True)                      # 回测时点的池快照 (symbol列表)
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


class USRealPosition(Base):
    """盈立真实持仓（CDP 从盈立客户端只读同步，唯一持仓数据源）"""
    __tablename__ = "us_real_positions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, unique=True, index=True)
    name = Column(String(64))
    exchange_type = Column(Integer, default=5)          # 5=美股, 52=美股碎股
    fund_account = Column(String(32))
    quantity = Column(Numeric(16, 4))
    cost_price = Column(Numeric(12, 4))
    last_price = Column(Numeric(12, 4))
    pre_close = Column(Numeric(12, 4))
    market_value = Column(Numeric(16, 4))
    hold_profit = Column(Numeric(12, 4))
    hold_profit_pct = Column(Numeric(8, 4))
    today_profit = Column(Numeric(12, 4))
    hold_info_id = Column(String(64))
    status = Column(String(16), default="ACTIVE")       # ACTIVE / CLOSED
    synced_at = Column(DateTime, default=func.now(), onupdate=func.now())



class USFactorScore(Base):
    """因子计算值存档 — 每只股票每日的各类因子值

    数据流：数据源 → USStockDaily（原始K线）→ 因子计算 → USFactorScore（因子值）
    用途：供策略扫描、回测、分析使用
    """
    __tablename__ = "us_factor_scores"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    factor_name = Column(String(64), nullable=False, comment="因子名称（如 value_price_to_52w_high）")
    factor_category = Column(String(32), comment="因子类别（如 价格价值型）")
    # 因子量纲差异很大（部分量价因子可超过 1e13），定点 NUMERIC(16,6)
    # 会溢出并让整批写入回滚，因此使用双精度浮点保存原始研究值。
    factor_value = Column(Float, comment="因子计算值")
    score_version = Column(String(32), default="1.0.0")
    params = Column(JSON, comment="计算参数快照")
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", "factor_name", name="uq_us_factor_score"),
        Index("ix_us_factor_scores_lookup", "symbol", "trade_date", "factor_name"),
        Index("ix_us_factor_scores_date", "trade_date", "factor_name"),
    )


class USStrategyTrack(Base):
    """美股每日策略命中跟踪（固定 30 个交易日）。"""
    __tablename__ = "us_strategy_tracks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    pool_date = Column(Date, nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    name = Column(String(128))
    strategy = Column(String(64), nullable=False)
    entry_price = Column(Numeric(12, 4))
    track_days = Column(Integer, default=30)
    status = Column(String(16), default="active", index=True)
    latest_date = Column(Date)
    latest_price = Column(Numeric(12, 4))
    latest_return_pct = Column(Numeric(8, 2))
    exit_date = Column(Date)
    exit_price = Column(Numeric(12, 4))
    exit_return_pct = Column(Numeric(8, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("pool_date", "symbol", "strategy", name="uq_us_strategy_track"),)


class USStrategyTrackDaily(Base):
    """美股策略跟踪每日价格和累计收益。"""
    __tablename__ = "us_strategy_track_daily"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tracker_id = Column(Integer, nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    day_n = Column(Integer, nullable=False)
    close = Column(Numeric(12, 4))
    daily_return_pct = Column(Numeric(8, 2))
    cum_return_pct = Column(Numeric(8, 2))
    __table_args__ = (UniqueConstraint("tracker_id", "trade_date", name="uq_us_strategy_track_daily"),)
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
        USSectorRotationSnapshot.__table__,
        USStrategyScore.__table__,
        USScanRun.__table__,
        USSignal.__table__,
        USRealPosition.__table__,
        USOrder.__table__,
        USUniverseMembership.__table__,
        USWatchlistSectorPreference.__table__,
        USUniverseRebalanceRun.__table__,
        USStockDaily.__table__,
        USBacktestResult.__table__,
        USBacktestTrade.__table__,
        USFactorScore.__table__,
        USStrategyTrack.__table__,
        USStrategyTrackDaily.__table__,
    ])
    _ensure_active_membership_uniqueness()


def _ensure_active_membership_uniqueness():
    """软关闭重复有效成员，再建立部分唯一索引。

    历史记录全部保留；每个股票池/代码最早生效的一条继续有效。
    """
    with engine.begin() as connection:
        connection.execute(text("""
            WITH duplicates AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY universe_code, symbol
                           ORDER BY effective_from ASC, id ASC
                       ) AS duplicate_rank
                FROM us_universe_memberships
                WHERE effective_to IS NULL
            )
            UPDATE us_universe_memberships AS membership
            SET effective_to = NOW(),
                exclusion_reason = COALESCE(membership.exclusion_reason, 'duplicate_active_repaired')
            FROM duplicates
            WHERE membership.id = duplicates.id
              AND duplicates.duplicate_rank > 1
        """))
        connection.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_us_uni_membership_active_symbol
            ON us_universe_memberships (universe_code, symbol)
            WHERE effective_to IS NULL
        """))

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from db.connection import Base


TAXONOMY_VERSION = "SW2021"


class IndustryStageTaxonomy(Base):
    """申万 2021 行业树；与旧 sector 字段完全隔离。"""

    __tablename__ = "industry_stage_taxonomy"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    version = Column(String(20), nullable=False, default=TAXONOMY_VERSION)
    index_code = Column(String(20), nullable=False)
    industry_code = Column(String(20), nullable=False)
    industry_name = Column(String(50), nullable=False)
    level = Column(String(4), nullable=False)
    parent_code = Column(String(20), nullable=False, default="0")
    source = Column(String(30), nullable=False, default="tushare_sw2021")
    is_active = Column(Boolean, nullable=False, default=True)
    fetched_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("version", "index_code", name="uq_industry_stage_taxonomy_version_code"),
        Index("ix_industry_stage_taxonomy_level", "version", "level", "is_active"),
    )


class IndustryStageMembership(Base):
    """股票与申万 L1/L2/L3 的有效期归属。"""

    __tablename__ = "industry_stage_membership"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    version = Column(String(20), nullable=False, default=TAXONOMY_VERSION)
    ts_code = Column(String(20), nullable=False)
    stock_name = Column(String(50), nullable=False, default="")
    l1_code = Column(String(20), nullable=False)
    l1_name = Column(String(50), nullable=False)
    l2_code = Column(String(20), nullable=False)
    l2_name = Column(String(50), nullable=False)
    l3_code = Column(String(20), nullable=False, default="")
    l3_name = Column(String(50), nullable=False, default="")
    in_date = Column(Date, nullable=True)
    out_date = Column(Date, nullable=True)
    is_current = Column(Boolean, nullable=False, default=True)
    source = Column(String(30), nullable=False, default="tushare_index_member_all")
    fetched_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "version", "ts_code", "l1_code", "l2_code", "l3_code", "in_date",
            name="uq_industry_stage_membership_period",
        ),
        Index("ix_industry_stage_membership_current", "version", "is_current", "l1_code"),
        Index("ix_industry_stage_membership_stock", "ts_code", "is_current"),
        Index("ix_industry_stage_membership_effective", "version", "ts_code", "in_date", "out_date"),
    )


class IndustryStageDailyBasic(Base):
    """云图面积和活跃度所需的日频基础指标。"""

    __tablename__ = "industry_stage_daily_basic"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False)
    ts_code = Column(String(20), nullable=False)
    close = Column(Float, nullable=True)
    total_mv = Column(Float, nullable=True)  # Tushare 单位：万元
    circ_mv = Column(Float, nullable=True)   # Tushare 单位：万元
    turnover_rate = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    source = Column(String(30), nullable=False, default="tushare_daily_basic")
    fetched_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", name="uq_industry_stage_daily_basic_date_code"),
        Index("ix_industry_stage_daily_basic_date", "trade_date"),
    )


class IndustryStageRun(Base):
    """一次完全离线的阶段池计算及其质量门禁。"""

    __tablename__ = "industry_stage_run"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, unique=True)
    status = Column(String(20), nullable=False)
    taxonomy_version = Column(String(20), nullable=False, default=TAXONOMY_VERSION)
    l1_count = Column(Integer, nullable=False, default=0)
    l2_count = Column(Integer, nullable=False, default=0)
    membership_count = Column(Integer, nullable=False, default=0)
    membership_coverage = Column(Float, nullable=False, default=0)
    daily_basic_count = Column(Integer, nullable=False, default=0)
    daily_basic_coverage = Column(Float, nullable=False, default=0)
    sector_count = Column(Integer, nullable=False, default=0)
    selected_stock_count = Column(Integer, nullable=False, default=0)
    message = Column(Text, nullable=False, default="")
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class IndustryStageSectorDaily(Base):
    """所有 L1 行业逐日评分及跨日状态。"""

    __tablename__ = "industry_stage_sector_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False)
    l1_code = Column(String(20), nullable=False)
    l1_name = Column(String(50), nullable=False)
    rank = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)
    state = Column(String(20), nullable=False)
    state_streak = Column(Integer, nullable=False, default=0)
    weak_streak = Column(Integer, nullable=False, default=0)
    universe_count = Column(Integer, nullable=False, default=0)
    valid_count = Column(Integer, nullable=False, default=0)
    selected_count = Column(Integer, nullable=False, default=0)
    core_count = Column(Integer, nullable=False, default=0)
    max_candidates = Column(Integer, nullable=False, default=0)
    ret_20d_median = Column(Float, nullable=True)
    ret_60d_median = Column(Float, nullable=True)
    breadth_ma20 = Column(Float, nullable=True)
    breadth_ma60 = Column(Float, nullable=True)
    advance_ratio = Column(Float, nullable=True)
    turnover_median = Column(Float, nullable=True)
    drawdown_median = Column(Float, nullable=True)
    total_mv = Column(Float, nullable=True)
    score_components_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("trade_date", "l1_code", name="uq_industry_stage_sector_date_code"),
        Index("ix_industry_stage_sector_date_rank", "trade_date", "rank"),
    )


class IndustryStageStockDaily(Base):
    """每个行业经过动态上限过滤后的阶段股票，不保存自动交易状态。"""

    __tablename__ = "industry_stage_stock_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False)
    l1_code = Column(String(20), nullable=False)
    l1_name = Column(String(50), nullable=False)
    l2_code = Column(String(20), nullable=False)
    l2_name = Column(String(50), nullable=False)
    ts_code = Column(String(20), nullable=False)
    stock_name = Column(String(50), nullable=False, default="")
    rank = Column(Integer, nullable=False)
    tier = Column(String(20), nullable=False)
    score = Column(Float, nullable=False)
    close = Column(Float, nullable=True)
    day_change_pct = Column(Float, nullable=True)
    ret_5d = Column(Float, nullable=True)
    ret_20d = Column(Float, nullable=True)
    ret_60d = Column(Float, nullable=True)
    above_ma20 = Column(Boolean, nullable=True)
    above_ma60 = Column(Boolean, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    turnover_rate = Column(Float, nullable=True)
    amount_20d = Column(Float, nullable=True)
    total_mv = Column(Float, nullable=True)
    circ_mv = Column(Float, nullable=True)
    drawdown_60d = Column(Float, nullable=True)
    reason = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("trade_date", "l1_code", "ts_code", name="uq_industry_stage_stock_date_sector"),
        Index("ix_industry_stage_stock_date_rank", "trade_date", "l1_code", "rank"),
        Index("ix_industry_stage_stock_code_date", "ts_code", "trade_date"),
    )


class IndustryStageRealtimeState(Base):
    """阶段池盘中行情采集状态；页面只读取这里，不在 GET 时外采。"""

    __tablename__ = "industry_stage_realtime_state"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False)
    pool_trade_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="WAITING")
    is_market_day = Column(Boolean, nullable=True)
    expected_count = Column(Integer, nullable=False, default=0)
    quote_count = Column(Integer, nullable=False, default=0)
    coverage = Column(Float, nullable=False, default=0)
    snapshot_time = Column(DateTime, nullable=True)
    source = Column(String(30), nullable=False, default="tencent_realtime")
    message = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("trade_date", name="uq_industry_stage_realtime_state_date"),
        Index("ix_industry_stage_realtime_state_updated", "trade_date", "updated_at"),
    )


class IndustryStageRealtimeQuote(Base):
    """阶段股票盘中最新行情；每个交易日每只股票仅保留最新一条。"""

    __tablename__ = "industry_stage_realtime_quote"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False)
    pool_trade_date = Column(Date, nullable=False)
    ts_code = Column(String(20), nullable=False)
    stock_name = Column(String(50), nullable=False, default="")
    price = Column(Float, nullable=False)
    previous_close = Column(Float, nullable=True)
    day_change_pct = Column(Float, nullable=True)
    amount_wan = Column(Float, nullable=True)  # 腾讯行情单位：万元
    turnover_rate = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    snapshot_time = Column(DateTime, nullable=False)
    source = Column(String(30), nullable=False, default="tencent_realtime")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", name="uq_industry_stage_realtime_quote_date_code"),
        Index("ix_industry_stage_realtime_quote_date_time", "trade_date", "snapshot_time"),
        Index("ix_industry_stage_realtime_quote_code_time", "ts_code", "snapshot_time"),
    )


INDUSTRY_STAGE_TABLES = (
    IndustryStageTaxonomy.__table__,
    IndustryStageMembership.__table__,
    IndustryStageDailyBasic.__table__,
    IndustryStageRun.__table__,
    IndustryStageSectorDaily.__table__,
    IndustryStageStockDaily.__table__,
    IndustryStageRealtimeState.__table__,
    IndustryStageRealtimeQuote.__table__,
)

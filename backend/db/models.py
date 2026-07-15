from sqlalchemy import Column, Integer, String, Date, DateTime, Numeric, Boolean, Text, UniqueConstraint, func, Index, Float, BigInteger
from db.connection import Base

class SectorFlow(Base):
    __tablename__ = "sector_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    sector = Column(String(50), nullable=False, index=True)
    money_inflow = Column(Numeric(18, 2))
    money_outflow = Column(Numeric(18, 2))
    net_flow = Column(Numeric(18, 2))
    rise_ratio = Column(Numeric(6, 2))
    limit_up_count = Column(Integer, default=0)
    avg_chg = Column(Numeric(6, 2))
    leader_stock = Column(String(20))
    leader_strength = Column(Numeric(6, 2))
    heat_score = Column(Numeric(8, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "sector", name="uq_sector_date"),)

class StockFlow(Base):
    __tablename__ = "stock_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(20))
    sector = Column(String(50), index=True)
    net_inflow = Column(Numeric(18, 2))
    main_force_inflow = Column(Numeric(18, 2))
    retail_flow = Column(Numeric(18, 2))
    price_chg = Column(Numeric(6, 2))
    price = Column(Numeric(10, 2))
    volume_change = Column(Numeric(10, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "ts_code", name="uq_stock_date"),)


class StockMoneyFlowDetail(Base):
    """个股主力资金 4 档细分净流入(东方财富/Tushare 通用格式)
    - super_large: 特大单净流入(>100 万)
    - large:      大单净流入(50-100 万)
    - small:      小单净流入(10-20 万)
    - tiny:       散单净流入(<5 万)
    - main_buy/sell: 主力买入/卖出金额(主力=特大+大)
    - retail_buy/sell: 散户买入/卖出金额
    - 占比 字段:占流通盘/换手率比例(由采集端算)
    - 数据源:tushare_moneyflow / eastmoney_push2
    """
    __tablename__ = "stock_money_flow_detail"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(20))

    # 4 档净流入(元)
    super_large_net = Column(Numeric(18, 2), default=0)   # 特大单净流入
    large_net = Column(Numeric(18, 2), default=0)         # 大单净流入
    medium_net = Column(Numeric(18, 2), default=0)        # 中单净流入
    small_net = Column(Numeric(18, 2), default=0)         # 小单净流入
    tiny_net = Column(Numeric(18, 2), default=0)          # 散单净流入

    # 主力/散户拆分
    main_net = Column(Numeric(18, 2), default=0)          # 主力净流入(特大+大)
    main_buy = Column(Numeric(18, 2), default=0)         # 主力买入
    main_sell = Column(Numeric(18, 2), default=0)        # 主力卖出
    retail_net = Column(Numeric(18, 2), default=0)       # 散户净流入
    retail_buy = Column(Numeric(18, 2), default=0)       # 散户买入
    retail_sell = Column(Numeric(18, 2), default=0)      # 散户卖出

    # 占比(占流通盘%)
    super_large_pct = Column(Numeric(6, 3), default=0)
    large_pct = Column(Numeric(6, 3), default=0)
    small_pct = Column(Numeric(6, 3), default=0)
    tiny_pct = Column(Numeric(6, 3), default=0)

    # 换手率
    turnover_rate = Column(Numeric(6, 3), default=0)

    # 元信息
    source = Column(String(20), default='tushare')       # tushare / eastmoney
    created_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "ts_code", name="uq_mfd_date"),)

class LeaderLifecycle(Base):
    __tablename__ = "leader_lifecycle"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(20))
    sector = Column(String(50))
    stage = Column(String(10), nullable=False)
    strength = Column(Numeric(6, 2))
    change_rate = Column(Numeric(6, 2))
    consecutive_days = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "ts_code", name="uq_leader_date"),)


# === 实时快照表（盘中每5分钟一条，保留30天用于回溯近期走势）===

class RealtimeSectorFlow(Base):
    """板块实时资金流向快照"""
    __tablename__ = "realtime_sector_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_time = Column(DateTime, nullable=False, index=True)  # 快照时间精确到分钟
    trade_date = Column(Date, nullable=False, index=True)
    sector = Column(String(50), nullable=False, index=True)
    money_inflow = Column(Numeric(18, 2))   # 万元
    money_outflow = Column(Numeric(18, 2))
    net_flow = Column(Numeric(18, 2))
    rise_ratio = Column(Numeric(6, 2))
    source = Column(String(20))  # sina/em/guosen
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("snapshot_time", "sector", name="uq_realtime_sector_time"),
        Index("ix_realtime_sector_date_sector", "trade_date", "sector"),
    )

class ConceptSector(Base):
    """概念板块定义（从 AkShare/同花顺同步）"""
    __tablename__ = "concept_sectors"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True, index=True)  # 概念名称，如"减肥药"
    source = Column(String(20), default='akshare_em')  # 数据来源 akshare_em / akshare_ths
    stocks = Column(Text)  # 成分股 ts_code 逗号分隔
    stock_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ConceptSectorFlow(Base):
    """概念板块日度资金流向（盘后聚合计算）"""
    __tablename__ = "concept_sector_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    concept_sector_id = Column(Integer, nullable=False, index=True)
    concept_name = Column(String(50), nullable=False, index=True)
    money_inflow = Column(Numeric(18, 2))   # 万元
    money_outflow = Column(Numeric(18, 2))
    net_flow = Column(Numeric(18, 2))
    rise_ratio = Column(Numeric(6, 2))
    avg_chg = Column(Numeric(6, 2))
    limit_up_count = Column(Integer, default=0)
    heat_score = Column(Numeric(8, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("trade_date", "concept_sector_id", name="uq_concept_sector_date"),
        Index("ix_concept_sector_flow_date_name", "trade_date", "concept_name"),
    )


class RealtimeConceptSectorFlow(Base):
    """概念板块实时资金流向快照"""
    __tablename__ = "realtime_concept_sector_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_time = Column(DateTime, nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    concept_sector_id = Column(Integer, nullable=False, index=True)
    concept_name = Column(String(50), nullable=False, index=True)
    money_inflow = Column(Numeric(18, 2))   # 万元
    money_outflow = Column(Numeric(18, 2))
    net_flow = Column(Numeric(18, 2))
    rise_ratio = Column(Numeric(6, 2))
    source = Column(String(20), default='computed')
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("snapshot_time", "concept_sector_id", name="uq_realtime_concept_sector_time"),
        Index("ix_realtime_concept_sector_date_name", "trade_date", "concept_name"),
    )


class RealtimeMoneyFlowSnapshot(Base):
    """概念/行业板块实时资金流向分钟级快照（数据中转防错专用）"""
    __tablename__ = "realtime_money_flow_snapshot"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    dimension = Column(String(20), nullable=False, index=True)      # concept / industry
    block_name = Column(String(50), nullable=False, index=True)
    minute = Column(String(5), nullable=False)                      # HH:MM
    net_inflow_yi = Column(Numeric(18, 4), nullable=False)          # 亿元
    source = Column(String(20), default='api')                      # api / ffill
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("trade_date", "dimension", "block_name", "minute",
                         name="uq_realtime_money_flow_snapshot"),
        Index("ix_realtime_money_flow_lookup",
              "trade_date", "dimension", "block_name", "minute"),
    )


class RealtimeStockFlow(Base):
    """个股实时资金流向快照（盘中 1 分钟级，保留 30 天）"""
    __tablename__ = "realtime_stock_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_time = Column(DateTime, nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(20))
    sector = Column(String(50), index=True)
    net_inflow = Column(Numeric(18, 2))         # 万元
    main_force_inflow = Column(Numeric(18, 2))  # 主力净流入（万元）
    retail_flow = Column(Numeric(18, 2))        # 小单净流入（万元）
    price_chg = Column(Numeric(6, 2))           # 涨跌幅 %
    price = Column(Numeric(10, 2))              # 最新价
    source = Column(String(200))  # em/guosen/tushare/...（逗号分隔）
    # === 数据质量追踪字段 ===
    confidence = Column(String(10))            # high/medium/low/disputed
    sources_count = Column(Integer)            # 参与复核的数据源数量
    sources_used = Column(String(200))         # 逗号分隔的数据源列表
    deviation_pct = Column(Numeric(6, 2))      # 多源偏差百分比
    is_corrected = Column(Boolean)             # 是否经过修正
    correction_note = Column(String(500))      # 修正说明
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("snapshot_time", "ts_code", name="uq_realtime_stock_time"),
        Index("ix_realtime_stock_date_code", "trade_date", "ts_code"),
        Index("ix_realtime_stock_date_time", "trade_date", "snapshot_time"),
    )


class StockMoneyFlowRealtime(Base):
    """盘中实时资金流分钟级快照（emdatah5 源）
    - 每次盘中采集追加一条新记录 → 数据持续沉淀积累
    - 可通过 (ts_code, trade_date, snapshot_time) 查询分钟级走势
    - 保留最近 30 天数据
    """
    __tablename__ = "stock_money_flow_realtime"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(20))
    snapshot_time = Column(DateTime, nullable=False, index=True)  # 采集时间戳

    main_buy = Column(Numeric(18, 2), default=0)   # 主力买入(元)
    main_sell = Column(Numeric(18, 2), default=0)  # 主力卖出(元)
    main_net = Column(Numeric(18, 2), default=0)   # 主力净额(元)
    retail_buy = Column(Numeric(18, 2), default=0)  # 散户买入(元)
    retail_sell = Column(Numeric(18, 2), default=0) # 散户卖出(元)
    retail_net = Column(Numeric(18, 2), default=0)  # 散户净额(元)
    turnover = Column(Numeric(18, 2), default=0)    # 成交量/换手率
    source = Column(String(20), default='emdatah5')

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_realtime_flow_ts_date", "ts_code", "trade_date", "snapshot_time"),
        Index("ix_realtime_flow_date", "trade_date", "snapshot_time"),
    )


class DataQualityLog(Base):
    """数据质量日志（每次复核记录）"""
    __tablename__ = "data_quality_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_time = Column(DateTime, nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), index=True)
    name = Column(String(20))
    indicator = Column(String(50))             # 指标名（main_force_inflow/price等）
    sources_data = Column(Text)                # JSON：各源的原始值
    authority_value = Column(Numeric(18, 2))   # 最终采用的权威值
    outliers = Column(String(200))             # 异常源列表
    quality_score = Column(Numeric(5, 2))      # 质量评分 0-100
    action = Column(String(20))                # accept/correct/reject/review
    created_at = Column(DateTime, server_default=func.now())


class DataCollectionAlert(Base):
    """数据采集告警（实时采集失败、断层、数据量异常等）"""
    __tablename__ = "data_collection_alert"
    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(10), nullable=False, index=True)      # warning/error/critical
    category = Column(String(50), nullable=False, index=True)   # collection_gap/quantity_anomaly/source_failure
    message = Column(String(500), nullable=False)
    details = Column(Text)                                      # JSON
    trade_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    __table_args__ = (
        Index("ix_data_collection_alert_date_level", "trade_date", "level"),
    )


class ManualReviewQueue(Base):
    """人工审核队列"""
    __tablename__ = "manual_review_queue"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(20))
    indicator = Column(String(50))
    reason = Column(String(200))               # 触发原因
    sources_data = Column(Text)                # JSON：各源数据
    status = Column(String(20), default='pending')  # pending/approved/rejected
    reviewed_by = Column(String(50))
    reviewed_at = Column(DateTime)
    final_value = Column(Numeric(18, 2))


class DataSourceReliability(Base):
    """数据源可靠性统计（用于动态调整权重）"""
    __tablename__ = "data_source_reliability"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    source = Column(String(20), nullable=False)    # em/guosen/tushare/sina/tencent/tdx
    total_count = Column(Integer, default=0)       # 总采集次数
    outlier_count = Column(Integer, default=0)     # 被标记为异常的次数
    avg_deviation = Column(Numeric(6, 2))          # 平均偏差百分比
    reliability_score = Column(Numeric(5, 2))      # 可靠性评分 0-100
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("date", "source", name="uq_source_date"),)


class Watchlist(Base):
    """自选股列表"""
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, unique=True, index=True)  # 6位代码
    stock_name = Column(String(20))
    note = Column(String(200))                  # 备注
    group_name = Column(String(50), default='默认')  # 分组
    sort_order = Column(Integer, default=0)     # 排序
    # 质量状态（不做杂毛体系）：杂毛/普通/合格/优质/强势/核心/淘汰
    quality_status = Column(String(10), default='普通')
    created_at = Column(DateTime, server_default=func.now())


class BSStrategy(Base):
    """BS选股策略配置"""
    __tablename__ = "bs_strategies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)           # 策略名称
    atr_period = Column(Integer, default=10)            # ATR周期
    atr_multiplier = Column(Numeric(4, 2), default=1.0) # ATR乘数
    scan_limit = Column(Integer, default=50)            # 扫描股票数量
    sector_filter = Column(String(200))                 # 板块筛选(逗号分隔)
    signal_type = Column(String(10), default='B')       # 信号类型: B/S/ALL
    volume_filter = Column(Boolean, default=False)      # 成交量过滤
    ma20_filter = Column(Boolean, default=False)        # MA20方向过滤
    ma60_trend = Column(Boolean, default=False)         # MA60趋势过滤
    rsi_filter = Column(Boolean, default=False)         # RSI过滤
    strong_volume = Column(Boolean, default=False)      # 强量突破过滤
    created_at = Column(DateTime, server_default=func.now())


class BSBacktestResult(Base):
    """BS回测历史记录（一次回测一行）"""
    __tablename__ = "bs_backtest_results"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50))                             # 回测名称/编号（用户自定义）
    run_at = Column(DateTime, server_default=func.now(), index=True)  # 回测时间
    dimension = Column(String(20), default='custom')    # 维度: all/chinext/star/custom
    stock_count = Column(Integer, default=0)            # 回测股票数
    start_date = Column(String(10))                     # 回测开始日期
    end_date = Column(String(10))                       # 回测结束日期
    initial_capital = Column(Numeric(14, 2), default=100000)  # 初始资金
    # 策略参数
    atr_period = Column(Integer, default=10)
    atr_multiplier = Column(Numeric(4, 2), default=1.0)
    volume_filter = Column(Boolean, default=False)
    ma20_filter = Column(Boolean, default=False)
    ma60_trend = Column(Boolean, default=False)
    rsi_filter = Column(Boolean, default=False)
    strong_volume = Column(Boolean, default=False)
    macd_filter = Column(Boolean, default=False)         # MACD动能过滤
    kdj_filter = Column(Boolean, default=False)          # KDJ超买过滤
    stop_loss_pct = Column(Numeric(5, 2), default=0)     # 止损百分比(0=不止损)
    # 回测统计
    total_trades = Column(Integer, default=0)
    win_trades = Column(Integer, default=0)
    loss_trades = Column(Integer, default=0)
    win_rate = Column(Numeric(5, 2), default=0)         # 交易胜率%
    stock_win_rate = Column(Numeric(5, 2), default=0)   # 个股胜率%
    total_profit_pct = Column(Numeric(8, 2), default=0) # 总收益率%
    annual_return = Column(Numeric(8, 2), default=0)    # 年化收益%
    max_drawdown_pct = Column(Numeric(6, 2), default=0) # 最大回撤%
    profit_factor = Column(Numeric(6, 2), default=0)    # 盈亏比
    avg_hold_days = Column(Numeric(6, 1), default=0)    # 平均持仓天数
    max_profit_pct = Column(Numeric(8, 2), default=0)   # 最大单笔盈利%
    max_loss_pct = Column(Numeric(8, 2), default=0)     # 最大单笔亏损%
    total_profit = Column(Numeric(14, 2), default=0)    # 总盈利金额
    note = Column(String(200))                          # 备注
    # 板块趋势过滤参数
    sector_uptrend_filter = Column(Boolean, default=False)  # 板块上升趋势过滤
    sector_top_n = Column(Integer, default=10)              # 每日Top N板块
    sector_filter_mode = Column(String(20), default='strong_rotation')  # strong_rotation/strong_only
    sector_no_data_action = Column(String(10), default='pass')  # 无数据日: pass/block


class LeaderHistory(Base):
    """龙头历史追踪表（V5：记录每日主龙，用于统计验证）"""
    __tablename__ = "leader_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(String(10), nullable=False, index=True)   # YYYY-MM-DD
    sector = Column(String(50), nullable=False, index=True)       # 所属板块
    leader_code = Column(String(20), nullable=False, index=True)  # 龙头股票代码
    leader_name = Column(String(20))                               # 龙头股票名称
    leader_score = Column(Numeric(5, 2))                           # 龙头评分(0-10)
    sector_score = Column(Numeric(5, 2))                           # 板块评分(0-10)
    stage = Column(String(10))                                     # 生命周期阶段
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("trade_date", "sector", name="uq_leader_history_date_sector"),
    )


# ===== 个股研究沉淀（妙想资讯/金融数据/AI分析） =====

class StockNewsSearch(Base):
    """个股资讯搜索历史（供 AI 分析数据沉淀）"""
    __tablename__ = "stock_news_search"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, index=True)   # 6位代码
    stock_name = Column(String(20))                                 # 股票名
    query_keyword = Column(String(500), nullable=False)             # 搜索关键词
    search_time = Column(DateTime, nullable=False, index=True)      # 搜索时间
    result_summary = Column(Text)                                   # 结果摘要（前500字）
    result_raw = Column(Text)                                      # 完整结果JSON（供AI分析）
    created_at = Column(DateTime, server_default=func.now())


class StockDataQuery(Base):
    """个股金融数据查询历史（供 AI 分析数据沉淀）"""
    __tablename__ = "stock_data_query"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(20))
    query_keyword = Column(String(500), nullable=False)
    query_time = Column(DateTime, nullable=False, index=True)
    result_tables = Column(Text)                                   # 结果表格JSON（供AI分析）
    created_at = Column(DateTime, server_default=func.now())


class AIAnalysisCache(Base):
    """AI 分析结果缓存（预留，供后续 AI 机器人写入）"""
    __tablename__ = "ai_analysis_cache"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, index=True)
    analysis_type = Column(String(50), nullable=False)              # news/financial/technical/comprehensive
    analysis_data = Column(Text)                                    # AI分析结果JSON
    data_sources = Column(Text)                                     # 引用的历史搜索id列表JSON
    model = Column(String(50))                                      # AI模型标识
    created_at = Column(DateTime, server_default=func.now())


class StockFeaturesDaily(Base):
    """个股每日特征数据（供 CHOPPY/TREND/IMPULSE 三态判定）
    最小字段集：价格结构 / 成交量 / 资金流(替代) / 波动结构 / 趋势一致性 / 板块"""
    __tablename__ = "stock_features_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, index=True)
    trade_date = Column(String(8), nullable=False, index=True)      # YYYYMMDD

    # ① 价格结构
    close = Column(Float)
    ma5 = Column(Float)
    ma20 = Column(Float)
    ma60 = Column(Float)
    ma20_slope = Column(Float)                                       # MA20斜率(归一化)
    close_vs_ma20 = Column(Float)                                    # (close-ma20)/ma20
    high_break_20d = Column(Integer)                                 # 近20日新高突破次数

    # ② 成交量
    volume = Column(BigInteger)
    volume_ma20 = Column(BigInteger)
    volume_ratio = Column(Float)                                     # volume/volume_ma20

    # ③ 资金流（主力净流入，来自StockFlow表）
    main_net_inflow_1d = Column(BigInteger)                           # 当日主力净流入
    main_net_inflow_3d = Column(BigInteger)                           # 3日累计主力净流入
    main_net_inflow_5d = Column(BigInteger)                           # 5日累计主力净流入
    flow_continuity = Column(Integer)                                # 连续净流入天数

    # ④ 波动结构
    atr_14 = Column(Float)
    noise_ratio = Column(Float)                                      # 上下影线/实体
    rsi_14 = Column(Float)                                           # RSI(14)

    # ⑤ 趋势一致性
    higher_high_flag = Column(Integer)                               # 近5日是否创新高 1/0
    higher_low_flag = Column(Integer)                               # 近5日是否创新低抬高 1/0
    trend_consistency_score = Column(Float)                         # 趋势一致性评分 0-1

    # ⑥ 板块
    sector_strength = Column(Float)                                 # 板块当日涨跌幅%

    # 最终判定
    market_state = Column(String(10))                               # CHOPPY / TREND / IMPULSE
    state_reasons = Column(Text)                                    # 判定原因JSON

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('ix_stock_features_code_date', 'stock_code', 'trade_date', unique=True),
    )


class StockDailyKline(Base):
    """个股日 K 线（Tushare daily 同步到本地,供 7 天生命周期等中转层使用）"""
    __tablename__ = "stock_daily_kline"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    open = Column(Numeric(10, 4))
    high = Column(Numeric(10, 4))
    low = Column(Numeric(10, 4))
    close = Column(Numeric(10, 4))
    volume = Column(BigInteger)
    amount = Column(Numeric(20, 4))
    pct_chg = Column(Numeric(8, 4))
    main_force_inflow = Column(Numeric(20, 4))
    sector = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_daily_kline_code_date"),
        Index("ix_daily_kline_date", "trade_date"),
    )


class StockRealtimeTick(Base):
    """盘中 tick 流水（每 3 秒一条,30 天 TTL）
    数据流:iTick/mootdx 拉分时 + 五档 → 大单检测 → 实时聚合
    """
    __tablename__ = "stock_realtime_tick"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_time = Column(DateTime, nullable=False, index=True)        # 精确到秒
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    price = Column(Numeric(10, 4))                                     # 最新价
    volume = Column(BigInteger)                                        # 累计成交量(手)
    amount = Column(Numeric(20, 4))                                    # 累计成交额(元)
    bid_price_1 = Column(Numeric(10, 4))                              # 买一价
    bid_vol_1 = Column(BigInteger)                                     # 买一量(手)
    ask_price_1 = Column(Numeric(10, 4))                              # 卖一价
    ask_vol_1 = Column(BigInteger)                                     # 卖一量(手)
    turnover_rate = Column(Numeric(6, 2))                              # 换手率%
    main_force_inflow = Column(Numeric(20, 4))                         # 主力净流入(元)
    source = Column(String(20))                                        # itick / tdx / sina
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        Index("ix_realtime_tick_lookup", "trade_date", "ts_code", "snapshot_time"),
    )


class StockRealtimeOrderbook(Base):
    """盘口快照（每 3 秒一条,保留 30 天,收盘后清理过期数据）"""
    __tablename__ = "stock_realtime_orderbook"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_time = Column(DateTime, nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    # 五档买盘
    bid_prices = Column(Text)      # JSON [b1, b2, b3, b4, b5]
    bid_vols = Column(Text)        # JSON [v1, v2, v3, v4, v5]
    ask_prices = Column(Text)
    ask_vols = Column(Text)
    source = Column(String(20))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        Index("ix_realtime_orderbook_lookup", "trade_date", "ts_code", "snapshot_time"),
    )


# ===== 策略选股结果 =====

class StrategyResult(Base):
    """每日策略选股结果（每只股票×每个策略×每天一条）
    用于个股详情页「策略标签」展示和策略中心健康监控。
    """
    __tablename__ = "strategy_result"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)                # 交易日期
    ts_code = Column(String(20), nullable=False, index=True)             # 股票代码
    strategy_key = Column(String(20), nullable=False, index=True)        # 策略key: baihu_v26/baihu_v30/qinglong/zhushenglang
    strategy_name = Column(String(20), nullable=False)                   # 策略中文名: 白虎/白虎V3/青龙/主升浪
    name = Column(String(20))                                             # 股票名称
    sector = Column(String(50))                                           # 所属板块
    score = Column(Numeric(5, 2))                                         # 策略评分
    scores_json = Column(Text)                                            # 评分明细JSON
    detail_json = Column(Text)                                            # 完整指标JSON（ma/rsi/bias等）
    exit_signal = Column(String(50))                                      # 退出信号（如有）
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", "strategy_key", name="uq_strategy_result_date_code_key"),
        Index('ix_strategy_result_date_key', 'trade_date', 'strategy_key'),
    )


class StrategyRunLog(Base):
    """策略运行日志（每次扫描一条，用于健康检查）"""
    __tablename__ = "strategy_run_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)                # 交易日期
    strategy_key = Column(String(20), nullable=False, index=True)        # 策略key
    strategy_name = Column(String(20), nullable=False)                   # 策略中文名
    started_at = Column(DateTime, nullable=False)                        # 开始时间
    finished_at = Column(DateTime)                                        # 结束时间
    duration_seconds = Column(Numeric(8, 2))                              # 耗时(秒)
    candidate_count = Column(Integer, default=0)                          # 候选股票数
    hit_count = Column(Integer, default=0)                                # 命中数
    status = Column(String(20), default='running')                        # running/success/failed
    error_msg = Column(Text)                                              # 错误信息
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("trade_date", "strategy_key", name="uq_strategy_run_log_date_key"),
    )


class BSDailyScan(Base):
    """BS策略每日预扫描结果（盘后批量计算，消除网页打开时的现场全市场扫描）
    每个 BSBacktestResult 策略每天一条，signals_json 存完整 signals 列表。
    """
    __tablename__ = "bs_daily_scan"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)                # 交易日期
    backtest_id = Column(Integer, nullable=False, index=True)            # 对应 BSBacktestResult.id
    strategy_name = Column(String(50))                                   # 策略名称
    dimension = Column(String(20))                                       # 维度 all/chinext/star
    signals_json = Column(Text)                                          # 完整 signals 列表 JSON
    summary_json = Column(Text)                                          # summary JSON
    scanned = Column(Integer, default=0)                                 # 扫描股票数
    hit_count = Column(Integer, default=0)                               # 命中数
    generated_at = Column(DateTime, server_default=func.now())           # 生成时间
    __table_args__ = (
        UniqueConstraint("trade_date", "backtest_id", name="uq_bs_daily_scan_date_bt"),
    )


class WatchlistSignalDaily(Base):
    """每日个股信号预计算结果（盘后批量计算，消除网页打开时的现场计算/HTTP拉取）
    被 /api/watchlist、/api/panorama/stocks、/api/leader/system 共用。
    """
    __tablename__ = "watchlist_signal_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)                # 交易日期
    ts_code = Column(String(20), nullable=False, index=True)             # 股票代码
    name = Column(String(20))                                            # 股票名称
    sector = Column(String(50))                                          # 所属板块
    sector_trend_json = Column(Text)                                     # 板块趋势JSON
    market_state_json = Column(Text)                                     # 市场状态JSON
    bs_signal = Column(String(2))                                        # B/S/None
    bs_reasons_json = Column(Text)                                       # BS原因JSON
    quality_status = Column(String(20))                                  # 质量状态
    buy_power_base = Column(Text)                                        # 购买力JSON（score/level/color/dimensions）
    change_rate = Column(Numeric(6, 2))                                  # 涨幅%
    main_force_inflow = Column(Numeric(18, 2))                           # 主力净流入
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", name="uq_watchlist_signal_date_code"),
    )


class AutoTradeConfig(Base):
    """自动化交易风控配置（单行表，id=1）"""
    __tablename__ = "auto_trade_config"
    id = Column(Integer, primary_key=True)  # 固定 id=1
    enabled = Column(Boolean, default=False)
    single_position_pct = Column(Numeric(5, 2), default=10)   # 单票仓位%
    max_positions = Column(Integer, default=10)               # 最大持仓数（总持仓上限）
    max_buy_count = Column(Integer, default=20)              # 每日最多买入只数
    stop_loss_pct = Column(Numeric(5, 2), default=-5)         # 止损%（负数）
    take_profit_pct = Column(Numeric(5, 2), default=15)       # 止盈%
    min_vote_score = Column(Integer, default=2)               # 最小投票数
    use_market_price = Column(Boolean, default=True)          # 市价委托
    buy_quantity = Column(Integer, default=100)               # 每次买入股数（100的整数倍）
    sell_quantity = Column(Integer, default=100)              # 每次卖出股数（100的整数倍）
    updated_at = Column(DateTime, server_default=func.now())


class AutoTradeLog(Base):
    """自动化交易日志（每次操作一条，落库审计）"""
    __tablename__ = "auto_trade_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, index=True)
    ts_code = Column(String(20), index=True)
    action = Column(String(10))           # buy/sell/skip
    reason = Column(String(200))
    vote_score = Column(Integer)
    strategies_json = Column(Text)        # 命中策略明细
    price = Column(Numeric(10, 2))
    quantity = Column(Integer)
    order_result = Column(Text)           # 妙想API返回
    status = Column(String(20))           # success/failed/skipped
    created_at = Column(DateTime, server_default=func.now())


class SimAccount(Base):
    """原模拟盘虚拟账户资金（单行表，id=1）"""
    __tablename__ = "sim_account"
    id = Column(Integer, primary_key=True)
    acc_name = Column(String(50), default='AIROBOT模拟盘')
    init_money = Column(Numeric(18, 2), default=1000000)
    total_assets = Column(Numeric(18, 2), default=1000000)
    avail_balance = Column(Numeric(18, 2), default=1000000)
    frozen_money = Column(Numeric(18, 2), default=0)
    total_pos_value = Column(Numeric(18, 2), default=0)
    total_pos_pct = Column(Numeric(5, 2), default=0)
    nav = Column(Numeric(10, 4), default=1)
    opr_days = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.now())


class SimPosition(Base):
    """原模拟盘虚拟持仓"""
    __tablename__ = "sim_position"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sec_code = Column(String(20), index=True)
    sec_name = Column(String(50))
    sec_mkt = Column(Integer, default=0)
    count = Column(Integer, default=0)
    avail_count = Column(Integer, default=0)
    cost_price = Column(Numeric(10, 3))
    price = Column(Numeric(10, 3))
    value = Column(Numeric(18, 2))
    day_profit = Column(Numeric(18, 2))
    day_profit_pct = Column(Numeric(6, 2))
    profit = Column(Numeric(18, 2))
    profit_pct = Column(Numeric(6, 2))
    pos_pct = Column(Numeric(5, 2))
    updated_at = Column(DateTime, server_default=func.now())


class SimOrder(Base):
    """原模拟盘虚拟委托记录"""
    __tablename__ = "sim_order"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sec_code = Column(String(20), index=True)
    sec_name = Column(String(50))
    sec_mkt = Column(Integer, default=0)
    drt = Column(Integer)                 # 1=买入, 2=卖出
    price = Column(Numeric(10, 3))
    count = Column(Integer)
    trade_count = Column(Integer, default=0)
    trade_price = Column(Numeric(10, 3))
    status = Column(Integer, default=4)   # 4=已成（模拟盘即时成交）
    time = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now())


class SimPositionSnapshot(Base):
    """模拟盘持仓每日快照（东财/本地统一归档，用于回溯历史持仓和盈亏）"""
    __tablename__ = "sim_position_snapshot"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    source = Column(String(20), default='mx')  # mx=东财模拟盘, local=本地模拟盘
    sec_code = Column(String(20), nullable=False, index=True)
    sec_name = Column(String(50))
    sec_mkt = Column(Integer, default=0)
    count = Column(Integer, default=0)
    avail_count = Column(Integer, default=0)
    cost_price = Column(Numeric(10, 3))
    price = Column(Numeric(10, 3))
    value = Column(Numeric(18, 2))
    day_profit = Column(Numeric(18, 2))
    day_profit_pct = Column(Numeric(6, 2))
    profit = Column(Numeric(18, 2))
    profit_pct = Column(Numeric(6, 2))
    pos_pct = Column(Numeric(5, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "source", "sec_code", name="uq_position_snapshot"),)


class SimAccountSnapshot(Base):
    """模拟盘账户资金每日快照"""
    __tablename__ = "sim_account_snapshot"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True, unique=True)
    source = Column(String(20), default='mx')
    acc_name = Column(String(50))
    acc_id = Column(String(50))
    init_money = Column(Numeric(18, 2))
    total_assets = Column(Numeric(18, 2))
    avail_balance = Column(Numeric(18, 2))
    frozen_money = Column(Numeric(18, 2))
    total_pos_value = Column(Numeric(18, 2))
    total_pos_pct = Column(Numeric(5, 2))
    nav = Column(Numeric(10, 4))
    opr_days = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())


class TradingSignalDaily(Base):
    """游资系统 4.0 每日交易信号日报（盘后批量预计算）
    每只候选股票每天一条，记录：4.0 信号分级 + 动态仓位 + 风控决策
    数据来源：WatchlistSignalDaily → 4.0 引擎增强
    """
    __tablename__ = "trading_signal_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(20))
    sector = Column(String(50), index=True)

    # 4.0 信号分级
    signal_4 = Column(String(10))           # STRONG_BUY / WATCH_BUY / FORBID
    signal_label = Column(String(10))       # 强买 / 观察买 / 禁止参与
    signal_color = Column(String(10))
    final_score = Column(Numeric(5, 2))
    score_detail_json = Column(Text)

    # 动态仓位决策
    position_pct = Column(Numeric(5, 2))
    position_amount = Column(Numeric(14, 2))
    stop_loss_pct = Column(Numeric(5, 2))   # 负数（基于 ATR）
    take_profit_pct = Column(Numeric(5, 2))
    atr_14 = Column(Float)
    risk_per_share = Column(Numeric(10, 2))

    # 风控决策
    risk_status = Column(String(10))        # ok / warn / forbid
    risk_reasons_json = Column(Text)
    market_state = Column(String(10))       # CHOPPY / TREND / IMPULSE
    sentiment_stage = Column(String(10))
    is_high_position = Column(Boolean)

    # 原始 signal 引用
    watchlist_signal_id = Column(Integer)
    reasons_json = Column(Text)

    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", name="uq_trading_signal_date_code"),
        Index("ix_trading_signal_date_signal", "trade_date", "signal_4"),
    )


# ============================================================
# 游资龙虎榜系统（Day1 盘后清洗 -> 量化共振 -> Day2 观察池）
# ============================================================

class YuziDict(Base):
    """顶级游资席位字典（可手动增删改）

    字段：
    - seat_name: 交易所营业部全称（来自 Tushare top_inst.ex_name）
    - yuzi_alias: 大佬标签（章盟主、方新侠、炒股养家 等）
    - yuzi_group: 顶级游资 / 实力游资 / 假游资 / 机构专用
    - style: 操作风格 (稳健/一日游/砸盘/接力/低吸/趋势/首板/机构) - 前端过滤+展示用
    - region: 地域
    - tags: 自定义标签 JSON
    - is_active: 是否启用监控
    """
    __tablename__ = "yuzi_dict"
    id = Column(Integer, primary_key=True, autoincrement=True)
    seat_name = Column(String(255), unique=True, nullable=False)
    yuzi_alias = Column(String(100), nullable=False)
    yuzi_group = Column(String(50), default='实力游资')   # 顶级/实力/机构/假游资
    style = Column(String(50), default='稳健')             # 稳健/一日游/砸盘/接力/低吸/趋势/首板/机构
    region = Column(String(50))
    tags = Column(Text)                                  # JSON 数组
    is_active = Column(Boolean, default=True)
    hot_score = Column(Integer, default=50)              # 0-100 大佬活跃度
    note = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class YuziQuantSignal(Base):
    """每日游资量化共振信号（一股一条，按 ts_code+trade_date 唯一）

    数据流：Tushare top_list/top_inst → 匹配 yuzi_dict →
           按 ts_code 聚合 net_buy + 评分 → 写入本表 →
           前端 /yuzi-billboard 直接读取
    """
    __tablename__ = "yuzi_quant_signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(String(8), nullable=False, index=True)  # YYYYMMDD
    ts_code = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(100))
    sector = Column(String(50))

    # 聚合后的核心字段
    total_net_buy = Column(Numeric(16, 2))     # 万元（圈选大佬净买入合计）
    total_buy = Column(Numeric(16, 2))
    total_sell = Column(Numeric(16, 2))
    resonance_count = Column(Integer)          # 共振大佬数量
    boss_list = Column(Text)                   # 逗号隔开的大佬名称
    seat_detail = Column(Text)                 # JSON 数组 [{alias,side,net_buy,buy,sell}]

    # 量化评分
    quant_score = Column(Numeric(5, 2))        # 0-100
    score_factors = Column(Text)               # JSON 评分因子明细

    # 股票上下文（用于联动）
    change_pct = Column(Numeric(6, 2))         # 涨跌幅
    close_price = Column(Numeric(10, 2))
    turnover_rate = Column(Numeric(6, 2))      # 换手率
    limit_up_flag = Column(Boolean)            # 是否涨停
    amount = Column(Numeric(18, 2))            # 成交额（元）

    # 上榜原因（来自 top_list.reason / explain）
    list_reason = Column(String(255))
    list_tag = Column(String(50))              # 涨停/跌停/异常波动/...

    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("trade_date", "ts_code", name="uq_yuzi_signal_date_code"),
        Index("ix_yuzi_signal_date_score", "trade_date", "quant_score"),
    )


class YuziSeatDaily(Base):
    """每日席位明细（一席位一条，便于游资画像/近 N 日战绩）

    数据流：Tushare top_inst → 写一份按 seat_name+ts_code+trade_date 唯一的明细
    """
    __tablename__ = "yuzi_seat_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(String(8), nullable=False, index=True)
    seat_name = Column(String(255), nullable=False, index=True)
    yuzi_alias = Column(String(100), index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(100))
    side = Column(String(10))                  # BUY / SELL
    buy_amount = Column(Numeric(16, 2))        # 万元
    sell_amount = Column(Numeric(16, 2))
    net_amount = Column(Numeric(16, 2))
    net_ratio = Column(Numeric(6, 2))          # 净买/总成交
    turnover_rate = Column(Numeric(6, 2))
    amount = Column(Numeric(18, 2))
    list_reason = Column(String(255))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("trade_date", "seat_name", "ts_code", name="uq_seat_date_code"),
        Index("ix_seat_alias_date", "yuzi_alias", "trade_date"),
    )


# ============================================================
# 游资 20 天生命周期跟踪表（T+20 Matrix，宽表 + JSONB）
# ============================================================
class YuziLifecycleTracker(Base):
    """游资共振股 20 天动态跟踪表（宽表结构 + JSONB 状态矩阵）

    数据流：
    Day 1 盘后：触发器（yuzi_quant_signals 当日净买>0 且 resonance>=2）
                → INSERT 触发记录（trigger_date, quant_score_d1, boss_list_d1）
    Day 2-20 盘后：调度器（lifecycle_tracker.py）
                → 拉 daily → 组装 7 维度 → UPDATE lifecycle_data JSONB
    Day 20+：    → 算 final_outcome（20d 收益分档）
                → 算 net_return_20d

    JSONB 格式：
    {
      "d2": {
        "price_stage": "连板/跌停A杀/震荡/晋级/分歧/锁仓/沉寂",
        "open_premium": 4.5,        # 竞价溢价 %
        "intra_amplitude": 9.5,     # 盘中振幅 %
        "turnover_status": 12.0,    # 换手率 %
        "capital_retention": "锁仓/减仓/出货/无数据",
        "support_level": "强/中/弱",
        "win_rate_impact": 6.5      # 今日涨幅贡献 %
      },
      "d3": {...}
    }
    """
    __tablename__ = "yuzi_lifecycle_tracker"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trigger_date = Column(String(8), nullable=False, index=True)  # YYYYMMDD
    ts_code = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(100))
    quant_score_d1 = Column(Numeric(5, 2))      # Day 1 原始评分
    boss_list_d1 = Column(Text)                  # Day 1 初始大佬（逗号隔开）
    resonance_count_d1 = Column(Integer)         # Day 1 共振数

    # 20 天状态矩阵
    lifecycle_data = Column(Text)                # JSON 字符串（PG 也可用 JSONB 字段类型）

    # 20 天最终结局
    final_outcome = Column(String(20), index=True)   # 大妖股/A杀退潮/高位震荡/横盘/弱势回调/未结束
    net_return_20d = Column(Numeric(6, 2))           # 20d 最高可实现最大收益率 %

    # 内部状态
    day_filled = Column(Integer, default=1)       # 已填到第几天
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("trigger_date", "ts_code", name="uq_tracker_date_code"),
        Index("ix_tracker_outcome", "final_outcome"),
        Index("ix_tracker_score", "quant_score_d1"),
    )


class StockHolderNumber(Base):
    """股东户数与户均持股（用于筹码集中度/主力吸筹判断）

    数据源：Tushare stk_holdernumber
    - ann_date: 公告日期
    - holder_num: 股东户数（户）
    - avg_shares: 户均持股（股）
    """
    __tablename__ = "stock_holder_number"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(20))
    ann_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=True, index=True)
    holder_num = Column(BigInteger, default=0)
    avg_shares = Column(Numeric(16, 2), default=0)
    source = Column(String(20), default='tushare')
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("ts_code", "ann_date", name="uq_holder_ts_date"),)


# ===== 研报中心（分析请求队列 + 报告结果，落 PG 以便多用户复用/查询）=====

class AnalysisRequest(Base):
    """研报中心：个股分析请求队列

    - status: pending -> processing -> completed / failed
    - 由 analysis_consumer 后台轮询 pending 并生成报告
    """
    __tablename__ = "analysis_requests"
    id = Column(String(20), primary_key=True)          # 12位 hex rid
    stock_code = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(50), default='')
    source = Column(String(20), default='tdx')         # tdx / ifind / recap
    status = Column(String(20), default='pending', index=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AnalysisReport(Base):
    """研报中心：个股分析报告结果（完整报告 JSON 落库）

    - report_json: 完整报告 dict 的 json.dumps（与前端渲染契约一致）
    - rating/target_price/confidence: 冗余列，便于列表快速过滤/展示
    """
    __tablename__ = "analysis_reports"
    id = Column(String(20), primary_key=True)          # = request id
    stock_code = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(50), default='')
    source = Column(String(20), default='tdx')
    report_type = Column(String(50), default='')
    rating = Column(String(20), default='')
    target_price = Column(String(40), default='')
    confidence = Column(String(20), default='')
    report_json = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (Index("ix_analysis_report_src_created", "source", "created_at"),)


class Notification(Base):
    """研报中心：分析完成通知（落 PG，前端读取未读列表）"""
    __tablename__ = "analysis_notifications"
    id = Column(String(40), primary_key=True)
    source = Column(String(20), default='')
    stock_code = Column(String(20), default='')
    stock_name = Column(String(50), default='')
    title = Column(String(120), default='')
    read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, server_default=func.now())


class StockF10(Base):
    """研报中心：F10 免费数据源缓存（Tushare 财务/机构 + 东方财富评级/目标价）

    按 ts_code 缓存整包 JSON，TTL 1 天（财务/机构日频变化）。
    任何免费源失败则该字段为 None，绝不阻断主报告生成。
    """
    __tablename__ = "stock_f10"
    ts_code = Column(String(20), primary_key=True)
    financial_json = Column(Text, nullable=True)      # 营收/净利/ROE/毛利率/eps
    institution_json = Column(Text, nullable=True)     # 机构数/持仓占流通比
    rating_json = Column(Text, nullable=True)          # 券商评级/目标价/一致EPS
    fetched_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class StockUniverse(Base):
    """全市场股票基础信息（来自 Tushare stock_basic，盘后增量刷新）

    作为量化选股/覆盖池的基础表：名称、申万/证监会行业、上市板块。
    F10 财务/机构数据按 ts_code 关联 stock_f10。
    """
    __tablename__ = "stock_universe"
    ts_code = Column(String(20), primary_key=True)
    name = Column(String(50), default='')
    industry = Column(String(50), default='')          # Tushare industry 字段（申万一级/证监会）
    market = Column(String(20), default='')            # 主板/创业板/科创板/北交所
    list_status = Column(String(5), default='L')       # L 上市 / D 退市 / P 暂停
    is_active = Column(Boolean, default=True, index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SimPositionCost(Base):
    """模拟盘持仓成本缓存（跨重启持久化）

    妙想 API 经常返回 costPrice=0 且委托记录重算也常失败。
    利用 PG 缓存最后一次成功获取的成本价，确保跨重启盈亏计算准确。
    """
    __tablename__ = "sim_position_cost"
    api_key = Column(String(20), primary_key=True)
    sec_code = Column(String(20), primary_key=True)
    cost_price = Column(Numeric(18, 4), default=0)
    quantity = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ===== 股票跟踪 =====

class StockTracker(Base):
    """用户选中加入跟踪的股票（记录入选时刻 + 入选价，计算 1-30 日收益）"""
    __tablename__ = "stock_tracker"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, unique=True, index=True)  # 6位代码
    stock_name = Column(String(20))
    entry_date = Column(Date, nullable=False)         # 加入跟踪的日期
    entry_price = Column(Numeric(10, 4))               # 加入跟踪时的收盘价
    active = Column(Boolean, default=True, index=True)  # 是否仍在跟踪
    note = Column(String(200))                         # 自定义备注
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class StockTrackerDaily(Base):
    """跟踪股每日表现（1-30 日，每天一条）"""
    __tablename__ = "stock_tracker_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tracker_id = Column(Integer, nullable=False, index=True)   # StockTracker.id
    trade_date = Column(Date, nullable=False, index=True)
    day_n = Column(Integer, nullable=False)                     # 入选后第 N 天（1-30）
    close_price = Column(Numeric(10, 4))                        # 当日收盘价
    pct_chg = Column(Numeric(8, 4))                             # 相对入选日的累计涨跌幅 %
    daily_chg = Column(Numeric(6, 2))                           # 当日涨跌幅 %
    volume = Column(BigInteger)                                 # 当日成交量
    reason = Column(String(500))                                # 涨跌原因简述
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        Index("ix_stock_tracker_daily_tracker_date", "tracker_id", "trade_date", unique=True),
    )

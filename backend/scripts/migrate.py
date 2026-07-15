"""
轻量级数据库迁移：确保新表/新列存在
启动时由 main.py lifespan 调用 run_migrations()
"""
from sqlalchemy import text


def _ensure_bs_strategy_columns():
    """确保 bs_strategies 和 bs_backtest_results 表存在"""
    from db.connection import engine, Base
    from db.models import BSStrategy, BSBacktestResult
    # 先确保表存在
    Base.metadata.create_all(bind=engine, tables=[BSStrategy.__table__, BSBacktestResult.__table__])
    # 确保个股研究沉淀新表存在（资讯搜索/金融数据查询/AI分析缓存）
    from db.models import StockNewsSearch, StockDataQuery, AIAnalysisCache
    Base.metadata.create_all(bind=engine, tables=[
        StockNewsSearch.__table__, StockDataQuery.__table__, AIAnalysisCache.__table__,
    ])
    # 确保个股特征每日表存在（CHOPPY/TREND/IMPULSE 三态判定）
    from db.models import StockFeaturesDaily
    Base.metadata.create_all(bind=engine, tables=[StockFeaturesDaily.__table__])
    # StockFeaturesDaily 新增 rsi_14 列（RSI(14) 技术指标，用于 7 段技术形态判定）
    with engine.connect() as conn:
        # 检查 rsi_14 列是否已存在，避免 ALTER TABLE 持锁阻塞查询
        rsi_exists = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name='stock_features_daily' AND column_name='rsi_14'"
        )).fetchone()
        if not rsi_exists:
            conn.execute(text(
                "ALTER TABLE stock_features_daily ADD COLUMN rsi_14 DOUBLE PRECISION"
            ))
            conn.commit()
    # 确保模拟盘持仓/账户快照表存在（支持历史盈亏回溯）
    from db.models import SimPositionSnapshot, SimAccountSnapshot
    Base.metadata.create_all(bind=engine, tables=[
        SimPositionSnapshot.__table__, SimAccountSnapshot.__table__,
    ])
    # 确保概念板块相关表存在
    from db.models import ConceptSector, ConceptSectorFlow, RealtimeConceptSectorFlow
    Base.metadata.create_all(bind=engine, tables=[
        ConceptSector.__table__, ConceptSectorFlow.__table__, RealtimeConceptSectorFlow.__table__,
    ])
    # 确保策略结果表 + 运行日志 + 个股信号预计算表存在
    from db.models import StrategyResult, StrategyRunLog, WatchlistSignalDaily
    Base.metadata.create_all(bind=engine, tables=[
        StrategyResult.__table__, StrategyRunLog.__table__, WatchlistSignalDaily.__table__,
    ])
    # 确保游资系统 4.0 交易信号日报表存在
    from db.models import TradingSignalDaily
    Base.metadata.create_all(bind=engine, tables=[TradingSignalDaily.__table__])
    # 确保游资龙虎榜（席位字典/共振信号/席位明细）表存在
    from db.models import YuziDict, YuziQuantSignal, YuziSeatDaily
    Base.metadata.create_all(bind=engine, tables=[
        YuziDict.__table__, YuziQuantSignal.__table__, YuziSeatDaily.__table__,
    ])
    # YuziDict 新增 style 列（操作风格:稳健/一日游/砸盘/接力/低吸/趋势/首板/机构）
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE yuzi_dict ADD COLUMN IF NOT EXISTS style VARCHAR(50) DEFAULT '稳健'"
        ))
        conn.commit()
    # 确保游资 20 天生命周期跟踪表存在
    from db.models import YuziLifecycleTracker
    Base.metadata.create_all(bind=engine, tables=[YuziLifecycleTracker.__table__])
    # 兼容旧列: net_return_7d → net_return_20d
    with engine.connect() as conn:
        conn.execute(text("""
            DO $$
            BEGIN
              IF EXISTS(SELECT 1 FROM information_schema.columns
                        WHERE table_name='yuzi_lifecycle_tracker' AND column_name='net_return_7d')
                AND NOT EXISTS(SELECT 1 FROM information_schema.columns
                               WHERE table_name='yuzi_lifecycle_tracker' AND column_name='net_return_20d')
              THEN
                ALTER TABLE yuzi_lifecycle_tracker RENAME COLUMN net_return_7d TO net_return_20d;
              END IF;
            END$$;
        """))
        conn.commit()
    # 确保自动化交易配置+日志表存在，并初始化默认配置行
    from db.models import AutoTradeConfig, AutoTradeLog, SimAccount, SimPosition, SimOrder
    from db.connection import get_db
    from db.session import get_db_session
    Base.metadata.create_all(bind=engine, tables=[
        AutoTradeConfig.__table__, AutoTradeLog.__table__,
        SimAccount.__table__, SimPosition.__table__, SimOrder.__table__,
    ])
    # 先确保 auto_trade_config 新列存在，再查询（避免 SQLAlchemy 模型与表结构不一致）
    with engine.connect() as conn:
        for col_def in [
            ('buy_quantity', 'INTEGER DEFAULT 100'),
            ('sell_quantity', 'INTEGER DEFAULT 100'),
        ]:
            conn.execute(text(
                f"ALTER TABLE auto_trade_config ADD COLUMN IF NOT EXISTS {col_def[0]} {col_def[1]}"
            ))
        conn.commit()
    with get_db_session() as _db:
        if not _db.query(AutoTradeConfig).filter_by(id=1).first():
            _db.add(AutoTradeConfig(id=1))
            _db.commit()
    # 再确保新列存在（兼容旧表）
    with engine.connect() as conn:
        # bs_strategies 新列
        for col in ['volume_filter', 'ma20_filter', 'ma60_trend', 'rsi_filter', 'strong_volume']:
            conn.execute(text(
                f"ALTER TABLE bs_strategies ADD COLUMN IF NOT EXISTS {col} BOOLEAN DEFAULT FALSE"
            ))
        # bs_backtest_results 新列
        for col_def in [
            ('name', 'VARCHAR(50)'),
            ('ma60_trend', 'BOOLEAN DEFAULT FALSE'),
            ('rsi_filter', 'BOOLEAN DEFAULT FALSE'),
            ('strong_volume', 'BOOLEAN DEFAULT FALSE'),
            ('macd_filter', 'BOOLEAN DEFAULT FALSE'),
            ('kdj_filter', 'BOOLEAN DEFAULT FALSE'),
            ('stop_loss_pct', 'NUMERIC(5,2) DEFAULT 0'),
        ]:
            conn.execute(text(
                f"ALTER TABLE bs_backtest_results ADD COLUMN IF NOT EXISTS {col_def[0]} {col_def[1]}"
            ))
        conn.commit()


def _ensure_analysis_tables():
    """确保研报中心相关表存在（请求/报告/通知 + F10 缓存 + 全市场基础信息）"""
    from db.connection import engine, Base
    from db.models import (AnalysisRequest, AnalysisReport, Notification,
                           StockF10, StockUniverse)
    Base.metadata.create_all(bind=engine, tables=[
        AnalysisRequest.__table__, AnalysisReport.__table__,
        Notification.__table__, StockF10.__table__, StockUniverse.__table__,
    ])


def _ensure_stock_tracker_tables():
    """创建股票跟踪相关表"""
    from db.connection import engine
    from db.models import StockTracker, StockTrackerDaily
    Base.metadata.create_all(bind=engine, tables=[
        StockTracker.__table__, StockTrackerDaily.__table__,
    ])


def run_migrations():
    """执行所有轻量级数据库迁移（创建表/添加列）"""
    _ensure_bs_strategy_columns()
    _ensure_analysis_tables()
    _ensure_stock_tracker_tables()

"""
轻量级数据库迁移：确保新表/新列存在
启动时由 main.py lifespan 调用 run_migrations()
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger(__name__)


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
    # 确保龙头生命周期跟踪状态表存在（跨日记忆：主龙阶段演进/板块轮动/接棒）
    from db.models import LeaderTrack
    Base.metadata.create_all(bind=engine, tables=[LeaderTrack.__table__])
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
    from db.models import (
        AutoTradeConfig,
        AutoTradeControlAudit,
        AutoTradeLog,
        AutoTradeStockConfig,
        SimAccount,
        SimOrder,
        SimPosition,
    )
    from db.connection import get_db
    from db.session import get_db_session
    Base.metadata.create_all(bind=engine, tables=[
        AutoTradeConfig.__table__, AutoTradeStockConfig.__table__,
        AutoTradeControlAudit.__table__, AutoTradeLog.__table__,
        SimAccount.__table__, SimPosition.__table__, SimOrder.__table__,
    ])
    # 先确保 auto_trade_config 新列存在，再查询（避免 SQLAlchemy 模型与表结构不一致）
    with engine.connect() as conn:
        for col_def in [
            ('buy_quantity', 'INTEGER DEFAULT 100'),
            ('sell_quantity', 'INTEGER DEFAULT 100'),
            ('account_source', "VARCHAR(20) DEFAULT 'displayed'"),
            ('run_environment', "VARCHAR(20) DEFAULT 'paper'"),
            ('paused', 'BOOLEAN DEFAULT FALSE'),
            ('pause_reason', "VARCHAR(200) DEFAULT ''"),
            ('paused_at', 'TIMESTAMP'),
            ('control_migrated_at', 'TIMESTAMP'),
        ]:
            conn.execute(text(
                f"ALTER TABLE auto_trade_config ADD COLUMN IF NOT EXISTS {col_def[0]} {col_def[1]}"
            ))
        conn.commit()
    with get_db_session() as _db:
        config = _db.query(AutoTradeConfig).filter_by(id=1).first()
        if config is None:
            config = AutoTradeConfig(id=1)
            _db.add(config)
            _db.flush()

        # 一次性把旧 JSON 控制面迁入数据库。迁移后 API 与调度器均只读写数据库，
        # 旧文件仅保留为历史备份，不再参与运行。
        if config.control_migrated_at is None:
            project_root = Path(__file__).resolve().parents[2]

            def load_legacy(name, default):
                try:
                    return json.loads((project_root / name).read_text(encoding='utf-8'))
                except (OSError, TypeError, ValueError):
                    return default

            def parse_time(value):
                if not value:
                    return None
                try:
                    return datetime.fromisoformat(str(value))
                except ValueError:
                    return None

            global_state = load_legacy('auto_trade_global.json', {})
            if isinstance(global_state, dict):
                config.enabled = bool(global_state.get('enabled', config.enabled))
                environment = global_state.get('run_environment')
                if environment in ('paper', 'live'):
                    config.run_environment = environment
                config.paused = bool(global_state.get('paused', False))
                config.pause_reason = str(global_state.get('pause_reason') or '')[:200]
                config.paused_at = parse_time(global_state.get('paused_at'))

            stock_states = load_legacy('auto_trade_stocks.json', {})
            if isinstance(stock_states, dict):
                for code, payload in stock_states.items():
                    if not isinstance(payload, dict):
                        continue
                    normalized_code = str(code or '').strip()
                    if not normalized_code:
                        continue
                    _db.add(AutoTradeStockConfig(
                        code=normalized_code,
                        config_json=json.dumps(payload, ensure_ascii=False),
                    ))

            audit_events = load_legacy('auto_trade_audit.json', [])
            if isinstance(audit_events, list):
                for event in audit_events:
                    if not isinstance(event, dict):
                        continue
                    _db.add(AutoTradeControlAudit(
                        code=str(event.get('code') or ''),
                        event_time=parse_time(event.get('event_time')) or datetime.now(),
                        event_json=json.dumps(event, ensure_ascii=False),
                    ))

            config.control_migrated_at = datetime.now()
            config.updated_at = datetime.now()
        _db.commit()
    # 再确保新列存在（兼容旧表）
    with engine.connect() as conn:
        # V2 自动交易审计字段：把“为什么选、依据哪天、是否真正成交”分开保存。
        # 旧表可能已经有历史日志，因此全部使用 IF NOT EXISTS 做增量迁移。
        for col_def in [
            ('signal_date', 'DATE'),
            ('account_source', 'VARCHAR(20)'),
            ('signal_state', 'VARCHAR(20)'),
            ('factor_score', 'NUMERIC(6,2)'),
            ('resonance_count', 'INTEGER DEFAULT 0'),
            ('order_id', 'VARCHAR(100)'),
            ('fill_status', 'VARCHAR(20)'),
            ('filled_quantity', 'INTEGER DEFAULT 0'),
            ('filled_price', 'NUMERIC(10,2)'),
            ('updated_at', 'TIMESTAMP DEFAULT NOW()'),
        ]:
            conn.execute(text(
                f"ALTER TABLE auto_trade_log ADD COLUMN IF NOT EXISTS {col_def[0]} {col_def[1]}"
            ))
        for table_name, columns in {
            'sim_account': [('source', "VARCHAR(20) DEFAULT 'miaoxiang'")],
            'sim_position': [('source', "VARCHAR(20) DEFAULT 'miaoxiang'")],
            'sim_order': [
                ('external_order_id', 'VARCHAR(100)'),
                ('source', "VARCHAR(20) DEFAULT 'miaoxiang'"),
            ],
        }.items():
            for column_name, column_type in columns:
                conn.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                ))
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

    # V2 因子、共振、结果验证表不依赖 ORM 模型，使用同一连接初始化。
    # 这样新环境和旧环境都能在服务启动时自动具备完整研究链路。
    from quant_vnext.repository import ensure_schema as ensure_quant_vnext_schema
    with engine.begin() as conn:
        ensure_quant_vnext_schema(conn)
    # 港美股统一研究/生产链路使用独立表，不改动 A 股旧表和 V2 兼容表。
    from market_quant.repository import ensure_schema as ensure_market_quant_schema
    ensure_market_quant_schema()
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE market_instruments ADD COLUMN IF NOT EXISTS is_inverse BOOLEAN DEFAULT FALSE"
        ))
        conn.commit()


def _ensure_analysis_tables():
    """确保研报中心相关表存在（请求/报告/通知 + F10 缓存 + 全市场基础信息）"""
    from db.connection import engine, Base
    from db.models import (AnalysisRequest, AnalysisReport, Notification,
                           StockF10, StockUniverse, WaveAnalysisSnapshot)
    Base.metadata.create_all(bind=engine, tables=[
        AnalysisRequest.__table__, AnalysisReport.__table__,
        Notification.__table__, StockF10.__table__, StockUniverse.__table__,
        WaveAnalysisSnapshot.__table__,
    ])


def _ensure_stock_universe_schema():
    """修正 stock_universe 兼容视图，统一从 instruments 读取 A 股基础信息。"""
    from db.connection import engine

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE OR REPLACE VIEW stock_universe AS
            SELECT symbol AS code,
                   name,
                   COALESCE(industry, sector, '')::VARCHAR(64) AS industry,
                   listing_status,
                   is_active,
                   is_tradeable,
                   market
            FROM instruments
            WHERE market IN ('主板', '创业板', '科创板', '北交所')
        """))
        visible = conn.execute(text('SELECT count(*) FROM stock_universe')).scalar()
        logger.info('[migrate] stock_universe view aligned; visible A-share instruments=%s', visible)

        name_result = conn.execute(text("""
            WITH latest_flow AS (
                SELECT DISTINCT ON (split_part(ts_code, '.', 1))
                       split_part(ts_code, '.', 1) AS stock_code, name
                FROM stock_flow
                WHERE name IS NOT NULL AND name <> ''
                ORDER BY split_part(ts_code, '.', 1), trade_date DESC
            )
            UPDATE watchlist AS target
               SET stock_name = source.name
              FROM latest_flow AS source
             WHERE target.stock_code = source.stock_code
               AND COALESCE(target.stock_name, '') = ''
        """))
        logger.info('[migrate] restored %s missing watchlist names from database', name_result.rowcount)


def _ensure_stock_tracker_tables():
    """创建股票跟踪相关表"""
    from db.connection import engine, Base
    from db.models import StockTracker, StockTrackerDaily
    Base.metadata.create_all(bind=engine, tables=[
        StockTracker.__table__, StockTrackerDaily.__table__,
    ])


def _ensure_strategy_track_tables():
    """创建策略共振股 20 天跟踪相关表"""
    from db.connection import engine, Base
    from db.models import StrategyTrack, StrategyTrackDaily
    Base.metadata.create_all(bind=engine, tables=[
        StrategyTrack.__table__, StrategyTrackDaily.__table__,
    ])


def _ensure_horseback_track_tables():
    """创建回马枪独立 20 日跟踪表。"""
    from horseback.tracking import ensure_schema
    ensure_schema()


def _ensure_index_daily_table():
    """创建指数每日行情日表（index_daily）：启动时确保存在

    该表由 api/index_daily 每日定时写入，供 dashboard 强弱对比/指数资金常规读取。
    仅对不存在的新表执行 create_all，幂等安全。
    """
    from db.connection import engine, Base
    from db.models import IndexDaily
    Base.metadata.create_all(bind=engine, tables=[IndexDaily.__table__])


def _ensure_horseback_v116_columns():
    """回马枪 v1.1.6：任务级实时门槛、板块开关与回放模式列。"""
    from db.connection import engine

    with engine.begin() as conn:
        for column_name, column_type in [
            ("mode", "VARCHAR(16) NOT NULL DEFAULT 'live'"),
            ("live_rise_pct_min", "DOUBLE PRECISION NOT NULL DEFAULT 3.0"),
            ("live_volume_ratio_min", "DOUBLE PRECISION NOT NULL DEFAULT 1.2"),
            ("allow_gem", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("allow_star", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ]:
            conn.execute(text(
                f"ALTER TABLE horseback_runs ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
            ))


def _ensure_industry_stage_v2_tables():
    """独立行业阶段池；不复用或变更旧 sector_rotation_snapshot。"""
    from db.connection import engine
    from industry_stage.collector import ensure_schema

    ensure_schema()
    # create_all 不会为已有表补建新索引；历史有效期查询需要按
    # (version, ts_code, in_date, out_date) 定位，避免每次回溯全表扫描。
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_industry_stage_membership_effective "
            "ON industry_stage_membership (version, ts_code, in_date, out_date)"
        ))


def run_migrations():
    """执行所有轻量级数据库迁移（创建表/添加列）"""
    _ensure_bs_strategy_columns()
    _ensure_horseback_v116_columns()
    _normalize_watchlist_codes()
    _normalize_stock_feature_codes()
    _ensure_us_quant_constraints()
    _ensure_analysis_tables()
    _ensure_stock_universe_schema()
    _ensure_stock_tracker_tables()
    _ensure_strategy_track_tables()
    _ensure_horseback_track_tables()
    _ensure_pingan_tables()
    _ensure_index_daily_table()
    _ensure_industry_stage_v2_tables()


def _normalize_watchlist_codes():
    """把自选表统一为 6 位代码，并无损合并历史后缀重复行。"""
    from collections import defaultdict

    from api.watchlist._shared import normalize_stock_code
    from db.connection import Base, engine
    from db.models import Watchlist
    from db.session import get_db_session

    Base.metadata.create_all(bind=engine, tables=[Watchlist.__table__])
    quality_rank = {
        '普通': 0, '杂毛': 1, '中性': 2, '合格': 3, '偏强': 4,
        '优质': 5, '强势': 6, '极强': 7, '核心': 8, '淘汰': 9,
    }
    with get_db_session() as db:
        rows = db.query(Watchlist).order_by(Watchlist.created_at, Watchlist.id).all()
        grouped = defaultdict(list)
        for row in rows:
            code = normalize_stock_code(row.stock_code)
            if code:
                grouped[code].append(row)

        normalized = 0
        merged = 0
        for code, candidates in grouped.items():
            keeper = next((row for row in candidates if row.stock_code == code), candidates[0])
            names = [row.stock_name for row in candidates if row.stock_name]
            notes = [row.note for row in candidates if row.note]
            groups = [row.group_name for row in candidates if row.group_name and row.group_name != '默认']
            qualities = [row.quality_status or '普通' for row in candidates]

            if names and not keeper.stock_name:
                keeper.stock_name = names[0]
            if notes and not keeper.note:
                keeper.note = notes[0]
            if groups and (not keeper.group_name or keeper.group_name == '默认'):
                keeper.group_name = groups[0]
            if qualities:
                keeper.quality_status = max(qualities, key=lambda item: quality_rank.get(item, 0))
            keeper.sort_order = min((row.sort_order or 0) for row in candidates)

            for duplicate in candidates:
                if duplicate is not keeper:
                    db.delete(duplicate)
                    merged += 1
            if keeper.stock_code != code:
                keeper.stock_code = code
                normalized += 1

        if normalized or merged:
            db.commit()
            logger.info(
                "[migration] watchlist code normalized=%s duplicate_rows_merged=%s",
                normalized,
                merged,
            )


def _normalize_stock_feature_codes():
    """特征表使用 6 位代码；移除后缀键造成的同日重复并归一剩余记录。"""
    from db.connection import engine

    with engine.begin() as conn:
        duplicate_result = conn.execute(text("""
            DELETE FROM stock_features_daily AS suffixed
            USING stock_features_daily AS canonical
            WHERE suffixed.stock_code ~ '^[0-9]{6}\\.(SH|SZ|BJ)$'
              AND canonical.stock_code = regexp_replace(
                    suffixed.stock_code, '\\.(SH|SZ|BJ)$', ''
                  )
              AND canonical.trade_date = suffixed.trade_date
        """))
        normalize_result = conn.execute(text("""
            UPDATE stock_features_daily
            SET stock_code = regexp_replace(stock_code, '\\.(SH|SZ|BJ)$', '')
            WHERE stock_code ~ '^[0-9]{6}\\.(SH|SZ|BJ)$'
        """))
    if duplicate_result.rowcount or normalize_result.rowcount:
        logger.info(
            "[migration] stock_features duplicate_rows_merged=%s normalized=%s",
            duplicate_result.rowcount,
            normalize_result.rowcount,
        )


def _ensure_us_quant_constraints():
    """补齐 create_all 无法添加到旧表的 US Quant 唯一约束。"""
    from db.connection import engine
    from us_quant.repository import ensure_schema

    ensure_schema()
    with engine.begin() as conn:
        factor_type = conn.execute(text("""
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = 'us_factor_scores' AND column_name = 'factor_value'
        """)).scalar()
        if factor_type != 'double precision':
            conn.execute(text("""
                ALTER TABLE us_factor_scores
                ALTER COLUMN factor_value TYPE DOUBLE PRECISION
                USING factor_value::DOUBLE PRECISION
            """))

        index_exists = conn.execute(text("""
            SELECT 1 FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'us_factor_scores'
              AND indexname = 'uq_us_factor_score'
        """)).scalar()
        if not index_exists:
            # 旧环境首次建索引前才去重；启动时不再扫描百万行。
            conn.execute(text("""
                DELETE FROM us_factor_scores older
                USING us_factor_scores newer
                WHERE older.symbol = newer.symbol
                  AND older.trade_date = newer.trade_date
                  AND older.factor_name = newer.factor_name
                  AND older.id < newer.id
            """))
            conn.execute(text("""
                CREATE UNIQUE INDEX uq_us_factor_score
                ON us_factor_scores (symbol, trade_date, factor_name)
            """))


def _ensure_pingan_tables():
    """创建平安证券数据采集相关表"""
    from db.connection import engine, Base
    from db.models import (
        PingAnStockQuote, PingAnSectorQuote, PingAnSectorStocks,
        PingAnFundFlow, PingAnKline, PingAnResearchReport,
        PingAnNews, PingAnGuYouQuan, PingAnEtfScreen, PingAnFundRank,
        SectorRotationSnapshot,
    )
    Base.metadata.create_all(bind=engine, tables=[
        PingAnStockQuote.__table__, PingAnSectorQuote.__table__,
        PingAnSectorStocks.__table__, PingAnFundFlow.__table__,
        PingAnKline.__table__, PingAnResearchReport.__table__,
        PingAnNews.__table__, PingAnGuYouQuan.__table__,
        PingAnEtfScreen.__table__, PingAnFundRank.__table__,
        SectorRotationSnapshot.__table__,
    ])
    with engine.connect() as conn:
        for col_def in [
            ('return_20d_pct', 'NUMERIC(10,4)'),
            ('return_1y_pct', 'NUMERIC(10,4)'),
            ('amount_20d', 'NUMERIC(20,4)'),
        ]:
            conn.execute(text(
                f"ALTER TABLE pingan_etf_screen ADD COLUMN IF NOT EXISTS {col_def[0]} {col_def[1]}"
            ))
        conn.commit()
    print('[migrate] pingan tables ensured')

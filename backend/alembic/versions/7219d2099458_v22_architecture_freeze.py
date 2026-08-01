"""V2.2 架构冻结 — 统一 instruments 主表 + 股票池 + 自选股 + 配置版本

阶段 1: 创建统一核心表（instruments, identifiers, universes, watchlists, config）
阶段 2: 数据迁移（A股 stock_universe → instruments, 美股 us_instruments → instruments）
阶段 3: 创建兼容视图（stock_universe, us_stock_universe）
阶段 4: 股票池定义 + 导入 179 种子 / ETF / 扩展候选
阶段 5: 配置版本快照

Revision ID: 7219d2099458
Revises: f8d6add9aa10
Create Date: 2026-07-31 23:46:50.993789
"""
from __future__ import annotations

from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = '7219d2099458'
down_revision: Union[str, Sequence[str], None] = 'f8d6add9aa10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 179 只初始化种子（US Quant Stock Universe V2.0 附录 B）
SEED_CORE_179 = [
    "MSFT","AAPL","ORCL","CRM","NOW","PLTR","ADBE","INTU","PANW","CRWD",
    "DDOG","NET","SNOW","MDB","APP","ANET","DELL","HPE","IBM","CSCO",
    "NVDA","AVGO","AMD","MU","AMAT","LRCX","KLAC","QCOM","MRVL","INTC",
    "ARM","TSM","ASML","SMCI","VRT","COHR","META","GOOGL","GOOG","NFLX",
    "AMZN","UBER","ABNB","DASH","SPOT","RDDT","PINS","SNAP","RBLX","EA",
    "TTWO","DIS","TMUS","T","VZ","TSLA","HD","LOW","NKE","MCD","SBUX",
    "BKNG","MAR","RCL","CCL","GM","F","RIVN","TGT","TJX","CMG","YUM",
    "ORLY","AZO","ROST","JPM","BAC","WFC","C","GS","MS","V","MA","AXP",
    "COF","SCHW","BLK","BX","KKR","HOOD","COIN","CME","ICE","SPGI","MCO",
    "GE","GEV","CAT","DE","BA","RTX","LMT","NOC","GD","ETN","PH","HON",
    "UNP","UPS","FDX","URI","PWR","CARR","TT","EMR","LLY","UNH","JNJ",
    "ABBV","MRK","AMGN","GILD","TMO","DHR","ISRG","BSX","MDT","SYK",
    "REGN","VRTX","MRNA","BMY","CVS","CI","HCA","XOM","CVX","COP","OXY",
    "EOG","DVN","SLB","HAL","MPC","VLO","LNG","FANG","FCX","NEM","NUE",
    "STLD","AA","CCJ","WMT","COST","PG","KO","PEP","PM","MO","MDLZ","CL",
    "MNST","KHC","KR","NEE","CEG","VST","SO","DUK","AEP","SRE","EXC",
    "DLR","AMT","PLD","EQIX","O","SPG",
]
MARKET_ETF = [
    "SPY","QQQ","IWM","RSP","DIA","XLK","SMH","SOXX","XLC","XLY","XLF",
    "XLI","XLV","XLE","XLB","XLP","XLU","XLRE","VIXY","TLT","HYG",
]
EXPANSION_CANDIDATES = [
    "WDAY","TEAM","ZS","OKTA","DOCU","ZM","TWLO","SQ","SHOP","ADSK",
    "CTSH","FTNT","ADI","TXN","NXPI","MPWR","PYPL","USB","PNC","TFC",
    "DFS","SOFI","NU","WM","ITW","MMM","ROP","ROK","PCAR","FAST","CPRT",
    "ODFL","CSX","NSC","PFE","ZTS","BDX","EW","DXCM","BIIB","HUM",
    "LULU","DPZ","DRI","EXPE","HLT","DECK","PSX","KMI","WMB","LIN","APD",
    "SHW","ECL","CHTR","CMCSA","LYV","D","ED","PEG",
]


def _table_exists(name: str) -> bool:
    try:
        from sqlalchemy import inspect
        return name in inspect(op.get_bind()).get_table_names()
    except Exception:
        return False


def _seed_instruments(conn, market: str, symbols: list[str], exchange: str, source: str):
    vals = []
    for s in symbols:
        sc = s.strip().upper().replace("'", "''")
        vals.append(f"('{market}', '{sc}', '{sc}', '{exchange}', 'COMMON_STOCK', '{source}', now())")
    if vals:
        conn.execute(sa.text(f"""
            INSERT INTO instruments (market, symbol, name, exchange, asset_type, source, source_updated_at)
            VALUES {','.join(vals)}
            ON CONFLICT (market, symbol) DO UPDATE SET source_updated_at = EXCLUDED.source_updated_at, source = EXCLUDED.source
        """))


def _insert_memberships(conn, universe_code: str, symbols: list[str], ts: str):
    if not symbols:
        return
    sym_list = ", ".join([f"'{s.strip().upper().replace(chr(39),chr(39)+chr(39))}'" for s in symbols])
    conn.execute(sa.text(f"""
        INSERT INTO universe_memberships (instrument_id, universe_code, tier, effective_from, inclusion_reason, source, config_version)
        SELECT i.id, :univ, 'active', CAST(:ts AS TIMESTAMPTZ), json_build_object('source', 'seed'), i.source, 'V2.2-2026-07-31'
        FROM instruments i
        WHERE i.market = 'US' AND i.symbol IN ({sym_list})
          AND NOT EXISTS (
            SELECT 1 FROM universe_memberships um
            WHERE um.instrument_id = i.id AND um.universe_code = :univ AND um.effective_to IS NULL
          )
    """), {"univ": universe_code, "ts": ts})


def upgrade() -> None:
    conn = op.get_bind()
    ts = datetime.utcnow().isoformat()

    # ── 阶段 1: 创建统一核心表 ──
    op.create_table("instruments",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("market", sa.String(8), nullable=False), sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("canonical_symbol", sa.String(32)), sa.Column("name", sa.Text),
        sa.Column("exchange", sa.String(32)), sa.Column("currency", sa.String(8), server_default="USD"),
        sa.Column("asset_type", sa.String(32), nullable=False, server_default="COMMON_STOCK"),
        sa.Column("sector", sa.String(64)), sa.Column("industry", sa.String(128)),
        sa.Column("listing_date", sa.Date), sa.Column("delisting_date", sa.Date),
        sa.Column("listing_status", sa.String(16), server_default="ACTIVE"),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("TRUE")),
        sa.Column("is_tradeable", sa.Boolean, server_default=sa.text("TRUE")),
        sa.Column("source", sa.String(32)), sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_instruments_market", "instruments", ["market"])
    op.create_index("ix_instruments_market_symbol", "instruments", ["market", "symbol"], unique=True)
    op.create_index("ix_instruments_active", "instruments", ["market", "is_active"])

    op.create_table("instrument_identifiers",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("instrument_id", UUID(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_symbol", sa.String(32), nullable=False),
        sa.Column("provider_exchange", sa.String(32)),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("is_primary", sa.Boolean, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_instid_provider", "instrument_identifiers", ["instrument_id", "provider"])

    op.create_table("universe_definitions",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("universe_code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("target_count", sa.Integer),
        sa.Column("rebalance_frequency", sa.String(32), nullable=False),
        sa.Column("rules", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("config_version", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table("universe_memberships",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("instrument_id", UUID(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("universe_code", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(16)),
        sa.Column("rank", sa.Integer),
        sa.Column("universe_score", sa.Numeric(10, 4)),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("inclusion_reason", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("exclusion_reason", JSONB()),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("config_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_univ_members_active", "universe_memberships", ["universe_code", "effective_to", "rank"])
    op.create_index("ix_univ_members_instrument", "universe_memberships", ["instrument_id"])

    op.create_table("universe_rebalance_runs",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("universe_code", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_count", sa.Integer), sa.Column("eligible_count", sa.Integer),
        sa.Column("selected_count", sa.Integer), sa.Column("added_count", sa.Integer),
        sa.Column("removed_count", sa.Integer), sa.Column("config_version", sa.String(64), nullable=False),
        sa.Column("data_version", sa.String(128)),
        sa.Column("metrics", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("errors", JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table("watchlists",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("market", sa.String(8), server_default="US"),
        sa.Column("description", sa.Text),
        sa.Column("is_default", sa.Boolean, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("INSERT INTO watchlists (name, market, is_default) VALUES ('US Watchlist', 'US', TRUE)")

    op.create_table("watchlist_members",
        sa.Column("watchlist_id", UUID(), sa.ForeignKey("watchlists.id"), primary_key=True),
        sa.Column("instrument_id", UUID(), sa.ForeignKey("instruments.id"), primary_key=True),
        sa.Column("group_name", sa.String(64)), sa.Column("priority", sa.Integer, server_default=sa.text("0")),
        sa.Column("notes", sa.Text),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
    )

    op.create_table("config_versions",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("config_key", sa.String(128), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("config_value", JSONB(), nullable=False),
        sa.Column("code_commit", sa.String(64)),
        sa.Column("data_version", sa.String(128)),
        sa.Column("universe_version", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_config_key", "config_versions", ["config_key"])

    # ── 阶段 2: 数据迁移 ──
    count_a = count_us = 0
    if _table_exists("stock_universe"):
        op.execute("""
            INSERT INTO instruments (market, symbol, name, exchange, currency, asset_type, sector, is_active, is_tradeable, source)
            SELECT
                COALESCE(NULLIF(market,''), 'CN') AS market,
                ts_code AS symbol,
                name,
                'SSE' AS exchange,
                'CNY' AS currency,
                'COMMON_STOCK' AS asset_type,
                industry AS sector,
                COALESCE(is_active, TRUE) AS is_active,
                TRUE AS is_tradeable,
                'migration' AS source
            FROM stock_universe WHERE ts_code IS NOT NULL
            ON CONFLICT (market, symbol) DO NOTHING
        """)
        count_a = conn.scalar(sa.text("SELECT COUNT(*) FROM instruments WHERE market='CN'"))
        print(f"[V2.2] 迁移 A 股: {count_a} 只")

    if _table_exists("us_instruments"):
        op.execute("""
            INSERT INTO instruments (market, symbol, name, exchange, currency, asset_type, sector, is_active, is_tradeable, source)
            SELECT 'US', symbol, name, exchange, 'USD'::varchar, 'COMMON_STOCK'::varchar, sector,
                   COALESCE(is_active, TRUE), TRUE, 'migration'
            FROM us_instruments WHERE symbol IS NOT NULL
            ON CONFLICT (market, symbol) DO NOTHING
        """)
        count_us = conn.scalar(sa.text("SELECT COUNT(*) FROM instruments WHERE market='US'"))
        print(f"[V2.2] 迁移美股: {count_us} 只")

    _seed_instruments(conn, "US", SEED_CORE_179, "NASDAQ", "seed_179")
    _seed_instruments(conn, "US", MARKET_ETF, "ARCA", "market_etf")
    _seed_instruments(conn, "US", EXPANSION_CANDIDATES, "NASDAQ", "expansion")
    total_us = conn.scalar(sa.text("SELECT COUNT(*) FROM instruments WHERE market='US'"))
    print(f"[V2.2] 美股 instruments 总计: {total_us} 只")

    # ── 阶段 3: 兼容视图（先备份原表，再建视图）──
    if _table_exists("stock_universe"):
        op.execute("ALTER TABLE IF EXISTS stock_universe RENAME TO stock_universe_old")
    if _table_exists("us_instruments"):
        op.execute("ALTER TABLE IF EXISTS us_instruments RENAME TO us_instruments_old")

    op.execute("""
        CREATE OR REPLACE VIEW stock_universe AS
        SELECT symbol AS code, name, sector AS industry,
               listing_status, is_active, is_tradeable
        FROM instruments WHERE market = 'CN'
    """)
    op.execute("""
        CREATE OR REPLACE VIEW us_stock_universe AS
        SELECT symbol, name, exchange, sector, currency, is_active, is_tradeable
        FROM instruments WHERE market = 'US'
    """)
    print("[V2.2] 兼容视图 stock_universe / us_stock_universe 已创建")

    # ── 阶段 4: 股票池定义 + 种子导入 ──
    pools = [
        ("US_MARKET_ETF", "市场与行业 ETF", 24, "manual"),
        ("US_CORE_A", "核心 A 池", 300, "monthly"),
        ("US_CORE_B", "核心 B 池", 500, "monthly"),
        ("US_RESEARCH", "动态研究池", 1500, "daily"),
        ("US_EVENT", "事件池", None, "intraday"),
        ("US_REALTIME", "实时监控池", 80, "intraday"),
        ("US_WATCHLIST", "US 自选池", None, "manual"),
    ]
    for code, name, target, freq in pools:
        conn.execute(sa.text("""
            INSERT INTO universe_definitions (universe_code, name, target_count, rebalance_frequency, config_version)
            VALUES (:c, :n, :t, :f, 'V2.2-2026-07-31')
            ON CONFLICT (universe_code) DO NOTHING
        """), {"c": code, "n": name, "t": target, "f": freq})

    _insert_memberships(conn, "US_MARKET_ETF", MARKET_ETF, ts)
    _insert_memberships(conn, "US_CORE_A", SEED_CORE_179, ts)
    _insert_memberships(conn, "US_CORE_B", EXPANSION_CANDIDATES, ts)
    _insert_memberships(conn, "US_RESEARCH", list(dict.fromkeys(SEED_CORE_179 + EXPANSION_CANDIDATES)), ts)
    _insert_memberships(conn, "US_WATCHLIST", ["AAPL","MSFT","NVDA","TSLA","META","AMZN","GOOGL","AMD","NFLX","TSM"], ts)

    # ── 阶段 5: 配置版本快照 ──
    conn.execute(sa.text("""
        INSERT INTO config_versions (config_key, config_hash, config_value, universe_version)
        VALUES ('v2.2-architecture-freeze', 'init',
                '{"version":"2.2","frozen_at":"2026-07-31","desc":"统一instruments主表+分层股票池+插件化架构"}',
                'V2.2-2026-07-31')
    """))
    print(f"[V2.2] ✓ 架构冻结完成: A股={count_a} 美股={total_us}")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS us_stock_universe")
    op.execute("DROP VIEW IF EXISTS stock_universe")
    for t in ["config_versions","watchlist_members","watchlists",
              "universe_rebalance_runs","universe_memberships","universe_definitions",
              "instrument_identifiers","instruments"]:
        if _table_exists(t):
            op.drop_table(t)
    print("[V2.2] 回滚完成")

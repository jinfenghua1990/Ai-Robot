"""P1 阶段数据库优化：补复合索引 + 补 is_delisted/is_anomaly 字段 + leader_lifecycle 30天清理
执行：python3 fix_p1_db.py
"""
import sys
sys.path.insert(0, '/Users/gino/Projects/AIROBOT/backend')
from sqlalchemy import text
from db.connection import engine

DDL_STATEMENTS = [
    # 补 is_delisted / is_anomaly 字段（is_suspended 之前已加）
    "ALTER TABLE stock_flow ADD COLUMN IF NOT EXISTS is_delisted BOOLEAN DEFAULT false",
    "ALTER TABLE stock_flow ADD COLUMN IF NOT EXISTS is_anomaly BOOLEAN DEFAULT false",
    # 标记异常：price_chg 超过 ±20%
    "UPDATE stock_flow SET is_anomaly = true WHERE price_chg > 20 OR price_chg < -20",
    # 补缺失的复合索引
    "CREATE INDEX IF NOT EXISTS ix_auto_trade_log_ts_date ON auto_trade_log(ts_code, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS ix_bs_backtest_results_dimension_run ON bs_backtest_results(dimension, run_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_leader_lifecycle_ts_date ON leader_lifecycle(ts_code, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS ix_watchlist_signal_daily_sector_date ON watchlist_signal_daily(sector, trade_date DESC)",
    # sector_flow 的列是 net_flow 不是 net_inflow
    "CREATE INDEX IF NOT EXISTS ix_sector_flow_net ON sector_flow(net_flow DESC) WHERE net_flow IS NOT NULL",
]

CLEANUP_QUERIES = [
    ("DELETE FROM leader_lifecycle WHERE trade_date < CURRENT_DATE - INTERVAL '30 days'", "leader_lifecycle"),
    ("DELETE FROM data_quality_log WHERE created_at < CURRENT_DATE - INTERVAL '30 days'", "data_quality_log"),
]


def main():
    print("=== 应用 DDL（每条独立事务）===")
    for sql in DDL_STATEMENTS:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
            print(f"  ✓ {sql[:80]}{'...' if len(sql) > 80 else ''}")
        except Exception as e:
            err_short = str(e).split('\n')[0][:100]
            print(f"  ✗ {sql[:60]}: {err_short}")

    print("\n=== 清理历史数据（每条独立事务）===")
    for sql, label in CLEANUP_QUERIES:
        try:
            with engine.begin() as conn:
                result = conn.execute(text(sql))
            print(f"  ✓ {label}: 删除 {result.rowcount} 行")
        except Exception as e:
            err_short = str(e).split('\n')[0][:100]
            print(f"  ✗ {label}: {err_short}")

    print("\n=== 验证 ===")
    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM stock_flow WHERE is_suspended = true) AS suspended,
                (SELECT COUNT(*) FROM stock_flow WHERE is_delisted = true) AS delisted,
                (SELECT COUNT(*) FROM stock_flow WHERE is_anomaly = true) AS anomaly,
                (SELECT COUNT(*) FROM leader_lifecycle) AS lifecycle_total,
                (SELECT MIN(trade_date) FROM leader_lifecycle) AS lifecycle_min_date,
                (SELECT COUNT(*) FROM data_quality_log) AS quality_log_total
        """))
        row = result.fetchone()
        print(f"  停牌股: {row[0]}")
        print(f"  退市股: {row[1]}")
        print(f"  异常涨跌幅: {row[2]}")
        print(f"  leader_lifecycle 总数: {row[3]} (最早: {row[4]})")
        print(f"  data_quality_log 总数: {row[5]}")

        result = conn.execute(text("""
            SELECT tablename, indexname FROM pg_indexes
            WHERE indexname IN (
                'ix_auto_trade_log_ts_date',
                'ix_bs_backtest_results_dimension_run',
                'ix_leader_lifecycle_ts_date',
                'ix_watchlist_signal_daily_sector_date',
                'ix_sector_flow_net'
            ) ORDER BY tablename, indexname
        """))
        print("\n  新增/确认索引:")
        for tbl, idx in result:
            print(f"    - {tbl}.{idx}")


if __name__ == "__main__":
    main()

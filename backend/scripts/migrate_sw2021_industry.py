"""One-time, recoverable migration of legacy A-share industry labels to SW2021.

The source tables are copied to ``*_legacy_sw2021`` before derived sector
tables are rebuilt.  Concept rows and US/HK tables are intentionally untouched.

Run from ``backend/`` after the service is stopped:

    ./.venv/bin/python scripts/migrate_sw2021_industry.py --sync
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import Base, engine
from db.session import get_db_session
from db.models import LeaderLifecycle, RealtimeStockFlow, SectorFlow, StockFlow
from industry_stage.collector import sync_taxonomy_and_membership
from industry_stage.models import INDUSTRY_STAGE_TABLES


logger = logging.getLogger("migrate_sw2021")


def _backup_table(conn, source: str) -> int:
    backup = f"{source}_legacy_sw2021"
    conn.execute(text(
        f"CREATE TABLE IF NOT EXISTS {backup} AS TABLE {source} WITH NO DATA"
    ))
    existing = conn.execute(text(f"SELECT count(*) FROM {backup}")).scalar() or 0
    if not existing:
        conn.execute(text(f"INSERT INTO {backup} SELECT * FROM {source}"))
    return int(conn.execute(text(f"SELECT count(*) FROM {backup}")).scalar() or 0)


def _update_membership_backed_table(conn, table: str, date_column: str) -> int:
    """Update one table using the membership effective on each row's date."""
    result = conn.execute(text(f"""
        UPDATE {table} AS target
           SET sector = membership.l2_name
          FROM LATERAL (
              SELECT m.l2_name
                FROM industry_stage_membership AS m
               WHERE m.version = 'SW2021'
                 AND m.ts_code = target.ts_code
                 AND (m.in_date IS NULL OR m.in_date <= target.{date_column})
                 AND (m.out_date IS NULL OR m.out_date >= target.{date_column})
               ORDER BY m.in_date DESC NULLS LAST, m.id DESC
               LIMIT 1
          ) AS membership
         WHERE membership.l2_name IS NOT NULL
           AND membership.l2_name <> ''
           AND target.sector IS DISTINCT FROM membership.l2_name
    """))
    return int(result.rowcount or 0)


def _update_instruments(conn) -> int:
    """Align the CN compatibility universe (sector=L2, industry=L1)."""
    result = conn.execute(text("""
        UPDATE instruments AS target
           SET sector = membership.l2_name,
               industry = membership.l1_name
          FROM LATERAL (
              SELECT m.l1_name, m.l2_name
                FROM industry_stage_membership AS m
               WHERE m.version = 'SW2021'
                 AND split_part(m.ts_code, '.', 1) = split_part(target.symbol, '.', 1)
                 AND m.is_current IS TRUE
               ORDER BY m.in_date DESC NULLS LAST, m.id DESC
               LIMIT 1
          ) AS membership
         WHERE target.market <> 'US'
           AND membership.l2_name IS NOT NULL
           AND membership.l2_name <> ''
           AND (target.sector IS DISTINCT FROM membership.l2_name
                OR target.industry IS DISTINCT FROM membership.l1_name)
    """))
    return int(result.rowcount or 0)


def _rebuild_daily_sector_flows() -> dict:
    """Recompute derived daily sector flows from canonical StockFlow rows."""
    from collectors.tdx_collector import aggregate_stock_sector_flows

    with get_db_session() as db:
        dates = [row[0] for row in db.execute(text(
            "SELECT DISTINCT trade_date FROM stock_flow ORDER BY trade_date"
        )).all()]
    written = 0
    ready_dates = 0
    for target_date in dates:
        result = aggregate_stock_sector_flows(target_date, force=True)
        if result.get("status") == "READY":
            ready_dates += 1
            written += int(result.get("written") or 0)
    return {"dates": len(dates), "ready_dates": ready_dates, "written": written}


def _rebuild_realtime_sector_flows(conn) -> int:
    """Recompute realtime SW2021 L2 aggregates; concept table is not touched."""
    conn.execute(text("DELETE FROM realtime_sector_flow"))
    result = conn.execute(text("""
        INSERT INTO realtime_sector_flow (
            snapshot_time, trade_date, sector, money_inflow, money_outflow,
            net_flow, rise_ratio, source
        )
        SELECT snapshot_time,
               trade_date,
               sector,
               SUM(CASE WHEN main_force_inflow > 0 THEN main_force_inflow ELSE 0 END),
               SUM(CASE WHEN main_force_inflow < 0 THEN -main_force_inflow ELSE 0 END),
               SUM(main_force_inflow),
               SUM(CASE WHEN price_chg > 0 THEN 1 ELSE 0 END) * 100.0
                   / NULLIF(COUNT(ts_code), 0),
               'computed_sw2021'
          FROM realtime_stock_flow
         WHERE sector IS NOT NULL
           AND sector <> ''
         GROUP BY snapshot_time, trade_date, sector
    """))
    return int(result.rowcount or 0)


def _rebuild_realtime_industry_snapshots(conn) -> int:
    """Replace only the middleman industry's labels with SW2021 aggregates."""
    conn.execute(text(
        "DELETE FROM realtime_money_flow_snapshot WHERE dimension = 'industry'"
    ))
    result = conn.execute(text("""
        INSERT INTO realtime_money_flow_snapshot (
            trade_date, dimension, block_name, minute, net_inflow_yi, source
        )
        SELECT trade_date,
               'industry',
               sector,
               to_char(snapshot_time, 'HH24:MI'),
               SUM(main_force_inflow) / 10000.0,
               'computed_sw2021'
          FROM realtime_stock_flow
         WHERE sector IS NOT NULL
           AND sector <> ''
         GROUP BY trade_date, sector, to_char(snapshot_time, 'HH24:MI')
    """))
    return int(result.rowcount or 0)


def migrate(*, sync: bool = False) -> dict:
    if sync:
        logger.info("syncing SW2021 taxonomy and effective memberships")
        sync_taxonomy_and_membership()

    # New tables are idempotent; this also makes the script safe on a fresh DB.
    Base.metadata.create_all(bind=engine, tables=list(INDUSTRY_STAGE_TABLES))
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_industry_stage_membership_effective "
            "ON industry_stage_membership (version, ts_code, in_date, out_date)"
        ))
        backup_counts = {
            table: _backup_table(conn, table)
            for table in (
                "stock_flow", "sector_flow", "realtime_stock_flow",
                "realtime_sector_flow", "leader_lifecycle",
                "realtime_money_flow_snapshot",
            )
        }
        updated = {
            "stock_flow": _update_membership_backed_table(conn, "stock_flow", "trade_date"),
            "realtime_stock_flow": _update_membership_backed_table(conn, "realtime_stock_flow", "trade_date"),
            "leader_lifecycle": _update_membership_backed_table(conn, "leader_lifecycle", "trade_date"),
            "instruments": _update_instruments(conn),
        }
        # Derived sector tables are rebuilt after stock labels are canonical.
        conn.execute(text("DELETE FROM sector_flow"))
        realtime_sector_rows = _rebuild_realtime_sector_flows(conn)
        realtime_industry_rows = _rebuild_realtime_industry_snapshots(conn)

    daily = _rebuild_daily_sector_flows()
    result = {
        "taxonomy": "SW2021",
        "backup_counts": backup_counts,
        "updated": updated,
        "realtime_sector_rows": realtime_sector_rows,
        "realtime_industry_snapshot_rows": realtime_industry_rows,
        "daily_sector_rebuild": daily,
    }
    logger.info("SW2021 migration complete: %s", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true", help="refresh Tushare taxonomy/history before migration")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print(migrate(sync=args.sync))
    return 0


if __name__ == "__main__":
    sys.exit(main())

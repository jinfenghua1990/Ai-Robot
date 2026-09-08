"""add per-stock latest-snapshot indexes

Revision ID: e89ce5f4b2d1
Revises: 7219d2099458
Create Date: 2026-08-26 11:00:00.000000

The stock-analysis realtime panel asks for the latest row for one code.  The
existing date-first indexes force a reverse scan of the whole realtime history
when a code has no current tick.  These indexes make that lookup bounded for
both a present and an absent stock.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e89ce5f4b2d1"
down_revision: Union[str, Sequence[str], None] = "7219d2099458"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The realtime tables are actively appended during market hours.  PostgreSQL
    # requires CONCURRENTLY to run outside the migration transaction.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_realtime_stock_code_time "
            "ON realtime_stock_flow (ts_code, snapshot_time DESC)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_realtime_tick_code_time "
            "ON stock_realtime_tick (ts_code, snapshot_time DESC)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_realtime_tick_code_time")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_realtime_stock_code_time")

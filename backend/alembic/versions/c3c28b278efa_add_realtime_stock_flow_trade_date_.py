"""add realtime_stock_flow trade_date_snapshot_time index

Revision ID: c3c28b278efa
Revises: 8bc02e0df999
Create Date: 2026-07-08 18:20:10.962913

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3c28b278efa'
down_revision: Union[str, Sequence[str], None] = '8bc02e0df999'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite index on realtime_stock_flow(trade_date, snapshot_time)."""
    op.create_index(
        'ix_realtime_stock_date_time',
        'realtime_stock_flow',
        ['trade_date', 'snapshot_time'],
        unique=False,
    )


def downgrade() -> None:
    """Drop composite index on realtime_stock_flow(trade_date, snapshot_time)."""
    op.drop_index('ix_realtime_stock_date_time', table_name='realtime_stock_flow')

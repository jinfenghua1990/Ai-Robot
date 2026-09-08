"""add horseback v1.1.5 live screening fields

Revision ID: b72a91c6f8d5
Revises: a3c7e12d9f44
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b72a91c6f8d5"
down_revision: Union[str, Sequence[str], None] = "a3c7e12d9f44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("horseback_runs", sa.Column("prefiltered_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("horseback_runs", sa.Column("quote_total", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("horseback_runs", sa.Column("quote_processed", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("horseback_runs", sa.Column("realtime_at", sa.DateTime()))

    op.add_column("horseback_results", sa.Column("limit_up_count", sa.Integer()))
    op.add_column("horseback_results", sa.Column("leader", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("horseback_results", sa.Column("structure_eligible", sa.Boolean()))
    op.add_column("horseback_results", sa.Column("realtime_price", sa.Numeric(12, 4)))
    op.add_column("horseback_results", sa.Column("realtime_change_pct", sa.Numeric(10, 4)))
    op.add_column("horseback_results", sa.Column("realtime_volume_ratio", sa.Numeric(10, 4)))
    op.add_column("horseback_results", sa.Column("realtime_open", sa.Numeric(12, 4)))
    op.add_column("horseback_results", sa.Column("realtime_high", sa.Numeric(12, 4)))
    op.add_column("horseback_results", sa.Column("realtime_low", sa.Numeric(12, 4)))
    op.add_column("horseback_results", sa.Column("realtime_volume", sa.Numeric(20, 4)))
    op.add_column("horseback_results", sa.Column("today_ma5", sa.Numeric(12, 4)))
    op.add_column("horseback_results", sa.Column("first_ma5_break", sa.Boolean()))
    op.add_column("horseback_results", sa.Column("realtime_gate", sa.String(300)))
    op.add_column("horseback_results", sa.Column("realtime_state", sa.String(80)))
    op.add_column("horseback_results", sa.Column("realtime_at", sa.DateTime()))


def downgrade() -> None:
    for column in (
        "realtime_at", "realtime_state", "realtime_gate", "first_ma5_break", "today_ma5",
        "realtime_volume", "realtime_low", "realtime_high", "realtime_open", "realtime_volume_ratio",
        "realtime_change_pct", "realtime_price", "structure_eligible", "leader", "limit_up_count",
    ):
        op.drop_column("horseback_results", column)
    for column in ("realtime_at", "quote_processed", "quote_total", "prefiltered_count"):
        op.drop_column("horseback_runs", column)

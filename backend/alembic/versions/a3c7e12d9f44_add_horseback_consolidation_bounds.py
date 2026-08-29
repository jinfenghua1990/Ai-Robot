"""Persist per-run horseback consolidation bounds.

Revision ID: a3c7e12d9f44
Revises: 4f6d88b7c1a2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3c7e12d9f44"
down_revision: Union[str, Sequence[str], None] = "4f6d88b7c1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "horseback_runs",
        sa.Column("min_consolidation_days", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "horseback_runs",
        sa.Column("max_consolidation_days", sa.Integer(), nullable=False, server_default="12"),
    )


def downgrade() -> None:
    op.drop_column("horseback_runs", "max_consolidation_days")
    op.drop_column("horseback_runs", "min_consolidation_days")

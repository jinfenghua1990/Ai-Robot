"""add data_collection_alert table

Revision ID: f8d6add9aa10
Revises: c3c28b278efa
Create Date: 2026-07-08 18:55:15.911542

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8d6add9aa10'
down_revision: Union[str, Sequence[str], None] = 'c3c28b278efa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create data_collection_alert table for realtime collection monitoring."""
    op.create_table(
        'data_collection_alert',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('level', sa.String(length=10), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('trade_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_data_collection_alert_category', 'data_collection_alert', ['category'], unique=False)
    op.create_index('ix_data_collection_alert_created_at', 'data_collection_alert', ['created_at'], unique=False)
    op.create_index('ix_data_collection_alert_date_level', 'data_collection_alert', ['trade_date', 'level'], unique=False)
    op.create_index('ix_data_collection_alert_level', 'data_collection_alert', ['level'], unique=False)
    op.create_index('ix_data_collection_alert_trade_date', 'data_collection_alert', ['trade_date'], unique=False)


def downgrade() -> None:
    """Drop data_collection_alert table."""
    op.drop_index('ix_data_collection_alert_trade_date', table_name='data_collection_alert')
    op.drop_index('ix_data_collection_alert_level', table_name='data_collection_alert')
    op.drop_index('ix_data_collection_alert_date_level', table_name='data_collection_alert')
    op.drop_index('ix_data_collection_alert_created_at', table_name='data_collection_alert')
    op.drop_index('ix_data_collection_alert_category', table_name='data_collection_alert')
    op.drop_table('data_collection_alert')

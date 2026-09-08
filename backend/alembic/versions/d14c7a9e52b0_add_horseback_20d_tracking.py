"""add horseback 20 trading day tracking

Revision ID: d14c7a9e52b0
Revises: b72a91c6f8d5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d14c7a9e52b0"
down_revision: Union[str, Sequence[str], None] = "b72a91c6f8d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "horseback_tracks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pool_date", sa.Date(), nullable=False),
        sa.Column("source_run_id", sa.String(36), nullable=False),
        sa.Column("source_mode", sa.String(16), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("structure_date", sa.Date(), nullable=False),
        sa.Column("ts_code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(50)),
        sa.Column("admission_status", sa.String(24), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("entry_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("entry_price_source", sa.String(32), nullable=False, server_default="realtime_snapshot"),
        sa.Column("entry_snapshot_at", sa.DateTime(), nullable=False),
        sa.Column("source_options_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_limit_date", sa.Date()),
        sa.Column("days_since_limit", sa.Integer()),
        sa.Column("suggested_buy", sa.Numeric(12, 4)),
        sa.Column("stop_loss", sa.Numeric(12, 4)),
        sa.Column("track_days", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("completed_date", sa.Date()),
        sa.Column("archive_reason", sa.String(80)),
        sa.Column("latest_day", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latest_trade_date", sa.Date()),
        sa.Column("latest_close", sa.Numeric(12, 4)),
        sa.Column("latest_daily_pct", sa.Numeric(10, 4)),
        sa.Column("latest_return_pct", sa.Numeric(10, 4)),
        sa.Column("max_return_pct", sa.Numeric(10, 4)),
        sa.Column("min_return_pct", sa.Numeric(10, 4)),
        sa.Column("max_drawdown_pct", sa.Numeric(10, 4)),
        sa.Column("final_return_pct", sa.Numeric(10, 4)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("pool_date", "ts_code", name="uq_horseback_track_pool_code"),
    )
    op.create_index("ix_horseback_tracks_pool_date", "horseback_tracks", ["pool_date"])
    op.create_index("ix_horseback_tracks_source_run_id", "horseback_tracks", ["source_run_id"])
    op.create_index("ix_horseback_tracks_structure_date", "horseback_tracks", ["structure_date"])
    op.create_index("ix_horseback_tracks_ts_code", "horseback_tracks", ["ts_code"])
    op.create_index("ix_horseback_tracks_admission_status", "horseback_tracks", ["admission_status"])
    op.create_index("ix_horseback_tracks_status", "horseback_tracks", ["status"])
    op.create_index("ix_horseback_track_status_pool", "horseback_tracks", ["status", "pool_date"])

    op.create_table(
        "horseback_track_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tracker_id",
            sa.Integer(),
            sa.ForeignKey("horseback_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("day_n", sa.Integer(), nullable=False),
        sa.Column("open", sa.Numeric(12, 4)),
        sa.Column("high", sa.Numeric(12, 4)),
        sa.Column("low", sa.Numeric(12, 4)),
        sa.Column("close", sa.Numeric(12, 4), nullable=False),
        sa.Column("daily_pct", sa.Numeric(10, 4)),
        sa.Column("cum_return_pct", sa.Numeric(10, 4)),
        sa.Column("drawdown_pct", sa.Numeric(10, 4)),
        sa.Column("volume", sa.Numeric(20, 4)),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tracker_id", "trade_date", name="uq_horseback_track_daily_tracker_date"),
        sa.UniqueConstraint("tracker_id", "day_n", name="uq_horseback_track_daily_tracker_day"),
    )
    op.create_index("ix_horseback_track_daily_tracker_id", "horseback_track_daily", ["tracker_id"])
    op.create_index("ix_horseback_track_daily_trade_date", "horseback_track_daily", ["trade_date"])


def downgrade() -> None:
    op.drop_table("horseback_track_daily")
    op.drop_table("horseback_tracks")

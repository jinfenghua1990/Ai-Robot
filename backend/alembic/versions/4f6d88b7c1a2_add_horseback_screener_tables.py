"""add native horseback screener run tables

Revision ID: 4f6d88b7c1a2
Revises: e89ce5f4b2d1
Create Date: 2026-08-28 10:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f6d88b7c1a2"
down_revision: Union[str, Sequence[str], None] = "e89ce5f4b2d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "horseback_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="QUEUED"),
        sa.Column("source", sa.String(32), nullable=False, server_default="ifind_mcp"),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("requested_end_date", sa.Date),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("window_start", sa.Date, nullable=False),
        sa.Column("window_end", sa.Date, nullable=False),
        sa.Column("min_limit_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("max_limit_count", sa.Integer, nullable=False, server_default="3"),
        sa.Column("min_score", sa.Integer, nullable=False, server_default="75"),
        sa.Column("max_candidates", sa.Integer, nullable=False, server_default="100"),
        sa.Column("source_query", sa.Text),
        sa.Column("source_payload_sha256", sa.String(64)),
        sa.Column("source_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pool_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("selected_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("message", sa.String(200)),
        sa.Column("error", sa.Text),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("started_at", sa.DateTime),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_horseback_runs_status", "horseback_runs", ["status"])
    op.create_index("ix_horseback_runs_as_of_date", "horseback_runs", ["as_of_date"])

    op.create_table(
        "horseback_candidates",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("horseback_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts_code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(50)),
        sa.Column("source_rank", sa.Integer, nullable=False),
        sa.Column("source_limit_count", sa.Integer),
        sa.Column("observed_limit_count", sa.Integer),
        sa.Column("effective_limit_count", sa.Integer),
        sa.Column("last_limit_date", sa.Date),
        sa.Column("admitted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("exclusion_reason", sa.String(200)),
        sa.Column("source_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "ts_code", name="uq_horseback_candidate_run_code"),
    )
    op.create_index("ix_horseback_candidates_run_id", "horseback_candidates", ["run_id"])
    op.create_index("ix_horseback_candidates_ts_code", "horseback_candidates", ["ts_code"])
    op.create_index("ix_horseback_candidate_run_admitted", "horseback_candidates", ["run_id", "admitted"])

    op.create_table(
        "horseback_results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("horseback_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts_code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(50)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("score", sa.Integer),
        sa.Column("kline_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_limit_date", sa.Date),
        sa.Column("days_since_limit", sa.Integer),
        sa.Column("close", sa.Numeric(12, 4)),
        sa.Column("pct_chg", sa.Numeric(10, 4)),
        sa.Column("ma5", sa.Numeric(12, 4)),
        sa.Column("ma10", sa.Numeric(12, 4)),
        sa.Column("ma20", sa.Numeric(12, 4)),
        sa.Column("ma60", sa.Numeric(12, 4)),
        sa.Column("pullback_pct", sa.Numeric(10, 4)),
        sa.Column("volume_ratio", sa.Numeric(10, 4)),
        sa.Column("ma_convergence_pct", sa.Numeric(10, 4)),
        sa.Column("suggested_buy", sa.Numeric(12, 4)),
        sa.Column("stop_loss", sa.Numeric(12, 4)),
        sa.Column("components_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("hard_failures_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "ts_code", name="uq_horseback_result_run_code"),
    )
    op.create_index("ix_horseback_results_run_id", "horseback_results", ["run_id"])
    op.create_index("ix_horseback_results_ts_code", "horseback_results", ["ts_code"])
    op.create_index("ix_horseback_results_status", "horseback_results", ["status"])
    op.create_index("ix_horseback_result_run_status_score", "horseback_results", ["run_id", "status", "score"])


def downgrade() -> None:
    op.drop_table("horseback_results")
    op.drop_table("horseback_candidates")
    op.drop_table("horseback_runs")

"""Scheduled write pipeline for the independent industry-stage module."""

import logging

from sqlalchemy import func

from db.session import get_db_session
from industry_stage.collector import (
    ensure_schema,
    latest_completed_trade_date,
    sync_daily_basic,
    sync_taxonomy_and_membership,
)
from industry_stage.compute import build_recent_snapshots
from industry_stage.models import IndustryStageMembership, IndustryStageTaxonomy


logger = logging.getLogger(__name__)


def _has_complete_classification() -> bool:
    with get_db_session() as db:
        l1_count = db.query(func.count(IndustryStageTaxonomy.id)).filter(
            IndustryStageTaxonomy.level == "L1",
            IndustryStageTaxonomy.is_active.is_(True),
        ).scalar() or 0
        l2_count = db.query(func.count(IndustryStageTaxonomy.id)).filter(
            IndustryStageTaxonomy.level == "L2",
            IndustryStageTaxonomy.is_active.is_(True),
        ).scalar() or 0
        member_count = db.query(func.count(func.distinct(IndustryStageMembership.ts_code))).filter(
            IndustryStageMembership.is_current.is_(True),
        ).scalar() or 0
    return l1_count == 31 and l2_count == 134 and member_count >= 5000


def run_pipeline(*, refresh_classification: bool = False, backfill_days: int = 10) -> dict:
    """External → DB → offline score.  Safe to rerun for the same trade date."""
    ensure_schema()
    classification = None
    if refresh_classification or not _has_complete_classification():
        classification = sync_taxonomy_and_membership()

    target = latest_completed_trade_date()
    if target is None:
        raise RuntimeError("stock_daily_kline has no completed trade date")
    daily_basic = sync_daily_basic(target)
    snapshots = build_recent_snapshots(target, days=max(3, min(int(backfill_days), 30)))
    result = {
        "classification": classification,
        "daily_basic": daily_basic,
        "snapshots": snapshots,
    }
    logger.info("[industry-stage] pipeline completed: %s", result)
    return result

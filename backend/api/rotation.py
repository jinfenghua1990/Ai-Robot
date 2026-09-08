from fastapi import APIRouter, Query
from analyzers.rotation import calculate_rotation
from api.validators import validate_date, validate_days
from db.connection import get_db
from db.session import get_db_session
from db.models import SectorFlow
from sqlalchemy import func
from datetime import datetime

router = APIRouter()


def _resolve_rotation_date(db, raw_date):
    """若 raw_date 当天无数据，向前查找最近一个交易日。"""
    if raw_date:
        try:
            end_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            return None
    else:
        end_date = datetime.now().date()

    latest = db.query(func.max(SectorFlow.trade_date)).filter(
        SectorFlow.trade_date <= end_date
    ).scalar()
    return latest.strftime('%Y-%m-%d') if latest else None


@router.get("/api/rotation")
def get_rotation(date: str = Query(None), days: int = Query(5)):
    """返回桑基图数据：流出板块→流入板块。若当天无数据，回退到最近交易日。"""
    trade_date = validate_date(date)
    days = validate_days(days)

    with get_db_session() as db:
        actual_date = _resolve_rotation_date(db, trade_date)
        if not actual_date:
            return {'nodes': [], 'links': [], 'signals': [], 'streaks': {}, 'actual_date': None}

        result = calculate_rotation(actual_date, days)
        result['actual_date'] = actual_date
        return result

from fastapi import APIRouter, Query
from db.connection import get_db
from db.models import LeaderLifecycle
from datetime import datetime

router = APIRouter()

@router.get("/api/lifecycle")
async def get_lifecycle(date: str = Query(None), stage: str = Query(None)):
    """返回龙头生命周期数据"""
    db = next(get_db())
    try:
        trade_date = date or datetime.now().strftime('%Y-%m-%d')
        query = db.query(LeaderLifecycle).filter_by(trade_date=trade_date)
        if stage:
            query = query.filter_by(stage=stage)
        leaders = query.all()
        return {
            'date': trade_date,
            'leaders': [{
                'ts_code': l.ts_code,
                'name': l.name or '',
                'sector': l.sector,
                'stage': l.stage,
                'strength': float(l.strength or 0),
                'change_rate': float(l.change_rate or 0),
                'consecutive_days': l.consecutive_days,
            } for l in leaders],
        }
    finally:
        db.close()

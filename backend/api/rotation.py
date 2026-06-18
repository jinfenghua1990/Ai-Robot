from fastapi import APIRouter, Query
from analyzers.rotation import calculate_rotation

router = APIRouter()

@router.get("/api/rotation")
async def get_rotation(date: str = Query(None), days: int = Query(5)):
    """返回桑基图数据：流出板块→流入板块"""
    trade_date = date or datetime.now().strftime('%Y-%m-%d')
    return calculate_rotation(trade_date, days)

from datetime import datetime

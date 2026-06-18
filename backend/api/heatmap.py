from fastapi import APIRouter, Query
from db.connection import get_db
from db.models import SectorFlow
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/api/heatmap")
async def get_heatmap(date: str = Query(None), days: int = Query(5)):
    """返回热力图数据：日期×板块的heat_score矩阵"""
    db = next(get_db())
    try:
        end_date = datetime.strptime(date, '%Y-%m-%d') if date else datetime.now()
        dates = [(end_date - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days)]
        
        sectors = db.query(SectorFlow).filter(
            SectorFlow.trade_date.in_([datetime.strptime(d, '%Y-%m-%d').date() for d in dates])
        ).all()
        
        # 构建矩阵
        sector_names = list(set(s.sector for s in sectors))
        values = []
        for s in sectors:
            x = dates.index(s.trade_date.strftime('%Y-%m-%d')) if s.trade_date.strftime('%Y-%m-%d') in dates else -1
            if x >= 0:
                y = sector_names.index(s.sector)
                values.append([x, y, float(s.heat_score or 0)])
        
        return {
            'dates': dates,
            'sectors': sector_names,
            'values': values,
        }
    finally:
        db.close()

"""BS 策略保存/加载/删除
- GET    /api/bs-screener/strategies
- POST   /api/bs-screener/strategies
- DELETE /api/bs-screener/strategies/{id}
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.connection import get_db
from db.session import get_db_session
from db.models import BSStrategy

router = APIRouter()


class StrategyRequest(BaseModel):
    name: str
    atr_period: int = 10
    atr_multiplier: float = 1.0
    scan_limit: int = 50
    sector_filter: str = ''
    signal_type: str = 'B'
    volume_filter: bool = False
    ma20_filter: bool = False
    ma60_trend: bool = False
    rsi_filter: bool = False
    strong_volume: bool = False


@router.get("/api/bs-screener/strategies")
def list_strategies():
    with get_db_session() as db:
        items = db.query(BSStrategy).order_by(BSStrategy.created_at.desc()).all()
        return {
            'strategies': [{
                'id': s.id,
                'name': s.name,
                'atr_period': s.atr_period,
                'atr_multiplier': float(s.atr_multiplier or 1.0),
                'scan_limit': s.scan_limit,
                'sector_filter': s.sector_filter or '',
                'signal_type': s.signal_type or 'B',
                'volume_filter': bool(s.volume_filter),
                'ma20_filter': bool(s.ma20_filter),
                'ma60_trend': bool(getattr(s, 'ma60_trend', False) and s.ma60_trend),
                'rsi_filter': bool(getattr(s, 'rsi_filter', False) and s.rsi_filter),
                'strong_volume': bool(getattr(s, 'strong_volume', False) and s.strong_volume),
                'created_at': s.created_at.strftime('%Y-%m-%d %H:%M') if s.created_at else '',
            } for s in items]
        }


@router.post("/api/bs-screener/strategies")
def save_strategy(req: StrategyRequest):
    with get_db_session() as db:
        item = BSStrategy(
            name=req.name,
            atr_period=req.atr_period,
            atr_multiplier=req.atr_multiplier,
            scan_limit=req.scan_limit,
            sector_filter=req.sector_filter,
            signal_type=req.signal_type,
            volume_filter=req.volume_filter,
            ma20_filter=req.ma20_filter,
            ma60_trend=req.ma60_trend,
            rsi_filter=req.rsi_filter,
            strong_volume=req.strong_volume,
        )
        db.add(item)
        db.commit()
        return {'success': True, 'id': item.id}


@router.delete("/api/bs-screener/strategies/{strategy_id}")
def delete_strategy(strategy_id: int):
    with get_db_session() as db:
        item = db.query(BSStrategy).filter_by(id=strategy_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="策略不存在")
        db.delete(item)
        db.commit()
        return {'success': True}

"""自动化交易 API 端点"""

from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel
from db.connection import get_db
from db.session import get_db_session
from db.models import AutoTradeConfig, AutoTradeLog
from services.auto_trade_engine import aggregate_signals, execute_auto_trade

router = APIRouter()


class ConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    single_position_pct: Optional[float] = None
    max_positions: Optional[int] = None
    max_buy_count: Optional[int] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    min_vote_score: Optional[int] = None
    use_market_price: Optional[bool] = None
    buy_quantity: Optional[int] = None
    sell_quantity: Optional[int] = None


@router.get("/api/auto-trade/config")
def get_config():
    """读取风控配置"""
    with get_db_session() as db:
        row = db.query(AutoTradeConfig).filter_by(id=1).first()
        if not row:
            return {'enabled': False, 'single_position_pct': 10, 'max_positions': 10,
                    'max_buy_count': 20,
                    'stop_loss_pct': -5, 'take_profit_pct': 15, 'min_vote_score': 2,
                    'use_market_price': True, 'buy_quantity': 100, 'sell_quantity': 100}
        return {
            'enabled': row.enabled,
            'single_position_pct': float(row.single_position_pct),
            'max_positions': row.max_positions,
            'max_buy_count': row.max_buy_count if row.max_buy_count is not None else 20,
            'stop_loss_pct': float(row.stop_loss_pct),
            'take_profit_pct': float(row.take_profit_pct),
            'min_vote_score': row.min_vote_score,
            'use_market_price': row.use_market_price,
            'buy_quantity': row.buy_quantity or 100,
            'sell_quantity': row.sell_quantity or 100,
            'updated_at': row.updated_at.strftime('%Y-%m-%d %H:%M:%S') if row.updated_at else '',
        }


@router.post("/api/auto-trade/config")
def update_config(req: ConfigUpdate):
    """更新风控配置"""
    with get_db_session() as db:
        row = db.query(AutoTradeConfig).filter_by(id=1).first()
        if not row:
            row = AutoTradeConfig(id=1)
            db.add(row)
        data = req.dict(exclude_none=True)
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = datetime.now()
        db.commit()
        return {'ok': True, 'message': '配置已更新'}


@router.get("/api/auto-trade/signals")
def get_signals():
    """当日聚合信号预览（不下单）"""
    with get_db_session() as db:
        today = date.today().strftime('%Y-%m-%d')
        signals = aggregate_signals(today, db)
        return {'date': today, 'signals': signals, 'count': len(signals)}


@router.get("/api/auto-trade/logs")
def get_logs(date_str: str = Query(None, alias='date')):
    """查询交易日志"""
    with get_db_session() as db:
        q = db.query(AutoTradeLog).order_by(AutoTradeLog.created_at.desc())
        if date_str:
            q = q.filter(AutoTradeLog.trade_date == date_str)
        rows = q.limit(100).all()
        return {
            'logs': [{
                'id': r.id,
                'trade_date': r.trade_date.strftime('%Y-%m-%d') if r.trade_date else '',
                'ts_code': r.ts_code,
                'action': r.action,
                'reason': r.reason,
                'vote_score': r.vote_score,
                'strategies': r.strategies_json or '[]',
                'price': float(r.price) if r.price else 0,
                'quantity': r.quantity,
                'status': r.status,
                'created_at': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
            } for r in rows],
            'count': len(rows),
        }


@router.post("/api/auto-trade/run")
async def run_once(dry_run: bool = Query(True, description="true=仅预览不下单")):
    """手动触发一次自动化交易扫描"""
    with get_db_session() as db:
        logs = await execute_auto_trade(db, dry_run=dry_run)
        return {'logs': logs, 'count': len(logs), 'dry_run': dry_run}

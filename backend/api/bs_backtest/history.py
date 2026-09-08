"""回测历史 CRUD
- POST   /api/bs-screener/backtest/save
- GET    /api/bs-screener/backtest/history
- DELETE /api/bs-screener/backtest/history/{id}
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.connection import get_db
from db.session import get_db_session
from db.models import BSBacktestResult

router = APIRouter()


class BacktestSaveRequest(BaseModel):
    name: str = ''
    dimension: str = 'custom'
    stock_count: int = 0
    start_date: str = ''
    end_date: str = ''
    initial_capital: float = 100000
    atr_period: int = 10
    atr_multiplier: float = 1.0
    volume_filter: bool = False
    ma20_filter: bool = False
    ma60_trend: bool = False
    rsi_filter: bool = False
    strong_volume: bool = False
    macd_filter: bool = False
    kdj_filter: bool = False
    stop_loss_pct: float = 0.0
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0
    stock_win_rate: float = 0
    total_profit_pct: float = 0
    annual_return: float = 0
    max_drawdown_pct: float = 0
    profit_factor: float = 0
    avg_hold_days: float = 0
    max_profit_pct: float = 0
    max_loss_pct: float = 0
    total_profit: float = 0
    note: str = ''
    sector_uptrend_filter: bool = False
    sector_top_n: int = 10
    sector_filter_mode: str = 'strong_rotation'
    sector_no_data_action: str = 'pass'


@router.post("/api/bs-screener/backtest/save")
def save_backtest_result(req: BacktestSaveRequest):
    """保存一次回测结果到历史记录"""
    with get_db_session() as db:
        item = BSBacktestResult(
            name=req.name,
            dimension=req.dimension,
            stock_count=req.stock_count,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
            atr_period=req.atr_period,
            atr_multiplier=req.atr_multiplier,
            volume_filter=req.volume_filter,
            ma20_filter=req.ma20_filter,
            ma60_trend=req.ma60_trend,
            rsi_filter=req.rsi_filter,
            strong_volume=req.strong_volume,
            macd_filter=req.macd_filter,
            kdj_filter=req.kdj_filter,
            stop_loss_pct=req.stop_loss_pct,
            total_trades=req.total_trades,
            win_trades=req.win_trades,
            loss_trades=req.loss_trades,
            win_rate=req.win_rate,
            stock_win_rate=req.stock_win_rate,
            total_profit_pct=req.total_profit_pct,
            annual_return=req.annual_return,
            max_drawdown_pct=req.max_drawdown_pct,
            profit_factor=req.profit_factor if req.profit_factor != float('inf') else 999.99,
            avg_hold_days=req.avg_hold_days,
            max_profit_pct=req.max_profit_pct,
            max_loss_pct=req.max_loss_pct,
            total_profit=req.total_profit,
            note=req.note,
            sector_uptrend_filter=req.sector_uptrend_filter,
            sector_top_n=req.sector_top_n,
            sector_filter_mode=req.sector_filter_mode,
            sector_no_data_action=req.sector_no_data_action,
        )
        db.add(item)
        db.commit()
        return {'success': True, 'id': item.id}


@router.get("/api/bs-screener/backtest/history")
def list_backtest_history(limit: int = Query(50, description="返回条数")):
    """获取回测历史记录列表"""
    with get_db_session() as db:
        items = db.query(BSBacktestResult).order_by(
            BSBacktestResult.run_at.desc()
        ).limit(limit).all()
        return {
            'history': [{
                'id': r.id,
                'name': r.name or f'BT-{r.id:03d}',
                'run_at': r.run_at.strftime('%Y-%m-%d %H:%M') if r.run_at else '',
                'dimension': r.dimension,
                'stock_count': r.stock_count,
                'start_date': r.start_date,
                'end_date': r.end_date,
                'initial_capital': float(r.initial_capital or 0),
                'atr_period': r.atr_period,
                'atr_multiplier': float(r.atr_multiplier or 1.0),
                'volume_filter': bool(r.volume_filter),
                'ma20_filter': bool(r.ma20_filter),
                'ma60_trend': bool(r.ma60_trend) if hasattr(r, 'ma60_trend') and r.ma60_trend else False,
                'rsi_filter': bool(r.rsi_filter) if hasattr(r, 'rsi_filter') and r.rsi_filter else False,
                'strong_volume': bool(r.strong_volume) if hasattr(r, 'strong_volume') and r.strong_volume else False,
                'macd_filter': bool(r.macd_filter) if hasattr(r, 'macd_filter') and r.macd_filter else False,
                'kdj_filter': bool(r.kdj_filter) if hasattr(r, 'kdj_filter') and r.kdj_filter else False,
                'stop_loss_pct': float(r.stop_loss_pct or 0) if hasattr(r, 'stop_loss_pct') else 0,
                'total_trades': r.total_trades,
                'win_trades': r.win_trades,
                'loss_trades': r.loss_trades,
                'win_rate': float(r.win_rate or 0),
                'stock_win_rate': float(r.stock_win_rate or 0),
                'total_profit_pct': float(r.total_profit_pct or 0),
                'annual_return': float(r.annual_return or 0),
                'max_drawdown_pct': float(r.max_drawdown_pct or 0),
                'profit_factor': float(r.profit_factor or 0),
                'avg_hold_days': float(r.avg_hold_days or 0),
                'max_profit_pct': float(r.max_profit_pct or 0),
                'max_loss_pct': float(r.max_loss_pct or 0),
                'total_profit': float(r.total_profit or 0),
                'note': r.note or '',
                'sector_uptrend_filter': bool(r.sector_uptrend_filter) if hasattr(r, 'sector_uptrend_filter') and r.sector_uptrend_filter else False,
                'sector_top_n': int(r.sector_top_n) if hasattr(r, 'sector_top_n') and r.sector_top_n else 10,
                'sector_filter_mode': r.sector_filter_mode if hasattr(r, 'sector_filter_mode') and r.sector_filter_mode else 'strong_rotation',
                'sector_no_data_action': r.sector_no_data_action if hasattr(r, 'sector_no_data_action') and r.sector_no_data_action else 'pass',
            } for r in items]
        }


@router.delete("/api/bs-screener/backtest/history/{result_id}")
def delete_backtest_result(result_id: int):
    """删除一条回测历史"""
    with get_db_session() as db:
        item = db.query(BSBacktestResult).filter_by(id=result_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="记录不存在")
        db.delete(item)
        db.commit()
        return {'success': True}

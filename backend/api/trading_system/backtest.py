"""GET /api/trading-system/backtest/summary — 回测表现摘要"""
import logging
from typing import Optional
from fastapi import APIRouter, Query
from db.session import get_db_session
from db.models import BSBacktestResult

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/trading-system/backtest/summary")
def get_backtest_summary(days: int = Query(30, description="最近 N 天")):
    """回测表现摘要：胜率/收益/回撤/盈亏比
    从 BSBacktestResult 表读取最近一次组合回测结果
    """
    with get_db_session() as db:
        # 最近一次回测
        latest = db.query(BSBacktestResult).order_by(
            BSBacktestResult.run_at.desc()
        ).first()

        # 历史 5 次对比
        history_rows = db.query(BSBacktestResult).order_by(
            BSBacktestResult.run_at.desc()
        ).limit(5).all()

        history = []
        for r in history_rows:
            history.append({
                'id': r.id,
                'name': r.name or '',
                'run_at': r.run_at.strftime('%Y-%m-%d %H:%M') if r.run_at else '',
                'stock_count': r.stock_count or 0,
                'win_rate': float(r.win_rate) if r.win_rate else 0,
                'total_profit_pct': float(r.total_profit_pct) if r.total_profit_pct else 0,
                'max_drawdown_pct': float(r.max_drawdown_pct) if r.max_drawdown_pct else 0,
                'profit_factor': float(r.profit_factor) if r.profit_factor else 0,
            })

        if not latest:
            return {
                'latest_run': None,
                'history': [],
                'message': '暂无回测数据，请先在 BS策略回测 页面运行回测',
            }

        latest_run = {
            'run_at': latest.run_at.strftime('%Y-%m-%d %H:%M') if latest.run_at else '',
            'name': latest.name or '',
            'stock_count': latest.stock_count or 0,
            'start_date': latest.start_date or '',
            'end_date': latest.end_date or '',
            'initial_capital': float(latest.initial_capital) if latest.initial_capital else 0,
            'total_trades': latest.total_trades or 0,
            'win_trades': latest.win_trades or 0,
            'loss_trades': latest.loss_trades or 0,
            'win_rate': float(latest.win_rate) if latest.win_rate else 0,
            'stock_win_rate': float(latest.stock_win_rate) if latest.stock_win_rate else 0,
            'total_profit_pct': float(latest.total_profit_pct) if latest.total_profit_pct else 0,
            'annual_return': float(latest.annual_return) if latest.annual_return else 0,
            'max_drawdown_pct': float(latest.max_drawdown_pct) if latest.max_drawdown_pct else 0,
            'profit_factor': float(latest.profit_factor) if latest.profit_factor else 0,
            'avg_hold_days': float(latest.avg_hold_days) if latest.avg_hold_days else 0,
            'max_profit_pct': float(latest.max_profit_pct) if latest.max_profit_pct else 0,
            'max_loss_pct': float(latest.max_loss_pct) if latest.max_loss_pct else 0,
        }

        return {
            'latest_run': latest_run,
            'history': history,
        }

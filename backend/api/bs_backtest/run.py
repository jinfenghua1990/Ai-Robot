"""POST /api/bs-screener/backtest  单股+组合回测"""
import asyncio
import math
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from api.bs_signals import _fetch_kline
from db.connection import get_db
from db.models import StockFlow
from .engine import _backtest_single, _calc_stats

router = APIRouter()


class BacktestRequest(BaseModel):
    stocks: List[str]
    atr_period: int = 10
    atr_multiplier: float = 1.0
    start_date: str
    end_date: str
    initial_capital: float = 100000.0
    volume_filter: bool = False
    ma20_filter: bool = False
    ma60_trend: bool = False
    rsi_filter: bool = False
    strong_volume: bool = False
    macd_filter: bool = False
    kdj_filter: bool = False
    stop_loss_pct: float = 0.0
    rsi_lower: int = 30
    rsi_upper: int = 70
    ma60_rising: bool = False
    sector_uptrend_filter: bool = False
    sector_top_n: int = 10
    sector_filter_mode: str = 'strong_rotation'
    sector_no_data_action: str = 'pass'
    main_force_filter: bool = False
    main_force_lookback: int = 3
    main_force_min_total: float = 0.0


def _scrub_nan(obj):
    """把所有 float 字段的 NaN/Inf 替换为 0（防止 JSON 序列化 500 错）"""
    if isinstance(obj, dict):
        return {k: _scrub_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_nan(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    return obj


@router.post("/api/bs-screener/backtest")
async def run_backtest(req: BacktestRequest):
    """运行 BS 策略回测（单股+组合）"""
    if not req.stocks:
        raise HTTPException(status_code=400, detail="请选择至少一只股票")
    if len(req.stocks) > 2000:
        raise HTTPException(status_code=400, detail="单次回测最多2000只股票")
    if req.start_date >= req.end_date:
        raise HTTPException(status_code=400, detail="开始日期必须早于结束日期")

    per_stock_capital = req.initial_capital

    sector_top10_map = None
    stock_sector_map = None
    if req.sector_uptrend_filter:
        from analyzers.sector_engine import build_sector_top_map
        sector_top10_map = build_sector_top_map(
            req.start_date, req.end_date, top_n=req.sector_top_n,
            mode=req.sector_filter_mode)
        with get_db_session() as _db:
            rows = _db.query(StockFlow.ts_code, StockFlow.sector).filter(
                StockFlow.sector.isnot(None), StockFlow.sector != '').all()
            stock_sector_map = {}
            for ts_code, sector in rows:
                bare = ts_code.replace('.SH', '').replace('.SZ', '')
                stock_sector_map[bare] = sector

    semaphore = asyncio.Semaphore(5)

    async def backtest_one(code: str):
        async with semaphore:
            try:
                klines = await _fetch_kline(code, 300)
                if not klines or len(klines) < 100:
                    return {'code': code, 'trades': [], 'stats': {}, 'equity_curve': [], 'error': f'kline too short: {len(klines) if klines else 0}'}
                mf_db = None
                if req.main_force_filter:
                    from db.connection import get_db as _gdb
                    mf_db = next(_gdb())
                try:
                    result = _backtest_single(
                        klines, req.atr_period, req.atr_multiplier,
                        per_stock_capital, req.start_date, req.end_date,
                        req.volume_filter, req.ma20_filter,
                        req.ma60_trend, req.rsi_filter, req.strong_volume,
                        req.macd_filter, req.kdj_filter, req.stop_loss_pct,
                        req.rsi_lower, req.rsi_upper, req.main_force_filter,
                        mf_db, req.main_force_lookback, req.main_force_min_total,
                        req.ma60_rising,
                        code, req.sector_uptrend_filter, sector_top10_map,
                        stock_sector_map, req.sector_no_data_action
                    )
                finally:
                    if mf_db is not None:
                        mf_db.close()
                result['code'] = code
                return result
            except Exception as e:
                return {'code': code, 'trades': [], 'stats': {}, 'equity_curve': [], 'error': str(e)}

    tasks = [backtest_one(c) for c in req.stocks]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    final_results = []
    exc_count = 0
    for r in results:
        if isinstance(r, Exception):
            exc_count += 1
            final_results.append({'code': 'unknown', 'trades': [], 'stats': {}, 'equity_curve': [], 'error': f'gather-exception: {type(r).__name__}: {str(r)[:200]}'})
        else:
            final_results.append(r)
    results = final_results

    all_trades = []
    all_equity = {}
    valid_results = [r for r in results if not r.get('error')]
    for r in valid_results:
        all_trades.extend(r['trades'])
        for point in r['equity_curve']:
            d = point['date']
            all_equity[d] = all_equity.get(d, 0) + point['equity']

    merged_curve = [{'date': d, 'equity': round(v, 2)} for d, v in sorted(all_equity.items())]
    summary = _calc_stats(all_trades, merged_curve, req.initial_capital)

    stock_win_rate = 0
    stock_profitable_count = 0
    stock_with_trades_count = 0
    for r in valid_results:
        ts = r.get('trades', [])
        if not ts:
            continue
        stock_with_trades_count += 1
        net_profit = sum(t.get('profit', 0) for t in ts)
        if net_profit > 0:
            stock_profitable_count += 1
    if stock_with_trades_count > 0:
        stock_win_rate = round(stock_profitable_count / stock_with_trades_count * 100, 1)
    summary['stock_win_rate'] = stock_win_rate
    summary['stock_profitable_count'] = stock_profitable_count
    summary['stock_with_trades_count'] = stock_with_trades_count

    per_stock = []
    for r in results:
        ts = r.get('trades', [])
        net_profit = sum(t.get('profit', 0) for t in ts) if ts else 0
        per_stock.append({
            'code': r['code'],
            'trades': len(ts),
            'net_profit': round(net_profit, 2),
            'profitable': net_profit > 0,
            'stats': r.get('stats', {}),
            'error': r.get('error'),
        })

    return _scrub_nan({
        'summary': summary,
        'per_stock': per_stock,
        'trades': all_trades,
        'equity_curve': merged_curve,
        'params': {
            'stocks': req.stocks,
            'atr_period': req.atr_period,
            'atr_multiplier': req.atr_multiplier,
            'start_date': req.start_date,
            'end_date': req.end_date,
            'initial_capital': req.initial_capital,
        },
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })

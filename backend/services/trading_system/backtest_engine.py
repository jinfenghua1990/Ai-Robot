"""4.0 组合回测引擎
按 signal_4 分级分配资金：STRONG_BUY 60% / WATCH_BUY 30% / FORBID 跳过
复用 bs_backtest.engine._backtest_single 做单股回测
"""
import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional

from api.bs_signals import _fetch_kline
from api.bs_backtest.engine import _backtest_single, _calc_stats

logger = logging.getLogger(__name__)


# signal_4 → 资金权重（占比初始资金的百分比）
SIGNAL_CAPITAL_WEIGHT = {
    'STRONG_BUY': 0.60,   # 强买：分配 60% 初始资金
    'WATCH_BUY': 0.30,    # 观察买：分配 30%
    'FORBID': 0.0,        # 禁止：不回测
}


async def _backtest_one(code: str, capital: float, start_date: str, end_date: str,
                       semaphore: asyncio.Semaphore) -> dict:
    """单股回测（带并发控制）"""
    if capital <= 0:
        return {'code': code, 'trades': [], 'stats': {}, 'equity_curve': [], 'error': 'capital=0'}

    async with semaphore:
        try:
            klines = await _fetch_kline(code, 300)
            if not klines or len(klines) < 100:
                return {'code': code, 'trades': [], 'stats': {}, 'equity_curve': [],
                        'error': f'kline too short: {len(klines) if klines else 0}'}
            result = _backtest_single(
                klines,
                atr_period=10,
                atr_multiplier=1.0,
                initial_capital=capital,
                start_date=start_date,
                end_date=end_date,
            )
            result['code'] = code
            result['allocated_capital'] = capital
            return result
        except Exception as e:
            logger.error(f'[backtest_engine] {code} error: {e}')
            return {'code': code, 'trades': [], 'stats': {}, 'equity_curve': [], 'error': str(e)}


async def run_portfolio_backtest(
    stock_signals: List[Dict],
    initial_capital: float,
    start_date: str,
    end_date: str,
    max_concurrency: int = 5,
) -> Dict:
    """组合回测：按 signal_4 分配资金后并发回测

    Args:
        stock_signals: [{'ts_code': '600000.SH', 'signal_4': 'STRONG_BUY', 'name': '...'}, ...]
        initial_capital: 总初始资金
        start_date/end_date: 回测区间
        max_concurrency: 最大并发数

    Returns:
        {
            'summary': {...},          # 组合级统计
            'per_stock': [{...}, ...],  # 每只股票统计
            'trades': [...],            # 全部交易记录
            'equity_curve': [...],      # 组合权益曲线
            'allocation': [...],        # 资金分配明细
        }
    """
    # 1. 按 signal_4 分配资金
    allocation = []
    total_weight = 0.0
    for s in stock_signals:
        sig = s.get('signal_4', 'FORBID')
        weight = SIGNAL_CAPITAL_WEIGHT.get(sig, 0.0)
        if weight > 0:
            allocation.append({
                'ts_code': s['ts_code'],
                'name': s.get('name', ''),
                'signal_4': sig,
                'weight': weight,
                'capital': round(initial_capital * weight, 2),
            })
            total_weight += weight

    # 归一化（总权重可能 > 1.0，按比例缩放）
    if total_weight > 1.0:
        for a in allocation:
            a['capital'] = round(a['capital'] / total_weight, 2)
            a['weight'] = round(a['weight'] / total_weight, 4)

    if not allocation:
        return {
            'summary': _empty_summary(),
            'per_stock': [],
            'trades': [],
            'equity_curve': [],
            'allocation': [],
            'message': '无 STRONG_BUY/WATCH_BUY 信号可回测',
        }

    # 2. 并发回测
    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = [_backtest_one(a['ts_code'].split('.')[0], a['capital'], start_date, end_date, semaphore)
             for a in allocation]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    final_results = []
    for r in results:
        if isinstance(r, Exception):
            final_results.append({'code': 'unknown', 'trades': [], 'stats': {}, 'equity_curve': [],
                                  'error': f'{type(r).__name__}: {str(r)[:200]}'})
        else:
            final_results.append(r)

    # 3. 合并交易 + 权益曲线
    all_trades = []
    all_equity = {}
    valid_results = [r for r in final_results if not r.get('error')]
    for r in valid_results:
        all_trades.extend(r['trades'])
        for point in r['equity_curve']:
            d = point['date']
            all_equity[d] = all_equity.get(d, 0) + point['equity']

    merged_curve = [{'date': d, 'equity': round(v, 2)} for d, v in sorted(all_equity.items())]
    summary = _calc_stats(all_trades, merged_curve, initial_capital)

    # 4. 个股级统计
    per_stock = []
    for r, a in zip(final_results, allocation):
        ts = r.get('trades', [])
        net_profit = sum(t.get('profit', 0) for t in ts) if ts else 0
        per_stock.append({
            'code': a['ts_code'],
            'name': a['name'],
            'signal_4': a['signal_4'],
            'allocated_capital': a['capital'],
            'trades': len(ts),
            'net_profit': round(net_profit, 2),
            'profitable': net_profit > 0,
            'stats': r.get('stats', {}),
            'error': r.get('error'),
        })

    # 5. 个股胜率
    stock_with_trades = [s for s in per_stock if s['trades'] > 0]
    stock_profitable = [s for s in stock_with_trades if s['net_profit'] > 0]
    summary['stock_win_rate'] = round(
        len(stock_profitable) / len(stock_with_trades) * 100, 1
    ) if stock_with_trades else 0
    summary['stock_profitable_count'] = len(stock_profitable)
    summary['stock_with_trades_count'] = len(stock_with_trades)

    return {
        'summary': summary,
        'per_stock': per_stock,
        'trades': all_trades,
        'equity_curve': merged_curve,
        'allocation': allocation,
    }


def _empty_summary() -> dict:
    return {
        'total_trades': 0, 'win_trades': 0, 'loss_trades': 0,
        'win_rate': 0, 'total_profit': 0, 'total_profit_pct': 0,
        'avg_profit_pct': 0, 'max_profit_pct': 0, 'max_loss_pct': 0,
        'avg_hold_days': 0, 'profit_factor': 0,
        'max_drawdown': 0, 'max_drawdown_pct': 0, 'annual_return': 0,
        'stock_win_rate': 0, 'stock_profitable_count': 0, 'stock_with_trades_count': 0,
    }


def run_backtest_from_signals(target_date: Optional[date] = None,
                              initial_capital: float = 100000.0,
                              days: int = 30) -> Dict:
    """从 TradingSignalDaily 取信号跑组合回测（同步入口）

    Args:
        target_date: 信号日期，默认今天
        initial_capital: 初始资金
        days: 回测区间天数

    Returns:
        组合回测结果
    """
    from db.session import get_db_session
    from db.models import TradingSignalDaily

    if target_date is None:
        target_date = date.today()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()

    end_date = target_date.strftime('%Y-%m-%d')
    start_date = (target_date - timedelta(days=days)).strftime('%Y-%m-%d')

    with get_db_session() as db:
        rows = db.query(TradingSignalDaily).filter(
            TradingSignalDaily.trade_date == target_date,
            TradingSignalDaily.signal_4.in_(['STRONG_BUY', 'WATCH_BUY']),
        ).all()

        stock_signals = [{'ts_code': r.ts_code, 'name': r.name, 'signal_4': r.signal_4} for r in rows]

    if not stock_signals:
        return {
            'summary': _empty_summary(),
            'per_stock': [],
            'trades': [],
            'equity_curve': [],
            'allocation': [],
            'message': f'{end_date} 无 STRONG_BUY/WATCH_BUY 信号',
        }

    return asyncio.run(run_portfolio_backtest(
        stock_signals, initial_capital, start_date, end_date,
    ))

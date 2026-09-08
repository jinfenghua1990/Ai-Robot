"""BS 回测核心引擎：单股回测 + 统计指标 + 交易费"""
import math
import logging
from datetime import datetime

from api.bs_signals import _generate_bs_signals
from services.indicators import calc_ma, calc_rsi

logger = logging.getLogger(__name__)

COMMISSION_RATE = 0.0005
STAMP_TAX_RATE = 0.001
MIN_TRADE_FEE = 5.0


def _calc_trade_fee(amount: float, is_buy: bool) -> float:
    commission = max(amount * COMMISSION_RATE, MIN_TRADE_FEE)
    if is_buy:
        return commission
    return commission + amount * STAMP_TAX_RATE


def _calc_hold_days(entry_date: str, exit_date: str) -> int:
    """计算持仓天数（自然日）"""
    try:
        d1 = datetime.strptime(entry_date[:10], '%Y-%m-%d')
        d2 = datetime.strptime(exit_date[:10], '%Y-%m-%d')
        return (d2 - d1).days
    except Exception:
        logger.debug(f"_calc_hold_days failed", exc_info=True)
        return 0


def _calc_stats(trades: list, equity_curve: list, initial_capital: float) -> dict:
    """计算回测统计指标"""
    def _safe(v, default=0):
        if v is None:
            return default
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f):
                return default
            return f
        except Exception:
            logger.debug(f"_safe failed", exc_info=True)
            return default
    for t in trades:
        t['profit'] = _safe(t.get('profit', 0))
        t['profit_pct'] = _safe(t.get('profit_pct', 0))
        t['hold_days'] = max(0, _safe(t.get('hold_days', 0), 0))
    for p in equity_curve:
        p['equity'] = _safe(p.get('equity', 0), 0)

    if not trades:
        return {
            'total_trades': 0,
            'win_trades': 0,
            'loss_trades': 0,
            'win_rate': 0,
            'total_profit': 0,
            'total_profit_pct': 0,
            'avg_profit_pct': 0,
            'max_profit_pct': 0,
            'max_loss_pct': 0,
            'avg_hold_days': 0,
            'profit_factor': 0,
            'max_drawdown': 0,
            'max_drawdown_pct': 0,
            'annual_return': 0,
            'sharpe_ratio': 0,
            'annual_volatility_pct': 0,
        }

    win_trades = [t for t in trades if t['profit'] > 0]
    loss_trades = [t for t in trades if t['profit'] <= 0]
    total_profit = sum(t['profit'] for t in trades)
    gross_profit = sum(t['profit'] for t in win_trades) if win_trades else 0
    gross_loss = abs(sum(t['profit'] for t in loss_trades)) if loss_trades else 0

    max_equity = 0
    max_drawdown = 0
    max_drawdown_pct = 0
    for point in equity_curve:
        eq = point['equity']
        if eq > max_equity:
            max_equity = eq
        dd = max_equity - eq
        if dd > max_drawdown:
            max_drawdown = dd
            max_drawdown_pct = (dd / max_equity * 100) if max_equity else 0

    total_days = _calc_hold_days(equity_curve[0]['date'], equity_curve[-1]['date']) if equity_curve else 1
    total_days = max(total_days, 1)
    total_return_pct = (total_profit / initial_capital * 100) if initial_capital else 0
    annual_return = ((1 + total_return_pct / 100) ** (365 / total_days) - 1) * 100 if total_days > 0 else 0

    # 风险调整指标：夏普比率 + 年化波动率（基于权益曲线日收益，252 交易日年化）
    sharpe = 0.0
    annual_vol = 0.0
    if len(equity_curve) >= 2:
        _rets = []
        for i in range(1, len(equity_curve)):
            prev_eq = equity_curve[i - 1]['equity']
            cur_eq = equity_curve[i]['equity']
            if prev_eq:
                _rets.append((cur_eq - prev_eq) / prev_eq)
        if _rets:
            _mean = sum(_rets) / len(_rets)
            _var = sum((r - _mean) ** 2 for r in _rets) / (len(_rets) - 1) if len(_rets) > 1 else 0
            _std = math.sqrt(_var)
            _tdays = 252
            annual_vol = _std * math.sqrt(_tdays) * 100
            if _std > 0:
                sharpe = (_mean * _tdays) / (math.sqrt(_tdays) * _std)

    result = {
        'total_trades': len(trades),
        'win_trades': len(win_trades),
        'loss_trades': len(loss_trades),
        'win_rate': round(len(win_trades) / len(trades) * 100, 1),
        'total_profit': round(total_profit, 2),
        'gross_profit': round(gross_profit, 2),
        'gross_loss': round(gross_loss, 2),
        'total_profit_pct': round(total_return_pct, 2),
        'avg_profit_pct': round(sum(t['profit_pct'] for t in trades) / len(trades), 2),
        'max_profit_pct': round(max(t['profit_pct'] for t in trades), 2),
        'max_loss_pct': round(min(t['profit_pct'] for t in trades), 2),
        'avg_hold_days': round(sum(t['hold_days'] for t in trades) / len(trades), 1),
        'profit_factor': round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.99,
        'max_drawdown': round(max_drawdown, 2),
        'max_drawdown_pct': round(max_drawdown_pct, 2),
        'annual_return': round(annual_return, 2),
        'sharpe_ratio': round(sharpe, 2),
        'annual_volatility_pct': round(annual_vol, 2),
    }
    for k, v in result.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            if k == 'profit_factor':
                result[k] = 99.99
            else:
                result[k] = 0
    return result


def _backtest_single(
    klines: list,
    atr_period: int,
    atr_multiplier: float,
    initial_capital: float,
    start_date: str,
    end_date: str,
    volume_filter: bool = False,
    ma20_filter: bool = False,
    ma60_trend: bool = False,
    rsi_filter: bool = False,
    strong_volume: bool = False,
    macd_filter: bool = False,
    kdj_filter: bool = False,
    stop_loss_pct: float = 0.0,
    rsi_lower: int = 30,
    rsi_upper: int = 70,
    main_force_filter: bool = False,
    main_force_db=None,
    main_force_lookback: int = 3,
    main_force_min_total: float = 0.0,
    ma60_rising: bool = False,
    code: str = '',
    sector_uptrend_filter: bool = False,
    sector_top10_map: dict = None,
    stock_sector_map: dict = None,
    sector_no_data_action: str = 'pass',
) -> dict:
    """单股回测
    B 点次日开盘买入，S 点次日开盘卖出，全仓操作
    """
    if len(klines) < 30:
        return {'trades': [], 'stats': {}, 'equity_curve': [], 'error': 'K线数据不足'}

    bs_signals, dif, dea, macd, ma5, ma20, k_vals, d_vals, j_vals, support, resistance, trend = \
        _generate_bs_signals(klines, atr_period, atr_multiplier)
    if not bs_signals:
        return {'trades': [], 'stats': {}, 'equity_curve': [], 'error': '无信号'}

    ma60 = None
    rsi_vals = None
    if ma60_trend or ma60_rising or rsi_filter:
        _closes = [k['close'] for k in klines]
        if ma60_trend or ma60_rising:
            ma60 = calc_ma(_closes, 60)
        if rsi_filter:
            rsi_vals = calc_rsi(_closes, 14)

    date_idx = {k['date']: i for i, k in enumerate(klines)}
    in_range_signals = [s for s in bs_signals if start_date <= s['date'] <= end_date]

    # 主力净流入批量预取（消除 N+1：原逻辑在信号循环内逐条查 StockFlow）
    _main_force_data = None
    if main_force_filter and main_force_db is not None and in_range_signals:
        try:
            from datetime import datetime as _dt, timedelta as _td
            from db.models import StockFlow
            _ts_code = code if (code.endswith('.SH') or code.endswith('.SZ')) else f"{code}.{'SH' if code.startswith('6') else 'SZ'}"
            _b_dates = [_dt.strptime(s['date'], '%Y-%m-%d').date()
                        for s in in_range_signals if s['type'] == 'B']
            if _b_dates:
                _min_dt = min(_b_dates) - _td(days=main_force_lookback + 3)
                _max_dt = max(_b_dates)
                _rows = main_force_db.query(StockFlow).filter(
                    StockFlow.ts_code == _ts_code,
                    StockFlow.trade_date > _min_dt,
                    StockFlow.trade_date <= _max_dt,
                ).all()
                _main_force_data = {}
                for _r in _rows:
                    _main_force_data.setdefault(_r.trade_date, []).append(_r)
        except Exception as e:
            logger.debug(f'[bs_backtest] 主力净流入批量预取失败: {e}')
            _main_force_data = None

    if volume_filter or ma20_filter or ma60_trend or ma60_rising or rsi_filter or strong_volume or macd_filter or kdj_filter or sector_uptrend_filter:
        filtered = []
        for sig in in_range_signals:
            if sig['type'] == 'S':
                filtered.append(sig)
                continue

            sig_idx = date_idx.get(sig['date'])
            if sig_idx is None or sig_idx == 0:
                filtered.append(sig)
                continue

            if volume_filter and sig_idx >= 5:
                vol_today = klines[sig_idx]['volume']
                vol_avg5 = sum(klines[sig_idx - 5 + j]['volume'] for j in range(5)) / 5
                if vol_today < vol_avg5:
                    continue

            if strong_volume and sig_idx >= 5:
                vol_today = klines[sig_idx]['volume']
                vol_avg5 = sum(klines[sig_idx - 5 + j]['volume'] for j in range(5)) / 5
                if vol_today < vol_avg5 * 2:
                    continue

            if ma20_filter and ma20 and sig_idx > 0:
                if ma20[sig_idx] is None or ma20[sig_idx - 1] is None:
                    continue
                if ma20[sig_idx] <= ma20[sig_idx - 1]:
                    continue

            if ma60_trend and ma60 and sig_idx > 0:
                if ma60[sig_idx] is None:
                    continue
                if klines[sig_idx]['close'] < ma60[sig_idx]:
                    continue

            if rsi_filter and rsi_vals and sig_idx > 0:
                rsi = rsi_vals[sig_idx]
                if rsi is None or rsi < rsi_lower or rsi > rsi_upper:
                    continue

            if ma60_rising and ma60 and sig_idx > 1:
                if ma60[sig_idx] is None or ma60[sig_idx - 1] is None:
                    continue
                if ma60[sig_idx] <= ma60[sig_idx - 1]:
                    continue

            if macd_filter and sig_idx > 0:
                if macd[sig_idx] is None or macd[sig_idx] <= 0:
                    continue

            if kdj_filter and sig_idx > 0:
                if k_vals[sig_idx] is None or k_vals[sig_idx] >= 80:
                    continue

            if sector_uptrend_filter:
                sig_date = sig['date']
                top10 = sector_top10_map.get(sig_date) if sector_top10_map else None
                if top10 is None:
                    if sector_no_data_action == 'block':
                        continue
                else:
                    sector = stock_sector_map.get(code) if stock_sector_map else None
                    if not sector or sector not in top10:
                        continue

            if main_force_filter and _main_force_data is not None:
                try:
                    from datetime import datetime as _dt, timedelta as _td
                    sig_dt = _dt.strptime(sig['date'], '%Y-%m-%d').date()
                    start_dt = sig_dt - _td(days=main_force_lookback + 3)
                    cand = sorted(
                        [r for d, rs in _main_force_data.items() if start_dt < d <= sig_dt for r in rs],
                        key=lambda r: r.trade_date, reverse=True
                    )[:main_force_lookback]
                    if cand:
                        total_wan = sum(float(r.main_force_inflow or 0) for r in cand) / 10000.0
                        if total_wan < main_force_min_total:
                            continue
                    # cand 为空时等同于原逻辑 if not rows: pass（放行，不拦截）
                except Exception as e:
                    logger.debug(f'[bs_backtest] 主力净流入查询失败: {e}')

            filtered.append(sig)
        in_range_signals = filtered

    trades = []
    position = 0
    entry_price = 0.0
    entry_date = ''
    capital = initial_capital
    equity_curve = []
    signal_map = {s['date']: s for s in in_range_signals}

    for i, k in enumerate(klines):
        cur_date = k['date']
        if cur_date < start_date:
            continue
        if cur_date > end_date:
            break

        if position > 0 and stop_loss_pct > 0 and i + 1 < len(klines):
            stop_price = entry_price * (1 - stop_loss_pct / 100)
            if k['low'] <= stop_price:
                next_k = klines[i + 1]
                trade_price = next_k['open']
                sell_amount = position * trade_price
                fee = _calc_trade_fee(sell_amount, False)
                capital += (sell_amount - fee)
                profit = (trade_price - entry_price) * position - _calc_trade_fee(entry_price * position, True) - fee
                profit_pct = (trade_price - entry_price) / entry_price * 100
                trades.append({
                    'code': code, 'entry_date': entry_date,
                    'entry_price': round(entry_price, 2), 'exit_date': next_k['date'],
                    'exit_price': round(trade_price, 2), 'shares': position,
                    'profit': round(profit, 2), 'profit_pct': round(profit_pct, 2),
                    'hold_days': _calc_hold_days(entry_date, next_k['date']),
                    'signal_reason': f'止损({stop_loss_pct}%)',
                })
                position = 0
                entry_price = 0.0
                continue

        sig = signal_map.get(cur_date)
        if sig and i + 1 < len(klines):
            next_k = klines[i + 1]
            trade_price = next_k['open']

            if sig['type'] == 'B' and position == 0:
                buy_amount = capital
                shares = int(buy_amount / trade_price / 100) * 100
                if shares <= 0:
                    continue
                cost = shares * trade_price
                fee = _calc_trade_fee(cost, True)
                capital -= (cost + fee)
                position = shares
                entry_price = trade_price
                entry_date = next_k['date']

            elif sig['type'] == 'S' and position > 0:
                sell_amount = position * trade_price
                fee = _calc_trade_fee(sell_amount, False)
                capital += (sell_amount - fee)
                profit = (trade_price - entry_price) * position - _calc_trade_fee(entry_price * position, True) - fee
                profit_pct = (trade_price - entry_price) / entry_price * 100
                trades.append({
                    'code': code, 'entry_date': entry_date,
                    'entry_price': round(entry_price, 2), 'exit_date': next_k['date'],
                    'exit_price': round(trade_price, 2), 'shares': position,
                    'profit': round(profit, 2), 'profit_pct': round(profit_pct, 2),
                    'hold_days': _calc_hold_days(entry_date, next_k['date']),
                    'signal_reason': sig.get('reasons', [''])[0] if sig.get('reasons') else '',
                })
                position = 0
                entry_price = 0.0

        equity = capital + position * k['close']
        equity_curve.append({'date': cur_date, 'equity': round(equity, 2)})

    if position > 0 and equity_curve:
        last_k = klines[-1]
        profit = (last_k['close'] - entry_price) * position
        profit_pct = (last_k['close'] - entry_price) / entry_price * 100
        trades.append({
            'code': code, 'entry_date': entry_date,
            'entry_price': round(entry_price, 2),
            'exit_date': equity_curve[-1]['date'] + '(未平仓)',
            'exit_price': round(last_k['close'], 2), 'shares': position,
            'profit': round(profit, 2), 'profit_pct': round(profit_pct, 2),
            'hold_days': _calc_hold_days(entry_date, equity_curve[-1]['date']),
            'signal_reason': '回测结束时未平仓',
        })

    stats = _calc_stats(trades, equity_curve, initial_capital)
    return {'trades': trades, 'stats': stats, 'equity_curve': equity_curve}

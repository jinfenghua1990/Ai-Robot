"""
主升浪策略回测脚本
- 股票池：科创(688.SH) + 创业(300/301.SZ)
- 周期：近1年
- 数据：K线用 pytdx（复用连接），主力资金用 StockFlow 表（需先跑 backfill_moneyflow.py）
- 策略：strategies.zhushenglang.zhushenglang_strategy
- 交易规则：
  - 买入：策略返回非None（score >= 5）
  - 卖出：exit_signal(跌破MA10) / 跌破MA20 / 持有满20天
  - 手续费：佣金万三(最低5元) + 印花税千一(卖出)
  - 仓位：每只股票独立等权（初始资金 10000 元/只）
"""
import os
import sys
import time
from datetime import datetime, date, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_db
from db.session import get_db_session
from db.models import StockFlow
from config import TUSHARE_TOKEN
from strategies.baihu_v26 import _parse_ts_code
from strategies.zhushenglang import zhushenglang_strategy
from collectors.tdx_collector import connect_with_retry
import tushare as ts
import logging
logger = logging.getLogger(__name__)

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

INITIAL_CAPITAL_PER_STOCK = 10000.0
COMMISSION_RATE = 0.0003
MIN_FEE = 5.0
STAMP_TAX = 0.001
MAX_HOLD_DAYS = 40  # 优化：从20天放宽到40天，作为安全阀，让大牛股跟随MA5跑得更远


def is_target(ts_code):
    if ts_code.startswith('688') and ts_code.endswith('.SH'):
        return True
    if ts_code.startswith(('300', '301')) and ts_code.endswith('.SZ'):
        return True
    return False


def get_kline_with_api(api, code, days=300):
    """复用 pytdx 连接拉取 K线，返回 oldest-first 字典列表
    注意：pytdx get_security_bars 实测返回 oldest-first，无需 reversed
    """
    market, pure_code = _parse_ts_code(code)
    if market is None:
        return None
    try:
        bars = api.get_security_bars(4, market, pure_code, 0, days)
    except Exception:
        logger.debug(f"get_kline_with_api failed", exc_info=True)
        return None
    if not bars or len(bars) < 65:
        return None
    # pytdx 实测返回 oldest-first，直接使用
    kline = []
    for b in bars:
        day = b.get('datetime', '')
        if not day and b.get('year'):
            day = f"{b['year']:04d}-{b['month']:02d}-{b['day']:02d}"
        kline.append({
            'close': float(b['close']),
            'open': float(b['open']),
            'high': float(b['high']),
            'low': float(b['low']),
            'volume': float(b.get('vol', b.get('volume', 0))),
            'day': day,
        })
    return kline


def calc_ma(closes, period):
    """计算 MA 序列"""
    result = [None] * len(closes)
    if len(closes) < period:
        return result
    s = sum(closes[:period])
    result[period - 1] = s / period
    for i in range(period, len(closes)):
        s += closes[i] - closes[i - period]
        result[i] = s / period
    return result


def preload_moneyflow(db, ts_codes, start_date):
    """预加载主力资金历史 {ts_code: {date_str: main_force_inflow}}"""
    mf_map = defaultdict(dict)
    rows = db.query(StockFlow.ts_code, StockFlow.trade_date, StockFlow.main_force_inflow).filter(
        StockFlow.trade_date >= start_date,
        StockFlow.ts_code.in_(ts_codes),
        StockFlow.main_force_inflow.isnot(None)
    ).all()
    for r in rows:
        mf_map[r.ts_code][str(r.trade_date)] = float(r.main_force_inflow or 0)
    return mf_map


def backtest_single(kline, mf_history_for_code, start_idx=65):
    """单只股票回测，返回交易列表"""
    trades = []
    closes = [k['close'] for k in kline]
    ma5_list = calc_ma(closes, 5)
    ma10_list = calc_ma(closes, 10)
    ma20_list = calc_ma(closes, 20)

    position = None  # {'buy_price', 'buy_idx', 'buy_date', 'shares'}

    for i in range(start_idx, len(kline)):
        today = kline[i]
        close = today['close']
        day_str = today.get('day', '')

        # 检查卖出
        if position:
            hold_days = i - position['buy_idx']
            ma5 = ma5_list[i]
            ma10 = ma10_list[i]
            ma20 = ma20_list[i]
            should_sell = False
            reason = ''
            # 条件1: 跌破MA20（主升浪生命线）- 硬止损
            if ma20 is not None and close < ma20:
                should_sell = True
                reason = '跌破MA20'
            # 条件2: 移动止盈 - 跌破MA5且持≥3天（让大牛股跟随MA5跑得更远）
            elif ma5 is not None and close < ma5 and hold_days >= 3:
                should_sell = True
                reason = '跌破MA5止盈'
            # 条件3: 持有满 MAX_HOLD_DAYS 天（安全阀）
            elif hold_days >= MAX_HOLD_DAYS:
                should_sell = True
                reason = '持有到期'

            if should_sell:
                sell_amount = close * position['shares']
                commission = max(sell_amount * COMMISSION_RATE, MIN_FEE)
                stamp = sell_amount * STAMP_TAX
                net = sell_amount - commission - stamp
                profit = net - position['cost']
                profit_pct = profit / position['cost'] * 100
                trades.append({
                    'buy_date': position['buy_date'],
                    'sell_date': day_str,
                    'buy_price': position['buy_price'],
                    'sell_price': close,
                    'shares': position['shares'],
                    'profit': round(profit, 2),
                    'profit_pct': round(profit_pct, 2),
                    'hold_days': hold_days,
                    'reason': reason,
                })
                position = None

        # 检查买入（空仓才能买）
        if not position:
            # 取近5日主力资金历史
            mf_history = None
            if mf_history_for_code:
                # 取该日及前4个有数据的交易日
                recent_mf = []
                for j in range(i, max(i - 20, -1), -1):
                    d = kline[j].get('day', '')
                    if d in mf_history_for_code:
                        recent_mf.insert(0, mf_history_for_code[d])
                        if len(recent_mf) >= 5:
                            break
                if len(recent_mf) >= 3:
                    mf_history = recent_mf

            result = zhushenglang_strategy(kline, day_index=i, main_force_history=mf_history)
            if result and result.get('score', 0) >= 5:
                buy_price = close
                # 买入扣除佣金
                raw_amount = INITIAL_CAPITAL_PER_STOCK
                commission = max(raw_amount * COMMISSION_RATE, MIN_FEE)
                usable = raw_amount - commission
                shares = int(usable / buy_price / 100) * 100  # 整手
                if shares >= 100:
                    cost = buy_price * shares + max(buy_price * shares * COMMISSION_RATE, MIN_FEE)
                    position = {
                        'buy_price': buy_price,
                        'buy_idx': i,
                        'buy_date': day_str,
                        'shares': shares,
                        'cost': cost,
                    }

    # 末尾平仓
    if position:
        close = kline[-1]['close']
        sell_amount = close * position['shares']
        commission = max(sell_amount * COMMISSION_RATE, MIN_FEE)
        stamp = sell_amount * STAMP_TAX
        net = sell_amount - commission - stamp
        profit = net - position['cost']
        profit_pct = profit / position['cost'] * 100
        trades.append({
            'buy_date': position['buy_date'],
            'sell_date': kline[-1].get('day', ''),
            'buy_price': position['buy_price'],
            'sell_price': close,
            'shares': position['shares'],
            'profit': round(profit, 2),
            'profit_pct': round(profit_pct, 2),
            'hold_days': len(kline) - 1 - position['buy_idx'],
            'reason': '末尾平仓',
        })

    return trades


def calc_stats(trades, num_stocks, initial_per_stock):
    """计算统计指标"""
    if not trades:
        return {'total_trades': 0, 'win_rate': 0, 'avg_profit_pct': 0, 'profit_factor': 0,
                'max_drawdown_pct': 0, 'avg_hold_days': 0}

    wins = [t for t in trades if t['profit'] > 0]
    losses = [t for t in trades if t['profit'] <= 0]
    gross_profit = sum(t['profit'] for t in wins)
    gross_loss = abs(sum(t['profit'] for t in losses))
    total_capital = num_stocks * initial_per_stock
    total_profit = sum(t['profit'] for t in trades)

    # 按卖出日期排序构建权益曲线
    sorted_trades = sorted(trades, key=lambda t: t['sell_date'])
    equity = total_capital
    peak = equity
    max_dd_pct = 0
    for t in sorted_trades:
        equity += t['profit']
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd_pct:
            max_dd_pct = dd

    total_return_pct = total_profit / total_capital * 100 if total_capital else 0

    return {
        'total_trades': len(trades),
        'win_trades': len(wins),
        'loss_trades': len(losses),
        'win_rate': round(len(wins) / len(trades) * 100, 1) if trades else 0,
        'total_profit': round(total_profit, 2),
        'total_profit_pct': round(total_return_pct, 2),
        'avg_profit_pct': round(sum(t['profit_pct'] for t in trades) / len(trades), 2),
        'max_profit_pct': round(max(t['profit_pct'] for t in trades), 2),
        'max_loss_pct': round(min(t['profit_pct'] for t in trades), 2),
        'avg_hold_days': round(sum(t['hold_days'] for t in trades) / len(trades), 1),
        'profit_factor': round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf'),
        'max_drawdown_pct': round(max_dd_pct, 2),
        'gross_profit': round(gross_profit, 2),
        'gross_loss': round(gross_loss, 2),
    }


def run_backtest(limit=None, kline_days=300):
    print('=' * 70)
    print('🚀 主升浪策略回测 (科创+创业板 · 近1年)')
    print('=' * 70)

    # 1. 股票列表
    print('[backtest] 获取股票列表...')
    basic = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
    targets = [r['ts_code'] for _, r in basic.iterrows() if is_target(r['ts_code'])]
    if limit:
        targets = targets[:limit]
    print(f'[backtest] 目标股票 {len(targets)} 只')

    # 2. 预加载主力资金
    start_date = date.today() - timedelta(days=400)
    print(f'[backtest] 预加载主力资金 (>= {start_date})...')
    with get_db_session() as db:
        mf_map = preload_moneyflow(db, targets, start_date)
    mf_covered = sum(1 for c in targets if c in mf_map)
    print(f'[backtest] 主力资金覆盖 {mf_covered}/{len(targets)} 只股票')

    # 3. 建立 pytdx 连接
    print('[backtest] 连接 pytdx...')
    api, server = connect_with_retry()
    if not api:
        print('[backtest] pytdx 连接失败！')
        return
    print(f'[backtest] pytdx 已连接: {server}')

    # 4. 逐只回测
    all_trades = []
    no_kline_count = 0
    t_start = time.time()
    for i, ts_code in enumerate(targets):
        if (i + 1) % 50 == 0:
            elapsed = time.time() - t_start
            print(f'[backtest] 进度 {i+1}/{len(targets)} ({(i+1)/len(targets)*100:.1f}%) '
                  f'已用 {elapsed:.0f}s 预计 {elapsed/(i+1)*len(targets):.0f}s 交易 {len(all_trades)} 笔')

        kline = get_kline_with_api(api, ts_code, days=kline_days)
        if not kline or len(kline) < 65:
            no_kline_count += 1
            continue

        mf_for_code = mf_map.get(ts_code, {})
        trades = backtest_single(kline, mf_for_code, start_idx=65)
        for t in trades:
            t['ts_code'] = ts_code
        all_trades.extend(trades)

    api.disconnect()
    elapsed = time.time() - t_start
    print(f'[backtest] 回测完成！{len(targets)} 只股票，{len(all_trades)} 笔交易，耗时 {elapsed:.0f}s')
    print(f'[backtest] 无K线数据: {no_kline_count} 只')

    # 5. 统计
    stats = calc_stats(all_trades, len(targets), INITIAL_CAPITAL_PER_STOCK)

    print()
    print('=' * 70)
    print('📊 回测报告：主升浪策略 (科创+创业板 · 近1年)')
    print('=' * 70)
    print(f'股票池:         {len(targets)} 只 (科创+创业)')
    print(f'初始资金:       每只 {INITIAL_CAPITAL_PER_STOCK:.0f} 元 (等权独立)')
    print(f'总交易次数:     {stats["total_trades"]} 笔')
    print(f'盈利交易:       {stats["win_trades"]} 笔')
    print(f'亏损交易:       {stats["loss_trades"]} 笔')
    print(f'胜率:           {stats["win_rate"]}%')
    print(f'总收益:         {stats["total_profit"]:.2f} 元 ({stats["total_profit_pct"]:.2f}%)')
    print(f'总盈利:         {stats["gross_profit"]:.2f} 元')
    print(f'总亏损:         {stats["gross_loss"]:.2f} 元')
    print(f'盈利因子:       {stats["profit_factor"]}')
    print(f'平均收益:       {stats["avg_profit_pct"]:.2f}%')
    print(f'最大盈利:       {stats["max_profit_pct"]:.2f}%')
    print(f'最大亏损:       {stats["max_loss_pct"]:.2f}%')
    print(f'平均持有天数:   {stats["avg_hold_days"]} 天')
    print(f'最大回撤:       {stats["max_drawdown_pct"]}%')
    print('=' * 70)

    # 6. 典型交易样本（前10笔盈利 + 前10笔亏损）
    if all_trades:
        print()
        print('--- 典型盈利交易 TOP 10 ---')
        sorted_profit = sorted(all_trades, key=lambda t: t['profit_pct'], reverse=True)[:10]
        for t in sorted_profit:
            print(f'  {t["ts_code"]:10s} {t["buy_date"]}→{t["sell_date"]} '
                  f'买{t["buy_price"]:.2f} 卖{t["sell_price"]:.2f} '
                  f'+{t["profit_pct"]:.2f}% 持{t["hold_days"]}天 ({t["reason"]})')

        print()
        print('--- 典型亏损交易 TOP 10 ---')
        sorted_loss = sorted(all_trades, key=lambda t: t['profit_pct'])[:10]
        for t in sorted_loss:
            print(f'  {t["ts_code"]:10s} {t["buy_date"]}→{t["sell_date"]} '
                  f'买{t["buy_price"]:.2f} 卖{t["sell_price"]:.2f} '
                  f'{t["profit_pct"]:.2f}% 持{t["hold_days"]}天 ({t["reason"]})')

    return stats, all_trades


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None, help='限制股票数量（测试用）')
    parser.add_argument('--days', type=int, default=300, help='K线天数（默认300）')
    args = parser.parse_args()
    run_backtest(limit=args.limit, kline_days=args.days)

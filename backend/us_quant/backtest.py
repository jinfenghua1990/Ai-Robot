"""US Quant System — 回测引擎

支持 3 套策略（Breakout / Pullback / Earnings Gap）的历史回测，
输出胜率、盈亏比、最大回撤、夏普比率等指标。
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from db.session import get_db_session
from us_quant.data_provider import get_klines, get_klines_batch
from us_quant.indicators import ema, sma, rsi as calc_rsi, atr as calc_atr
from us_quant.strategies import score_breakout, score_pullback, score_earnings_gap
from us_quant.states import determine_stock_state
from us_quant.filters import check_hard_filters
from us_quant.repository import USBacktestResult, USBacktestTrade

logger = logging.getLogger(__name__)

# ─── 预设回测股票池 ──────────────────────────────────────────────────────────

BACKTEST_POOL = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "TSM",
    "AVGO", "AMD", "JPM", "V", "MA", "UNH", "HD", "DIS", "NFLX",
    "ADBE", "CRM", "INTC", "CSCO", "ORCL", "IBM", "QCOM", "TXN",
    "BA", "CAT", "GE", "MMM", "HON", "UPS", "RTX", "LMT",
    "XOM", "CVX", "COP", "OXY", "SLB", "DUK", "NEE", "SO",
    "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY", "TMO", "DHR",
    "PG", "KO", "PEP", "WMT", "COST", "MCD", "SBUX", "NKE",
    "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "AXP",
]

# ─── 回测结果数据结构 ────────────────────────────────────────────────────────


@dataclass
class BacktestTrade:
    """单笔交易记录"""
    symbol: str
    strategy: str
    entry_date: str
    entry_price: float
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    direction: str = "LONG"
    shares: int = 0
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    bars_held: int = 0
    exit_reason: str = ""


@dataclass
class BacktestMetrics:
    """回测指标汇总"""
    symbol: str
    strategy: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    avg_bars_held: float = 0.0
    trades: list[BacktestTrade] = field(default_factory=list)


# ─── 核心回测逻辑 ────────────────────────────────────────────────────────────


def _is_us_trading_day(check_date: date) -> bool:
    """简单判断是否为美股交易日：周一至周五"""
    return check_date.weekday() < 5


def _get_trading_days(start_date: date, end_date: date) -> list[date]:
    """获取交易日列表"""
    days = []
    cur = start_date
    while cur <= end_date:
        if _is_us_trading_day(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


def run_backtest(
    symbol: str,
    strategy: str = "ALL",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    initial_capital: float = 100000.0,
    max_positions: int = 1,
    stop_loss_pct: float = 0.05,
    take_profit_pct: float = 0.15,
) -> BacktestMetrics:
    """对单只股票运行回测

    Args:
        symbol: 股票代码
        strategy: 策略名称 (breakout / pullback / earnings_gap / ALL)
        start_date: 开始日期 YYYY-MM-DD（默认 1 年前）
        end_date: 结束日期 YYYY-MM-DD（默认今天）
        initial_capital: 初始资金
        max_positions: 最大同时持仓数
        stop_loss_pct: 止损比例
        take_profit_pct: 止盈比例

    Returns:
        BacktestMetrics 回测指标
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if start_date is None:
        start = datetime.now() - timedelta(days=365)
        start_date = start.strftime("%Y-%m-%d")

    # 获取足够的历史 K 线（回测需要 1 年+ 的数据）
    klines = get_klines(symbol, "1y")
    if not klines or len(klines) < 60:
        logger.warning(f"[backtest] {symbol}: 数据不足，跳过")
        return BacktestMetrics(symbol=symbol, strategy=strategy)

    # 过滤日期范围
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    klines = [k for k in klines if start_dt <= datetime.fromisoformat(k.get("date", k.get("timestamp", ""))) <= end_dt]  # noqa
    if len(klines) < 60:
        logger.warning(f"[backtest] {symbol}: 日期范围内数据不足，跳过")
        return BacktestMetrics(symbol=symbol, strategy=strategy)

    # 提取价格序列
    dates = []
    closes = []
    highs = []
    lows = []
    volumes = []
    for k in klines:
        ts = k.get("date", k.get("timestamp", ""))
        if isinstance(ts, str):
            dates.append(ts[:10])
        else:
            dates.append(str(ts)[:10])
        closes.append(float(k["close"]))
        highs.append(float(k.get("high", k["close"])))
        lows.append(float(k.get("low", k["close"])))
        volumes.append(float(k.get("volume", 0)))

    metrics = BacktestMetrics(symbol=symbol, strategy=strategy)
    trades: list[BacktestTrade] = []
    in_position = False
    current_trade: Optional[BacktestTrade] = None
    equity_curve = [initial_capital]
    peak_equity = initial_capital

    strategies_to_run = ["breakout", "pullback", "earnings_gap"] if strategy == "ALL" else [strategy]

    # 对每个策略分别回测
    # 简化为在每个交易日计算信号，有信号则开仓，触及止损/止盈则平仓
    for strat in strategies_to_run:
        in_position = False
        current_trade = None
        entry_bar = 0
        equity = initial_capital

        for i in range(50, len(closes)):  # 从第 50 根开始，确保有足够数据计算指标
            bar_date = dates[i]
            price = closes[i]
            high = highs[i]
            low = lows[i]
            vol = volumes[i]

            # 计算技术指标
            close_slice = closes[:i + 1]
            high_slice = highs[:i + 1]
            low_slice = lows[:i + 1]
            vol_slice = volumes[:i + 1]

            ema10_vals = ema(close_slice, 10)
            ema20_vals = ema(close_slice, 20)
            ma50_vals = sma(close_slice, 50)
            rsi_val = calc_rsi(close_slice, 14)
            atr_val = calc_atr(high_slice, low_slice, close_slice, 14)

            ema10 = ema10_vals[-1] if ema10_vals else None
            ema20 = ema20_vals[-1] if ema20_vals else None
            ma50 = ma50_vals[-1] if ma50_vals else None

            if not in_position:
                # 计算信号
                signal = False
                signal_score = 0

                if strat == "breakout" or strat == "ALL":
                    high_52w = max(closes[max(0, i - 252):i + 1])
                    base_high = max(closes[max(0, i - 20):i + 1])
                    base_low = min(closes[max(0, i - 20):i + 1])
                    base_days = 20
                    rel_vol = (vol / (sum(volumes[max(0, i - 5):i]) / 5)) if i >= 5 else 1.0
                    change_today = (price - closes[i - 1]) / closes[i - 1] * 100 if i >= 1 else 0

                    bs = score_breakout(
                        price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                        high_52w=high_52w, base_high=base_high, base_low=base_low,
                        base_days=base_days, rel_volume=rel_vol,
                        change_pct_today=change_today,
                    )
                    if bs.hard_pass and bs.total >= 60:
                        signal = True
                        signal_score = bs.total

                if not signal and (strat == "pullback" or strat == "ALL"):
                    prior_uptrend = bool(ema10 and ema20 and ma50 and ema10 > ema20 > ma50)
                    pullback_pct = None
                    if i >= 10:
                        peak = max(closes[max(0, i - 10):i + 1])
                        pullback_pct = (peak - price) / peak * 100

                    ps = score_pullback(
                        price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                        prior_uptrend=prior_uptrend, first_pullback=True,
                        pullback_pct=pullback_pct, volume_contracted=True,
                        no_consecutive_bearish=True,
                    )
                    if ps.hard_pass and ps.total >= 60:
                        signal = True
                        signal_score = ps.total

                if not signal and (strat == "earnings_gap" or strat == "ALL"):
                    # 财报跳空在回测中简化判断：使用当日涨幅>5% + 放量>2倍
                    gap_pct = change_today = (price - closes[i - 1]) / closes[i - 1] * 100 if i >= 1 else 0
                    vol_ratio = vol / (sum(volumes[max(0, i - 20):i]) / max(20, i)) if i >= 20 else 1.0

                    if gap_pct > 5 and vol_ratio > 2:
                        es = score_earnings_gap(
                            price=price, gap_pct=gap_pct, volume_ratio=vol_ratio,
                            first_day_close_strong=True, gap_not_filled=True,
                            event_source_reliable=True, catalyst_grade="B",
                        )
                        if es.hard_pass and es.total >= 60:
                            signal = True
                            signal_score = es.total

                if signal:
                    shares = int(equity * 0.95 / price)
                    if shares > 0:
                        in_position = True
                        entry_bar = i
                        cost = shares * price
                        equity -= cost
                        current_trade = BacktestTrade(
                            symbol=symbol, strategy=strat,
                            entry_date=bar_date, entry_price=price,
                            shares=shares, direction="LONG",
                        )
            else:
                # 持仓中：检查止损/止盈/退出信号
                stop_price = current_trade.entry_price * (1 - stop_loss_pct)
                target_price = current_trade.entry_price * (1 + take_profit_pct)
                exit_signal = False
                exit_reason = ""

                if low <= stop_price:
                    exit_price = stop_price
                    exit_reason = "止损"
                    exit_signal = True
                elif high >= target_price:
                    exit_price = target_price
                    exit_reason = "止盈"
                    exit_signal = True
                else:
                    # 趋势跟踪退出：跌破 MA50 或 RSI 下穿 50
                    if ma50 and price < ma50 * 0.97:
                        exit_price = price
                        exit_reason = "趋势转弱"
                        exit_signal = True
                    elif rsi_val and rsi_val < 45:
                        exit_price = price
                        exit_reason = "RSI走弱"
                        exit_signal = True

                if exit_signal and current_trade:
                    proceeds = current_trade.shares * exit_price
                    trade_pnl = proceeds - (current_trade.shares * current_trade.entry_price)
                    trade_pnl_pct = trade_pnl / (current_trade.shares * current_trade.entry_price) * 100
                    equity += proceeds
                    bars_held = i - entry_bar

                    current_trade.exit_date = bar_date
                    current_trade.exit_price = exit_price
                    current_trade.pnl = round(trade_pnl, 2)
                    current_trade.pnl_pct = round(trade_pnl_pct, 2)
                    current_trade.bars_held = bars_held
                    current_trade.exit_reason = exit_reason
                    trades.append(current_trade)
                    in_position = False
                    current_trade = None

                # 收盘强制平仓（持仓超过 60 天）
                if in_position and (i - entry_bar) > 60:
                    exit_price = price
                    proceeds = current_trade.shares * exit_price
                    trade_pnl = proceeds - (current_trade.shares * current_trade.entry_price)
                    trade_pnl_pct = trade_pnl / (current_trade.shares * current_trade.entry_price) * 100
                    equity += proceeds

                    current_trade.exit_date = bar_date
                    current_trade.exit_price = exit_price
                    current_trade.pnl = round(trade_pnl, 2)
                    current_trade.pnl_pct = round(trade_pnl_pct, 2)
                    current_trade.bars_held = i - entry_bar
                    current_trade.exit_reason = "持仓超期"
                    trades.append(current_trade)
                    in_position = False
                    current_trade = None

            # 更新权益曲线
            current_equity = equity
            if in_position and current_trade:
                current_equity += current_trade.shares * price
            equity_curve.append(current_equity)
            peak_equity = max(peak_equity, current_equity)

        # 策略结束时强制平仓
        if in_position and current_trade:
            exit_price = closes[-1]
            proceeds = current_trade.shares * exit_price
            trade_pnl = proceeds - (current_trade.shares * current_trade.entry_price)
            trade_pnl_pct = trade_pnl / (current_trade.shares * current_trade.entry_price) * 100

            current_trade.exit_date = dates[-1]
            current_trade.exit_price = exit_price
            current_trade.pnl = round(trade_pnl, 2)
            current_trade.pnl_pct = round(trade_pnl_pct, 2)
            current_trade.bars_held = len(closes) - 1 - entry_bar
            current_trade.exit_reason = "回测结束"
            trades.append(current_trade)

    # ─── 计算指标 ───
    metrics.trades = trades
    metrics.total_trades = len(trades)

    if not trades:
        return metrics

    winning = [t for t in trades if t.pnl and t.pnl > 0]
    losing = [t for t in trades if t.pnl and t.pnl <= 0]
    metrics.winning_trades = len(winning)
    metrics.losing_trades = len(losing)
    metrics.win_rate = round(metrics.winning_trades / metrics.total_trades * 100, 2) if metrics.total_trades > 0 else 0.0

    metrics.total_pnl = round(sum(t.pnl or 0 for t in trades), 2)
    total_cost = sum(t.shares * t.entry_price for t in trades)
    metrics.total_pnl_pct = round(metrics.total_pnl / total_cost * 100, 2) if total_cost > 0 else 0.0

    metrics.avg_win = round(sum(t.pnl for t in winning) / len(winning), 2) if winning else 0.0
    metrics.avg_loss = round(abs(sum(t.pnl for t in losing) / len(losing)), 2) if losing else 0.0

    total_win = sum(t.pnl for t in winning) if winning else 0
    total_loss = abs(sum(t.pnl for t in losing)) if losing else 0
    metrics.profit_factor = round(total_win / total_loss, 2) if total_loss > 0 else float("inf")

    metrics.avg_bars_held = round(sum(t.bars_held for t in trades) / metrics.total_trades, 1) if metrics.total_trades > 0 else 0.0

    # 最大回撤
    if equity_curve:
        peak = equity_curve[0]
        dd = 0
        for v in equity_curve:
            if v > peak:
                peak = v
            dd = max(dd, (peak - v) / peak * 100)
        metrics.max_drawdown_pct = round(dd, 2)

    # 夏普比率
    if len(equity_curve) > 1:
        returns = [(equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1] for i in range(1, len(equity_curve))]
        avg_ret = sum(returns) / len(returns)
        std_ret = math.sqrt(sum((r - avg_ret) ** 2 for r in returns) / len(returns))
        if std_ret > 0:
            metrics.sharpe_ratio = round(avg_ret / std_ret * math.sqrt(252), 2)

    return metrics


def run_backtest_batch(
    symbols: Optional[list[str]] = None,
    strategy: str = "ALL",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    save_to_db: bool = True,
) -> list[BacktestMetrics]:
    """批量回测多个股票

    Args:
        symbols: 股票代码列表，None 则使用预设池
        strategy: 策略名称
        start_date: 开始日期
        end_date: 结束日期
        save_to_db: 是否保存到数据库

    Returns:
        回测结果列表
    """
    if symbols is None:
        symbols = BACKTEST_POOL

    results = []
    for sym in symbols:
        try:
            metrics = run_backtest(sym, strategy, start_date, end_date)
            results.append(metrics)
            logger.info(f"[backtest] {sym} ({strategy}): {metrics.total_trades} trades, "
                        f"WR={metrics.win_rate}%, PnL={metrics.total_pnl_pct}%")
        except Exception as e:
            logger.error(f"[backtest] {sym} error: {e}")

    if save_to_db:
        _save_backtest_results(results, strategy)

    return results


def _save_backtest_results(results: list[BacktestMetrics], strategy: str):
    """保存回测结果到数据库"""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        with get_db_session() as db:
            for m in results:
                if m.total_trades == 0:
                    continue
                row = USBacktestResult(
                    run_id=run_id,
                    symbol=m.symbol,
                    strategy=strategy,
                    total_trades=m.total_trades,
                    winning_trades=m.winning_trades,
                    losing_trades=m.losing_trades,
                    win_rate=Decimal(str(m.win_rate)),
                    total_pnl=Decimal(str(m.total_pnl)),
                    total_pnl_pct=Decimal(str(m.total_pnl_pct)),
                    avg_win=Decimal(str(m.avg_win)) if m.avg_win else None,
                    avg_loss=Decimal(str(m.avg_loss)) if m.avg_loss else None,
                    profit_factor=Decimal(str(m.profit_factor)) if m.profit_factor != float("inf") else None,
                    max_drawdown_pct=Decimal(str(m.max_drawdown_pct)),
                    sharpe_ratio=Decimal(str(m.sharpe_ratio)) if m.sharpe_ratio else None,
                    avg_bars_held=Decimal(str(m.avg_bars_held)),
                    run_at=datetime.now(),
                )
                db.add(row)

                # 保存每笔交易详情
                for t in m.trades:
                    trade_row = USBacktestTrade(
                        run_id=run_id,
                        symbol=t.symbol,
                        strategy=t.strategy,
                        entry_date=t.entry_date,
                        entry_price=Decimal(str(t.entry_price)),
                        exit_date=t.exit_date,
                        exit_price=Decimal(str(t.exit_price)) if t.exit_price else None,
                        direction=t.direction,
                        shares=t.shares,
                        pnl=Decimal(str(t.pnl)) if t.pnl else None,
                        pnl_pct=Decimal(str(t.pnl_pct)) if t.pnl_pct else None,
                        bars_held=t.bars_held,
                        exit_reason=t.exit_reason,
                    )
                    db.add(trade_row)
            db.commit()
            logger.info(f"[backtest] 保存 {len(results)} 条回测结果 (run_id={run_id})")
    except Exception as e:
        logger.error(f"[backtest] 保存回测结果失败: {e}")
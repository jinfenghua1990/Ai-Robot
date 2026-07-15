"""自动化交易引擎：多策略信号聚合 + 风控 + 下单"""

import json
from datetime import datetime, date
from typing import List, Dict, Optional
from sqlalchemy import func

from db.connection import get_db
from db.models import (
    StrategyResult, BSDailyScan, WatchlistSignalDaily,
    AutoTradeConfig, AutoTradeLog,
)
import logging
logger = logging.getLogger(__name__)


STRATEGY_LABELS = {
    'baihu_v26': '白虎V2.6',
    'baihu_v30': '白虎V3.0',
    'qinglong': '青龙',
    'zhushenglang': '主升浪',
    'volume_breakout': '放量突破',
    'macd_golden_cross': 'MACD金叉',
}


def aggregate_signals(trade_date: str, db) -> List[Dict]:
    """聚合多策略信号，返回投票排序后的候选列表。

    数据来源（全部预计算，不现场扫描）：
    1. strategy_result 表：4个策略命中，每命中 vote+1
    2. bs_daily_scan 表：B信号，每命中 vote+1
    3. watchlist_signal_daily 表：bs_signal='B'，vote+1
    """
    vote_map: Dict[str, Dict] = {}

    def _ensure(code):
        if code not in vote_map:
            vote_map[code] = {'ts_code': code, 'name': '', 'vote_score': 0, 'strategies': []}
        return vote_map[code]

    # 1. strategy_result 表
    sr_rows = db.query(StrategyResult).filter(
        StrategyResult.trade_date == trade_date,
        StrategyResult.strategy_key.in_(list(STRATEGY_LABELS.keys())),
    ).all()
    for r in sr_rows:
        entry = _ensure(r.ts_code)
        entry['vote_score'] += 1
        entry['name'] = r.name or entry['name']
        entry['strategies'].append(STRATEGY_LABELS.get(r.strategy_key, r.strategy_key))

    # 2. bs_daily_scan 表（取最新一天的）
    latest_bs_date = db.query(func.max(BSDailyScan.trade_date)).scalar()
    if latest_bs_date:
        bs_rows = db.query(BSDailyScan).filter(BSDailyScan.trade_date == latest_bs_date).all()
        for row in bs_rows:
            signals = json.loads(row.signals_json or '[]')
            for sig in signals:
                code = sig.get('secCode') or sig.get('ts_code') or ''
                if not code or '.' in code:
                    code_raw = code.split('.')[0] if '.' in code else code
                else:
                    code_raw = code
                if not code_raw or len(code_raw) != 6:
                    continue
                ts_code = f"{code_raw}.SH" if code_raw[0] in ('6', '9') else f"{code_raw}.SZ"
                signal_type = sig.get('signalType') or sig.get('signal') or ''
                if signal_type == 'B':
                    entry = _ensure(ts_code)
                    entry['vote_score'] += 1
                    entry['name'] = sig.get('secName') or entry['name']
                    entry['strategies'].append(f"BS-{row.strategy_name or row.backtest_id}")

    # 3. watchlist_signal_daily 表
    # 质量门槛：仅优质/强势/核心 计入投票；普通/合格/杂毛 不计票（避免噪声淹没多策略共振）
    # 兼容新旧命名：旧(优质/强势) + 新(强势/极强) + 核心
    BS_QUALITY_WHITELIST = {'优质', '强势', '极强', '核心'}
    latest_wl_date = db.query(func.max(WatchlistSignalDaily.trade_date)).scalar()
    if latest_wl_date:
        wl_rows = db.query(WatchlistSignalDaily).filter(
            WatchlistSignalDaily.trade_date == latest_wl_date,
            WatchlistSignalDaily.bs_signal == 'B',
            WatchlistSignalDaily.quality_status.in_(list(BS_QUALITY_WHITELIST)),
        ).all()
        for wl in wl_rows:
            entry = _ensure(wl.ts_code)
            entry['vote_score'] += 1
            entry['name'] = wl.name or entry['name']
            entry['strategies'].append(f"BS信号({wl.quality_status})")

    result = sorted(vote_map.values(), key=lambda x: x['vote_score'], reverse=True)
    return result


async def get_account_overview(db) -> Dict:
    """获取东财模拟盘账户资金和持仓（复用 mx_trading.py 接口）"""
    from api.mx_trading import get_balance, get_positions
    balance = await get_balance(force=1)
    positions_resp = await get_positions(force=1)
    positions = positions_resp.get('positions', [])
    return {'balance': balance, 'positions': positions}


async def execute_auto_trade(db, dry_run: bool = False) -> List[Dict]:
    """执行一次自动化交易扫描。

    流程：聚合信号 → 风控检查 → 下单 → 写日志
    返回操作日志列表。
    """
    from api.mx_trading import trade as do_trade, _clear_cache

    config = db.query(AutoTradeConfig).filter_by(id=1).first()
    if not config:
        return [{'status': 'skipped', 'reason': '配置未初始化'}]

    today = date.today().strftime('%Y-%m-%d')
    signals = aggregate_signals(today, db)
    account = await get_account_overview(db)
    balance = account['balance']
    positions = account['positions']

    total_assets = float(balance.get('totalAssets', 0) or 0)
    avail_balance = float(balance.get('availBalance', 0) or 0)
    held_codes = {p.get('secCode', '').split('.')[0] for p in positions}

    logs = []

    # 1. 检查止盈止损（先卖后买）
    sell_qty = max(int(config.sell_quantity or 100), 100)
    for pos in positions:
        code = pos.get('secCode', '').split('.')[0]
        cost_price = float(pos.get('costPrice', 0) or 0)
        current_price = float(pos.get('price', 0) or 0)
        count = int(pos.get('count', 0) or 0)
        if cost_price <= 0 or count <= 0 or current_price <= 0:
            continue
        profit_pct = (current_price - cost_price) / cost_price * 100

        if profit_pct <= float(config.stop_loss_pct):
            qty = min(sell_qty, count)
            reason = f'止损: 盈亏{profit_pct:.1f}% ≤ {config.stop_loss_pct}%, 卖出{qty}股'
            log_entry = _make_log(today, code, pos.get('secName', ''), 'sell', reason, 0, [], current_price, qty)
            if not dry_run and config.enabled:
                try:
                    result = await do_trade(_build_trade_req('sell', code, qty, config.use_market_price))
                    _clear_cache()
                    log_entry['order_result'] = json.dumps(result, ensure_ascii=False)
                    log_entry['status'] = 'success'
                except Exception as e:
                    log_entry['order_result'] = str(e)
                    log_entry['status'] = 'failed'
            else:
                log_entry['status'] = 'skipped'
            logs.append(log_entry)
            _save_log(db, log_entry)

        elif profit_pct >= float(config.take_profit_pct):
            qty = min(sell_qty, count)
            reason = f'止盈: 盈亏{profit_pct:.1f}% ≥ {config.take_profit_pct}%, 卖出{qty}股'
            log_entry = _make_log(today, code, pos.get('secName', ''), 'sell', reason, 0, [], current_price, qty)
            if not dry_run and config.enabled:
                try:
                    result = await do_trade(_build_trade_req('sell', code, qty, config.use_market_price))
                    _clear_cache()
                    log_entry['order_result'] = json.dumps(result, ensure_ascii=False)
                    log_entry['status'] = 'success'
                except Exception as e:
                    log_entry['order_result'] = str(e)
                    log_entry['status'] = 'failed'
            else:
                log_entry['status'] = 'skipped'
            logs.append(log_entry)
            _save_log(db, log_entry)

    # 2. 买入信号（vote_score >= min_vote_score）
    max_buy_count = int(config.max_buy_count or 20)
    bought_today = 0
    for sig in signals:
        if len(positions) >= config.max_positions:
            logs.append(_skip_log(today, sig, f'总持仓数已达上限{config.max_positions}'))
            continue
        if bought_today >= max_buy_count:
            logs.append(_skip_log(today, sig, f'今日买入数已达上限{max_buy_count}只'))
            break
        code = sig['ts_code'].split('.')[0]
        if code in held_codes:
            continue
        if sig['vote_score'] < config.min_vote_score:
            continue

        # 获取实时价格
        from api.trading import get_realtime_quote
        try:
            quote = await get_realtime_quote(code=code)
            current_price = float(quote.get('price', 0) or 0)
        except Exception as e:
            logger.warning(f'[auto_trade] 获取实时价格失败 {code}: {e}')
            current_price = 0
        if current_price <= 0:
            logs.append(_skip_log(today, sig, '无法获取实时价格'))
            continue

        # 计算下单数量：优先使用风控配置的固定买入数量，同时受单票仓位上限和可用资金约束
        buy_qty = max(int(config.buy_quantity or 100), 100)
        target_amount_max = total_assets * float(config.single_position_pct) / 100
        quantity = min(buy_qty, int(target_amount_max / current_price / 100) * 100)
        if quantity < 100:
            logs.append(_skip_log(today, sig, f'资金不足: 目标{buy_qty}股约{buy_qty * current_price:.0f}元, 单票上限{target_amount_max:.0f}元'))
            continue
        if quantity * current_price > avail_balance:
            logs.append(_skip_log(today, sig, f'可用资金不足: 需{quantity * current_price:.0f}元, 可用{avail_balance:.0f}元'))
            continue

        reason = f"投票{sig['vote_score']}票: {'+'.join(sig['strategies'])}, 买入{quantity}股"
        log_entry = _make_log(today, code, sig['name'], 'buy', reason, sig['vote_score'], sig['strategies'], current_price, quantity)
        if not dry_run and config.enabled:
            try:
                result = await do_trade(_build_trade_req('buy', code, quantity, config.use_market_price))
                _clear_cache()
                log_entry['order_result'] = json.dumps(result, ensure_ascii=False)
                log_entry['status'] = 'success'
            except Exception as e:
                log_entry['order_result'] = str(e)
                log_entry['status'] = 'failed'
        else:
            log_entry['status'] = 'skipped'
        logs.append(log_entry)
        _save_log(db, log_entry)
        bought_today += 1

    return logs


def _build_trade_req(trade_type, stock_code, quantity, use_market_price, price=None):
    from api.mx_trading import TradeRequest
    return TradeRequest(
        type=trade_type,
        stockCode=stock_code,
        quantity=quantity,
        useMarketPrice=use_market_price,
        price=price,
    )


def _make_log(trade_date, code, name, action, reason, vote_score, strategies, price, quantity):
    return {
        'trade_date': trade_date,
        'ts_code': code,
        'stock_name': name,
        'action': action,
        'reason': reason,
        'vote_score': vote_score,
        'strategies_json': json.dumps(strategies, ensure_ascii=False),
        'price': price,
        'quantity': quantity,
        'order_result': '',
        'status': 'pending',
    }


def _skip_log(trade_date, sig, reason):
    return _make_log(trade_date, sig['ts_code'].split('.')[0], sig['name'], 'skip', reason, sig['vote_score'], sig['strategies'], 0, 0)


def _save_log(db, log_entry):
    """落库交易日志"""
    try:
        row = AutoTradeLog(
            trade_date=datetime.strptime(log_entry['trade_date'], '%Y-%m-%d').date(),
            ts_code=log_entry['ts_code'],
            action=log_entry['action'],
            reason=log_entry['reason'],
            vote_score=log_entry['vote_score'],
            strategies_json=log_entry['strategies_json'],
            price=log_entry['price'],
            quantity=log_entry['quantity'],
            order_result=log_entry.get('order_result', ''),
            status=log_entry['status'],
        )
        db.add(row)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f'[auto_trade] save_log error: {e}')

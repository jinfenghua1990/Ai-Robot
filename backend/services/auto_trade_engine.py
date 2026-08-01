"""V2 execution bridge.

The legacy implementation treated independent strategy hits as buy votes.  V2
uses the quant_vnext production snapshots as the only buy authority:

    full universe -> factor score -> dimension resonance -> TRIGGERED

The bridge still keeps the existing AutoTradeLog table/API for compatibility,
but records factor/resonance context and distinguishes an accepted order from
an actually filled order.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Dict, List, Optional

from db.models import AutoTradeConfig, AutoTradeLog
from quant_vnext.production import run_production

logger = logging.getLogger(__name__)


def _code6(value: str) -> str:
    return (value or "").split(".", 1)[0]


def _date_value(value: Optional[str | date]) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _candidate_from_snapshot(item: dict, signal_date: date) -> dict:
    resonance = item.get("resonance") or {}
    dimensions = item.get("dimensions") or {}
    return {
        "ts_code": item.get("ts_code", ""),
        "name": item.get("name", ""),
        "sector": item.get("sector", ""),
        "signal_date": signal_date.isoformat(),
        "rank": item.get("rank", 0),
        "factor_score": item.get("factor_score"),
        "dimensions": dimensions,
        "resonance_count": resonance.get("count", 0),
        "resonance_dimensions": resonance.get("dimensions", []),
        "failed_dimensions": resonance.get("failed_dimensions", []),
        "resonance_eligible": bool(resonance.get("eligible", False)),
        "resonance_reason": resonance.get("reason", ""),
        "lifecycle": item.get("lifecycle", ""),
        "trading_state": item.get("trading_state", "INVALID"),
        "market_state": item.get("market_state", ""),
        "reasons": item.get("reasons", []),
        # Compatibility fields for existing cards; they are no longer used
        # as the buy decision.
        "vote_score": resonance.get("count", 0),
        "strategies": resonance.get("dimensions", []),
    }


def aggregate_signals(
    trade_date: Optional[str | date],
    db,
    limit: Optional[int] = None,
) -> List[Dict]:
    """Return V2 ranked signals, never legacy strategy votes.

    ``trade_date`` is resolved to the latest completed daily bar <= that date,
    so an intraday call on a new calendar day cannot silently label yesterday's
    signal as today's signal.
    """

    result = run_production(
        db,
        requested_date=_date_value(trade_date),
        display_limit=limit,
    )
    signal_date = result.get("trade_date")
    if not signal_date:
        return []
    return [
        _candidate_from_snapshot(item, signal_date)
        for item in result.get("signals", [])
    ]


async def get_account_overview(db) -> Dict:
    """Fetch the configured Miaoxiang trading account."""

    from api.mx_trading import get_balance, get_positions

    balance = await get_balance(force=1)
    positions_resp = await get_positions(force=1)
    return {
        "balance": balance,
        "positions": positions_resp.get("positions", []),
    }


def _signal_context(signal: Optional[dict]) -> dict:
    if not signal:
        return {}
    return {
        "signal_date": signal.get("signal_date"),
        "signal_state": signal.get("trading_state"),
        "factor_score": signal.get("factor_score"),
        "resonance_count": signal.get("resonance_count", 0),
        "strategies": signal.get("resonance_dimensions", []),
    }


async def _submit_order(req, do_trade, clear_cache):
    """Submit an order and return API payload plus a stable order id if any."""

    result = await do_trade(req)
    clear_cache()
    order_id = ""
    if isinstance(result, dict):
        for key in ("orderId", "order_id", "id", "entrustId", "entrust_id"):
            if result.get(key) not in (None, ""):
                order_id = str(result[key])
                break
        nested = result.get("data")
        if not order_id and isinstance(nested, dict):
            for key in ("orderId", "order_id", "id", "entrustId", "entrust_id"):
                if nested.get(key) not in (None, ""):
                    order_id = str(nested[key])
                    break
    return result, order_id


async def execute_auto_trade(db, dry_run: bool = False) -> List[Dict]:
    """Execute V2 signals with account-aware gates and auditable status.

    Buys are allowed only for TRIGGERED signals with eligible resonance.  A
    submitted order is recorded as ``submitted``/``fill_status=submitted``;
    it is not falsely labelled as filled before order reconciliation.
    """

    from api.mx_trading import trade as do_trade, _clear_cache

    config = db.query(AutoTradeConfig).filter_by(id=1).first()
    if not config:
        return [{"status": "skipped", "reason": "配置未初始化"}]
    if not config.enabled and not dry_run:
        return [{"status": "skipped", "reason": "V2自动交易已关闭"}]

    # Use all ranked snapshots for held-position exits; the execution loop
    # applies the max-buy/max-position limits after the signal gate.
    signals = aggregate_signals(None, db, limit=None)
    if not signals:
        return [{"status": "skipped", "reason": "没有可用的已完成交易日信号"}]

    signal_date = signals[0].get("signal_date")
    try:
        signal_age = (date.today() - datetime.strptime(signal_date, "%Y-%m-%d").date()).days
    except Exception:
        signal_age = 999
    if signal_age > 3:
        return [{
            "status": "skipped",
            "reason": f"信号过期：{signal_date}，距今{signal_age}天",
        }]

    try:
        account = await get_account_overview(db)
    except Exception as exc:
        logger.error("[auto_trade] account unavailable: %s", exc)
        return [{"status": "failed", "reason": f"账户数据不可用: {exc}"}]

    balance = account["balance"]
    positions = account["positions"]
    total_assets = float(balance.get("totalAssets", 0) or 0)
    available_balance = float(balance.get("availBalance", 0) or 0)
    held_codes = {_code6(p.get("secCode", "")) for p in positions}
    signal_map = {item["ts_code"]: item for item in signals}
    signal_map.update({_code6(item["ts_code"]): item for item in signals})
    logs: list[dict] = []

    def append_log(entry: dict) -> None:
        logs.append(entry)
        _save_log(db, entry)

    # 1. Exits: fixed thresholds remain configurable, but signal invalidation
    # is now an independent V2 exit reason.  A-share T+1 is enforced through
    # availCount, not total count.
    sell_qty = max(int(config.sell_quantity or 100), 100)
    for position in positions:
        code = _code6(position.get("secCode", ""))
        cost = float(position.get("costPrice", 0) or 0)
        current = float(position.get("price", 0) or 0)
        total_count = int(position.get("count", 0) or 0)
        available_count = int(position.get("availCount", total_count) or 0)
        if cost <= 0 or current <= 0 or total_count <= 0:
            continue

        profit_pct = (current - cost) / cost * 100
        signal = signal_map.get(position.get("secCode")) or signal_map.get(code)
        reasons = []
        if profit_pct <= float(config.stop_loss_pct):
            reasons.append(f"止损：盈亏{profit_pct:.1f}%≤{config.stop_loss_pct}%")
        elif profit_pct >= float(config.take_profit_pct):
            reasons.append(f"止盈：盈亏{profit_pct:.1f}%≥{config.take_profit_pct}%")
        if signal and signal.get("trading_state") == "INVALID":
            reasons.append("V2信号失效")
        if signal and signal.get("lifecycle") == "退潮":
            reasons.append("生命周期退潮")
        if not reasons:
            continue

        if available_count <= 0:
            append_log(_make_log(
                signal_date, code, position.get("secName", ""), "skip",
                "；".join(reasons) + "；T+1无可卖数量", 0, current, 0,
                _signal_context(signal), status="skipped",
            ))
            continue

        quantity = min(sell_qty, available_count)
        entry = _make_log(
            signal_date, code, position.get("secName", ""), "sell",
            f"{'；'.join(reasons)}；卖出{quantity}股", 0, current, quantity,
            _signal_context(signal),
        )
        if not dry_run and config.enabled:
            try:
                from api.mx_trading import TradeRequest
                result, order_id = await _submit_order(
                    TradeRequest(
                        type="sell", stockCode=code, quantity=quantity,
                        useMarketPrice=bool(config.use_market_price),
                    ),
                    do_trade,
                    _clear_cache,
                )
                entry.update({
                    "order_result": json.dumps(result, ensure_ascii=False),
                    "order_id": order_id,
                    "status": "submitted",
                    "fill_status": "submitted",
                })
            except Exception as exc:
                entry.update({"order_result": str(exc), "status": "failed", "fill_status": "failed"})
        else:
            entry.update({"status": "skipped", "fill_status": "dry_run"})
        append_log(entry)

    # 2. Buys: only a right-side TRIGGERED signal can enter this loop.
    buyable = [
        item for item in signals
        if item.get("trading_state") == "TRIGGERED"
        and item.get("resonance_eligible")
    ]
    buyable.sort(key=lambda item: (item.get("factor_score") or -1), reverse=True)
    max_positions = int(config.max_positions or 10)
    max_buy_count = int(config.max_buy_count or 20)
    position_count = len(held_codes)
    bought_count = 0
    base_assets = total_assets or available_balance

    for signal in buyable:
        if position_count >= max_positions:
            break
        if bought_count >= max_buy_count:
            break
        code = _code6(signal["ts_code"])
        if code in held_codes:
            continue

        from api.trading import get_realtime_quote
        try:
            quote = await get_realtime_quote(code=code)
            current_price = float(quote.get("price", 0) or 0)
        except Exception as exc:
            append_log(_make_log(
                signal_date, code, signal.get("name", ""), "skip",
                f"无法获取实时价格：{exc}", signal.get("resonance_count", 0), 0, 0,
                _signal_context(signal), status="skipped",
            ))
            continue
        if current_price <= 0:
            continue

        buy_qty = max(int(config.buy_quantity or 100), 100)
        target_max = base_assets * float(config.single_position_pct or 10) / 100
        quantity = min(buy_qty, int(target_max / current_price / 100) * 100)
        if quantity < 100 or quantity * current_price > available_balance:
            append_log(_make_log(
                signal_date, code, signal.get("name", ""), "skip",
                "资金或单票仓位不足", signal.get("resonance_count", 0), current_price, 0,
                _signal_context(signal), status="skipped",
            ))
            continue

        entry = _make_log(
            signal_date, code, signal.get("name", ""), "buy",
            f"V2触发：因子分{signal.get('factor_score')}; "
            f"共振{signal.get('resonance_count')}维；买入{quantity}股",
            signal.get("resonance_count", 0), current_price, quantity,
            _signal_context(signal),
        )
        if not dry_run and config.enabled:
            try:
                from api.mx_trading import TradeRequest
                result, order_id = await _submit_order(
                    TradeRequest(
                        type="buy", stockCode=code, quantity=quantity,
                        useMarketPrice=bool(config.use_market_price),
                    ),
                    do_trade,
                    _clear_cache,
                )
                entry.update({
                    "order_result": json.dumps(result, ensure_ascii=False),
                    "order_id": order_id,
                    "status": "submitted",
                    "fill_status": "submitted",
                })
            except Exception as exc:
                entry.update({"order_result": str(exc), "status": "failed", "fill_status": "failed"})
        else:
            entry.update({"status": "skipped", "fill_status": "dry_run"})
        append_log(entry)
        bought_count += 1
        position_count += 1
        held_codes.add(code)
        available_balance -= quantity * current_price

    return logs


def _make_log(
    signal_date: str,
    code: str,
    name: str,
    action: str,
    reason: str,
    resonance_count: int,
    price: float,
    quantity: int,
    context: Optional[dict] = None,
    status: str = "pending",
) -> dict:
    context = context or {}
    return {
        "trade_date": date.today().isoformat(),
        "signal_date": signal_date,
        "ts_code": code,
        "stock_name": name,
        "action": action,
        "reason": reason,
        "vote_score": resonance_count,
        "strategies_json": json.dumps(context.get("strategies", []), ensure_ascii=False),
        "price": price,
        "quantity": quantity,
        "order_result": "",
        "order_id": "",
        "status": status,
        "fill_status": "pending",
        "signal_state": context.get("signal_state", ""),
        "factor_score": context.get("factor_score"),
        "resonance_count": context.get("resonance_count", resonance_count),
    }


def _save_log(db, log_entry: dict) -> None:
    """Persist the signal-to-order audit row."""

    try:
        row = AutoTradeLog(
            trade_date=datetime.strptime(log_entry["trade_date"], "%Y-%m-%d").date(),
            signal_date=datetime.strptime(log_entry["signal_date"], "%Y-%m-%d").date() if log_entry.get("signal_date") else None,
            ts_code=log_entry["ts_code"],
            action=log_entry["action"],
            reason=log_entry["reason"],
            vote_score=log_entry.get("vote_score", 0),
            strategies_json=log_entry.get("strategies_json", "[]"),
            price=log_entry.get("price", 0),
            quantity=log_entry.get("quantity", 0),
            order_result=log_entry.get("order_result", ""),
            order_id=log_entry.get("order_id", ""),
            status=log_entry.get("status", "pending"),
            fill_status=log_entry.get("fill_status", "pending"),
            signal_state=log_entry.get("signal_state", ""),
            factor_score=log_entry.get("factor_score"),
            resonance_count=log_entry.get("resonance_count", 0),
        )
        db.add(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("[auto_trade] save_log error: %s", exc)

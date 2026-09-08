"""Fail-closed authorization guard for the automated trading executor.

The control plane stores per-stock permissions in AutoTradeStockConfig, while
legacy execution only checked the global switch.  This module wraps the existing
executor and guards the actual external order call, so an unconfigured/off stock
can never reach the broker/simulation API.

Current execution backend is Eastmoney ``mockTrading`` only. Therefore ``live``
is deliberately rejected until a real broker execution connector is wired.

The order guard is context-local: manual /api/mx-trading calls remain untouched,
while scheduled/manual *automatic* execution carries an authorization context.
This avoids permission leakage if two async requests overlap.
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException

from db.models import AutoTradeStockConfig

logger = logging.getLogger(__name__)
_ACTIVE_STATUSES = {"MONITORING", "SIGNAL_READY", "ORDER_WORKING"}

_AUTO_CONTEXT: ContextVar[bool] = ContextVar("airobot_auto_trade_context", default=False)
_AUTO_CONTROLS: ContextVar[dict[str, dict] | None] = ContextVar("airobot_auto_trade_controls", default=None)
_AUTO_ENVIRONMENT: ContextVar[str] = ContextVar("airobot_auto_trade_environment", default="paper")


def _code6(value: str) -> str:
    return str(value or "").strip().upper().split(".", 1)[0]


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def load_stock_controls(db) -> dict[str, dict]:
    """Load the durable per-stock control plane, normalised by 6-digit code."""
    controls: dict[str, dict] = {}
    for row in db.query(AutoTradeStockConfig).all():
        try:
            payload = json.loads(row.config_json or "{}")
        except (TypeError, ValueError):
            payload = {}
        if isinstance(payload, dict):
            controls[_code6(row.code)] = payload
    return controls


def authorization_reason(control: dict | None, action: str, global_environment: str) -> str | None:
    """Return None when an automatic order is authorised, else a block reason."""
    if not isinstance(control, dict):
        return "个股未配置自动交易，默认OFF"

    mode = str(control.get("mode") or "off")
    status = str(control.get("status") or "OFF")
    stock_environment = str(control.get("run_environment") or "paper")

    if mode not in {"risk_only", "full_auto"}:
        return "个股自动交易模式为OFF"
    if status not in _ACTIVE_STATUSES:
        return f"个股状态{status or 'OFF'}不允许自动下单"

    enabled_at = _parse_dt(control.get("enabled_at"))
    if enabled_at is None:
        return "个股未完成显式启用授权"

    expiry_type = str(control.get("authorization_expiry_type") or "daily")
    if expiry_type == "daily" and enabled_at.date() != date.today():
        return "个股当日授权已失效，需要重新启用"

    expires_at = _parse_dt(control.get("authorization_expired_at"))
    if expires_at is not None and expires_at <= datetime.now():
        return "个股自动交易授权已过期"

    # 当前执行端明确是 Eastmoney mockTrading。任何 live 标记都 fail closed，
    # 避免 UI 显示“实盘”但实际上仍操作模拟组合。
    if global_environment != "paper" or stock_environment != "paper":
        return "当前仅接入东财模拟盘，live模式已安全阻断"

    actions = control.get("actions") if isinstance(control.get("actions"), dict) else {}
    if action == "buy":
        if mode != "full_auto":
            return "risk_only模式禁止自动买入"
        if not bool(actions.get("allow_entry", False)):
            return "个股未授权自动开仓"
    elif action == "sell":
        if not any(bool(actions.get(key, False)) for key in (
            "allow_reduce", "allow_exit", "allow_stop", "allow_take_profit", "allow_trailing"
        )):
            return "个股未授权任何自动卖出动作"
    else:
        return f"未知交易动作: {action}"

    return None


def _ensure_context_order_guard() -> None:
    """Patch mx_trading.trade once; enforce only inside auto-trade ContextVar."""
    from api import mx_trading

    if getattr(mx_trading, "_AIROBOT_AUTO_CONTEXT_GUARD", False):
        return

    original_trade = mx_trading.trade

    async def context_guarded_trade(req):
        if not _AUTO_CONTEXT.get():
            # Manual trade endpoint or another direct caller: preserve existing behaviour.
            return await original_trade(req)

        controls = _AUTO_CONTROLS.get() or {}
        environment = _AUTO_ENVIRONMENT.get()
        code = _code6(getattr(req, "stockCode", ""))
        action = str(getattr(req, "type", "") or "").lower()
        reason = authorization_reason(controls.get(code), action, environment)
        if reason:
            logger.warning("[auto_trade_guard] blocked %s %s: %s", action, code, reason)
            raise HTTPException(status_code=403, detail=reason)
        return await original_trade(req)

    context_guarded_trade.__name__ = getattr(original_trade, "__name__", "trade")
    context_guarded_trade.__doc__ = getattr(original_trade, "__doc__", None)
    mx_trading.trade = context_guarded_trade
    mx_trading._AIROBOT_AUTO_CONTEXT_GUARD = True
    mx_trading._AIROBOT_AUTO_CONTEXT_ORIGINAL_TRADE = original_trade


def install_auto_trade_guard(engine_module) -> None:
    """Wrap ``engine_module.execute_auto_trade`` once with durable permissions."""
    if getattr(engine_module, "_PER_STOCK_AUTH_GUARD_INSTALLED", False):
        return

    original_execute = engine_module.execute_auto_trade

    async def guarded_execute_auto_trade(db, dry_run: bool = False):
        # Dry runs never submit an order, so they remain useful for previewing signals.
        if dry_run:
            return await original_execute(db, dry_run=True)

        global_config = db.query(engine_module.AutoTradeConfig).filter_by(id=1).first()
        global_environment = str(getattr(global_config, "run_environment", "paper") or "paper")
        if global_environment != "paper":
            return [{
                "status": "skipped",
                "reason": "当前自动交易执行器仅接入东财模拟盘；global live模式已安全阻断",
            }]

        controls = load_stock_controls(db)
        _ensure_context_order_guard()

        token_active = _AUTO_CONTEXT.set(True)
        token_controls = _AUTO_CONTROLS.set(controls)
        token_env = _AUTO_ENVIRONMENT.set(global_environment)
        try:
            return await original_execute(db, dry_run=False)
        finally:
            _AUTO_ENVIRONMENT.reset(token_env)
            _AUTO_CONTROLS.reset(token_controls)
            _AUTO_CONTEXT.reset(token_active)

    guarded_execute_auto_trade.__name__ = "execute_auto_trade"
    guarded_execute_auto_trade.__doc__ = (
        "Fail-closed automated trading executor with durable per-stock authorization."
    )
    engine_module.execute_auto_trade = guarded_execute_auto_trade
    engine_module._PER_STOCK_AUTH_GUARD_INSTALLED = True

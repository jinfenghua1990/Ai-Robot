"""Fail-closed authorization guard for the automated trading executor.

The control plane stores per-stock permissions in AutoTradeStockConfig, while
legacy execution only checked the global switch.  This module wraps the existing
executor and guards the actual external order call, so an unconfigured/off stock
can never reach the broker/simulation API.

Current execution backend is Eastmoney ``mockTrading`` only.  Therefore ``live``
is deliberately rejected until a real broker execution connector is wired.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException

from db.models import AutoTradeStockConfig

logger = logging.getLogger(__name__)
_ACTIVE_STATUSES = {"MONITORING", "SIGNAL_READY", "ORDER_WORKING"}


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
    """Return None when an order is authorised; otherwise the blocking reason.

    action is ``buy`` or ``sell``.  Missing/invalid configuration is always
    treated as OFF.  This function is intentionally pure so it can be regression
    tested without a database or external API.
    """
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

    # AIROBOT 当前下单实现明确调用 Eastmoney mockTrading；任何 live 标记都
    # fail closed，避免界面写着实盘但实际上仍调用模拟组合。
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


def install_auto_trade_guard(engine_module) -> None:
    """Wrap ``engine_module.execute_auto_trade`` once.

    The existing executor remains the single owner of signal generation,
    positions, T+1, sizing and audit logging.  We only replace the external
    order function during that invocation and restore it afterwards.
    """
    if getattr(engine_module, "_PER_STOCK_AUTH_GUARD_INSTALLED", False):
        return

    original_execute = engine_module.execute_auto_trade

    async def guarded_execute_auto_trade(db, dry_run: bool = False):
        # Dry runs never call the external order function, so preserve the
        # original preview behaviour.  Real scheduled/manual execution is gated.
        if dry_run:
            return await original_execute(db, dry_run=True)

        global_config = db.query(engine_module.AutoTradeConfig).filter_by(id=1).first()
        global_environment = str(getattr(global_config, "run_environment", "paper") or "paper")
        controls = load_stock_controls(db)

        # Global live must also fail closed even before an individual symbol is reached.
        if global_environment != "paper":
            return [{
                "status": "skipped",
                "reason": "当前自动交易执行器仅接入东财模拟盘；global live模式已安全阻断",
            }]

        from api import mx_trading

        original_trade = mx_trading.trade

        async def guarded_trade(req):
            code = _code6(getattr(req, "stockCode", ""))
            action = str(getattr(req, "type", "") or "").lower()
            reason = authorization_reason(controls.get(code), action, global_environment)
            if reason:
                logger.warning("[auto_trade_guard] blocked %s %s: %s", action, code, reason)
                raise HTTPException(status_code=403, detail=reason)
            return await original_trade(req)

        mx_trading.trade = guarded_trade
        try:
            return await original_execute(db, dry_run=False)
        finally:
            mx_trading.trade = original_trade

    guarded_execute_auto_trade.__name__ = "execute_auto_trade"
    guarded_execute_auto_trade.__doc__ = (
        "Fail-closed automated trading executor with durable per-stock authorization."
    )
    engine_module.execute_auto_trade = guarded_execute_auto_trade
    engine_module._PER_STOCK_AUTH_GUARD_INSTALLED = True

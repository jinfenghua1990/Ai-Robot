"""自动化交易 API 端点"""

import json
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Query, Depends
from api.auth import verify_api_key
from pydantic import BaseModel
from db.connection import get_db
from db.session import get_db_session
from db.models import AutoTradeConfig, AutoTradeLog
from services.auto_trade_engine import aggregate_signals, execute_auto_trade

router = APIRouter()


class ConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    single_position_pct: Optional[float] = None
    max_positions: Optional[int] = None
    max_buy_count: Optional[int] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    min_vote_score: Optional[int] = None
    use_market_price: Optional[bool] = None
    buy_quantity: Optional[int] = None
    sell_quantity: Optional[int] = None


@router.get("/api/auto-trade/config")
def get_config():
    """读取风控配置"""
    with get_db_session() as db:
        row = db.query(AutoTradeConfig).filter_by(id=1).first()
        if not row:
            return {'enabled': False, 'single_position_pct': 10, 'max_positions': 10,
                    'max_buy_count': 20,
                    'stop_loss_pct': -5, 'take_profit_pct': 15, 'min_vote_score': 2,
                    'use_market_price': True, 'buy_quantity': 100, 'sell_quantity': 100}
        return {
            'enabled': row.enabled,
            'single_position_pct': float(row.single_position_pct),
            'max_positions': row.max_positions,
            'max_buy_count': row.max_buy_count if row.max_buy_count is not None else 20,
            'stop_loss_pct': float(row.stop_loss_pct),
            'take_profit_pct': float(row.take_profit_pct),
            'min_vote_score': row.min_vote_score,
            'use_market_price': row.use_market_price,
            'buy_quantity': row.buy_quantity or 100,
            'sell_quantity': row.sell_quantity or 100,
            'updated_at': row.updated_at.strftime('%Y-%m-%d %H:%M:%S') if row.updated_at else '',
        }


@router.post("/api/auto-trade/config")
def update_config(req: ConfigUpdate):
    """更新风控配置"""
    with get_db_session() as db:
        row = db.query(AutoTradeConfig).filter_by(id=1).first()
        if not row:
            row = AutoTradeConfig(id=1)
            db.add(row)
        data = req.dict(exclude_none=True)
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = datetime.now()
        db.commit()
        return {'ok': True, 'message': '配置已更新'}


@router.get("/api/auto-trade/signals")
def get_signals():
    """读取最近一个已完成交易日的 V2 信号（不下单）。"""
    with get_db_session() as db:
        requested_date = date.today().isoformat()
        signals = aggregate_signals(None, db)
        signal_date = signals[0].get('signal_date') if signals else None
        return {
            'date': signal_date,
            'requested_date': requested_date,
            'signals': signals,
            'count': len(signals),
            'buyable_count': sum(
                1 for item in signals
                if item.get('trading_state') == 'TRIGGERED'
                and item.get('resonance_eligible')
            ),
            'market_state': signals[0].get('market_state') if signals else None,
        }


@router.get("/api/auto-trade/logs")
def get_logs(date_str: str = Query(None, alias='date')):
    """查询交易日志"""
    with get_db_session() as db:
        q = db.query(AutoTradeLog).order_by(AutoTradeLog.created_at.desc())
        if date_str:
            q = q.filter(AutoTradeLog.trade_date == date_str)
        rows = q.limit(100).all()
        return {
            'logs': [{
                'id': r.id,
                'trade_date': r.trade_date.strftime('%Y-%m-%d') if r.trade_date else '',
                'signal_date': r.signal_date.strftime('%Y-%m-%d') if r.signal_date else '',
                'ts_code': r.ts_code,
                'action': r.action,
                'reason': r.reason,
                'vote_score': r.vote_score,
                'signal_state': r.signal_state or '',
                'factor_score': float(r.factor_score) if r.factor_score is not None else None,
                'resonance_count': r.resonance_count or 0,
                'strategies': json.loads(r.strategies_json or '[]')
                if (r.strategies_json or '').strip().startswith(('[', '{')) else [],
                'price': float(r.price) if r.price else 0,
                'quantity': r.quantity,
                'order_id': r.order_id or '',
                'status': r.status,
                'fill_status': r.fill_status or '',
                'filled_quantity': r.filled_quantity or 0,
                'filled_price': float(r.filled_price) if r.filled_price is not None else None,
                'created_at': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
            } for r in rows],
            'count': len(rows),
        }


@router.post("/api/auto-trade/run", dependencies=[Depends(verify_api_key)])
async def run_once(dry_run: bool = Query(True, description="true=仅预览不下单")):
    """手动触发一次自动化交易扫描"""
    with get_db_session() as db:
        logs = await execute_auto_trade(db, dry_run=dry_run)
        return {'logs': logs, 'count': len(logs), 'dry_run': dry_run}


# ─────────────────────────────────────────────────────────────
# 个股级自动交易配置（V1.0 设计规范：两级权限 / 三模式 / 环境 / 快照 / 审计）
# 存储：项目根 JSON（与 portfolio.json 一致，避免动 DB schema）
# 约定：个股自动交易默认关闭；总开关控制全账户下单；风险指令优先
# ─────────────────────────────────────────────────────────────
import os as _os

_AUTO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
GLOBAL_AUTO_TRADE_PATH = _os.path.join(_AUTO_ROOT, "auto_trade_global.json")
STOCK_AUTO_TRADE_PATH = _os.path.join(_AUTO_ROOT, "auto_trade_stocks.json")
AUDIT_AUTO_TRADE_PATH = _os.path.join(_AUTO_ROOT, "auto_trade_audit.json")
AUDIT_LIMIT = 200
VALID_MODES = ("off", "risk_only", "full_auto")
VALID_ENVS = ("paper", "live")


def _read_json_file(path, default):
    if not _os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json_file(path, data):
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _default_global():
    return {
        "enabled": False,                 # 账户自动交易总开关
        "run_environment": "paper",       # paper 模拟 / live 实盘
        "paused": False,                  # 一键暂停
        "pause_reason": "",
        "paused_at": None,
        "today_orders": 0,
        "today_pnl": 0.0,
        "updated_at": "",
    }


def _default_stock(code="", name=""):
    return {
        "code": code,
        "name": name,
        "mode": "off",                    # off / risk_only / full_auto
        "run_environment": "paper",
        "authorization_expiry_type": "daily",   # daily / persistent
        "authorization_expired_at": None,
        "status": "OFF",                  # OFF/MONITORING/SIGNAL_READY/ORDER_WORKING/PAUSED/ERROR
        "status_reason": "",
        "strategy_id": "",
        "strategy_version": "",
        "strategy_snapshot_json": None,
        "prices": {
            "support_price": None, "breakdown_price": None, "hard_stop_price": None,
            "breakout_price": None, "take_profit_1": None, "take_profit_2": None,
            "trailing_stop_type": "off", "trailing_stop_value": None,
        },
        "risk": {
            "max_position_pct": 15, "max_single_buy_pct": 30, "max_single_sell_pct": 50,
            "max_daily_loss": None, "max_total_loss": None, "max_daily_orders": 2,
            "max_slippage_pct": 0.5, "signal_cooldown_seconds": 600,
        },
        "actions": {
            "allow_entry": False, "allow_add": False, "allow_reduce": True, "allow_exit": True,
            "allow_stop": True, "allow_take_profit": True, "allow_trailing": True,
        },
        "enabled_at": None, "enabled_by": "",
        "disabled_at": None, "disabled_by": "",
        "paused_at": None, "paused_reason": "",
        "last_signal_at": None, "last_order_at": None,
        "created_at": _now_str(), "updated_at": _now_str(),
    }


def get_global_config():
    g = _read_json_file(GLOBAL_AUTO_TRADE_PATH, _default_global())
    return g if isinstance(g, dict) else _default_global()


def _save_global_config(g):
    _write_json_file(GLOBAL_AUTO_TRADE_PATH, g)


def get_stock_configs():
    d = _read_json_file(STOCK_AUTO_TRADE_PATH, {})
    return d if isinstance(d, dict) else {}


def get_stock_config(code):
    return get_stock_configs().get(code)


def _save_stock_configs(d):
    _write_json_file(STOCK_AUTO_TRADE_PATH, d)


def _append_audit(event):
    logs = _read_json_file(AUDIT_AUTO_TRADE_PATH, [])
    logs = logs if isinstance(logs, list) else []
    logs.append(event)
    _write_json_file(AUDIT_AUTO_TRADE_PATH, logs[-AUDIT_LIMIT:])


def _audit(code, event_type, operator="user", reason="", before=None, after=None):
    _append_audit({
        "id": int(datetime.now().timestamp() * 1000),
        "code": code, "event_type": event_type, "operator": operator,
        "event_time": _now_str(), "reason": reason,
        "before_json": before, "after_json": after,
    })


def _today_orders_count():
    try:
        from db.session import get_db_session
        with get_db_session() as db:
            return db.query(AutoTradeLog).filter(AutoTradeLog.trade_date == date.today()).count()
    except Exception:
        return 0


class GlobalUpdate(BaseModel):
    enabled: Optional[bool] = None
    run_environment: Optional[str] = None


class PauseRequest(BaseModel):
    reason: str = ""


class StockConfigUpdate(BaseModel):
    name: Optional[str] = None
    mode: Optional[str] = None
    run_environment: Optional[str] = None
    authorization_expiry_type: Optional[str] = None
    strategy_id: Optional[str] = None
    strategy_version: Optional[str] = None
    prices: Optional[dict] = None
    risk: Optional[dict] = None
    actions: Optional[dict] = None


class StockEnableRequest(BaseModel):
    operator: str = "user"


@router.get("/api/auto-trade/global")
def api_get_global():
    g = get_global_config()
    g["today_orders"] = _today_orders_count()
    return g


@router.post("/api/auto-trade/global")
def api_update_global(req: GlobalUpdate):
    g = get_global_config()
    before = dict(g)
    if req.enabled is not None:
        g["enabled"] = bool(req.enabled)
    if req.run_environment in VALID_ENVS:
        g["run_environment"] = req.run_environment
    g["updated_at"] = _now_str()
    _save_global_config(g)
    _audit("", "global_update", "user", before=before, after=g)
    return g


@router.post("/api/auto-trade/global/pause")
def api_pause_global(req: PauseRequest):
    g = get_global_config()
    before = dict(g)
    g["paused"] = True
    g["pause_reason"] = req.reason or "人工暂停"
    g["paused_at"] = _now_str()
    g["updated_at"] = _now_str()
    _save_global_config(g)
    _audit("", "global_pause", "user", reason=g["pause_reason"], before=before, after=g)
    return g


@router.post("/api/auto-trade/global/resume")
def api_resume_global():
    g = get_global_config()
    before = dict(g)
    g["paused"] = False
    g["pause_reason"] = ""
    g["paused_at"] = None
    g["updated_at"] = _now_str()
    _save_global_config(g)
    _audit("", "global_resume", "user", before=before, after=g)
    return g


@router.get("/api/auto-trade/stocks")
def api_list_stocks():
    return {"items": get_stock_configs()}


@router.get("/api/auto-trade/stocks/{code}/config")
def api_get_stock(code: str):
    cfg = get_stock_config(code)
    return cfg or _default_stock(code=code)


@router.put("/api/auto-trade/stocks/{code}/config")
def api_update_stock(code: str, req: StockConfigUpdate):
    d = get_stock_configs()
    cfg = d.get(code) or _default_stock(code=code)
    before = dict(cfg)
    if req.name is not None:
        cfg["name"] = req.name
    if req.mode in VALID_MODES:
        cfg["mode"] = req.mode
    if req.run_environment in VALID_ENVS:
        cfg["run_environment"] = req.run_environment
    if req.authorization_expiry_type in ("daily", "persistent"):
        cfg["authorization_expiry_type"] = req.authorization_expiry_type
    if req.strategy_id is not None:
        cfg["strategy_id"] = req.strategy_id
    if req.strategy_version is not None:
        cfg["strategy_version"] = req.strategy_version
    if isinstance(req.prices, dict):
        cfg["prices"] = {**cfg.get("prices", {}), **{k: v for k, v in req.prices.items() if v is not None}}
    if isinstance(req.risk, dict):
        cfg["risk"] = {**cfg.get("risk", {}), **{k: v for k, v in req.risk.items() if v is not None}}
    if isinstance(req.actions, dict):
        cfg["actions"] = {**cfg.get("actions", {}), **req.actions}
    cfg["updated_at"] = _now_str()
    d[code] = cfg
    _save_stock_configs(d)
    _audit(code, "config_update", "user", before=before, after=cfg)
    return cfg


@router.post("/api/auto-trade/stocks/{code}/enable")
def api_enable_stock(code: str, req: StockEnableRequest = None):
    """开启个股自动交易：开启前检查(硬止损/最大仓位/最大亏损/滑点/模式) + 策略快照"""
    d = get_stock_configs()
    cfg = d.get(code) or _default_stock(code=code)
    before = dict(cfg)
    operator = (req.operator if req else "user") or "user"

    missing = []
    if cfg["mode"] not in ("risk_only", "full_auto"):
        missing.append("交易模式未设置（风控托管或全自动）")
    if not cfg["prices"].get("hard_stop_price"):
        missing.append("硬止损价未配置")
    if not cfg["risk"].get("max_position_pct"):
        missing.append("单票最大仓位未配置")
    if not cfg["risk"].get("max_total_loss") and not cfg["risk"].get("max_daily_loss"):
        missing.append("最大亏损未配置")
    if cfg["risk"].get("max_slippage_pct") is None:
        missing.append("最大滑点未配置")
    if missing:
        return {"ok": False, "missing": missing, "message": "开启前检查未通过，请补齐配置"}

    cfg["strategy_snapshot_json"] = json.dumps({
        "strategy_id": cfg["strategy_id"], "strategy_version": cfg["strategy_version"],
        "prices": cfg["prices"], "risk": cfg["risk"], "actions": cfg["actions"],
        "enabled_at": _now_str(), "enabled_by": operator,
    }, ensure_ascii=False)
    cfg["status"] = "MONITORING"
    cfg["status_reason"] = "监控中"
    cfg["enabled_at"] = _now_str()
    cfg["enabled_by"] = operator
    cfg["disabled_at"] = None
    cfg["paused_at"] = None
    cfg["paused_reason"] = ""
    cfg["updated_at"] = _now_str()
    d[code] = cfg
    _save_stock_configs(d)
    _audit(code, "enable", operator, before=before, after=cfg)
    return {"ok": True, "config": cfg}


@router.post("/api/auto-trade/stocks/{code}/disable")
def api_disable_stock(code: str):
    d = get_stock_configs()
    cfg = d.get(code) or _default_stock(code=code)
    before = dict(cfg)
    cfg["mode"] = "off"
    cfg["status"] = "OFF"
    cfg["status_reason"] = "已手动关闭"
    cfg["disabled_at"] = _now_str()
    cfg["disabled_by"] = "user"
    cfg["enabled_at"] = None
    cfg["updated_at"] = _now_str()
    d[code] = cfg
    _save_stock_configs(d)
    _audit(code, "disable", "user", before=before, after=cfg)
    return {"ok": True, "config": cfg}


@router.post("/api/auto-trade/stocks/{code}/pause")
def api_pause_stock(code: str, req: PauseRequest):
    d = get_stock_configs()
    cfg = d.get(code) or _default_stock(code=code)
    before = dict(cfg)
    cfg["status"] = "PAUSED"
    cfg["status_reason"] = req.reason or "手动暂停"
    cfg["paused_at"] = _now_str()
    cfg["paused_reason"] = req.reason or "手动暂停"
    cfg["updated_at"] = _now_str()
    d[code] = cfg
    _save_stock_configs(d)
    _audit(code, "pause", "user", reason=cfg["paused_reason"], before=before, after=cfg)
    return {"ok": True, "config": cfg}


@router.post("/api/auto-trade/stocks/{code}/resume")
def api_resume_stock(code: str):
    d = get_stock_configs()
    cfg = d.get(code) or _default_stock(code=code)
    before = dict(cfg)
    cfg["status"] = "MONITORING"
    cfg["status_reason"] = "监控中"
    cfg["paused_at"] = None
    cfg["paused_reason"] = ""
    cfg["updated_at"] = _now_str()
    d[code] = cfg
    _save_stock_configs(d)
    _audit(code, "resume", "user", before=before, after=cfg)
    return {"ok": True, "config": cfg}


@router.get("/api/auto-trade/audit")
def api_audit(code: str = None, limit: int = Query(50, le=200)):
    logs = _read_json_file(AUDIT_AUTO_TRADE_PATH, [])
    logs = logs if isinstance(logs, list) else []
    if code:
        logs = [l for l in logs if l.get("code") == code]
    return {"items": logs[-limit:][::-1], "count": min(len(logs), limit)}

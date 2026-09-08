"""监控规则引擎 —— 移植自 tickflow-stock-panel (MIT) 的 monitor_rules 设计。

规则模型（JSON 文件存储，backend/data/monitor_rules/*.json）：
  {id, name, type(signal/price), market(a/us/hk), scope(symbols/all),
   symbols[], conditions[{field, op(>,>=,<,<=,==,!=,truth), value}],
   logic(and/or), cooldown_seconds, severity, enabled, message}

评估：对候选池每只股票计算特征快照 → 按规则条件判定 → 命中写入触发记录。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Query, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from api.strategy_lib import compute_features, enrich_features  # noqa: E402

router = APIRouter()
logger = logging.getLogger(__name__)

DATA_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / ".." / "data" / "monitor_rules"
DATA_DIR = DATA_DIR.resolve()
LOG_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / ".." / "data" / "monitor_logs"
LOG_DIR = LOG_DIR.resolve()

ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
OPS = {">", ">=", "<", "<=", "==", "!="}
LOGICS = {"and", "or"}
SEVERITIES = {"info", "warn", "critical"}
RULE_MARKETS = {"a", "hk", "us"}


def _normalize_rule_market(value: str) -> str:
    normalized = str(value or "a").strip().lower()
    if normalized not in RULE_MARKETS:
        raise HTTPException(status_code=400, detail="market 必须是 a、hk 或 us")
    return normalized

# 条件字段白名单（A股/港股/美股通用，来自特征快照）
ALLOWED_FIELDS = {
    "price": "现价", "change_pct": "涨跌幅(小数)", "change_pct_pct": "涨跌幅(%)",
    "volume": "成交量", "vol_ratio_5d": "量比(5日)", "rsi_14": "RSI(14)",
    "momentum_20d": "20日动量(小数)", "annual_vol_20d": "年化波动率",
    "ma20_bias": "价/MA20偏离(小数)", "ma60_bias": "价/MA60偏离(小数)",
    "amplitude": "日振幅(小数)", "consecutive_limit_ups": "连板数(A股)",
    "near_limit_up_pct": "距涨停%(A股)", "limit_up": "当日涨停(A股, truth)",
    "macd_golden": "MACD金叉(truth)", "breakout_ma20": "突破MA20(truth)",
}


# ── 持久化 ────────────────────────────────────────────────

def _rules_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def _logs_dir() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR


def load_all(market: str = "") -> list:
    out = []
    for f in sorted(_rules_dir().glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            r = normalize(r)
            if not market or r.get("market") == market:
                out.append(r)
        except Exception as e:
            logger.warning("monitor rule load failed %s: %s", f.name, e)
    return out


def save_one(rule: dict) -> None:
    validate(rule)
    r = normalize(rule)
    p = _rules_dir() / f"{r['id']}.json"
    p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_one(rule_id: str) -> bool:
    p = _rules_dir() / f"{rule_id}.json"
    if p.exists():
        p.unlink()
        return True
    return False


# ── 校验 ──────────────────────────────────────────────────

def validate(rule: dict) -> None:
    rid = rule.get("id", "")
    if not isinstance(rid, str) or not ID_RE.match(rid):
        raise ValueError(f"规则 id 非法（仅小写字母数字下划线，1-40字符）: {rid!r}")
    if not isinstance(rule.get("name"), str) or not rule["name"].strip():
        raise ValueError("规则 name 不能为空")
    if rule.get("market") not in ("a", "hk", "us"):
        raise ValueError("market 必须是 a(A股)、hk(港股) 或 us(美股)")
    if rule.get("type") not in ("signal", "price"):
        raise ValueError("type 必须是 signal 或 price")
    conds = rule.get("conditions")
    if not isinstance(conds, list) or len(conds) == 0:
        raise ValueError("conditions 不能为空")
    if len(conds) > 8:
        raise ValueError("conditions 最多 8 条")
    if rule.get("logic", "and") not in LOGICS:
        raise ValueError(f"logic 必须是 {LOGICS} 之一")
    for i, c in enumerate(conds):
        if not isinstance(c, dict):
            raise ValueError(f"第 {i+1} 个条件格式错误")
        field = c.get("field", "")
        op = c.get("op", "")
        if op == "truth":
            if field not in ("limit_up", "macd_golden", "breakout_ma20"):
                raise ValueError(f"第 {i+1} 个条件: op=truth 时 field 必须是布尔字段之一")
        elif op in OPS:
            if field not in ALLOWED_FIELDS:
                raise ValueError(f"第 {i+1} 个条件: 字段 {field!r} 不在白名单")
            if not isinstance(c.get("value"), (int, float)):
                raise ValueError(f"第 {i+1} 个条件: value 必须是数字")
        else:
            raise ValueError(f"第 {i+1} 个条件: op {op!r} 非法（应为 truth 或 {OPS}）")
    if rule.get("scope", "symbols") not in ("symbols", "all"):
        raise ValueError("scope 必须是 symbols 或 all")
    if rule.get("scope") == "symbols":
        syms = rule.get("symbols")
        if not isinstance(syms, list) or len(syms) == 0:
            raise ValueError("scope=symbols 时 symbols 不能为空")
    if rule.get("severity", "info") not in SEVERITIES:
        raise ValueError(f"severity 必须是 {SEVERITIES} 之一")
    cd = rule.get("cooldown_seconds", 3600)
    if not isinstance(cd, (int, float)) or cd < 0:
        raise ValueError("cooldown_seconds 必须是非负整数")
    channels = rule.get("webhook_channels")
    if channels is not None:
        if not isinstance(channels, list) or any(c not in ("feishu",) for c in channels):
            raise ValueError("webhook_channels 只能是 ['feishu'] 的子集")


def normalize(rule: dict) -> dict:
    r = dict(rule)
    r.setdefault("enabled", True)
    r.setdefault("market", "a")
    r.setdefault("type", "price")
    r.setdefault("scope", "symbols")
    r.setdefault("symbols", [])
    r.setdefault("conditions", [])
    r.setdefault("logic", "and")
    r.setdefault("cooldown_seconds", 3600)
    r.setdefault("severity", "info")
    r.setdefault("message", "")
    r.setdefault("webhook_channels", [])
    r.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    return r


# ── 评估引擎 ──────────────────────────────────────────────

def _cond_ok(feats: dict, cond: dict) -> bool:
    field = cond.get("field", "")
    op = cond.get("op", "")
    if op == "truth":
        return bool(feats.get(field))
    val = feats.get(field)
    if val is None:
        return False
    target = cond.get("value")
    try:
        v, t = float(val), float(target)
    except (TypeError, ValueError):
        return False
    if op == ">":
        return v > t
    if op == ">=":
        return v >= t
    if op == "<":
        return v < t
    if op == "<=":
        return v <= t
    if op == "==":
        return abs(v - t) < 1e-9
    if op == "!=":
        return abs(v - t) >= 1e-9
    return False


def evaluate_rule(rule: dict, feats: dict, symbol: str, name: str) -> bool:
    """对单只股票的特征快照判定规则是否命中。"""
    conds = rule.get("conditions", [])
    if not conds:
        return False
    results = [_cond_ok(feats, c) for c in conds]
    return all(results) if rule.get("logic", "and") == "and" else any(results)


def _log_trigger(rule: dict, symbol: str, name: str, feats: dict) -> None:
    """写入触发记录（append 到当日 JSON 文件，含冷却时间检查）。"""
    try:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        log_file = _logs_dir() / f"{rule['id']}.{today}.jsonl"
        entry = {
            "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
            "rule_id": rule["id"], "rule_name": rule["name"],
            "market": rule.get("market"), "symbol": symbol, "name": name,
            "price": round(float(feats.get("price") or 0), 2),
            "change_pct": round((feats.get("change_pct") or 0) * 100, 2),
            "feats": {k: round(float(v), 3) if isinstance(v, (int, float)) else v
                      for k, v in feats.items() if k in ALLOWED_FIELDS},
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("monitor log failed: %s", e)


# 冷却记录: {rule_id: {symbol: last_ts}}
_cooldown: dict = {}


def _cooldown_ok(rule_id: str, symbol: str, cd_sec: float) -> bool:
    now = time.time()
    last = _cooldown.get(rule_id, {}).get(symbol, 0)
    if now - last < cd_sec:
        return False
    _cooldown.setdefault(rule_id, {})[symbol] = now
    return True


async def _feats_for(market: str, symbol: str) -> Optional[dict]:
    """取单只股票特征快照（行情 + K线）。"""
    try:
        if market == "a":
            from api.bs_screener.core import _fetch_kline_cached, _get_quote
            klines = await _fetch_kline_cached(symbol, 120)
            quote = await _get_quote(symbol)
            if not klines or len(klines) < 30:
                return None
            f = enrich_features(klines, symbol)
            if quote:
                f["price"] = quote["price"]
            else:
                f["price"] = f.get("close")
        else:
            # 港美股统一优先读取 market_quant 已落库的日线，避免监控页面
            # 打开/检查时再次请求外部行情。数据库不足时不伪造结果，直接跳过。
            from db.session import get_db_session
            from market_quant.identity import normalize_market, normalize_symbol
            from market_quant.repository import MarketDailyBar, MarketInstrument

            db_market = normalize_market(market)
            db_symbol = normalize_symbol(db_market, symbol)
            with get_db_session() as db:
                rows = db.query(MarketDailyBar).filter(
                    MarketDailyBar.market == db_market,
                    MarketDailyBar.symbol == db_symbol,
                    MarketDailyBar.quality_status == "VALID",
                ).order_by(MarketDailyBar.trade_date.desc()).limit(120).all()
                instrument = db.query(MarketInstrument).filter_by(
                    market=db_market, symbol=db_symbol
                ).first()
            klines = [{
                "date": row.trade_date.isoformat(),
                "open": float(row.open or 0),
                "high": float(row.high or 0),
                "low": float(row.low or 0),
                "close": float(row.close or 0),
                "volume": float(row.volume or 0),
            } for row in reversed(rows)]
            if not klines or len(klines) < 30:
                return None
            # 数字港股代码不能被特征库误识别为 A 股涨停代码。
            f = enrich_features(klines, f"${db_market}:{db_symbol}")
            f["price"] = float(instrument.price) if instrument and instrument.price is not None else f.get("close")
        f["change_pct_pct"] = (f.get("change_pct") or 0) * 100
        if f.get("ma20"):
            f["ma20_bias"] = f["price"] / f["ma20"] - 1
        if f.get("ma60"):
            f["ma60_bias"] = f["price"] / f["ma60"] - 1
        return f
    except Exception:
        return None


async def _candidate_pool(market: str, limit: int = 80) -> list:
    """候选池：scope=all 时扫描。"""
    try:
        if market == "a":
            from db.session import get_db_session
            from db.models import StockFlow
            from sqlalchemy import func as sql_func
            with get_db_session() as db:
                latest = db.query(sql_func.max(StockFlow.id).label("max_id")).group_by(StockFlow.ts_code).subquery()
                rows = db.query(StockFlow).join(
                    latest, StockFlow.id == latest.c.max_id
                ).filter(StockFlow.main_force_inflow > 0).order_by(
                    StockFlow.main_force_inflow.desc()).limit(limit).all()
                return [{"code": r.ts_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", ""),
                         "name": r.name} for r in rows]
        else:
            from db.session import get_db_session
            from market_quant.universe import get_members
            from market_quant.repository import MarketInstrument

            db_market = "US" if market == "us" else "HK"
            members = list(get_members(db_market, "CORE"))[:limit]
            with get_db_session() as db:
                rows = db.query(MarketInstrument).filter(
                    MarketInstrument.market == db_market,
                    MarketInstrument.symbol.in_(members),
                ).all()
            names = {row.symbol: (row.name or row.symbol) for row in rows}
            return [{"code": symbol, "name": names.get(symbol, symbol)} for symbol in members]
    except Exception:
        return []


@router.post("/api/monitor-rules/check")
async def check_rules(market: str = Query("a"), symbols: str = Query("", description="只检查指定代码（逗号分隔）")):
    """评估全部启用规则，返回命中结果。"""
    market = _normalize_rule_market(market)
    rules = [r for r in load_all(market) if r.get("enabled")]
    if not rules:
        return {"ok": True, "data": {"checked": 0, "triggers": []}, "error": None}

    # 汇总需要扫描的标的
    needed: dict = {}
    for r in rules:
        if r.get("scope") == "symbols":
            for s in r.get("symbols", []):
                needed.setdefault(s, r["market"])
        else:
            pool = await _candidate_pool(r["market"])
            for p in pool:
                needed.setdefault(p["code"], r["market"])

    if symbols.strip():
        for s in symbols.split(","):
            s = s.strip().upper()
            if s:
                needed[s] = market

    semaphore = asyncio.Semaphore(10)

    async def get_feats(code, mkt):
        async with semaphore:
            return await _feats_for(mkt, code)

    feats_map = {}
    results = await asyncio.gather(
        *[get_feats(c, m) for c, m in needed.items()], return_exceptions=True)
    for (code, _m), r in zip(needed.items(), results):
        if r and not isinstance(r, Exception):
            feats_map[code] = r

    triggers = []
    for r in rules:
        scope_symbols = r.get("symbols", []) if r.get("scope") == "symbols" else list(needed.keys())
        for sym in scope_symbols:
            f = feats_map.get(sym)
            if not f:
                continue
            try:
                if evaluate_rule(r, f, sym, sym):
                    cd = float(r.get("cooldown_seconds", 3600))
                    if _cooldown_ok(r["id"], sym, cd):
                        _log_trigger(r, sym, sym, f)
                        try:
                            from services.feishu_notify import push_rule_trigger
                            push_rule_trigger(
                                r, sym, sym, f,
                                price=round(float(f.get("price") or 0), 2),
                                change_pct=round((f.get("change_pct") or 0) * 100, 2),
                            )
                        except Exception:
                            pass
                        triggers.append({
                            "rule_id": r["id"], "rule_name": r["name"],
                            "severity": r.get("severity", "info"),
                            "market": r.get("market"), "symbol": sym,
                            "price": round(float(f.get("price") or 0), 2),
                            "change_pct": round((f.get("change_pct") or 0) * 100, 2),
                            "feats": {k: round(float(f[k]), 3) if isinstance(f.get(k), (int, float)) else f[k]
                                      for k in ALLOWED_FIELDS if f.get(k) is not None},
                        })
            except Exception:
                continue

    return {"ok": True, "data": {"checked": len(needed), "rules": len(rules), "triggers": triggers}, "error": None}


@router.get("/api/monitor-rules/logs")
def rule_logs(
    rule_id: str = Query(""),
    market: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
):
    """最近触发记录（跨规则、跨日期合并，按时间倒序）。"""
    try:
        if market:
            market = _normalize_rule_market(market)
        entries = []
        for f in sorted(_logs_dir().glob("*.jsonl")):
            if rule_id and not f.name.startswith(f"{rule_id}."):
                continue
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
        if market:
            entries = [entry for entry in entries if entry.get("market") == market]
        entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
        return {"ok": True, "data": entries[:limit], "error": None}
    except Exception as e:
        return {"ok": False, "data": [], "error": str(e)}


# ── CRUD API ──────────────────────────────────────────────

class RuleBody(BaseModel):
    rule: dict


@router.get("/api/monitor-rules/list")
def rules_list(market: str = Query("a")):
    try:
        market = _normalize_rule_market(market)
        return {"ok": True, "data": load_all(market), "error": None}
    except Exception as e:
        return {"ok": False, "data": [], "error": str(e)}


@router.post("/api/monitor-rules/save")
def rule_save(body: RuleBody):
    try:
        save_one(body.rule)
        return {"ok": True, "data": body.rule.get("id"), "error": None}
    except ValueError as e:
        return {"ok": False, "data": None, "error": str(e)}
    except Exception as e:
        return {"ok": False, "data": None, "error": f"保存失败: {e}"}


@router.delete("/api/monitor-rules/{rule_id}")
def rule_delete(rule_id: str):
    try:
        if not delete_one(rule_id):
            raise HTTPException(status_code=404, detail="规则不存在")
        return {"ok": True, "data": rule_id, "error": None}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "data": None, "error": str(e)}


@router.get("/api/monitor-rules/feishu-config")
def feishu_config():
    """飞书推送配置状态（不返回 secret，只返回是否已配置）。"""
    try:
        from services.feishu_notify import get_feishu_config
        cfg = get_feishu_config()
        return {"ok": True, "data": {"configured": bool(cfg["url"]), "has_secret": bool(cfg["secret"])}, "error": None}
    except Exception as e:
        return {"ok": False, "data": None, "error": str(e)}


@router.post("/api/monitor-rules/test-push")
async def test_push():
    """发送一条测试消息到飞书，验证 Webhook 配置（同步等待结果）。"""
    try:
        from services.feishu_notify import get_feishu_config, send_feishu
        cfg = get_feishu_config()
        if not cfg["url"]:
            return {"ok": False, "data": None, "error": "未配置 FEISHU_WEBHOOK_URL（飞书群自定义机器人 Webhook 地址）"}
        ok = await asyncio.to_thread(
            send_feishu, cfg["url"], "✅ AIROBOT 测试消息",
            "监控规则飞书推送通道配置成功\n发送时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            cfg["secret"],
        )
        if ok:
            return {"ok": True, "data": "已发送", "error": None}
        return {"ok": False, "data": None, "error": "推送失败（请检查 Webhook 地址/签名，详见后端日志）"}
    except Exception as e:
        return {"ok": False, "data": None, "error": f"测试推送异常: {e}"}

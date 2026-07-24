"""港股/美股策略扫描 API
- GET /api/hk-strategy/list              获取所有策略
- POST /api/hk-strategy/strategies       保存策略
- DELETE /api/hk-strategy/strategies/{id}  删除策略
- POST /api/hk-strategy/scan             执行策略扫描

策略维度（基于 watchlist-enhanced 已有的技术指标）：
- signal_type: B（买入信号）/ S（卖出信号）
- change_pct: 当日涨跌幅
- deviation: 偏离 MA20 度数
- rsi: RSI(14)
- change5d / change20d: 区间涨跌幅
- volume_filter: 成交量放大
- ma20_support: MA20 支撑（价格在 MA20 ±2% 内）
- trend: 趋势方向（多头排列/空头排列）
"""
import logging
from datetime import datetime
from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db.session import get_db_session
from db.models import BSStrategy

from .global_market import DEFAULT_WATCHLIST, _fetch_enhanced_for_stock
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── 策略规则定义（可扩展）─────────────────────────────────────────────────────
# 每条规则是一个字典：{key, name, desc, test(item) -> bool}
def _rule_deviation_revert(item):
    """回踩 MA20：价格在 MA20 ±2% 内（潜在反弹/反转点）"""
    d = item.get("deviation")
    return d is not None and abs(d) <= 2


def _rule_rsi_oversold(item):
    """RSI 超卖：RSI(14) ≤ 30"""
    r = item.get("rsi")
    return r is not None and r <= 30


def _rule_rsi_overbought(item):
    """RSI 超买：RSI(14) ≥ 70"""
    r = item.get("rsi")
    return r is not None and r >= 70


def _rule_bull_align(item):
    """多头排列：MA5 > MA10 > MA20 且价格 > MA5"""
    ma5, ma10, ma20, price = item.get("ma5"), item.get("ma10"), item.get("ma20"), item.get("price")
    if not all(v is not None for v in [ma5, ma10, ma20, price]):
        return False
    return ma5 > ma10 > ma20 and price > ma5


def _rule_bear_align(item):
    """空头排列：MA5 < MA10 < MA20 且价格 < MA5"""
    ma5, ma10, ma20, price = item.get("ma5"), item.get("ma10"), item.get("ma20"), item.get("price")
    if not all(v is not None for v in [ma5, ma10, ma20, price]):
        return False
    return ma5 < ma10 < ma20 and price < ma5


def _rule_5d_pullback(item):
    """5 日回调：5 日跌幅 ≤ -3%（超跌反弹机会）"""
    c = item.get("change5d")
    return c is not None and c <= -3


def _rule_5d_breakout(item):
    """5 日突破：5 日涨幅 ≥ 5%（动量延续）"""
    c = item.get("change5d")
    return c is not None and c >= 5


def _rule_20d_uptrend(item):
    """20 日上行：20 日涨幅 ≥ 8%"""
    c = item.get("change20d")
    return c is not None and c >= 8


def _rule_20d_downtrend(item):
    """20 日下行：20 日跌幅 ≤ -8%"""
    c = item.get("change20d")
    return c is not None and c <= -8


def _rule_volume_active(item):
    """成交活跃：成交量 > 100M（流动性充足）"""
    v = item.get("volume")
    return v is not None and v >= 100_000_000


# 策略规则注册表
RULES = [
    {"key": "deviation_revert", "name": "回踩MA20", "desc": "价格在 MA20 ±2% 内（潜在反弹/反转点）", "test": _rule_deviation_revert, "signal": "B"},
    {"key": "rsi_oversold", "name": "RSI超卖", "desc": "RSI(14) ≤ 30，超卖反弹机会", "test": _rule_rsi_oversold, "signal": "B"},
    {"key": "rsi_overbought", "name": "RSI超买", "desc": "RSI(14) ≥ 70，超买回调风险", "test": _rule_rsi_overbought, "signal": "S"},
    {"key": "bull_align", "name": "多头排列", "desc": "MA5 > MA10 > MA20 且价格 > MA5", "test": _rule_bull_align, "signal": "B"},
    {"key": "bear_align", "name": "空头排列", "desc": "MA5 < MA10 < MA20 且价格 < MA5", "test": _rule_bear_align, "signal": "S"},
    {"key": "5d_pullback", "name": "5日超跌", "desc": "5 日跌幅 ≤ -3%，超跌反弹机会", "test": _rule_5d_pullback, "signal": "B"},
    {"key": "5d_breakout", "name": "5日突破", "desc": "5 日涨幅 ≥ 5%，动量延续", "test": _rule_5d_breakout, "signal": "B"},
    {"key": "20d_uptrend", "name": "20日上行", "desc": "20 日涨幅 ≥ 8%", "test": _rule_20d_uptrend, "signal": "B"},
    {"key": "20d_downtrend", "name": "20日下行", "desc": "20 日跌幅 ≤ -8%", "test": _rule_20d_downtrend, "signal": "S"},
    {"key": "volume_active", "name": "成交活跃", "desc": "成交量 ≥ 100M，流动性充足", "test": _rule_volume_active, "signal": "B"},
]


def _scan_item(item: dict, enabled_rules: list[str], signal_type: str = "B") -> dict:
    """对单只股票执行策略扫描，返回命中规则列表"""
    if not item or item.get("price") is None:
        return {"code": item.get("code", "?"), "name": item.get("name", "?"), "hits": [], "signal": "—"}
    hits = []
    for rule in RULES:
        if rule["key"] not in enabled_rules:
            continue
        if signal_type == "B" and rule["signal"] == "S":
            continue
        if signal_type == "S" and rule["signal"] == "B":
            continue
        try:
            if rule["test"](item):
                hits.append({"key": rule["key"], "name": rule["name"], "signal": rule["signal"]})
        except Exception as e:
            logger.warning(f"策略规则 {rule['key']} 执行失败: {e}")
    # 综合信号：所有命中规则的 signal 投票
    if not hits:
        signal = "—"
    else:
        b_count = sum(1 for h in hits if h["signal"] == "B")
        s_count = sum(1 for h in hits if h["signal"] == "S")
        if b_count > s_count:
            signal = "B"
        elif s_count > b_count:
            signal = "S"
        else:
            signal = "—"
    return {"code": item["code"], "name": item["name"], "hits": hits, "signal": signal, **{k: v for k, v in item.items() if k not in ("code", "name")}}


class ScanRequest(BaseModel):
    market: str = "HK"
    rules: list[str] = []
    signal_type: str = "B"  # B / S / ALL


@router.get("/api/hk-strategy/rules")
def list_rules():
    """返回所有可用策略规则"""
    return {"rules": [{"key": r["key"], "name": r["name"], "desc": r["desc"], "signal": r["signal"]} for r in RULES]}


@router.post("/api/hk-strategy/scan")
def scan_strategies(req: ScanRequest):
    """执行策略扫描：基于 watchlist-enhanced 数据 + 启用的规则"""
    market = req.market.upper()
    if market not in ("HK", "US"):
        return {"market": market, "items": [], "error": "仅支持 HK / US"}
    watchlist = DEFAULT_WATCHLIST.get(market, [])
    if not watchlist:
        return {"market": market, "items": [], "total": 0, "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S")}

    # 并行拉取所有股票的技术指标数据（复用 global_market 的函数）
    results = [None] * len(watchlist)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch_enhanced_for_stock, market, s): i for i, s in enumerate(watchlist)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                results[idx] = {"code": watchlist[idx]["code"], "name": watchlist[idx]["name"], "price": None, "error": str(e)}

    # 执行策略扫描
    enabled_rules = req.rules if req.rules else [r["key"] for r in RULES]
    scanned = [_scan_item(item, enabled_rules, req.signal_type) for item in results]
    # 只返回有命中的股票
    hits_only = [s for s in scanned if s.get("hits")]

    return {
        "market": market,
        "items": hits_only,
        "total": len(hits_only),
        "scanned": len(scanned),
        "rules": enabled_rules,
        "signal_type": req.signal_type,
        "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }

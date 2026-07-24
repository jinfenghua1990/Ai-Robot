"""
数据契约适配层：把各策略的 result.json 统一成前端期望的格式。

不同策略的 JSON 结构不同，本模块负责适配：
  - 大部分：data.stocks
  - 青龙白虎：data.qinglong + data.baihu
  - 智能评分：results（顶层，不在 data 下）
  - 行业轮动：data.stocks + sectors

对外统一返回：
  {
    "robot": "robot-7",
    "name": "青龙白虎",
    "trade_date": "...",
    "count": N,
    "data": {"stocks": [...], "extra": {...可选}},
  }
"""
from __future__ import annotations
import json
import os
from typing import Any
from pathlib import Path

from api.hermes_native.config import ROBOT_STRATEGY_MAP, ROBOT_ID_TO_KEY


# ── 字段映射：把各 robot 的字段统一到前端期望的字段名 ──────────────
# 前端 useBacktestData.js 期望的字段：symbol/code, name, score,
#   change_pct, 20day_gain, deviation, rsi, vol_ratio, ma20/ma10/ma5, close
# 不同 robot 用的字段名不同，这里做归一化。

def _normalize_stock(raw: dict[str, Any]) -> dict[str, Any]:
    """把单只股票的字段统一成前端期望格式"""
    if not isinstance(raw, dict):
        return {}

    # 提取 code/symbol
    code = raw.get("symbol") or raw.get("code") or raw.get("ts_code", "")

    # 提取名称
    name = raw.get("name") or raw.get("stock_name", "")

    # 提取百分比
    change_pct = (
        raw.get("change_pct")
        or raw.get("pct_chg")
        or raw.get("pct")
        or 0
    )

    # 提取 RSI
    rsi = raw.get("rsi", 0)

    # 提取量比
    vol_ratio = raw.get("vol_ratio", 0)

    # 提取 close
    close = raw.get("close") or raw.get("current_price") or raw.get("price", 0)

    # 提取均线
    ma5 = raw.get("ma5", 0)
    ma10 = raw.get("ma10", 0)
    ma20 = raw.get("ma20", 0)

    # 提取 20 日涨幅
    gain_20d = raw.get("20day_gain") or raw.get("change_20d") or 0

    # 提取 deviation
    deviation = raw.get("deviation", 0)

    # 提取 score
    score = raw.get("score", 0)

    # 提取 industry/theme
    industry = raw.get("industry") or raw.get("theme") or ""

    # 保留原始未识别字段
    extras = {k: v for k, v in raw.items() if k not in {
        "symbol", "code", "ts_code", "name", "stock_name",
        "change_pct", "pct_chg", "pct", "rsi", "vol_ratio",
        "close", "current_price", "price",
        "ma5", "ma10", "ma20",
        "20day_gain", "change_20d", "deviation", "score",
        "industry", "theme", "indicators",
    }}

    # 处理嵌套 indicators
    if "indicators" in raw and isinstance(raw["indicators"], dict):
        ind = raw["indicators"]
        if not rsi: rsi = ind.get("rsi", 0)
        if not vol_ratio: vol_ratio = ind.get("vol_ratio", 0)
        if not ma5: ma5 = ind.get("ma5", 0)
        if not ma10: ma10 = ind.get("ma10", 0)
        if not ma20: ma20 = ind.get("ma20", 0)
        if not gain_20d: gain_20d = ind.get("change_20d", 0)
        if not change_pct: change_pct = ind.get("change_pct", 0)
        if not close: close = ind.get("current_price", 0)
        deviation = ind.get("deviation", deviation)

    return {
        "symbol": code,
        "code": code,
        "name": name,
        "change_pct": round(float(change_pct or 0), 2),
        "rsi": round(float(rsi or 0), 1),
        "vol_ratio": round(float(vol_ratio or 0), 1),
        "close": round(float(close or 0), 2),
        "ma5": round(float(ma5 or 0), 2),
        "ma10": round(float(ma10 or 0), 2),
        "ma20": round(float(ma20 or 0), 2),
        "20day_gain": round(float(gain_20d or 0), 2),
        "deviation": round(float(deviation or 0), 2),
        "score": score,
        "industry": industry,
        "_raw": extras,  # 保留原始数据供调试
    }


# ── 适配各 robot 的特殊结构 ─────────────────────────────────────────

def _adapt_qinglong(data: dict[str, Any]) -> list[dict[str, Any]]:
    """青龙白虎 - 合并 data.qinglong + data.baihu + data.stocks 后备"""
    inner = data.get("data", {})
    ql = inner.get("qinglong", []) or []
    bh = inner.get("baihu", []) or []
    st = inner.get("stocks", []) or []
    merged = []
    for s in ql:
        s2 = dict(s)
        s2["strategy"] = "青龙"
        merged.append(s2)
    for s in bh:
        s2 = dict(s)
        s2["strategy"] = "白虎"
        merged.append(s2)
    # 后备：如果 ql+bh 都为空但 stocks 有数据，直接使用 stocks
    if not merged and st:
        return [_normalize_stock(s) for s in st]
    return [_normalize_stock(s) for s in merged]


def _adapt_score(data: dict[str, Any]) -> list[dict[str, Any]]:
    """智能评分 - 顶层 results 字段"""
    results = data.get("results", []) or []
    return [_normalize_stock(s) for s in results]


def _adapt_default(data: dict[str, Any]) -> list[dict[str, Any]]:
    """默认：data.stocks"""
    inner = data.get("data", {})
    if isinstance(inner, dict):
        stocks = inner.get("stocks", []) or []
    else:
        stocks = []
    return [_normalize_stock(s) for s in stocks]


_ADAPTERS = {
    "qinglong": _adapt_qinglong,
    "score": _adapt_score,
}


def load_robot_result(strategy_key: str) -> dict[str, Any]:
    """读取并适配指定策略的信号结果（始终读取日常信号文件，不回测数据）"""
    info = ROBOT_STRATEGY_MAP.get(strategy_key)
    if not info:
        return {"error": f"unknown strategy: {strategy_key}", "stocks": []}

    current_path = Path(info["path"])

    raw: dict[str, Any] = {}
    if current_path.exists():
        try:
            with open(current_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}

    # 如果没有数据文件，尝试用白虎信号数据做后备
    if not raw and strategy_key != "baihu":
        baihu_info = ROBOT_STRATEGY_MAP.get("baihu")
        if baihu_info:
            fallback_path = Path(baihu_info["path"])
            if fallback_path.exists():
                try:
                    with open(fallback_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    # 标记为后备数据
                    raw["_fallback"] = True
                except Exception:
                    raw = {}

    if not raw:
        return {
            "robot": info["id"],
            "name": info["name"],
            "trade_date": "",
            "count": 0,
            "data": {"stocks": []},
            "info": "no data file",
        }

    # 选择适配器（后备数据用默认适配器）
    if raw.get("_fallback"):
        adapter = _adapt_default
    else:
        adapter = _ADAPTERS.get(strategy_key, _adapt_default)
    stocks = adapter(raw)

    # 提取 trade_date（多个 robot 字段名不同）
    trade_date = (
        raw.get("trade_date")
        or (raw.get("generated_at", "")[:10] if raw.get("generated_at") else "")
        or ""
    )

    # 提取 sector 信息（robot-14 专属）
    extra = {}
    if strategy_key == "sector_rotate" and "sectors" in raw.get("data", {}):
        extra["sectors"] = raw["data"]["sectors"]

    result = {
        "robot": info["id"],
        "name": info["name"],
        "trade_date": trade_date,
        "count": len(stocks),
        "data": {"stocks": stocks, **extra},
    }

    # 保留原 raw 的关键顶层字段
    for k in ("strategy", "factors", "features", "generated_at", "params", "stock_filter_key", "stock_filter_label", "_fallback"):
        if k in raw:
            result[k] = raw[k]

    # 保留回测指标（来自 save_result 的 data 层，如 win_rate, sharpe 等）
    raw_data = raw.get("data")
    if isinstance(raw_data, dict):
        for bk in ("total_signals", "win_rate", "avg_return", "max_drawdown", "sharpe", "date_range", "period", "total_stocks"):
            if bk in raw_data:
                result["data"][bk] = raw_data[bk]

    return result

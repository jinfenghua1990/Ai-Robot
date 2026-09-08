"""关键价位计算 API —— 移植自 tickflow-stock-panel (MIT) 的 indicators/levels.py 设计。

纯 Python 实现（无 polars 依赖），输入 OHLCV 日K列表，输出 11 类价位点：
  sr(筹码分布) / pivot(枢轴点) / extreme(前高前低) / boll(布林带) /
  keltner_s/m/l / atr_stop / gap(缺口) / fib(斐波那契) / round(整数关口)

每个点位: {value, label, type, side(resistance/support/neutral), strength, rank?}
"""
from __future__ import annotations

import logging
import math
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# 价位分组 → 中文标签
LEVEL_TYPES = {
    "sr": "压力支撑",
    "pivot": "枢轴点",
    "extreme": "前高前低",
    "boll": "布林带",
    "keltner_s": "Keltner短期",
    "keltner_m": "Keltner中期",
    "keltner_l": "Keltner长期",
    "atr_stop": "ATR波动通道",
    "gap": "缺口位",
    "fib": "斐波那契",
    "round": "整数关口",
}


# ================================================================
# 基础工具
# ================================================================

def _ok(v: Any) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0


def _side(level: float, close: float) -> str:
    if level > close * 1.001:
        return "resistance"
    if level < close * 0.999:
        return "support"
    return "neutral"


def _aggregate_levels(values: List[float], tol: float) -> List[float]:
    if not values:
        return []
    values = sorted(values)
    out: List[float] = [values[0]]
    for v in values[1:]:
        if abs(v - out[-1]) / out[-1] <= tol:
            out[-1] = v
        else:
            out.append(v)
    return out


def _sma(values: List[float], window: int) -> Optional[float]:
    """末位 SMA。返回 None 表示数据不足。"""
    if len(values) < window or window <= 0:
        return None
    return sum(values[-window:]) / window


def _sma_series(values: List[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= window:
            s -= values[i - window]
        if i >= window - 1:
            out.append(s / window)
        else:
            out.append(None)
    return out


def _atr_14(highs: List[float], lows: List[float], closes: List[float]) -> Optional[float]:
    """末位 ATR(14) —— Wilder 平滑。"""
    n = len(closes)
    if n < 15:
        return None
    trs = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    # Wilder: 首值 SMA14，之后平滑
    atr = sum(trs[:14]) / 14.0
    for i in range(14, len(trs)):
        atr = (atr * 13 + trs[i]) / 14.0
    return atr


def _cols(klines: List[dict]) -> dict:
    """从 klines 提取列数组。"""
    return {
        "date": [k.get("date") for k in klines],
        "open": [float(k.get("open") or 0) for k in klines],
        "high": [float(k.get("high") or 0) for k in klines],
        "low": [float(k.get("low") or 0) for k in klines],
        "close": [float(k.get("close") or 0) for k in klines],
        "volume": [float(k.get("volume") or 0) for k in klines],
        "turnover_rate": [float(k["turnover_rate"]) if k.get("turnover_rate") is not None else None for k in klines],
    }


# ================================================================
# 1. 压力位/支撑位 —— 筹码分布（换手率衰减模型）
# ================================================================

def _support_resistance(klines: List[dict], bins: int = 40) -> List[dict]:
    """筹码分布（换手率衰减）：当日筹码 = 前日筹码 × (1-换手率) + 当日新增分摊。"""
    if len(klines) < 20:
        return []
    cols = _cols(klines)
    highs, lows, vols, closes = cols["high"], cols["low"], cols["volume"], cols["close"]

    hi = max(highs)
    lo = min(lows)
    if not (hi > lo > 0):
        return []

    n = len(closes)
    step = (hi - lo) / bins
    edges = [lo + i * step for i in range(bins + 1)]
    turnovers = cols["turnover_rate"]

    chips = [0.0] * bins
    for i in range(n):
        t = float(turnovers[i]) if turnovers[i] is not None else 0.0
        decay = 1.0 - max(0.0, min(t, 100.0)) / 100.0
        if decay < 1.0:
            for k in range(bins):
                chips[k] *= decay
        v = vols[i] or 0
        if v > 0:
            k_low = min(int((lows[i] - lo) / step), bins - 1)
            k_high = min(int((highs[i] - lo) / step), bins - 1)
            if k_low > k_high:
                k_low, k_high = k_high, k_low
            if k_high < 0 or k_low >= bins:
                continue
            k_low = max(k_low, 0)
            k_high = min(k_high, bins - 1)
            share = v / (k_high - k_low + 1)
            for k in range(k_low, k_high + 1):
                chips[k] += share

    bin_ids = [k for k in range(bins) if chips[k] > 0]
    if not bin_ids:
        return []
    vals = [chips[k] for k in bin_ids]
    mean_val = sum(vals) / len(vals) if vals else 0

    def bin_mid(bid: int) -> float:
        return (edges[bid] + edges[bid + 1]) / 2

    close = closes[-1]
    out: List[dict] = []
    poc_pos = max(range(len(vals)), key=lambda i: vals[i])
    poc_mid = bin_mid(bin_ids[poc_pos])
    out.append({"value": round(poc_mid, 2), "label": "成交密集区(POC)",
                "type": "sr", "side": _side(poc_mid, close), "strength": "strong"})
    candidates = [(i, v) for i, v in enumerate(vals) if v > mean_val and i != poc_pos]
    candidates.sort(key=lambda x: x[1], reverse=True)
    for i, _v in candidates[:2]:
        mid = bin_mid(bin_ids[i])
        out.append({"value": round(mid, 2), "label": "成交密集区",
                    "type": "sr", "side": _side(mid, close), "strength": "medium"})
    return out


# ================================================================
# 2. 枢轴点 Pivot
# ================================================================

def _pivot_points(klines: List[dict]) -> List[dict]:
    if not klines:
        return []
    last = klines[-1]
    h = float(last.get("high") or 0)
    l = float(last.get("low") or 0)
    c = float(last.get("close") or 0)
    if not (_ok(h) and _ok(l) and _ok(c)):
        return []
    p = (h + l + c) / 3
    r1, s1 = 2 * p - l, 2 * p - h
    r2, s2 = p + (h - l), p - (h - l)
    r3, s3 = h + 2 * (p - l), l - 2 * (h - p)

    def lv(v: float, label: str, side: str, strength: str, rank: int) -> dict:
        return {"value": round(v, 2), "label": label, "type": "pivot",
                "side": side, "strength": strength, "rank": rank}

    return [
        lv(p, "枢轴位 P", "neutral", "strong", 0),
        lv(r1, "压力位 R1", "resistance", "medium", 1),
        lv(r2, "压力位 R2", "resistance", "medium", 2),
        lv(r3, "压力位 R3", "resistance", "weak", 3),
        lv(s1, "支撑位 S1", "support", "medium", 1),
        lv(s2, "支撑位 S2", "support", "medium", 2),
        lv(s3, "支撑位 S3", "support", "weak", 3),
    ]


# ================================================================
# 3. 前高前低 —— 60/250 日极值 + swing 高低点
# ================================================================

def _extreme_levels(klines: List[dict]) -> List[dict]:
    if not klines:
        return []
    cols = _cols(klines)
    highs, lows, closes = cols["high"], cols["low"], cols["close"]
    close = closes[-1]
    out: List[dict] = []

    for n in (60, 250):
        if len(closes) < n:
            continue
        sub_h = highs[-n:]
        sub_l = lows[-n:]
        hi, lo = max(sub_h), min(sub_l)
        if _ok(hi):
            out.append({"value": round(hi, 2), "label": f"{n}日新高",
                        "type": "extreme", "side": "resistance", "strength": "strong"})
        if _ok(lo):
            out.append({"value": round(lo, 2), "label": f"{n}日新低",
                        "type": "extreme", "side": "support", "strength": "strong"})

    win = 5
    if len(closes) > win * 2 and close:
        swing_highs: List[float] = []
        swing_lows: List[float] = []
        for i in range(win, len(highs) - win):
            if highs[i] == max(highs[i - win:i + win + 1]):
                swing_highs.append(float(highs[i]))
            if lows[i] == min(lows[i - win:i + win + 1]):
                swing_lows.append(float(lows[i]))

        agg_h = _aggregate_levels(swing_highs, 0.01)
        agg_h = [v for v in agg_h if v > close * 1.001]
        agg_h.sort(key=lambda v: abs(v - close))
        for v in agg_h[:2]:
            out.append({"value": round(v, 2), "label": "前高",
                        "type": "extreme", "side": "resistance", "strength": "medium"})

        agg_l = _aggregate_levels(swing_lows, 0.01)
        agg_l = [v for v in agg_l if v < close * 0.999]
        agg_l.sort(key=lambda v: abs(v - close))
        for v in agg_l[:2]:
            out.append({"value": round(v, 2), "label": "前低",
                        "type": "extreme", "side": "support", "strength": "medium"})
    return out


# ================================================================
# 4. 布林带 + Keltner 通道
# ================================================================

def _boll_channel(klines: List[dict]) -> List[dict]:
    if len(klines) < 20:
        return []
    cols = _cols(klines)
    closes = cols["close"]
    close = closes[-1]
    ma20 = _sma(closes, 20)
    if not ma20:
        return []
    var = sum((c - ma20) ** 2 for c in closes[-20:]) / 20
    std = math.sqrt(var)
    bu, bl = ma20 + 2 * std, ma20 - 2 * std
    out = [
        {"value": round(bu, 2), "label": "布林上轨",
         "type": "boll", "side": _side(bu, close), "strength": "medium"},
        {"value": round(bl, 2), "label": "布林下轨",
         "type": "boll", "side": _side(bl, close), "strength": "medium"},
        {"value": round(ma20, 2), "label": "布林中轨",
         "type": "boll", "side": _side(ma20, close), "strength": "medium"},
    ]
    return out


def _keltner_band(klines: List[dict], window: int, n_mult: float,
                  label_short: str, type_key: str) -> List[dict]:
    if len(klines) < max(20, window):
        return []
    cols = _cols(klines)
    closes, highs, lows = cols["close"], cols["high"], cols["low"]
    close = closes[-1]
    atr = _atr_14(highs, lows, closes)
    if not atr:
        return []
    ma = _sma(closes, window)
    if not ma:
        return []
    upper, lower = ma + n_mult * atr, ma - n_mult * atr
    return [
        {"value": round(upper, 2), "label": f"{label_short}通道上轨",
         "type": type_key, "side": _side(upper, close), "strength": "medium"},
        {"value": round(lower, 2), "label": f"{label_short}通道下轨",
         "type": type_key, "side": _side(lower, close), "strength": "medium"},
    ]


# ================================================================
# 5. ATR 波动通道
# ================================================================

def _atr_stops(klines: List[dict]) -> List[dict]:
    if len(klines) < 15:
        return []
    cols = _cols(klines)
    close = cols["close"][-1]
    atr = _atr_14(cols["high"], cols["low"], cols["close"])
    if not (_ok(close) and _ok(atr)):
        return []

    def lv(v: float, label: str, side: str, strength: str) -> dict:
        return {"value": round(v, 2), "label": label, "type": "atr_stop",
                "side": side, "strength": strength}

    return [
        lv(close + 2 * atr, "ATR 上轨(+2)", "resistance", "medium"),
        lv(close + 1.5 * atr, "ATR 上轨(+1.5)", "resistance", "weak"),
        lv(close - 1.5 * atr, "ATR 下轨(-1.5)", "support", "weak"),
        lv(close - 2 * atr, "ATR 下轨(-2)", "support", "medium"),
    ]


# ================================================================
# 6. 缺口位 —— 未回补跳空缺口
# ================================================================

def _gap_levels(klines: List[dict], lookback: int = 120) -> List[dict]:
    if len(klines) < 5:
        return []
    cols = _cols(klines)
    highs = cols["high"][-lookback:]
    lows = cols["low"][-lookback:]
    close = cols["close"][-1]

    up_gaps: List[tuple] = []
    dn_gaps: List[tuple] = []
    for i in range(1, len(highs)):
        if _ok(highs[i]) and _ok(lows[i]) and _ok(highs[i - 1]) and _ok(lows[i - 1]):
            if lows[i] > highs[i - 1]:
                up_gaps.append((i, float(highs[i - 1]), float(lows[i])))
            elif highs[i] < lows[i - 1]:
                dn_gaps.append((i, float(highs[i]), float(lows[i - 1])))

    def _filter_unfilled(gaps: List[tuple]) -> List[float]:
        mids: List[float] = []
        for i, g_lo, g_hi in gaps:
            filled = False
            for j in range(i + 1, len(highs)):
                if lows[j] <= g_hi and highs[j] >= g_lo:
                    filled = True
                    break
            if not filled:
                mids.append((g_lo + g_hi) / 2)
        agg = _aggregate_levels(mids, 0.005)
        agg.sort(key=lambda v: abs(v - close))
        return agg[:3]

    out: List[dict] = []
    for mid in _filter_unfilled(up_gaps):
        out.append({"value": round(mid, 2), "label": "向上缺口",
                    "type": "gap", "side": _side(mid, close), "strength": "medium"})
    for mid in _filter_unfilled(dn_gaps):
        out.append({"value": round(mid, 2), "label": "向下缺口",
                    "type": "gap", "side": _side(mid, close), "strength": "medium"})
    return out


# ================================================================
# 7. 斐波那契回撤
# ================================================================

def _fibonacci_levels(klines: List[dict], window: int = 120) -> List[dict]:
    if len(klines) < 10:
        return []
    cols = _cols(klines)
    highs = cols["high"][-window:]
    lows = cols["low"][-window:]
    close = cols["close"][-1]
    hi_pos = highs.index(max(highs))
    lo_pos = lows.index(min(lows))
    hi_val, lo_val = float(highs[hi_pos]), float(lows[lo_pos])
    if not (_ok(hi_val) and _ok(lo_val)) or hi_val <= lo_val:
        return []
    ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
    rng = hi_val - lo_val
    up_trend = hi_pos > lo_pos
    out: List[dict] = []
    for r in ratios:
        val = hi_val - rng * r if up_trend else lo_val + rng * r
        out.append({"value": round(val, 2), "label": f"Fib {int(r * 1000) / 10:.1f}%",
                    "type": "fib", "side": _side(val, close), "strength": "medium"})
    return out


# ================================================================
# 8. 整数关口
# ================================================================

def _round_numbers(klines: List[dict], pct: float = 0.10, max_count: int = 8) -> List[dict]:
    if not klines:
        return []
    close = float(klines[-1].get("close") or 0)
    if not _ok(close):
        return []
    if close < 10:
        step = 0.5
    elif close < 20:
        step = 1.0
    elif close < 100:
        step = 5.0
    elif close < 500:
        step = 10.0
    else:
        step = 50.0

    lo = close * (1 - pct)
    hi = close * (1 + pct)
    start = (int(lo / step) + (1 if lo % step > 0 else 0)) * step
    candidates: List[float] = []
    v = start
    while v <= hi:
        if v > 0:
            candidates.append(round(v, 2))
        v += step
    candidates.sort(key=lambda x: abs(x - close))
    out: List[dict] = []
    for v in candidates[:max_count]:
        if abs(v - close) / close < 0.01:
            continue
        out.append({"value": round(v, 2), "label": f"整数关口 {v:g}",
                    "type": "round", "side": _side(v, close), "strength": "weak"})
    return out


# ================================================================
# 主入口
# ================================================================

def compute_levels(klines: List[dict]) -> dict:
    """计算 11 类价位点，返回 {分组key: [点位...]}。"""
    if not klines:
        return {k: [] for k in LEVEL_TYPES}
    try:
        return {
            "sr": _support_resistance(klines),
            "pivot": _pivot_points(klines),
            "extreme": _extreme_levels(klines),
            "boll": _boll_channel(klines),
            "keltner_s": _keltner_band(klines, 20, 2.0, "短期", "keltner_s"),
            "keltner_m": _keltner_band(klines, 60, 2.5, "中期", "keltner_m"),
            "keltner_l": _keltner_band(klines, 120, 3.0, "长期", "keltner_l"),
            "atr_stop": _atr_stops(klines),
            "gap": _gap_levels(klines),
            "fib": _fibonacci_levels(klines),
            "round": _round_numbers(klines),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("compute_levels failed: %s", e)
        return {k: [] for k in LEVEL_TYPES}


def summarize_levels(levels: dict, close: Optional[float]) -> str:
    """生成 AI 提示词用的价位摘要文本。"""
    if not close:
        return "无价位数据"
    parts: List[str] = [f"当前价 {close:.2f}"]
    for key, label in LEVEL_TYPES.items():
        pts = levels.get(key, []) or []
        if not pts:
            continue
        ranked = sorted(pts, key=lambda p: abs(p["value"] - close))[:2]
        desc = "、".join(f"{p['label']}={p['value']}" for p in ranked)
        parts.append(f"{label}: {desc}")
    return " · ".join(parts)


# ================================================================
# API 层
# ================================================================

import sys
import os
from typing import Optional as _Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import APIRouter, Query  # noqa: E402

router = APIRouter()


MIN_ANALYSIS_BARS = 30


async def _get_klines(market: str, symbol: str, as_of: _Optional[str] = None) -> list:
    """读取日K；美股严格只读本地数据库，不在接口请求中触发采集。

    A股换手率字段在 bs_signals 路径缺失 → 筹码分布退化为纯累加；
    如有本地 StockDailyKline.turnover 可直接增强，不影响功能。
    """
    symbol = symbol.strip().upper()
    if market == "a":
        from analyzers.market_state import _stock_code_to_tushare
        from db.models import StockDailyKline
        from db.session import get_db_session

        ts_code = _stock_code_to_tushare(symbol)
        with get_db_session() as db:
            query = db.query(StockDailyKline).filter(
                StockDailyKline.ts_code == ts_code,
                StockDailyKline.open.isnot(None),
                StockDailyKline.high.isnot(None),
                StockDailyKline.low.isnot(None),
                StockDailyKline.close.isnot(None),
            )
            if as_of:
                from datetime import datetime
                query = query.filter(
                    StockDailyKline.trade_date <= datetime.strptime(as_of, "%Y-%m-%d").date()
                )
            rows = query.order_by(StockDailyKline.trade_date.desc()).limit(252).all()
        rows.reverse()
        klines = [{
            "date": row.trade_date.isoformat(),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": int(row.volume or 0),
        } for row in rows]
        if len(klines) < MIN_ANALYSIS_BARS:
            raise ValueError(
                f"数据库日K不足：{symbol} 仅有 {len(klines)} 根，至少需要 {MIN_ANALYSIS_BARS} 根"
            )
        return klines
    from us_quant.collector import get_db_klines
    klines = get_db_klines(symbol, end_date=as_of)
    if not klines or len(klines) < MIN_ANALYSIS_BARS:
        count = len(klines) if klines else 0
        raise ValueError(
            f"数据库日K不足：{symbol} 仅有 {count} 根，至少需要 {MIN_ANALYSIS_BARS} 根"
        )
    return klines[-252:]


@router.get("/api/price-levels")
async def get_price_levels(
    market: str = Query("a", description="a= A股, us= 美股"),
    symbol: str = Query(..., description="股票代码，如 600519 / MSFT"),
    as_of: _Optional[str] = Query(None, description="数据库快照截止日 YYYY-MM-DD"),
):
    """个股关键价位：11 类支撑/压力位点。"""
    try:
        klines = await _get_klines(market, symbol, as_of=as_of)
        levels = compute_levels(klines)
        close = float(klines[-1].get("close") or 0)
        data_as_of = klines[-1].get("date") or klines[-1].get("day")
        return {
            "ok": True,
            "status": "READY",
            "source": "database",
            "data": {
                "symbol": symbol.strip().upper(),
                "market": market,
                "close": round(close, 2),
                "types": LEVEL_TYPES,
                "levels": levels,
                "summary": summarize_levels(levels, close),
                "n_days": len(klines),
                "source": "database",
                "status": "READY",
                "data_as_of": data_as_of,
                "min_required_bars": MIN_ANALYSIS_BARS,
            },
            "error": None,
        }
    except Exception as e:
        message = str(e)
        return {
            "ok": False,
            "status": "INSUFFICIENT" if "不足" in message else "ERROR",
            "source": "database",
            "data": None,
            "error": message,
        }

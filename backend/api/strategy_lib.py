"""选股策略库 —— 移植自 tickflow-stock-panel (MIT) 的 builtin 策略设计。

纯 Python 实现：输入日K列表，计算特征，逐策略判定信号。
A股/美股通用（涨停/连板类策略仅 A 股适用）。

特征命名与 TSP 的 matrix_feature 对齐：ma5/ma10/ma20/ma60/ma120/ma250、
vol_ratio_5d、rsi_14、momentum_20d、annual_vol_20d、change_pct、low_60d、
high_60d、boll_upper/boll_lower、macd(dif/dea)、turnover_rate、
consecutive_limit_ups、limit_up_locked。
"""
from __future__ import annotations

import math
from typing import List, Optional


# ================================================================
# 特征计算
# ================================================================

def _sma(vals: List[float], w: int) -> Optional[float]:
    if len(vals) < w or w <= 0:
        return None
    return sum(vals[-w:]) / w


def _ema(vals: List[float], span: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    k = 2.0 / (span + 1)
    prev: Optional[float] = None
    for i, v in enumerate(vals):
        if prev is None:
            prev = v
        else:
            prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def _rsi(vals: List[float], period: int = 14) -> Optional[float]:
    if len(vals) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = vals[i] - vals[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    avg_g, avg_l = gains / period, losses / period
    for i in range(period + 1, len(vals)):
        d = vals[i] - vals[i - 1]
        g = max(d, 0.0)
        l = max(-d, 0.0)
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)


def _atr_14(highs, lows, closes) -> Optional[float]:
    n = len(closes)
    if n < 15:
        return None
    trs = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    atr = sum(trs[:14]) / 14.0
    for i in range(14, len(trs)):
        atr = (atr * 13 + trs[i]) / 14.0
    return atr


def limit_pct_for(code: str) -> float:
    """A股涨跌停幅度：688/300/301=20%，8/4 开头北交=30%，其余 10%。"""
    c = code.upper()
    if c.startswith(("688", "300", "301")):
        return 0.20
    if c.startswith(("8", "4")):
        return 0.30
    return 0.10


def _consecutive_limit_ups(closes: List[float], limit_pct: float) -> int:
    """连续涨停天数（含当日）。容差：涨幅 ≥ limit*0.95。"""
    if len(closes) < 2:
        return 0
    n = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i - 1] > 0 and (closes[i] / closes[i - 1] - 1) >= limit_pct * 0.95:
            n += 1
        else:
            break
    return n


def compute_features(klines: List[dict], code: str = "") -> dict:
    """从日K列表计算末位特征快照。klines 需按日期升序。"""
    n = len(klines)
    if n < 3:
        return {}
    opens = [float(k.get("open") or 0) for k in klines]
    highs = [float(k.get("high") or 0) for k in klines]
    lows = [float(k.get("low") or 0) for k in klines]
    closes = [float(k.get("close") or 0) for k in klines]
    vols = [float(k.get("volume") or 0) for k in klines]

    close = closes[-1]
    f: dict = {"close": close, "open": opens[-1], "high": highs[-1], "low": lows[-1],
               "volume": vols[-1], "n": n, "date": klines[-1].get("date")}

    # 均线
    for w in (5, 10, 20, 60, 120, 250):
        v = _sma(closes, w)
        if v is not None:
            f[f"ma{w}"] = v

    # 量比 5 日
    if n >= 6 and vols[-5] > 0:
        f["vol_ratio_5d"] = vols[-1] / (sum(vols[-5:]) / 5) if sum(vols[-5:]) > 0 else 1.0

    # RSI
    r14 = _rsi(closes, 14)
    if r14 is not None:
        f["rsi_14"] = r14

    # 动量
    if n >= 21 and closes[-21] > 0:
        f["momentum_20d"] = close / closes[-21] - 1

    # 20 日年化波动率
    if n >= 21:
        rets = [closes[i] / closes[i - 1] - 1 for i in range(n - 20, n) if closes[i - 1] > 0]
        if len(rets) >= 5:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            f["annual_vol_20d"] = math.sqrt(var) * math.sqrt(252)

    # 涨跌幅
    if n >= 2 and closes[-2] > 0:
        f["change_pct"] = close / closes[-2] - 1

    # 60 日高低
    if n >= 2:
        sub_h = highs[-min(n, 60):]
        sub_l = lows[-min(n, 60):]
        f["high_60d"] = max(sub_h)
        f["low_60d"] = min(sub_l)

    # 布林带
    ma20 = f.get("ma20")
    if ma20 and n >= 20:
        var = sum((c - ma20) ** 2 for c in closes[-20:]) / 20
        std = math.sqrt(var)
        f["boll_upper"] = ma20 + 2 * std
        f["boll_lower"] = ma20 - 2 * std

    # MACD
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    if len(ema12) >= 2:
        dif_series = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
        dea_series = _ema(dif_series, 9)
        if len(dea_series) >= 3:
            f["macd_dif"] = dif_series[-1]
            f["macd_dea"] = dea_series[-1]
            f["macd_golden"] = (dif_series[-1] > dea_series[-1]
                                and dif_series[-2] <= dea_series[-2])
            f["macd_dead"] = (dif_series[-1] < dea_series[-1]
                              and dif_series[-2] >= dea_series[-2])

    # ATR
    atr = _atr_14(highs, lows, closes)
    if atr:
        f["atr_14"] = atr

    # 换手率（数据源有则带）
    tr = klines[-1].get("turnover_rate")
    if tr is not None:
        try:
            f["turnover_rate"] = float(tr)
        except (TypeError, ValueError):
            pass

    # 涨停/连板（A股）
    if code and code[0] not in ("$", "^") and not code[0].isalpha():
        lp = limit_pct_for(code)
        f["limit_pct"] = lp
        prev_close = closes[-2] if n >= 2 and closes[-2] > 0 else None
        if prev_close:
            f["limit_price"] = round(prev_close * (1 + lp), 2)
            f["limit_up"] = close >= prev_close * (1 + lp) * 0.995
            f["limit_up_locked"] = close >= prev_close * (1 + lp) * 0.999
        f["consecutive_limit_ups"] = _consecutive_limit_ups(closes, lp)
        f["near_limit_up_pct"] = (f.get("limit_price", close) - close) / max(close, 0.01) * 100 if f.get("limit_price") else None

    return f


# ================================================================
# 策略定义：META + check(features, params) -> (hit, reason)
# ================================================================

def _p(f, key, default):
    return f.get(key, default)


def _above(f, key, op, val):
    v = f.get(key)
    return v is not None and op(v, val)


def _hit(f, params, conditions, reason):
    for c in conditions:
        if not c:
            return False, ""
    return True, reason


STRATEGIES = []
_ALL = "all"
_A_ONLY = "a"


def _register(meta, fn):
    STRATEGIES.append({"meta": meta, "check": fn})


# 1. 趋势突破
_register({
    "id": "trend_breakout", "name": "趋势突破",
    "description": "MA60上方 + 60日新高 + 量能 ≥ 2倍均量",
    "tags": ["趋势", "突破", "放量"], "market": _ALL,
    "params": [
        {"id": "require_above_ma60", "label": "要求收盘价在MA60上方", "type": "bool", "default": True},
        {"id": "require_n_day_high", "label": "要求60日新高", "type": "bool", "default": True},
        {"id": "use_volume_filter", "label": "启用量比过滤", "type": "bool", "default": True},
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 2.0, "min": 0.5, "max": 10.0, "step": 0.1},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("close") and (not p.get("require_above_ma60", True) or (f.get("ma60") and f["close"] > f["ma60"])),
    not p.get("require_n_day_high", True) or (f.get("high_60d") and f["close"] >= f["high_60d"] * 0.995),
    not p.get("use_volume_filter", True) or (f.get("vol_ratio_5d") is not None and f["vol_ratio_5d"] >= float(p.get("vol_ratio_min", 2.0))),
], "MA60上方+60日新高+放量"))

# 2. 布林突破
_register({
    "id": "boll_breakout", "name": "布林突破",
    "description": "突破布林上轨 + 放量 ≥ 1.5倍",
    "tags": ["布林", "突破"], "market": _ALL,
    "params": [
        {"id": "require_boll_breakout", "label": "要求突破布林上轨", "type": "bool", "default": True},
        {"id": "use_volume_filter", "label": "启用量比过滤", "type": "bool", "default": True},
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.5, "min": 0.5, "max": 5.0, "step": 0.1},
    ],
}, lambda f, p: _hit(f, p, [
    not p.get("require_boll_breakout", True) or (f.get("boll_upper") and f["close"] > f["boll_upper"]),
    not p.get("use_volume_filter", True) or (f.get("vol_ratio_5d") is not None and f["vol_ratio_5d"] >= float(p.get("vol_ratio_min", 1.5))),
], "突破布林上轨+放量"))

# 3. 均线金叉
_register({
    "id": "ma_golden_cross", "name": "均线金叉",
    "description": "MA5上穿MA20 + 量能配合 + MA60上方",
    "tags": ["均线", "金叉"], "market": _ALL,
    "params": [
        {"id": "use_volume_filter", "label": "启用量比过滤", "type": "bool", "default": True},
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.2, "min": 0.5, "max": 5.0, "step": 0.1},
        {"id": "require_above_ma60", "label": "要求收盘价在MA60上方", "type": "bool", "default": True},
    ],
}, lambda f, p: _hit(f, p, [
    (f.get("ma5") is not None and f.get("ma20") is not None
     and f["ma5"] > f["ma20"] and f.get("prev_ma5", f["ma5"]) <= f.get("prev_ma20", f["ma20"])
     if f.get("prev_ma5") is not None else True),
    not p.get("use_volume_filter", True) or (f.get("vol_ratio_5d") is not None and f["vol_ratio_5d"] >= float(p.get("vol_ratio_min", 1.2))),
    not p.get("require_above_ma60", True) or (f.get("ma60") and f["close"] > f["ma60"]),
], "MA5上穿MA20"))

# 4. MACD金叉
_register({
    "id": "macd_golden", "name": "MACD金叉放量",
    "description": "MACD金叉当日 + 量能放大",
    "tags": ["MACD", "金叉"], "market": _ALL,
    "params": [
        {"id": "use_volume_filter", "label": "启用量比过滤", "type": "bool", "default": True},
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.5, "min": 0.5, "max": 5.0, "step": 0.1},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("macd_golden") is True,
    not p.get("use_volume_filter", True) or (f.get("vol_ratio_5d") is not None and f["vol_ratio_5d"] >= float(p.get("vol_ratio_min", 1.5))),
], "MACD金叉+放量"))

# 5. 超跌反转
_register({
    "id": "oversold_reversal", "name": "超跌反转",
    "description": "RSI14<30 超卖 + 涨幅>1% + 站上MA5",
    "tags": ["超跌", "反弹", "RSI"], "market": _ALL,
    "params": [
        {"id": "rsi_max", "label": "RSI上限", "type": "float", "default": 30.0},
        {"id": "min_change", "label": "最小涨幅%", "type": "float", "default": 1.0},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("rsi_14") is not None and f["rsi_14"] < float(p.get("rsi_max", 30.0)),
    f.get("change_pct") is not None and f["change_pct"] > float(p.get("min_change", 1.0)) / 100,
    f.get("ma5") and f["close"] > f["ma5"],
], "RSI超卖+收阳站上MA5"))

# 6. 超跌反弹
_register({
    "id": "oversold_bounce", "name": "超跌反弹",
    "description": "RSI14<30 超卖区 + 当日收阳 + 放量",
    "tags": ["超卖", "抄底"], "market": _ALL,
    "params": [
        {"id": "rsi_max", "label": "RSI上限", "type": "float", "default": 30.0},
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.5},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("rsi_14") is not None and f["rsi_14"] < float(p.get("rsi_max", 30.0)),
    f.get("close") and f.get("open") and f["close"] > f["open"],
    f.get("vol_ratio_5d") is not None and f["vol_ratio_5d"] >= float(p.get("vol_ratio_min", 1.5)),
], "超卖+收阳+放量"))

# 7. 均线多头
_register({
    "id": "bullish_alignment", "name": "均线多头",
    "description": "MA5>MA10>MA20>MA60 多头排列 + 20日动量为正",
    "tags": ["趋势", "多头"], "market": _ALL,
    "params": [
        {"id": "require_positive_momentum", "label": "要求20日动量为正", "type": "bool", "default": True},
    ],
}, lambda f, p: _hit(f, p, [
    all(f.get(k) is not None for k in ("ma5", "ma10", "ma20", "ma60")) and f["ma5"] > f["ma10"] > f["ma20"] > f["ma60"],
    not p.get("require_positive_momentum", True) or (f.get("momentum_20d") is not None and f["momentum_20d"] > 0),
], "均线多头排列"))

# 8. 低波动龙头
_register({
    "id": "low_volatility_leader", "name": "低波动龙头",
    "description": "20日动量为正 + 年化波动<30% + MA20上方",
    "tags": ["低波动", "强势"], "market": _ALL,
    "params": [
        {"id": "vol_max", "label": "年化波动上限", "type": "float", "default": 0.30},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("momentum_20d") is not None and f["momentum_20d"] > 0,
    f.get("annual_vol_20d") is not None and f["annual_vol_20d"] < float(p.get("vol_max", 0.30)),
    f.get("ma20") and f["close"] > f["ma20"],
], "低波动+MA20上方"))

# 9. 新低反转
_register({
    "id": "n_day_low_reversal", "name": "新低反转",
    "description": "触及60日新低后当日收阳放量",
    "tags": ["反转", "抄底"], "market": _ALL,
    "params": [
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.5},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("low_60d") is not None and f["close"] <= f["low_60d"] * 1.001,
    f.get("close") and f.get("open") and f["close"] > f["open"],
    f.get("vol_ratio_5d") is not None and f["vol_ratio_5d"] >= float(p.get("vol_ratio_min", 1.5)),
], "60日新低+收阳放量"))

# 10. 均线回踩反弹
_register({
    "id": "pullback_ma20_bounce", "name": "均线回踩反弹",
    "description": "价格在MA20附近(±2%) + MA5>MA20>MA60 多头 + 收阳",
    "tags": ["回踩", "均线"], "market": _ALL,
    "params": [
        {"id": "ma_proximity", "label": "距MA20容差%", "type": "float", "default": 0.02},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("ma20") and abs(f["close"] / f["ma20"] - 1) <= float(p.get("ma_proximity", 0.02)),
    f.get("ma5") and f.get("ma20") and f.get("ma60") and f["ma5"] > f["ma20"] > f["ma60"],
    f.get("change_pct") is not None and f["change_pct"] > 0,
], "回踩MA20+多头排列+收阳"))

# 11. 缩量回踩
_register({
    "id": "pullback_to_support", "name": "缩量回踩",
    "description": "回踩MA20附近 + 缩量 + 中期趋势向上",
    "tags": ["回踩", "缩量"], "market": _ALL,
    "params": [
        {"id": "ma_proximity", "label": "距MA20容差%", "type": "float", "default": 0.02},
        {"id": "vol_ratio_max", "label": "量比上限", "type": "float", "default": 0.8},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("ma20") and abs(f["close"] / f["ma20"] - 1) <= float(p.get("ma_proximity", 0.02)),
    f.get("vol_ratio_5d") is not None and f["vol_ratio_5d"] < float(p.get("vol_ratio_max", 0.8)),
    f.get("ma60") and f["close"] > f["ma60"],
    f.get("momentum_20d") is not None and f["momentum_20d"] > 0,
], "回踩MA20+缩量+趋势向上"))

# 12. 强势高开
_register({
    "id": "strong_open", "name": "强势高开",
    "description": "高开>3% 且收盘高于开盘价",
    "tags": ["高开", "竞价"], "market": _ALL,
    "params": [
        {"id": "min_open_gap", "label": "最小高开%", "type": "float", "default": 3.0},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("prev_close") and f["open"] > f["prev_close"] * (1 + float(p.get("min_open_gap", 3.0)) / 100),
    f.get("close") and f.get("open") and f["close"] > f["open"],
    f.get("change_pct") is not None and f["change_pct"] > float(p.get("min_change", 3.0)) / 100,
], "强势高开收阳"))

# 13. 量价齐升
_register({
    "id": "volume_price_surge", "name": "量价齐升",
    "description": "突破MA20 + 放量 + 收阳",
    "tags": ["突破", "放量"], "market": _ALL,
    "params": [
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.5},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("breakout_ma20") is True,
    f.get("vol_ratio_5d") is not None and f["vol_ratio_5d"] >= float(p.get("vol_ratio_min", 1.5)),
    f.get("close") and f.get("open") and f["close"] > f["open"],
], "突破MA20+放量收阳"))

# 14. 高换手拉升
_register({
    "id": "high_turnover_surge", "name": "高换手拉升",
    "description": "换手率>5% 且涨幅>3%，资金活跃",
    "tags": ["换手", "资金"], "market": _ALL,
    "params": [
        {"id": "min_turnover", "label": "最小换手%", "type": "float", "default": 5.0},
        {"id": "min_change", "label": "最小涨幅%", "type": "float", "default": 3.0},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("turnover_rate") is not None and f["turnover_rate"] > float(p.get("min_turnover", 5.0)),
    f.get("change_pct") is not None and f["change_pct"] > float(p.get("min_change", 3.0)) / 100,
], "高换手+拉升"))

# 15. 逼近涨停（A股）
_register({
    "id": "near_limit_up", "name": "逼近涨停",
    "description": "涨幅>7% 且距涨停<3%（A股）",
    "tags": ["涨停", "追涨"], "market": _A_ONLY,
    "params": [
        {"id": "min_change", "label": "最小涨幅%", "type": "float", "default": 7.0},
        {"id": "limit_gap", "label": "距涨停最大%", "type": "float", "default": 3.0},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("change_pct") is not None and f["change_pct"] > float(p.get("min_change", 7.0)) / 100,
    f.get("near_limit_up_pct") is not None and f["near_limit_up_pct"] < float(p.get("limit_gap", 3.0)),
], "逼近涨停"))

# 16. 连板股（A股）
_register({
    "id": "consecutive_limit_ups", "name": "连板股",
    "description": "当日涨停且连续涨停≥2天（A股）",
    "tags": ["连板", "强势"], "market": _A_ONLY,
    "params": [
        {"id": "min_boards", "label": "最少连板数", "type": "int", "default": 2},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("limit_up") is True,
    f.get("consecutive_limit_ups", 0) >= int(p.get("min_boards", 2)),
], "连板≥2"))

# 17. 连板接力（A股）
_register({
    "id": "limit_up_momentum", "name": "连板接力",
    "description": "连板股 + 今日涨幅>5%（A股）",
    "tags": ["连板", "接力"], "market": _A_ONLY,
    "params": [
        {"id": "min_change", "label": "最小涨幅%", "type": "float", "default": 5.0},
        {"id": "min_boards", "label": "最少连板数", "type": "int", "default": 1},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("change_pct") is not None and f["change_pct"] > float(p.get("min_change", 5.0)) / 100,
    f.get("consecutive_limit_ups", 0) >= int(p.get("min_boards", 1)),
], "连板+强势"))

# 18. 断板反包（A股）—— 前5日内曾有≥2连板，今日放量反包收阳
_register({
    "id": "broken_board_recovery", "name": "断板反包",
    "description": "连板≥2后断板1-2天，今日放量反包（A股）",
    "tags": ["反包", "连板"], "market": _A_ONLY,
    "params": [
        {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.5},
    ],
}, lambda f, p: _hit(f, p, [
    f.get("had_2board_recently") is True,
    f.get("vol_ratio_5d") is not None and f["vol_ratio_5d"] >= float(p.get("vol_ratio_min", 1.5)),
    f.get("close") and f.get("open") and f["close"] > f["open"],
], "断板反包+放量"))


def list_strategies(market: str = "all") -> list:
    """返回策略元数据列表（market=a/us/all 过滤）。"""
    out = []
    for s in STRATEGIES:
        m = s["meta"]
        if market == "a" or market == "us":
            if m["market"] == _A_ONLY and market != "a":
                continue
        out.append({k: v for k, v in m.items()})
    return out


def run_strategy(strategy_id: str, features: dict, params: dict = None) -> Optional[dict]:
    """对单只股票特征执行策略，返回 {hit, reason}。"""
    for s in STRATEGIES:
        if s["meta"]["id"] == strategy_id:
            try:
                hit, reason = s["check"](features, params or {})
                return {"hit": bool(hit), "reason": reason}
            except Exception:
                return {"hit": False, "reason": ""}
    return None


def enrich_features(klines: List[dict], code: str = "") -> dict:
    """计算特征并补充跨日字段（prev_ma5/prev_ma20/prev_close/breakout_ma20/had_2board_recently）。"""
    f = compute_features(klines, code)
    n = len(klines)
    if n < 2:
        return f
    closes = [float(k.get("close") or 0) for k in klines]
    opens = [float(k.get("open") or 0) for k in klines]
    vols = [float(k.get("volume") or 0) for k in klines]

    if closes[-2] > 0:
        f["prev_close"] = closes[-2]

    # 前一日 MA5/MA20
    def _sma_prev(w):
        if n - 1 >= w:
            return sum(closes[-1 - w:-1]) / w
        return None
    pm5, pm20 = _sma_prev(5), _sma_prev(20)
    if pm5:
        f["prev_ma5"] = pm5
    if pm20:
        f["prev_ma20"] = pm20

    # 突破 MA20（今日上穿）
    if f.get("ma20") and pm20 and closes[-1] > f["ma20"] >= closes[-2]:
        f["breakout_ma20"] = True

    # 前5日内出现过连续≥2涨停（A股）
    if code and code[0] not in ("$", "^") and not code[0].isalpha():
        lp = f.get("limit_pct") or limit_pct_for(code)
        had = False
        streak = 0
        for i in range(max(1, n - 8), n):
            if closes[i - 1] > 0 and (closes[i] / closes[i - 1] - 1) >= lp * 0.95:
                streak += 1
            else:
                streak = 0
            if streak >= 2 and i < n - 2:  # 曾连板且已断板（非今日收盘状态）
                had = True
                break
        f["had_2board_recently"] = had

    return f

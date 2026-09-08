# -*- coding: utf-8 -*-
"""
美股个股分析聚合接口
- 实时行情：腾讯 qt.gtimg.cn（含 52周高低 / PE / EPS / 成交额）
- 历史K线+技术统计：只读本地 us_stock_daily 数据库
- 个股新闻：腾讯 proxy.finance.qq.com 新闻搜索
外部历史行情只允许采集器先落库，详情请求不触发历史行情采集；接口缓存 60s。
"""
from __future__ import annotations

import math
import re
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Query
from sqlalchemy import func

router = APIRouter(prefix="/api/us-stock-analysis", tags=["us-stock-analysis"])

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "*/*",
}
_SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}

_TX_QUOTE = "https://qt.gtimg.cn/q={codes}"
_SINA_KLINE = (
    "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20_t=/US_MinKService.getDailyK"
    "?symbol={sym}&___qn=3"
)
_TX_NEWS = (
    "https://proxy.finance.qq.com/ifzqgtimg/appstock/news/info/search"
    "?symbol={sym}&type=2&page=1&n={n}"
)
_TX_MINUTE = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=us{sym}"

_cache: Dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()
_TTL = 60
_MAX_CACHE = 500
MIN_ANALYSIS_BARS = 30

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-]{1,12}$")
_KLINE_RE = re.compile(
    r'\{"d":"([^"]+)","o":"([^"]*)","h":"([^"]*)","l":"([^"]*)","c":"([^"]*)","v":"([^"]*)"[^}]*\}'
)


def _get(url: str, timeout: int = 10, **kw) -> Optional[requests.Response]:
    headers = dict(_HEADERS)
    extra = kw.pop("headers", None)
    if extra:
        headers.update(extra)
    try:
        return requests.get(url, headers=headers, timeout=timeout, **kw)
    except Exception:
        return None


def _cached(key: str, builder, ttl: int = _TTL):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = builder()
    with _lock:
        _cache[key] = (time.time(), val)
        # 容量保护：先清过期键，仍超限则淘汰最旧键（per-symbol 缓存会随查询增长）
        if len(_cache) > _MAX_CACHE:
            expired = [k for k, (t, _) in _cache.items() if now - t >= _TTL]
            for k in expired:
                _cache.pop(k, None)
        if len(_cache) > _MAX_CACHE:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
    return val


# ─── 腾讯实时行情 ─────────────────────────────────────────────────────────────
def _tx_quote(symbol: str) -> Optional[dict]:
    resp = _get(_TX_QUOTE.format(codes="us" + symbol))
    if not resp:
        return None
    try:
        text = resp.content.decode("gbk", errors="ignore")
    except Exception:
        return None
    m = re.search(r'v_us' + re.escape(symbol) + r'="([^"]*)"', text, re.IGNORECASE)
    if not m or "none_match" in m.group(1):
        return None
    f = m.group(1).split("~")
    if len(f) < 50:
        return None

    def num(i):
        try:
            return float(f[i]) if f[i] not in ("", "-") else None
        except (ValueError, IndexError):
            return None

    price = num(3)
    prev = num(4)
    chg = num(31)
    chg_pct = num(32)
    # 字段位序（0-based，group(1) 不含 v_usXXX=" 前缀）：46=英文名 47=EPS 48=52周高 49=52周低
    high52, low52 = num(48), num(49)
    return {
        "symbol": symbol,
        "name": f[1],
        "code": f[2],
        "english_name": f[46] if len(f) > 46 else "",
        "price": price,
        "prev_close": prev,
        "open": num(5),
        "high": num(33),
        "low": num(34),
        "volume": num(36),
        "amount": num(37),
        "time": f[30],
        "change": chg,
        "chg_pct": chg_pct,
        "currency": f[35] if len(f) > 35 else "USD",
        "pe": num(39),
        "eps": num(47),
        "high_52w": high52,
        "low_52w": low52,
        # 涨跌方向（腾讯美股无涨跌停概念，直接按涨跌）
        "pct_52w_pos": (
            round((price - low52) / (high52 - low52) * 100, 1)
            if price and high52 and low52 and high52 > low52
            else None
        ),
    }


def _tx_intraday(symbol: str) -> List[dict]:
    """腾讯美股当日分时；盘后通常仅保留收盘点，调用方必须如实提示数据不足。"""
    resp = _get(_TX_MINUTE.format(sym=symbol))
    if not resp:
        return []
    try:
        raw = ((resp.json().get("data") or {}).get("us" + symbol, {}).get("data") or {}).get("data") or []
    except Exception:
        return []
    points = []
    for item in raw:
        part = str(item).split()
        try:
            if len(part) >= 2:
                points.append({"t": part[0], "p": float(part[1]), "v": float(part[2]) if len(part) > 2 else 0})
        except ValueError:
            continue
    return points


# ─── 数据库美股日K（页面与策略的唯一历史行情读口） ────────────────────────────
def _db_kline(symbol: str) -> List[dict]:
    """只读本地 us_stock_daily，不在详情请求中触发外部历史行情抓取。"""
    from us_quant.collector import get_db_klines

    rows = get_db_klines(symbol)[-500:]
    return [{
        "d": row["date"], "o": float(row["open"]), "h": float(row["high"]),
        "l": float(row["low"]), "c": float(row["close"]), "v": float(row.get("volume") or 0),
    } for row in rows]


def _db_quote(symbol: str, rows: List[dict]) -> Optional[dict]:
    """由数据库标的表和已落库日K生成页面报价快照。"""
    if not rows:
        return None
    from db.session import get_db_session
    from us_quant.repository import USInstrument

    with get_db_session() as db:
        instrument = db.query(USInstrument).filter(USInstrument.symbol == symbol).first()
    latest = rows[-1]
    previous = rows[-2] if len(rows) >= 2 else latest
    price = latest["c"]
    prev_close = previous["c"]
    change = price - prev_close
    recent = rows[-252:]
    high_52w = max(row["h"] for row in recent)
    low_52w = min(row["l"] for row in recent)
    return {
        "symbol": symbol,
        "name": instrument.name if instrument else symbol,
        "code": symbol,
        "english_name": "",
        "price": price,
        "prev_close": prev_close,
        "open": latest["o"],
        "high": latest["h"],
        "low": latest["l"],
        "volume": latest["v"],
        "amount": latest["v"] * price if latest["v"] else None,
        "time": latest["d"],
        "change": round(change, 4),
        "chg_pct": round(change / prev_close * 100, 4) if prev_close else None,
        "currency": "USD",
        "pe": None,
        "eps": None,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "pct_52w_pos": (
            round((price - low_52w) / (high_52w - low_52w) * 100, 1)
            if high_52w > low_52w else None
        ),
        "source": "database",
        "data_as_of": latest["d"],
        "is_real_time": False,
    }


def _db_latest_quotes(symbols: List[str]) -> Dict[str, dict]:
    """一次查询读取多只美股最新两根数据库日K。"""
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return {}
    from db.session import get_db_session
    from us_quant.repository import USInstrument, USStockDaily

    with get_db_session() as db:
        ranked = db.query(
            USStockDaily.symbol.label("symbol"),
            USStockDaily.trade_date.label("trade_date"),
            USStockDaily.open.label("open"),
            USStockDaily.high.label("high"),
            USStockDaily.low.label("low"),
            USStockDaily.close.label("close"),
            USStockDaily.volume.label("volume"),
            func.row_number().over(
                partition_by=USStockDaily.symbol,
                order_by=USStockDaily.trade_date.desc(),
            ).label("row_no"),
        ).filter(
            USStockDaily.symbol.in_(symbols),
            USStockDaily.close.isnot(None),
            USStockDaily.source.is_(None) | (USStockDaily.source != "synthetic"),
        ).subquery()
        bars = db.query(
            ranked.c.symbol,
            ranked.c.trade_date,
            ranked.c.open,
            ranked.c.high,
            ranked.c.low,
            ranked.c.close,
            ranked.c.volume,
        ).filter(ranked.c.row_no <= 2).order_by(
            ranked.c.symbol, ranked.c.trade_date.asc(),
        ).all()
        names = dict(db.query(USInstrument.symbol, USInstrument.name).filter(
            USInstrument.symbol.in_(symbols),
        ).all())

    grouped: Dict[str, List[Any]] = {symbol: [] for symbol in symbols}
    for bar in bars:
        grouped.setdefault(bar.symbol, []).append(bar)
    result = {}
    for symbol, rows in grouped.items():
        if not rows:
            continue
        latest = rows[-1]
        previous = rows[-2] if len(rows) >= 2 else latest
        price = float(latest.close)
        prev_close = float(previous.close)
        result[symbol] = {
            "symbol": symbol,
            "name": names.get(symbol) or symbol,
            "price": price,
            "prev_close": prev_close,
            "chg": round(price - prev_close, 4),
            "chg_pct": round((price / prev_close - 1) * 100, 4) if prev_close else None,
            "vol": int(latest.volume or 0),
            "amount": int(latest.volume or 0) * price,
            "high": float(latest.high) if latest.high is not None else None,
            "low": float(latest.low) if latest.low is not None else None,
            "vwap": None,
            "pos_in_range": None,
            "data_as_of": latest.trade_date.isoformat(),
            "source": "database",
        }
    return result


# ─── 新浪美股日K（仅供采集器写库使用，详情页不直接调用） ────────────────────
def _sina_kline(symbol: str) -> List[dict]:
    """返回升序日K [{"d": "2026-08-01", "o":.., "h":.., "l":.., "c":.., "v":..}]"""
    resp = _get(_SINA_KLINE.format(sym=symbol), headers=_SINA_HEADERS)
    if not resp:
        return []
    text = resp.text
    m = re.search(r"\((\[.*\])\)", text, re.DOTALL)
    if not m:
        return []
    rows = []
    for km in _KLINE_RE.finditer(m.group(1)):
        try:
            rows.append({
                "d": km.group(1),
                "o": float(km.group(2)),
                "h": float(km.group(3)),
                "l": float(km.group(4)),
                "c": float(km.group(5)),
                "v": float(km.group(6)),
            })
        except (ValueError, TypeError):
            continue
    return rows


def _ma(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return round(sum(closes[-n:]) / n, 2)


def _ret(closes: List[float], n: int) -> Optional[float]:
    if len(closes) <= n or closes[-n - 1] == 0:
        return None
    return round((closes[-1] / closes[-n - 1] - 1) * 100, 2)


def _max_drawdown(closes: List[float]) -> Optional[float]:
    """最近一年最大回撤（%）"""
    win = closes[-252:]
    if len(win) < 20:
        return None
    peak = win[0]
    mdd = 0.0
    for c in win:
        peak = max(peak, c)
        if peak > 0:
            mdd = min(mdd, c / peak - 1)
    return round(mdd * 100, 2)


def _vol_annual(closes: List[float]) -> Optional[float]:
    """年化波动率（%，250 日）"""
    win = closes[-252:]
    if len(win) < 30:
        return None
    rets = [(win[i] / win[i - 1] - 1) for i in range(1, len(win)) if win[i - 1] > 0]
    if not rets:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return round(math.sqrt(var) * math.sqrt(250) * 100, 2)


# ─── 增强指标（纯 Python，参考 InStock / daily_stock_analysis 设计） ────────────
def _atr_series(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[Optional[float]]:
    """Wilder ATR 序列（与通达信/同花顺一致）"""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    trs = []
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    atr = sum(trs[:period]) / period
    out[period] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i + 1] = atr
    return out


def _supertrend(highs: List[float], lows: List[float], closes: List[float],
                period: int = 10, mult: float = 3.0) -> Optional[dict]:
    """Supertrend(10,3)：方向 + 当前趋势线 + 最近翻转信号"""
    n = len(closes)
    if n < period + 5:
        return None
    atr_list = _atr_series(highs, lows, closes, period)
    hl2 = [(h + l) / 2.0 for h, l in zip(highs, lows)]
    upper: List[Optional[float]] = [None] * n
    lower: List[Optional[float]] = [None] * n
    for i in range(period, n):
        atr = atr_list[i]
        if atr is None:
            continue
        upper[i] = hl2[i] + mult * atr
        lower[i] = hl2[i] - mult * atr
    for i in range(period + 1, n):
        # 标准 Supertrend 平滑：今日带更激进信号则更新，否则沿用昨日
        if upper[i] is not None and upper[i - 1] is not None:
            if not (upper[i] < upper[i - 1] or closes[i - 1] > upper[i - 1]):
                upper[i] = upper[i - 1]
        if lower[i] is not None and lower[i - 1] is not None:
            if not (lower[i] > lower[i - 1] or closes[i - 1] < lower[i - 1]):
                lower[i] = lower[i - 1]
    dirs = [1] * n
    for i in range(period + 1, n):
        if upper[i] is not None and closes[i] > upper[i - 1]:
            dirs[i] = 1
        elif lower[i] is not None and closes[i] < lower[i - 1]:
            dirs[i] = -1
        else:
            dirs[i] = dirs[i - 1]
    trend_line = [upper[i] if dirs[i] == -1 else lower[i] for i in range(n)]
    last_dir = dirs[-1]
    last_line = trend_line[-1]
    if last_line is None:
        return None
    flip = None
    for i in range(n - 1, max(period, n - 6), -1):
        if dirs[i] != dirs[i - 1]:
            flip = ("多头" if dirs[i] == 1 else "空头") + "翻转"
            break
    return {
        "direction": "多头" if last_dir == 1 else "空头",
        "line": round(float(last_line), 2),
        "flip": flip,
    }


def _rsi_series(closes: List[float], period: int = 14) -> List[Optional[float]]:
    """Wilder RSI 序列"""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_g, avg_l = gains / period, losses / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def _ema_series(values: List[float], period: int) -> List[Optional[float]]:
    """EMA 序列；前 period-1 根保持空值，避免用不完整样本伪造指标。"""
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    ema = sum(values[:period]) / period
    out[period - 1] = ema
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        ema = values[i] * alpha + ema * (1 - alpha)
        out[i] = ema
    return out


def _macd_series(closes: List[float]) -> Dict[str, List[Optional[float]]]:
    """MACD(12,26,9)，hist 返回常见的 DIF-DEA 柱值。"""
    fast, slow = _ema_series(closes, 12), _ema_series(closes, 26)
    dif: List[Optional[float]] = [None] * len(closes)
    for i, (f, s) in enumerate(zip(fast, slow)):
        if f is not None and s is not None:
            dif[i] = f - s
    valid = [v for v in dif if v is not None]
    dea: List[Optional[float]] = [None] * len(closes)
    if len(valid) >= 9:
        ema = sum(valid[:9]) / 9
        first = next(i for i, v in enumerate(dif) if v is not None) + 8
        dea[first] = ema
        for i in range(first + 1, len(closes)):
            if dif[i] is not None:
                ema = dif[i] * 0.2 + ema * 0.8
                dea[i] = ema
    hist = [(d - e) if d is not None and e is not None else None for d, e in zip(dif, dea)]
    return {"dif": dif, "dea": dea, "hist": hist}


def _kdj_series(highs: List[float], lows: List[float], closes: List[float], period: int = 9) -> Dict[str, List[Optional[float]]]:
    """KDJ(9,3,3)，使用递推 SMA，与国内常用行情软件口径一致。"""
    k: List[Optional[float]] = [None] * len(closes)
    d: List[Optional[float]] = [None] * len(closes)
    j: List[Optional[float]] = [None] * len(closes)
    kv = dv = 50.0
    for i in range(period - 1, len(closes)):
        hi, lo = max(highs[i - period + 1:i + 1]), min(lows[i - period + 1:i + 1])
        rsv = 50.0 if hi == lo else (closes[i] - lo) / (hi - lo) * 100
        kv = (2 * kv + rsv) / 3
        dv = (2 * dv + kv) / 3
        k[i], d[i], j[i] = kv, dv, 3 * kv - 2 * dv
    return {"k": k, "d": d, "j": j}


def _boll_series(closes: List[float], period: int = 20, mult: float = 2.0) -> Dict[str, List[Optional[float]]]:
    mid: List[Optional[float]] = [None] * len(closes)
    upper: List[Optional[float]] = [None] * len(closes)
    lower: List[Optional[float]] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        win = closes[i - period + 1:i + 1]
        avg = sum(win) / period
        std = math.sqrt(sum((v - avg) ** 2 for v in win) / period)
        mid[i], upper[i], lower[i] = avg, avg + mult * std, avg - mult * std
    return {"mid": mid, "upper": upper, "lower": lower}


def _obv_series(closes: List[float], volumes: List[float]) -> List[float]:
    out = [0.0] * len(closes)
    for i in range(1, len(closes)):
        out[i] = out[i - 1] + (volumes[i] if closes[i] > closes[i - 1] else -volumes[i] if closes[i] < closes[i - 1] else 0)
    return out


def _adx_series(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict[str, List[Optional[float]]]:
    """ADX/DMI(14)：趋势强度 ADX 与方向线 +DI/-DI。"""
    n = len(closes)
    plus_di: List[Optional[float]] = [None] * n
    minus_di: List[Optional[float]] = [None] * n
    adx: List[Optional[float]] = [None] * n
    if n < period * 2 + 1:
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}
    trs, plus, minus = [], [], []
    for i in range(1, n):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
    tr_s, p_s, m_s = sum(trs[:period]), sum(plus[:period]), sum(minus[:period])
    dxs: List[tuple[int, float]] = []
    for i in range(period, n):
        if i > period:
            j = i - 1
            tr_s = tr_s - tr_s / period + trs[j]
            p_s = p_s - p_s / period + plus[j]
            m_s = m_s - m_s / period + minus[j]
        pdi, mdi = (100 * p_s / tr_s if tr_s else 0), (100 * m_s / tr_s if tr_s else 0)
        plus_di[i], minus_di[i] = pdi, mdi
        dxs.append((i, 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0))
    if len(dxs) >= period:
        value = sum(v for _, v in dxs[:period]) / period
        adx[dxs[period - 1][0]] = value
        for i, dx in dxs[period:]:
            value = (value * (period - 1) + dx) / period
            adx[i] = value
    return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}


def _bs_signals(opens: List[float], closes: List[float], volumes: List[float],
                ma5: List[Optional[float]], ma20: List[Optional[float]],
                ma60: List[Optional[float]], macd: Dict[str, List[Optional[float]]],
                kdj: Dict[str, List[Optional[float]]], rsi: List[Optional[float]]) -> List[dict]:
    """兼容个股分析接口；具体策略逻辑由因子库共享模块统一维护。"""
    from us_quant.bs_strategy import generate_signals_from_indicators
    return generate_signals_from_indicators(opens, closes, volumes, ma5, ma20, ma60, macd, kdj, rsi)


def _sma_fill(values: List[Optional[float]], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    s = 0.0
    cnt = 0
    for i, v in enumerate(values):
        if v is not None:
            s += v
            cnt += 1
        if i >= window and values[i - window] is not None:
            s -= values[i - window]
            cnt -= 1
        out.append(s / window if cnt == window else None)
    return out


def _stochrsi(closes: List[float], rsi_period: int = 14, stoch_period: int = 14,
              k_smooth: int = 3, d_smooth: int = 3) -> Optional[dict]:
    """STOCHRSI(14,14,3,3)：K/D + 状态 + 金叉死叉"""
    n = len(closes)
    if n < rsi_period + stoch_period + k_smooth + d_smooth + 2:
        return None
    rsi = _rsi_series(closes, rsi_period)
    raw_k: List[Optional[float]] = [None] * n
    for i in range(stoch_period - 1, n):
        win = [rsi[j] for j in range(i - stoch_period + 1, i + 1) if rsi[j] is not None]
        if len(win) < stoch_period:
            continue
        hi, lo = max(win), min(win)
        raw_k[i] = 100.0 if hi == lo else (win[-1] - lo) / (hi - lo) * 100
    k_series = _sma_fill(raw_k, k_smooth)
    d_series = _sma_fill(k_series, d_smooth)
    k_last, d_last = k_series[-1], d_series[-1]
    if k_last is None or d_last is None:
        return None
    k_prev, d_prev = k_series[-2], d_series[-2]
    cross = None
    if k_prev is not None and d_prev is not None:
        if k_prev <= d_prev and k_last > d_last:
            cross = "金叉"
        elif k_prev >= d_prev and k_last < d_last:
            cross = "死叉"
    state = "超买" if k_last >= 80 else "超卖" if k_last <= 20 else ("偏强" if k_last > 50 else "偏弱")
    return {
        "k": round(k_last, 1),
        "d": round(d_last, 1),
        "state": state,
        "cross": cross,
    }


def _bias(closes: List[float], n: int) -> Optional[float]:
    """BIAS 乖离率（%）"""
    ma = _ma(closes, n)
    if not ma or ma == 0:
        return None
    return round((closes[-1] / ma - 1) * 100, 2)


def _candlestick_patterns(rows: List[dict]) -> List[dict]:
    """K线形态识别（最近 1-3 根）：锤头/上吊/十字/吞没/曙光/乌云/三连"""
    if len(rows) < 3:
        return []
    pats: List[dict] = []
    cur, prev = rows[-1], rows[-2]
    o, h, l, c = cur["o"], cur["h"], cur["l"], cur["c"]
    body = abs(c - o)
    rng = max(h - l, 1e-9)
    upper_sh = h - max(o, c)
    lower_sh = min(o, c) - l
    is_bull = c > o

    def add(name: str, side: str):
        if len(pats) < 3 and name not in [p["name"] for p in pats]:
            pats.append({"name": name, "side": side})

    if body / rng < 0.1:
        add("十字星", "neutral")
    elif body / rng < 0.35 and lower_sh > 2 * body and upper_sh < body * 0.5:
        add("锤头线" if not is_bull else "上吊线", "bullish" if not is_bull else "bearish")
    elif body / rng < 0.35 and upper_sh > 2 * body and lower_sh < body * 0.5:
        add("倒锤头" if not is_bull else "射击之星", "bullish" if not is_bull else "bearish")
    po, pc = prev["o"], prev["c"]
    prev_bear = pc < po
    if prev_bear and is_bull and c >= po and o <= pc and body > abs(pc - po) * 0.5:
        add("看涨吞没", "bullish")
    elif not prev_bear and not is_bull and o >= pc and c <= po and body > abs(pc - po) * 0.5:
        add("看跌吞没", "bearish")
    if prev_bear and is_bull:
        mid = (po + pc) / 2
        if o < mid and c > mid and c < pc:
            add("曙光初现", "bullish")
    elif not prev_bear and not is_bull:
        mid = (po + pc) / 2
        if o > mid and c < mid and c > pc:
            add("乌云盖顶", "bearish")
    if len(rows) >= 3:
        last3 = rows[-3:]
        if all(r["c"] > r["o"] for r in last3):
            add("三连阳", "bullish")
        elif all(r["c"] < r["o"] for r in last3):
            add("三连阴", "bearish")
    return pats


def _chip_profile(rows: List[dict], window: int = 250) -> Optional[dict]:
    """筹码分布估算（成交量加权价格分布，美股无换手率）
    输出：获利盘比例 / 平均成本 / 集中度 / 筹码主峰价
    """
    win = rows[-window:]
    if len(win) < 60:
        return None
    highs = [r["h"] for r in win]
    lows = [r["l"] for r in win]
    hi, lo = max(highs), min(lows)
    if not (hi > lo > 0):
        return None
    close = win[-1]["c"]
    bins = 50
    step = (hi - lo) / bins
    chips = [0.0] * bins
    for r in win:
        v = r.get("v") or 0
        if v <= 0:
            continue
        k1 = min(int((r["l"] - lo) / step), bins - 1)
        k2 = min(int((r["h"] - lo) / step), bins - 1)
        if k1 > k2:
            k1, k2 = k2, k1
        k1 = max(k1, 0)
        share = v / (k2 - k1 + 1)
        for k in range(k1, k2 + 1):
            chips[k] += share
    total = sum(chips)
    if total <= 0:
        return None
    ci = min(int((close - lo) / step), bins - 1)
    profit = sum(chips[:ci + 1]) / total * 100
    mid_of = lambda k: lo + (k + 0.5) * step  # noqa: E731
    avg_cost = sum(mid_of(k) * chips[k] for k in range(bins)) / total
    var = sum((mid_of(k) - avg_cost) ** 2 * chips[k] for k in range(bins)) / total
    concentration = math.sqrt(var) / avg_cost * 100 if avg_cost > 0 else 0.0
    poc = max(range(bins), key=lambda k: chips[k])
    poc_price = mid_of(poc)
    return {
        "profit_ratio": round(profit, 1),
        "avg_cost": round(avg_cost, 2),
        "concentration": round(concentration, 1),
        "poc": round(poc_price, 2),
        "dist_to_poc": round((poc_price / close - 1) * 100, 1),
    }


def _kline_stats(symbol: str, rows: Optional[List[dict]] = None) -> Optional[dict]:
    rows = _db_kline(symbol) if rows is None else rows
    if len(rows) < MIN_ANALYSIS_BARS:
        return None
    opens, closes = [r["o"] for r in rows], [r["c"] for r in rows]
    last = closes[-1]
    ma5, ma10, ma20 = _ma(closes, 5), _ma(closes, 10), _ma(closes, 20)
    ma60, ma120, ma250 = _ma(closes, 60), _ma(closes, 120), _ma(closes, 250)
    highs, lows, volumes = [r["h"] for r in rows], [r["l"] for r in rows], [r["v"] for r in rows]
    ma5_series, ma10_series = _sma_fill(closes, 5), _sma_fill(closes, 10)
    ma20_series, ma60_series = _sma_fill(closes, 20), _sma_fill(closes, 60)
    macd, kdj, boll = _macd_series(closes), _kdj_series(highs, lows, closes), _boll_series(closes)
    rsi, atr, obv = _rsi_series(closes), _atr_series(highs, lows, closes), _obv_series(closes, volumes)
    adx = _adx_series(highs, lows, closes)

    # 均线形态
    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            trend = "多头排列"
        elif ma5 < ma20 < ma60:
            trend = "空头排列"
        else:
            trend = "均线纠缠"
    else:
        trend = "—"

    # 金叉 / 死叉（MA5 与 MA20 当日穿越）
    signal = "—"
    if len(closes) > 21 and ma5 and ma20:
        prev5 = sum(closes[-6:-1]) / 5
        prev20 = sum(closes[-21:-1]) / 20
        if prev5 <= prev20 and ma5 > ma20:
            signal = "金叉"
        elif prev5 >= prev20 and ma5 < ma20:
            signal = "死叉"

    return {
        "bars": len(rows),
        "data_source": "database",
        "data_as_of": rows[-1]["d"],
        "min_required_bars": MIN_ANALYSIS_BARS,
        "last_close": last,
        "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "ma60": ma60, "ma120": ma120, "ma250": ma250,
        "trend": trend,
        "signal": signal,
        "ret_1d": _ret(closes, 1),
        "ret_5d": _ret(closes, 5),
        "ret_20d": _ret(closes, 20),
        "ret_60d": _ret(closes, 60),
        "ret_120d": _ret(closes, 120),
        "ret_250d": _ret(closes, 250),
        "vol_annual": _vol_annual(closes),
        "max_dd_1y": _max_drawdown(closes),
        "rsi14": round(rsi[-1], 2) if rsi[-1] is not None else None,
        "macd": {k: round(v[-1], 4) if v[-1] is not None else None for k, v in macd.items()},
        "kdj": {k: round(v[-1], 2) if v[-1] is not None else None for k, v in kdj.items()},
        "boll": {k: round(v[-1], 2) if v[-1] is not None else None for k, v in boll.items()},
        "atr14": round(atr[-1], 2) if atr[-1] is not None else None,
        "obv": round(obv[-1], 0) if obv else None,
        "adx": {k: round(v[-1], 2) if v[-1] is not None else None for k, v in adx.items()},
        # 增强指标（InStock / daily_stock_analysis 思路）
        "supertrend": _supertrend(highs, lows, closes),
        "stochrsi": _stochrsi(closes),
        "bias6": _bias(closes, 6),
        "bias12": _bias(closes, 12),
        "bias24": _bias(closes, 24),
        "patterns": _candlestick_patterns(rows),
        "chip_profile": _chip_profile(rows),
        # 最近 500 根用于前端绘图；指标数组与 K 线索引严格对齐。
        "kline": rows[-500:],
        "chart_indicators": {
            "ma5": ma5_series[-500:], "ma10": ma10_series[-500:], "ma20": ma20_series[-500:], "ma60": ma60_series[-500:],
            "boll": {k: v[-500:] for k, v in boll.items()},
            "macd": {k: v[-500:] for k, v in macd.items()},
            "kdj": {k: v[-500:] for k, v in kdj.items()},
            "rsi": rsi[-500:], "atr": atr[-500:], "obv": obv[-500:], "adx": {k: v[-500:] for k, v in adx.items()},
            "bs_signals": [dict(sig, i=sig["i"] - max(0, len(rows) - 500)) for sig in _bs_signals(opens, closes, volumes, ma5_series, ma20_series, ma60_series, macd, kdj, rsi) if sig["i"] >= max(0, len(rows) - 500)],
        },
    }


# ─── 腾讯个股新闻 ─────────────────────────────────────────────────────────────
def _tx_news(symbol: str, limit: int = 10) -> List[dict]:
    resp = _get(_TX_NEWS.format(sym="us" + symbol, n=limit))
    if not resp:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    items = (payload.get("data") or {}).get("data") or []
    out = []
    for it in items:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "time": it.get("time", ""),
            "src": it.get("src", ""),
            "url": it.get("url", ""),
        })
    return out[:limit]


# ─── 主聚合 ───────────────────────────────────────────────────────────────────
@router.get("/overview")
def overview(
    symbol: str = Query(..., description="美股代码，如 MSFT / AAPL / BRK.B"),
    news_limit: int = Query(10, ge=1, le=20),
):
    sym = (symbol or "").strip().upper()
    if not _SYMBOL_RE.match(sym):
        return {"ok": False, "error": "代码格式不正确"}

    def build():
        try:
            rows = _db_kline(sym)
        except Exception:
            return {"ok": False, "error": "数据库日K读取失败，请检查数据库连接"}
        stats = _kline_stats(sym, rows=rows)
        history = {
            "source": "database",
            "status": "READY" if stats else ("INSUFFICIENT" if rows else "MISSING"),
            "bars": len(rows),
            "min_required_bars": MIN_ANALYSIS_BARS,
            "data_as_of": rows[-1]["d"] if rows else None,
            "message": (
                "数据库日K已就绪" if stats
                else f"数据库仅有 {len(rows)} 根日K，至少需要 {MIN_ANALYSIS_BARS} 根"
            ),
        }
        quote = _db_quote(sym, rows)
        if not quote and not stats:
            return {"ok": False, "error": f"未找到美股代码 {sym}，请检查后重试"}
        return {
            "ok": True,
            "symbol": sym,
            "quote": quote,
            "stats": stats,
            "history": history,
            "intraday": [],
            "intraday_status": {"source": "database", "status": "MISSING", "message": "暂无已入库分时数据"},
            "news": [],
            "news_status": {"source": "database", "status": "MISSING", "message": "暂无已入库美股新闻"},
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    return _cached("usa_" + sym, build)


@router.get("/quote")
def quote_api(symbol: str = Query(..., description="美股代码")):
    sym = (symbol or "").strip().upper()
    if not _SYMBOL_RE.match(sym):
        return {"ok": False, "error": "代码格式不正确"}
    def build():
        rows = _db_kline(sym)
        quote = _db_quote(sym, rows)
        return {"ok": quote is not None, "quote": quote, "error": None if quote else "数据库暂无日K"}

    return _cached("usaq_" + sym, build)


@router.get("/watchlist")
def watchlist():
    """自选池代码列表 + 行业映射（用于页面侧栏快捷切换与板块展示）"""
    def build():
        symbols = []
        sectors = {}
        try:
            from us_quant.universe import get_universe_members
            symbols = get_universe_members("US_WATCHLIST")[:60]
            # 行业映射（盈立同步时由 us_sector_fetcher 自动补采落库）
            from db.session import get_db_session
            from us_quant.repository import USInstrument
            with get_db_session() as db:
                rows = db.query(USInstrument.symbol, USInstrument.sector).filter(
                    USInstrument.symbol.in_(symbols),
                    USInstrument.sector.isnot(None),
                    USInstrument.sector != "",
                ).all()
                sectors = {sym: sec for sym, sec in rows}
        except Exception:
            symbols = []
        return {"ok": True, "symbols": symbols, "count": len(symbols),
                "sectors": sectors}

    return _cached("usa_wl", build, ttl=300)


# ─── 盘前策略（新浪美股实时行情，盘前/盘中/盘后通用） ───────────────────────────

_SINA_GB = "https://hq.sinajs.cn/list={codes}"
# 大盘风向标（盘前情绪参考 QQQ/SPY/DIA）
_MARKET_ETFS = ["QQQ", "SPY", "DIA"]
# 新浪 gb_ 字段位序（0-based，实测 2026-08）：
# 0名称 1现价(=盘前/盘后价) 2涨跌幅% 3北京时间 4涨跌额 5今开 6最高 7最低
# 21盘前均价 24美东时间 26昨收 27盘前成交量(股) 31盘前最高 32盘前最低 33盘前成交额(USD) 35现价


def _sina_gb(codes: List[str]) -> Dict[str, list]:
    """批量请求新浪美股 gb_ 行情，返回 {SYM: 字段列表}（无效/无数据代码跳过）"""
    if not codes:
        return {}
    url = _SINA_GB.format(codes=",".join("gb_" + c.lower() for c in codes))
    resp = _get(url, headers=_SINA_HEADERS)
    if not resp:
        return {}
    try:
        text = resp.content.decode("gbk", errors="ignore")
    except Exception:
        return {}
    out: Dict[str, list] = {}
    for m in re.finditer(r'hq_str_gb_([A-Za-z.]+)="([^"]*)"', text):
        payload = m.group(2)
        if not payload or payload == "0":
            continue
        f = payload.split(",")
        if len(f) >= 36:
            out[m.group(1).upper()] = f
    return out


def _sg_session() -> str:
    """按新加坡/北京时间判定美股时段（夏令时；冬令时整体 +1 小时）

    盘前 16:00—21:30 | 盘中 21:30—次日 04:00 | 盘后 04:00—08:00 | 夜盘/休市 08:00—16:00
    """
    lt = time.localtime()
    h = lt.tm_hour + lt.tm_min / 60
    if 21.5 <= h or h < 4:
        return "盘中"
    if 4 <= h < 8:
        return "盘后"
    if 8 <= h < 16:
        return "夜盘/休市"
    return "盘前"


@router.get("/premarket")
def premarket(symbols: str = Query("", description="额外纳入实时行情的美股代码，逗号分隔")):
    """盘前策略：自选池及指定候选的实时行情（盘前价/量/高低/均价）+ 大盘风向

    任何时段可调用：盘前时段即盘前数据，盘中即实时，盘后即盘后数据。
    """
    requested_symbols: List[str] = []
    for raw in (symbols or "").upper().split(","):
        sym = raw.strip()
        if sym and _SYMBOL_RE.match(sym) and sym not in requested_symbols:
            requested_symbols.append(sym)
    # 每次工作台最多附带 30 个候选，避免异常 URL 或外部批量行情请求过大。
    requested_symbols = requested_symbols[:30]

    def build():
        watchlist_symbols = []
        try:
            from us_quant.universe import get_universe_members
            watchlist_symbols = get_universe_members("US_WATCHLIST")[:60]
        except Exception:
            watchlist_symbols = []

        # 候选只是在实时校验中附带展示，并不会写入自选池或改变原盘前页面的范围。
        quote_symbols = list(dict.fromkeys(watchlist_symbols + requested_symbols))[:90]

        db_quotes = _db_latest_quotes(_MARKET_ETFS + quote_symbols)
        market = [db_quotes[sym] for sym in _MARKET_ETFS if sym in db_quotes]
        stocks = [db_quotes[sym] for sym in quote_symbols if sym in db_quotes]

        # 默认按异动幅度（|涨跌幅|）降序：盘前选股先看异动
        stocks.sort(key=lambda x: abs(x["chg_pct"] or 0), reverse=True)
        as_of_values = [item.get("data_as_of") for item in market + stocks if item.get("data_as_of")]
        us_time = max(as_of_values) if as_of_values else ""
        return {
            "ok": True,
            "session": "数据库收盘",
            "sgt_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "us_time": us_time,
            "market": market,
            "stocks": stocks,
            "count": len(stocks),
            "requested_symbols": requested_symbols,
            "source": "database",
        }

    cache_key = "usa_pm:" + (",".join(requested_symbols) if requested_symbols else "watchlist")
    return _cached(cache_key, build, ttl=30)

"""
Global Market API — 港股/美股行情（迁移自 hermes-cockpit）

数据源: Yahoo Finance API (query1.finance.yahoo.com)
- 指数行情: 恒生/国企/恒生科技 + 道琼斯/标普/纳指
- 关注列表行情: 默认 12 只港股 + 12 只美股
- K线历史: 1-120 天
- 增强版监控: 含 MA5/MA10/MA20/RSI/区间涨跌幅/均线偏离
- 批量K线: 迷你图用

依赖: requests (走本地代理 127.0.0.1:7897)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/global-market", tags=["global-market"])

# ─── 默认关注列表 ──────────────────────────────────────────────────────────────

DEFAULT_WATCHLIST = {
    "HK": [
        {"code": "00700", "name": "腾讯控股"},
        {"code": "09988", "name": "阿里巴巴-W"},
        {"code": "09999", "name": "网易-S"},
        {"code": "03690", "name": "美团-W"},
        {"code": "09888", "name": "百度集团-SW"},
        {"code": "01810", "name": "小米集团-W"},
        {"code": "09618", "name": "京东集团-SW"},
        {"code": "00981", "name": "中芯国际"},
        {"code": "00388", "name": "香港交易所"},
        {"code": "00005", "name": "汇丰控股"},
        {"code": "01211", "name": "比亚迪股份"},
        {"code": "02269", "name": "药明生物"},
    ],
    "US": [
        {"code": "AAPL", "name": "苹果"},
        {"code": "MSFT", "name": "微软"},
        {"code": "GOOGL", "name": "谷歌"},
        {"code": "AMZN", "name": "亚马逊"},
        {"code": "NVDA", "name": "英伟达"},
        {"code": "TSLA", "name": "特斯拉"},
        {"code": "META", "name": "Meta"},
        {"code": "TSM", "name": "台积电"},
        {"code": "BABA", "name": "阿里巴巴"},
        {"code": "PDD", "name": "拼多多"},
        {"code": "JD", "name": "京东"},
        {"code": "BIDU", "name": "百度"},
    ],
}

MARKET_INDICES = {
    "HK": [
        {"code": "HSI", "name": "恒生指数", "yahoo": "^HSI"},
        {"code": "HSCEI", "name": "国企指数", "yahoo": "^HSCE"},
        {"code": "HSTECH", "name": "恒生科技", "yahoo": "^HSTECH"},
    ],
    "US": [
        {"code": "DJI", "name": "道琼斯", "yahoo": "^DJI"},
        {"code": "SPX", "name": "标普500", "yahoo": "^GSPC"},
        {"code": "IXIC", "name": "纳斯达克", "yahoo": "^IXIC"},
    ],
}


# ─── Yahoo Finance 辅助函数 ─────────────────────────────────────────────────────

_YAHOO_PROXIES = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _yahoo_fetch(symbol: str, range_str: str = "5d") -> list[dict] | None:
    """通过 Yahoo Finance API 获取 K 线数据

    symbol: Yahoo 代码 (港股 0700.HK / 美股 AAPL / 指数 ^HSI)
    range_str: 1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/ytd/max
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_str, "interval": "1d"}
    try:
        resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, proxies=_YAHOO_PROXIES, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data["chart"]["result"][0]
        ts_list = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])
        items = []
        prev_close = None
        for i in range(len(ts_list)):
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            l = lows[i] if i < len(lows) else None
            c = closes[i] if i < len(closes) else None
            v = volumes[i] if i < len(volumes) else None
            if c is None:
                continue
            import datetime as _dt
            dt = _dt.datetime.fromtimestamp(ts_list[i])
            change_pct = None
            change_amount = None
            if prev_close and prev_close > 0:
                change_amount = round(c - prev_close, 4)
                change_pct = round((c - prev_close) / prev_close * 100, 4)
            items.append({
                "date": dt.strftime("%Y-%m-%d"),
                "open": round(o, 4) if o else None,
                "high": round(h, 4) if h else None,
                "low": round(l, 4) if l else None,
                "close": round(c, 4),
                "volume": int(v) if v else 0,
                "change_pct": change_pct,
                "change_amount": change_amount,
                "prev_close": round(prev_close, 4) if prev_close else None,
            })
            prev_close = c
        return items if items else None
    except Exception as e:
        logger.warning(f"Yahoo Finance fetch failed for {symbol}: {e}")
        return None


def _to_yahoo_symbol(market: str, code: str) -> str:
    """把业务代码转成 Yahoo 代码
    HK: 00700 → 0700.HK (去前导0, 加 .HK)
    US: AAPL → AAPL (不变)
    """
    if market == "HK":
        stripped = code.lstrip("0")
        return f"{stripped}.HK" if stripped else code
    return code


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


# ─── 技术指标计算 ───────────────────────────────────────────────────────────────

def _calc_ma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0, delta))
        losses.append(max(0, -delta))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _calc_change_pct(closes: list[float], periods: int) -> float | None:
    if len(closes) < periods + 1:
        return None
    old = closes[-(periods + 1)]
    new = closes[-1]
    if old == 0:
        return None
    return round((new - old) / old * 100, 2)


# ─── 指数行情 ──────────────────────────────────────────────────────────────────

def _fetch_index(idx: dict) -> dict:
    """拉单个指数 (供线程池并行)"""
    klines = _yahoo_fetch(idx["yahoo"], range_str="5d")
    if klines:
        latest = klines[-1]
        return {
            "code": idx["code"],
            "name": idx["name"],
            "price": latest.get("close"),
            "change_pct": latest.get("change_pct"),
            "change_amount": latest.get("change_amount"),
            "volume": latest.get("volume", ""),
            "updated": latest.get("date", ""),
        }
    return {"code": idx["code"], "name": idx["name"], "price": None, "change_pct": None}


@router.get("/indices/{market}")
def get_indices(market: str):
    """获取市场主要指数行情 (恒生/道琼斯等, 并行拉取)"""
    market = market.upper()
    if market not in ("HK", "US"):
        return {"market": market, "indices": [], "error": "仅支持 HK / US"}
    indices = MARKET_INDICES.get(market, [])
    results = [None] * len(indices)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_index, idx): i for i, idx in enumerate(indices)}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return {"market": market, "indices": results, "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S")}


# ─── 关注列表行情 ──────────────────────────────────────────────────────────────

def _fetch_quote_for_stock(market: str, stock: dict) -> dict:
    """拉单只股票的最新行情 (供线程池并行调用)"""
    yahoo_sym = _to_yahoo_symbol(market, stock["code"])
    klines = _yahoo_fetch(yahoo_sym, range_str="5d")
    if klines:
        latest = klines[-1]
        return {
            "code": stock["code"],
            "name": stock["name"],
            "price": latest.get("close"),
            "change_pct": latest.get("change_pct"),
            "change_amount": latest.get("change_amount"),
            "volume": latest.get("volume"),
            "high": latest.get("high"),
            "low": latest.get("low"),
            "open": latest.get("open"),
            "prev_close": latest.get("prev_close"),
            "updated": latest.get("date", ""),
        }
    return {"code": stock["code"], "name": stock["name"], "price": None, "change_pct": None}


@router.get("/quotes/{market}")
def get_quotes(market: str):
    """获取关注列表实时行情 (Yahoo Finance, 并行拉取)"""
    market = market.upper()
    if market not in ("HK", "US"):
        return {"market": market, "quotes": [], "error": "仅支持 HK / US"}
    watchlist = DEFAULT_WATCHLIST.get(market, [])
    results = [None] * len(watchlist)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch_quote_for_stock, market, s): i for i, s in enumerate(watchlist)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                results[idx] = {"code": watchlist[idx]["code"], "name": watchlist[idx]["name"], "price": None, "change_pct": None, "error": str(e)}
    return {"market": market, "quotes": results, "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S")}


# ─── K线历史 ───────────────────────────────────────────────────────────────────

@router.get("/kline/{market}/{code}")
def get_kline(market: str, code: str, days: int = Query(default=30, le=120)):
    """获取个股K线历史 (Yahoo Finance)"""
    market = market.upper()
    if market not in ("HK", "US"):
        return {"market": market, "code": code, "data": [], "error": "仅支持 HK / US"}
    # Yahoo range 映射: 30天以内用 1mo, 60天用 3mo, 120天用 6mo
    if days <= 30:
        range_str = "1mo"
    elif days <= 60:
        range_str = "3mo"
    else:
        range_str = "6mo"
    yahoo_sym = _to_yahoo_symbol(market, code)
    items = _yahoo_fetch(yahoo_sym, range_str=range_str)
    if items:
        data = [
            {
                "trade_date": item.get("date", ""),
                "open": item.get("open"),
                "high": item.get("high"),
                "low": item.get("low"),
                "close": item.get("close"),
                "volume": item.get("volume", 0),
                "change_pct": item.get("change_pct"),
            }
            for item in items[-days:]
        ]
        return {"market": market, "code": code, "data": data, "source": "yahoo", "days": days}
    return {"market": market, "code": code, "data": [], "source": "yahoo", "note": "K线数据暂不可用"}


# ─── 市场概览 ──────────────────────────────────────────────────────────────────

@router.get("/overview/{market}")
def get_overview(market: str):
    """市场概览: 指数 + 关注列表 + 涨跌统计"""
    market = market.upper()
    if market not in ("HK", "US"):
        return {"market": market, "error": "仅支持 HK / US"}
    market_label = "港股" if market == "HK" else "美股"
    indices_data = get_indices(market)
    quotes_data = get_quotes(market)
    quotes = quotes_data.get("quotes", [])
    up_count = sum(1 for q in quotes if (q.get("change_pct") or 0) > 0)
    down_count = sum(1 for q in quotes if (q.get("change_pct") or 0) < 0)
    flat_count = len(quotes) - up_count - down_count
    return {
        "market": market,
        "market_label": market_label,
        "indices": indices_data.get("indices", []),
        "quotes": quotes,
        "stats": {"total": len(quotes), "up": up_count, "down": down_count, "flat": flat_count},
        "updated_at": quotes_data.get("updated_at", ""),
    }


# ─── 增强版选股监控 (含技术指标) ────────────────────────────────────────────────

def _fetch_enhanced_for_stock(market: str, stock: dict) -> dict:
    """拉单只股票的增强行情 + 技术指标 (供线程池并行)"""
    yahoo_sym = _to_yahoo_symbol(market, stock["code"])
    klines = _yahoo_fetch(yahoo_sym, range_str="1mo") or []
    closes = [k["close"] for k in klines if k.get("close") is not None]
    last_k = klines[-1] if klines else {}
    price = _safe_float(last_k.get("close"))
    change_pct = _safe_float(last_k.get("change_pct"))
    ma5 = _calc_ma(closes, 5)
    ma10 = _calc_ma(closes, 10)
    ma20 = _calc_ma(closes, 20)
    rsi = _calc_rsi(closes, 14)
    change5d = _calc_change_pct(closes, 5)
    change10d = _calc_change_pct(closes, 10)
    change20d = _calc_change_pct(closes, 20)
    amplitude = None
    if last_k.get("high") and last_k.get("low") and last_k.get("prev_close"):
        pc = _safe_float(last_k["prev_close"])
        h = _safe_float(last_k["high"])
        l = _safe_float(last_k["low"])
        if pc and h is not None and l is not None and pc > 0:
            amplitude = round((h - l) / pc * 100, 2)
    deviation = None
    if ma20 and price and ma20 > 0:
        deviation = round((price - ma20) / ma20 * 100, 2)
    return {
        "code": stock["code"],
        "name": stock["name"],
        "price": price,
        "change_pct": change_pct,
        "open": _safe_float(last_k.get("open")),
        "high": _safe_float(last_k.get("high")),
        "low": _safe_float(last_k.get("low")),
        "volume": last_k.get("volume"),
        "amplitude": amplitude,
        "prev_close": _safe_float(last_k.get("prev_close")),
        "trade_date": last_k.get("date", ""),
        "source": "yahoo" if klines else "none",
        "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "rsi": rsi,
        "change5d": change5d, "change10d": change10d, "change20d": change20d,
        "deviation": deviation,
        "sparkline": [
            {"d": k.get("date", ""), "c": k.get("close")}
            for k in klines[-20:]
        ] if klines else [],
    }


@router.get("/watchlist-enhanced/{market}")
def get_watchlist_enhanced(market: str):
    """关注列表 + 技术指标 (并行拉取, MA5/MA10/MA20/RSI/区间涨跌幅/均线偏离/迷你图)"""
    market = market.upper()
    if market not in ("HK", "US"):
        return {"market": market, "items": [], "error": "仅支持 HK / US"}
    watchlist = DEFAULT_WATCHLIST.get(market, [])
    results = [None] * len(watchlist)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch_enhanced_for_stock, market, s): i for i, s in enumerate(watchlist)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                results[idx] = {"code": watchlist[idx]["code"], "name": watchlist[idx]["name"], "price": None, "change_pct": None, "error": str(e)}
    return {
        "market": market,
        "items": results,
        "total": len(results),
        "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }


# ─── 批量K线 (迷你图) ──────────────────────────────────────────────────────────

@router.get("/kline-batch/{market}")
def get_kline_batch(market: str, days: int = Query(default=20, le=60)):
    """批量获取关注列表 K 线 (迷你图用)"""
    market = market.upper()
    if market not in ("HK", "US"):
        return {"market": market, "data": {}, "error": "仅支持 HK / US"}
    watchlist = DEFAULT_WATCHLIST.get(market, [])
    range_str = "1mo" if days <= 30 else "3mo"
    result = {}
    for stock in watchlist:
        yahoo_sym = _to_yahoo_symbol(market, stock["code"])
        klines = _yahoo_fetch(yahoo_sym, range_str=range_str) or []
        result[stock["code"]] = [
            {"d": k.get("date", ""), "c": k.get("close"), "v": k.get("volume", 0)}
            for k in klines[-days:]
        ]
    return {"market": market, "data": result, "days": days, "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S")}

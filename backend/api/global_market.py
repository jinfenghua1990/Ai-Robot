"""
Global Market API — 港股/美股行情（迁移自 hermes-cockpit）

数据源: Yahoo Finance API (query1.finance.yahoo.com)
- 指数行情: 恒生/国企/恒生科技 + 道琼斯/标普/纳指
- 关注列表行情: 默认 12 只港股 + 12 只美股
- K线历史: 1-120 天
- 增强版监控: 含 MA5/MA10/MA20/RSI/区间涨跌幅/均线偏离
- 批量K线: 迷你图用

默认直连 Yahoo Finance；如需代理，设置环境变量 YAHOO_PROXY_URL，
例如 http://127.0.0.1:7897。
"""
from __future__ import annotations

import logging
import os
import time
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

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_cache: dict[str, tuple[float, list[dict] | None]] = {}
_CACHE_TTL = 300  # 5 分钟缓存，避免对 Yahoo Finance 的重复慢速调用


def _get_yahoo_proxies() -> dict[str, str] | None:
    """从环境变量读取可选代理，默认直连。"""
    proxy_url = os.environ.get("YAHOO_PROXY_URL") or os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy_url:
        return {"http": proxy_url, "https": proxy_url}
    return None


def _yahoo_fetch(symbol: str, range_str: str = "5d") -> list[dict] | None:
    """通过 Yahoo Finance API 获取 K 线；港股失败时回退新浪。

    每次请求独立 Session（避免多线程共享会话死锁）；不做 crumb 刷新
    （实测 Yahoo 对本机 IP  blanket 429，crumb 无效且 fc.yahoo.com 易挂起拖慢页面）。
    Yahoo 不可用时快速失败（429/异常/空结果）→ 港股回退新浪，其余返回 None。
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_str, "interval": "1d"}
    s = requests.Session()
    s.headers.update(_YAHOO_HEADERS)
    try:
        try:
            resp = s.get(url, params=params, timeout=10)
            if resp.status_code == 429:
                logger.warning(f"Yahoo 429 for {symbol}")
            else:
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
                    close = closes[i] if i < len(closes) else None
                    if close is None:
                        continue
                    import datetime as _dt
                    dt = _dt.datetime.fromtimestamp(ts_list[i])
                    open_price = opens[i] if i < len(opens) else None
                    high = highs[i] if i < len(highs) else None
                    low = lows[i] if i < len(lows) else None
                    volume = volumes[i] if i < len(volumes) else None
                    change_amount = round(close - prev_close, 4) if prev_close and prev_close > 0 else None
                    change_pct = round((close - prev_close) / prev_close * 100, 4) if prev_close and prev_close > 0 else None
                    items.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "open": round(open_price, 4) if open_price else None,
                        "high": round(high, 4) if high else None,
                        "low": round(low, 4) if low else None,
                        "close": round(close, 4),
                        "volume": int(volume) if volume else 0,
                        "change_pct": change_pct,
                        "change_amount": change_amount,
                        "prev_close": round(prev_close, 4) if prev_close else None,
                    })
                    prev_close = close
                if items:
                    return items
        except Exception as exc:
            logger.warning(f"Yahoo Finance fetch failed for {symbol}: {exc}")
        # Yahoo 不可用（429/异常/空结果）→ 港股回退新浪，其余快速返回 None
        if symbol.endswith(".HK"):
            return _sina_hk_kline(symbol, range_str)
        return None
    finally:
        s.close()


def _yfinance_fetch(symbol: str, range_str: str = "5d") -> list[dict] | None:
    """使用本地 yfinance 包作为 Yahoo chart API 的备用实现。"""
    try:
        import yfinance as yf

        frame = yf.download(
            symbol,
            period=range_str,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if frame is None or frame.empty:
            return None
        if hasattr(frame.columns, "levels"):
            frame.columns = frame.columns.get_level_values(0)
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(set(frame.columns)):
            return None
        items = []
        previous = None
        for index, row in frame.iterrows():
            close = _safe_float(row.get("Close"))
            if close is None:
                continue
            change_amount = round(close - previous, 4) if previous else None
            change_pct = round((close - previous) / previous * 100, 4) if previous else None
            items.append({
                "date": index.strftime("%Y-%m-%d"),
                "open": _safe_float(row.get("Open")),
                "high": _safe_float(row.get("High")),
                "low": _safe_float(row.get("Low")),
                "close": round(close, 4),
                "volume": int(_safe_float(row.get("Volume")) or 0),
                "change_pct": change_pct,
                "change_amount": change_amount,
                "prev_close": round(previous, 4) if previous else None,
            })
            previous = close
        return items or None
    except Exception as exc:
        logger.warning("local yfinance fallback failed for %s: %s", symbol, exc)
        return None


def _sina_hk_kline(yahoo_symbol: str, range_str: str = "5d") -> list[dict] | None:
    """新浪港股日K兜底（Yahoo 不可用时）。yahoo_symbol 形如 0700.HK / 700.HK → 新浪 hk00700"""
    code = yahoo_symbol.replace(".HK", "")
    sina_symbol = f"hk{code.zfill(5)}"
    _datalen_map = {"5d": 8, "1mo": 30, "3mo": 90, "6mo": 120, "1y": 250, "2y": 500, "5y": 1200, "ytd": 250, "max": 1200}
    datalen = _datalen_map.get(range_str, 30)
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": sina_symbol, "scale": "240", "ma": "no", "datalen": str(datalen)}
    try:
        resp = requests.get(
            url, params=params,
            headers={"User-Agent": _YAHOO_HEADERS["User-Agent"], "Referer": "https://finance.sina.com.cn"},
            timeout=8,
        )
        resp.encoding = "gbk"
        arr = resp.json()
        if not isinstance(arr, list) or not arr:
            return None
        items = []
        prev_close = None
        for row in arr:
            d = (row.get("day") or "")[:10]
            try:
                c = float(row.get("close"))
            except (TypeError, ValueError):
                continue
            o = _safe_float(row.get("open"))
            h = _safe_float(row.get("high"))
            l = _safe_float(row.get("low"))
            v = _safe_float(row.get("volume"))
            change_pct = None
            change_amount = None
            if prev_close and prev_close > 0:
                change_amount = round(c - prev_close, 4)
                change_pct = round((c - prev_close) / prev_close * 100, 4)
            items.append({
                "date": d,
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
        logger.warning(f"Sina HK kline failed for {yahoo_symbol}: {e}")
        return None


def _yahoo_fetch_cached(symbol: str, range_str: str = "5d") -> list[dict] | None:
    """带缓存的 _yahoo_fetch，5 分钟 TTL 避免重复慢速调用"""
    cache_key = f"{symbol}:{range_str}"
    now = time.time()
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < _CACHE_TTL:
            return data
    data = _yahoo_fetch(symbol, range_str)
    _cache[cache_key] = (now, data)
    return data


def _to_yahoo_symbol(market: str, code: str) -> str:
    """把业务代码转成 Yahoo 代码
    HK: 00700 → 0700.HK (去前导0, 加 .HK)
    US: AAPL → AAPL (不变)
    """
    if market == "HK":
        stripped = code.upper().replace(".HK", "").strip()
        try:
            return f"{int(stripped):04d}.HK"
        except ValueError:
            return f"{stripped.zfill(4)}.HK"
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
    klines = _yahoo_fetch_cached(idx["yahoo"], range_str="5d")
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
    klines = _yahoo_fetch_cached(yahoo_sym, range_str="5d")
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
    klines = _yahoo_fetch_cached(yahoo_sym, range_str="1mo") or []
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


# ─── 真实基本面（腾讯 gtimg 行情，覆盖估算） ─────────────────────────────────
# 数据源：腾讯 gtimg (qt.gtimg.cn)。覆盖港股/美股，含 PE/PB/股息/市值/52周高低，
# 且不像 Eastmoney 那样限流。字段为真实值；ROE/增速/南向/资金流等需 F10 或另源，保留估算。
# 字段索引（已实测校准）：
#   [3]=现价 [32]=涨跌幅% [39]=市盈率TTM [44]=总市值(亿元)
#   [48]=52周最高 [49]=52周最低 [58]=市净率(HK可靠) [59]=股息率%(HK可靠)
_GT_CACHE: dict[str, tuple[float, dict]] = {}
_GT_CACHE_TTL = 3600  # 1 小时缓存


def _to_gtimg(market: str, code: str) -> str:
    """业务代码 → 腾讯 gtimg 查询符号"""
    if market == "HK":
        return "hk" + code.zfill(5)          # 00700 → hk00700
    return "us" + code.upper()               # AAPL  → usAAPL


def _gtimg_fetch(q: str):
    import re as _re
    url = f"https://qt.gtimg.cn/q={q}"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.qq.com/"},
            timeout=12,
        )
        resp.encoding = "gbk"
        m = _re.search(r'="(.*)";', resp.text)
        if not m:
            return None
        return m.group(1).split("~")
    except Exception as e:
        logger.warning(f"gtimg fetch failed for {q}: {e}")
        return None


def _gt_num(arr, idx):
    try:
        v = arr[idx]
        if v in (None, ""):
            return None
        return float(v)
    except Exception:
        return None


def _parse_fundamentals(market: str, arr) -> dict:
    if not arr or len(arr) < 50:
        return {}
    real: dict = {}
    pe = _gt_num(arr, 39)          # 市盈率(TTM)
    pb = _gt_num(arr, 58)          # 市净率（HK 可靠；美股 gtimg 该位不准，跳过）
    div = _gt_num(arr, 59)         # 股息率(%)
    mcap = _gt_num(arr, 44)        # 总市值(亿元)
    high52 = _gt_num(arr, 48)      # 52周最高
    low52 = _gt_num(arr, 49)       # 52周最低
    price = _gt_num(arr, 3)
    if pe is not None and pe > 0:
        real["pe"] = round(pe, 2)
    if market == "HK" and pb is not None and pb > 0:
        real["pb"] = round(pb, 2)
    if market == "HK" and div is not None and div >= 0:
        real["divYield"] = round(div, 2)
    if mcap is not None and mcap > 0:
        real["marketCap"] = round(mcap, 1)   # 亿元
    if price and high52 and low52 and high52 > low52 > 0:
        pct = (price - low52) / (high52 - low52) * 100
        real["pePercentile"] = round(max(0.0, min(100.0, pct)), 1)
    return real


def _fetch_fundamentals(market: str) -> dict:
    """逐只抓取真实基本面；仅填充可获得的真实字段，缺失字段由前端回退估算。"""
    watchlist = DEFAULT_WATCHLIST.get(market, [])
    result: dict[str, dict] = {}
    for stock in watchlist:
        code = stock["code"]
        q = _to_gtimg(market, code)
        arr = _gtimg_fetch(q)
        real = _parse_fundamentals(market, arr) if arr else {}
        result[code] = {
            "code": code, "name": stock["name"], "real": real,
            "source": "gtimg" if real else None, "estimated": not real, "query": q,
        }
        time.sleep(0.05)
    return result


@router.get("/fundamentals/{market}")
def get_fundamentals(market: str, raw: bool = Query(default=False)):
    """真实基本面（腾讯 gtimg）：PE/PB/股息率/市值/52周估值分位。
    real 字段为真实值，前端用它覆盖估算；estimated=true 表示未取到真实值。"""
    market = market.upper()
    if market not in ("HK", "US"):
        return {"market": market, "error": "仅支持 HK / US"}
    cache_key = f"fund:{market}"
    now = time.time()
    if cache_key in _GT_CACHE:
        ts, data = _GT_CACHE[cache_key]
        if now - ts < _GT_CACHE_TTL:
            return {"market": market, "items": data, "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                    "source": "gtimg", "cached": True}
    data = _fetch_fundamentals(market)
    _GT_CACHE[cache_key] = (now, data)
    out = {"market": market, "items": data, "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
           "source": "gtimg"}
    if raw:
        out["raw"] = {code: _gtimg_fetch(_to_gtimg(market, code)) for code in data}
    return out


# ─── 南向资金（Eastmoney 港股通） ──────────────────────────────────────────────
_SB_CACHE: dict[str, tuple[float, dict]] = {}
_SB_CACHE_TTL = 1800  # 30 分钟


def _fetch_southbound() -> dict:
    """港股通南向资金：聚合净买入(最新+20日) + 个股港股通持股变化(尽力)。"""
    out = {"totalNet20d": None, "latestNet": None, "latestDate": None, "byStock": {}, "source": None}
    # 1) 聚合：港股通南向净买入时序
    kline_url = "https://push2.eastmoney.com/api/qt/kamt.kline/get"
    kp = {"fields1": "f1,f3", "fields2": "f51,f52", "klt": "101", "lmt": "30",
          "ut": "b2884a393a59ad64003c8a8bbb4d8fb9", "invt": "2"}
    try:
        r = requests.get(kline_url, params=kp, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/hsgt/index.html"}, timeout=12)
        j = r.json().get("data") or {}
        klines = j.get("klines") or []
        vals = []
        for row in klines:
            parts = row.split(",")
            if len(parts) >= 2:
                try:
                    vals.append((parts[0], float(parts[1])))
                except Exception:
                    pass
        if vals:
            out["latestDate"] = vals[-1][0]
            out["latestNet"] = round(vals[-1][1], 2)
            out["totalNet20d"] = round(sum(v for _, v in vals[-20:]), 2)
            out["source"] = "eastmoney"
    except Exception as e:
        logger.warning(f"Eastmoney southbound kline failed: {e}")
    # 2) 个股：港股通标的持股变化（尽力，失败不影响聚合）
    try:
        clist_url = "https://push2.eastmoney.com/api/qt/clist/get"
        cp = {"pn": "1", "pz": "2000", "fid": "f62", "fs": "m:105+t:3",
              "fields": "f12,f14,f62,f63,f64,f65", "invt": "2", "fltt": "2"}
        r2 = requests.get(clist_url, params=cp, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/hsgt/index.html"}, timeout=12)
        arr = (r2.json().get("data") or {}).get("diff") or []
        for it in arr:
            code = str(it.get("f12") or "").zfill(5)
            chg = _em_num(it.get("f65"))  # 持股变化(估算，字段待校准)
            if chg is not None:
                out["byStock"][code] = round(chg, 2)
    except Exception as e:
        logger.warning(f"Eastmoney southbound byStock failed: {e}")
    return out


@router.get("/southbound")
def get_southbound(raw: bool = Query(default=False)):
    """港股通南向资金（Eastmoney）。聚合真实；个股持股变化尽力获取。"""
    cache_key = "southbound"
    now = time.time()
    if cache_key in _SB_CACHE:
        ts, data = _SB_CACHE[cache_key]
        if now - ts < _SB_CACHE_TTL:
            data = {**data, "cached": True}
            return data
    data = _fetch_southbound()
    _SB_CACHE[cache_key] = (now, data)
    if raw:
        data = {**data, "raw_note": "见服务端日志/调试"}
    return data

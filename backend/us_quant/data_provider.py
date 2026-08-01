"""US Quant 数据源 provider — 自动识别系统代理 + 多源实时行情。

此前采集不到的真正根因：后端 uvicorn 进程既没读 macOS 系统代理设置，
也没有 HTTP_PROXY 环境变量，是裸连出网的；而 Yahoo 等免费源在大陆网络被
墙 / 限流，于是请求失败 → 一路降级到离线模拟。

现在的架构（数据源优先级，全部经本机代理出网）：
  1. 自动识别出网代理：环境变量 HTTP(S)_PROXY，否则在 macOS 上读系统代理
     (scutil --proxy)。让后端像浏览器一样走代理。
  2. 主数据源 Nasdaq 官方 API（免费、无需 key、真实数据）。
     股票用 assetclass=stocks，ETF 必须用 assetclass=etf（否则 Symbol not exists）。
  3. VIX 波动率：CBOE 官方 CSV（Nasdaq 不带 VIX）。
  4. 兜底：Yahoo Finance（经代理），仍可能被限流(429)。
  5. 最后兜底：确定性离线模拟——仅在以上全部不可达时使用，避免页面空白。

所有外部请求带 60s TTL 缓存与失败重试（429/5xx 退避）。
"""

from __future__ import annotations

import logging
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ─── 已知 ETF（Nasdaq 对 ETF 必须用 assetclass=etf）──────────────────────
_KNOWN_ETFS = {
    "SPY", "QQQ", "IWM", "RSP", "DIA", "VTI", "VOO", "VIG", "IVE", "IWD",
    "XLK", "SMH", "SOXX", "XLC", "XLY", "XLF", "XLI", "XLV", "XLE", "XLB",
    "XLP", "XLU", "XLRE", "XBI", "XRT", "XHB", "XME", "KBE", "KRE", "ARKK",
}

_RANGE_DAYS = {
    "1d": 1, "5d": 5, "1mo": 22, "2mo": 44, "3mo": 66, "6mo": 126, "1y": 252,
}


def _range_to_days(range_str: str) -> int:
    return _RANGE_DAYS.get(range_str, 22)


# ─── 代理自动识别 ──────────────────────────────────────────────────────────
_PROXY_URL: Optional[str] = None
_PROXY_PROBED = False


def _detect_proxy() -> Optional[str]:
    """优先取环境变量，否则在 macOS 上读取系统代理(scutil)。"""
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(key)
        if v:
            return v
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["/usr/sbin/scutil", "--proxy"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            http_host = http_port = https_host = https_port = None
            http_en = https_en = False
            for line in out.splitlines():
                s = line.strip()
                if s.startswith("HTTPEnable") and ": 1" in s:
                    http_en = True
                elif s.startswith("HTTPProxy :"):
                    http_host = s.split(":", 1)[1].strip()
                elif s.startswith("HTTPPort :"):
                    http_port = s.split(":", 1)[1].strip()
                elif s.startswith("HTTPSEnable") and ": 1" in s:
                    https_en = True
                elif s.startswith("HTTPSProxy :"):
                    https_host = s.split(":", 1)[1].strip()
                elif s.startswith("HTTPSPort :"):
                    https_port = s.split(":", 1)[1].strip()
            if https_en and https_host and https_port:
                return f"http://{https_host}:{https_port}"
            if http_en and http_host and http_port:
                return f"http://{http_host}:{http_port}"
        except Exception as exc:
            logger.debug(f"[us_quant] proxy detect failed: {exc}")
    return None


def _get_proxies() -> Optional[dict]:
    global _PROXY_URL, _PROXY_PROBED
    if not _PROXY_PROBED:
        _PROXY_URL = _detect_proxy()
        _PROXY_PROBED = True
        if _PROXY_URL:
            logger.info(f"[us_quant] 使用系统代理出网: {_PROXY_URL}")
    if not _PROXY_URL:
        return None
    return {"http": _PROXY_URL, "https": _PROXY_URL}


# ─── 请求会话（带重试）────────────────────────────────────────────────────
_SESSION: Optional[requests.Session] = None


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        s = requests.Session()
        try:
            retry = requests.packages.urllib3.util.retry.Retry(
                total=2, backoff_factor=0.3,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["GET"]),
            )
            adapter = requests.adapters.HTTPAdapter(max_retries=retry)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
        except Exception:
            pass
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "application/json",
        })
        # trust_env 是 Session 级属性：关掉，避免意外继承环境中的 HTTP_PROXY
        s.trust_env = False
        _SESSION = s
    return _SESSION


def _get_json(url: str, params: Optional[dict] = None) -> Optional[dict]:
    try:
        resp = _session().get(url, params=params, proxies=_get_proxies(),
                              timeout=(5, 12))
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as exc:
        logger.debug(f"[us_quant] GET json failed {url}: {exc}")
        return None


def _get_text(url: str) -> Optional[str]:
    try:
        resp = _session().get(url, proxies=_get_proxies(),
                              timeout=(5, 12))
        if resp.status_code != 200:
            return None
        return resp.text
    except Exception as exc:
        logger.debug(f"[us_quant] GET text failed {url}: {exc}")
        return None


def _num(s) -> Optional[float]:
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    if s in ("", "N/A", "NA", "—", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ─── Nasdaq 实时源 ────────────────────────────────────────────────────────
def _assetclass(symbol: str) -> str:
    return "etf" if symbol in _KNOWN_ETFS else "stocks"


def _nasdaq_historical(symbol: str, assetclass: str, days: int) -> Optional[list[dict]]:
    to_d = date.today()
    from_d = to_d - timedelta(days=int(days * 1.7) + 6)
    url = f"https://api.nasdaq.com/api/quote/{symbol}/historical"
    params = {
        "assetclass": assetclass,
        "fromdate": from_d.strftime("%Y-%m-%d"),
        "todate": to_d.strftime("%Y-%m-%d"),
    }
    data = _get_json(url, params=params)
    if not data or data.get("data") is None:
        return None
    rows = data["data"].get("tradesTable", {}).get("rows", [])
    items: list[dict] = []
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%m/%d/%Y").strftime("%Y-%m-%d")
        except Exception:
            continue
        close = _num(r.get("close"))
        if close is None:
            continue
        items.append({
            "date": d,
            "open": _num(r.get("open")),
            "high": _num(r.get("high")),
            "low": _num(r.get("low")),
            "close": close,
            "volume": int((r.get("volume") or "0").replace(",", "")) if r.get("volume") else 0,
        })
    if len(items) > days:
        items = items[-days:]
    return items if items else None


def _nasdaq_info(symbol: str, assetclass: str) -> Optional[dict]:
    """实时报价（last sale + 涨跌幅）。"""
    url = f"https://api.nasdaq.com/api/quote/{symbol}/info"
    data = _get_json(url, params={"assetclass": assetclass})
    if not data or data.get("data") is None:
        return None
    pd = data["data"].get("primaryData", {})
    price = _num(pd.get("lastSalePrice"))
    if price is None:
        return None
    change = _num(pd.get("netChange"))
    pct = _num(pd.get("percentageChange"))
    vol = _num(pd.get("volume"))
    return {
        "price": price,
        "prev_close": round(price - change, 4) if change is not None else None,
        "close": price,
        "change": change,
        "change_pct": pct,
        "volume": int(vol) if vol is not None else None,
        "currency": "USD",
        "exchange": data["data"].get("exchange", ""),
        "is_real_time": pd.get("isRealTime", False),
    }


# ─── CBOE VIX ─────────────────────────────────────────────────────────────
def _cboe_vix_klines(days: int) -> Optional[list[dict]]:
    url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    txt = _get_text(url)
    if not txt:
        return None
    items: list[dict] = []
    for line in txt.strip().splitlines():
        if line.startswith("Date") or not line.strip():
            continue
        p = line.split(",")
        if len(p) < 5:
            continue
        try:
            d = datetime.strptime(p[0], "%m/%d/%Y").strftime("%Y-%m-%d")
            items.append({
                "date": d,
                "open": float(p[1]), "high": float(p[2]),
                "low": float(p[3]), "close": float(p[4]), "volume": 0,
            })
        except Exception:
            continue
    items.reverse()  # CSV 日期降序 → 升序
    if len(items) > days:
        items = items[-days:]
    return items if items else None


# ─── Yahoo 兜底（经代理）──────────────────────────────────────────────────
def _fetch_yahoo_live(symbol: str, range_str: str) -> Optional[list[dict]]:
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"range": range_str, "interval": "1d"}
        resp = _session().get(url, params=params, proxies=_get_proxies(),
                              trust_env=False, timeout=(4, 8))
        if resp.status_code != 200:
            return None
        result = resp.json()["chart"]["result"][0]
        ts = result.get("timestamp", [])
        q = result.get("indicators", {}).get("quote", [{}])[0]
        o, h, l, c, v = (q.get(k, []) for k in ("open", "high", "low", "close", "volume"))
        items = []
        for i in range(len(ts)):
            close = c[i] if i < len(c) and c[i] is not None else None
            if close is None:
                continue
            items.append({
                "date": datetime.fromtimestamp(ts[i]).strftime("%Y-%m-%d"),
                "open": round(o[i], 4) if i < len(o) and o[i] else None,
                "high": round(h[i], 4) if i < len(h) and h[i] else None,
                "low": round(l[i], 4) if i < len(l) and l[i] else None,
                "close": round(close, 4),
                "volume": int(v[i]) if i < len(v) and v[i] else 0,
            })
        return items if items else None
    except Exception as exc:
        logger.debug(f"[us_quant] Yahoo failed for {symbol}: {exc}")
        return None


# ─── 离线确定性模拟（仅最后兜底）──────────────────────────────────────────
_BASE_PRICE = {
    "SPY": 560.0, "QQQ": 480.0, "IWM": 220.0, "RSP": 180.0, "^VIX": 15.0,
    "AAPL": 195.0, "MSFT": 420.0, "GOOGL": 175.0, "AMZN": 185.0,
    "NVDA": 125.0, "TSLA": 250.0, "META": 510.0, "TSM": 175.0,
    "XLK": 230.0, "SMH": 255.0, "SOXX": 240.0, "XLC": 95.0, "XLY": 230.0,
    "XLF": 48.0, "XLI": 130.0, "XLV": 145.0, "XLE": 95.0, "XLB": 95.0,
    "XLP": 80.0, "XLU": 78.0, "XLRE": 42.0,
}


def _symbol_seed(symbol: str) -> int:
    h = 0
    for ch in symbol:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


def _synthetic_klines(symbol: str, days: int) -> list[dict]:
    rng = random.Random(_symbol_seed(symbol))
    base = _BASE_PRICE.get(symbol, 50.0 + (_symbol_seed(symbol) % 400))
    drift = (rng.random() - 0.42) * 0.0018
    vol = 0.010 + rng.random() * 0.022
    price = base * (0.82 + rng.random() * 0.12)
    today = date.today()
    d = today
    items: list[dict] = []
    count = 0
    while count < days:
        if d.weekday() < 5:
            ret = drift + rng.gauss(0, vol)
            open_p = price
            close_p = max(0.5, open_p * (1 + ret))
            amp = abs(rng.gauss(0, vol / 2))
            high_p = max(open_p, close_p) * (1 + amp)
            low_p = min(open_p, close_p) * (1 - amp)
            volume = int((1_000_000 + rng.random() * 9_000_000) * (1 + abs(ret) * 18))
            items.append({
                "date": d.strftime("%Y-%m-%d"),
                "open": round(open_p, 4), "high": round(high_p, 4),
                "low": round(low_p, 4), "close": round(close_p, 4),
                "volume": volume,
            })
            price = close_p
            count += 1
        d -= timedelta(days=1)
    items.reverse()
    return items


# ─── 公共接口 ─────────────────────────────────────────────────────────────
_KLINE_CACHE: dict = {}
_KLINE_TTL = 300.0


def get_klines(symbol: str, range_str: str = "1mo") -> Optional[list[dict]]:
    """获取 K 线：数据库优先 → 多源采集 → 离线模拟。

    数据流：
      1. 先读 USStockDaily 表（已有数据直接返回）
      2. 表里没有 → 触发采集（gstock → akshare → Nasdaq → Yahoo → 合成）→ 入库
      3. 再次从库读取返回
    """
    days = max(_range_to_days(range_str), 2)
    key = (symbol, range_str)
    now = time.time()
    cached = _KLINE_CACHE.get(key)
    if cached and (now - cached[0]) < _KLINE_TTL:
        return cached[1]

    # 1. 优先从数据库读（已有数据则直接返回）
    try:
        from us_quant.collector import get_db_klines
        db_result = get_db_klines(symbol)
        if db_result and len(db_result) >= days * 0.5:
            if len(db_result) > days:
                db_result = db_result[-days:]
            _KLINE_CACHE[key] = (now, db_result)
            return db_result
    except Exception as exc:
        logger.debug(f"[us_quant] get_klines db read failed {symbol}: {exc}")

    # 2. 数据库数据不足，从外部源采集（采集器会自动入库）
    result: Optional[list[dict]] = None
    try:
        if symbol == "^VIX":
            result = _cboe_vix_klines(days) or _fetch_yahoo_live(symbol, range_str)
        else:
            # 优先通过采集器入库
            try:
                from us_quant.collector import collect_symbol
                collect_symbol(symbol)
                from us_quant.collector import get_db_klines as get_db
                db_result = get_db(symbol)
                if db_result and len(db_result) >= 2:
                    result = db_result
            except Exception:
                pass

            if not result:
                ac = _assetclass(symbol)
                result = _nasdaq_historical(symbol, ac, days)
                if not result and ac == "stocks":
                    result = _nasdaq_historical(symbol, "etf", days)
            if not result:
                result = _fetch_yahoo_live(symbol, range_str)
        if result and len(result) < days * 0.5:
            logger.info(f'[us_quant] {symbol}: 真实数据仅 {len(result)} 条 (需求 {days})，切换到合成数据')
            result = _synthetic_klines(symbol, days)
        if not result:
            result = _synthetic_klines(symbol, days)
    except Exception as exc:
        logger.warning(f"[us_quant] get_klines fallback for {symbol}: {exc}")
        try:
            result = _synthetic_klines(symbol, days)
        except Exception:
            result = None

    if result and len(result) > days:
        result = result[-days:]

    _KLINE_CACHE[key] = (now, result)
    return result


def get_klines_batch(symbols: list[str], range_str: str = "1mo",
                      max_workers: int = 4) -> dict[str, Optional[list[dict]]]:
    """并行批量拉取多个标的的 K 线，把串行耗时压成「取最大」而非「累加」。

    个别标的失败（限流/超时）不影响其余，失败项返回 None，由调用方决定降级。
    """
    syms = list(dict.fromkeys(symbols))  # 去重保序
    results: dict[str, Optional[list[dict]]] = {}
    if not syms:
        return results
    with ThreadPoolExecutor(max_workers=min(max_workers, len(syms))) as ex:
        fut_to_sym = {ex.submit(get_klines, s, range_str): s for s in syms}
        for fut in as_completed(fut_to_sym):
            s = fut_to_sym[fut]
            try:
                results[s] = fut.result()
            except Exception as exc:
                logger.debug(f"[us_quant] batch klines failed {s}: {exc}")
                results[s] = None
    # 失败项串行重试（缓解 Nasdaq 偶发 429 限流导致的丢数据）
    for _attempt in range(2):
        _failed = [s for s in syms if results.get(s) is None]
        if not _failed:
            break
        time.sleep(1.2)
        for s in _failed:
            try:
                results[s] = get_klines(s, range_str)
            except Exception as exc:
                logger.debug(f"[us_quant] batch retry failed {s}: {exc}")
                results[s] = None
    for s in syms:
        results.setdefault(s, None)
    return results


def get_quote(symbol: str) -> Optional[dict]:
    """获取单只最新行情：优先 Nasdaq 实时报价，否则用 K 线末两根推算。"""
    if symbol == "^VIX":
        k = get_klines(symbol, "5d")
        if not k or len(k) < 1:
            return None
        last = k[-1]["close"]
        prev = k[-2]["close"] if len(k) >= 2 else last
        return {"price": last, "prev_close": prev, "close": last,
                "currency": "USD", "exchange": "CBOE", "is_real_time": False}
    ac = _assetclass(symbol)
    info = _nasdaq_info(symbol, ac)
    if not info and ac == "stocks":
        info = _nasdaq_info(symbol, "etf")
    if info:
        return info
    k = get_klines(symbol, "5d")
    if not k or len(k) < 1:
        return None
    last = k[-1]["close"]
    prev = k[-2]["close"] if len(k) >= 2 else last
    return {"price": last, "prev_close": prev, "close": last,
            "currency": "USD", "exchange": "", "is_real_time": False}


# ─── 实时源可用性（带 TTL 缓存）──────────────────────────────────────────
_LIVE_CACHE: dict = {"ok": None, "ts": 0.0}
_LIVE_TTL = 300.0


def is_live_available() -> bool:
    """探活：Nasdaq 实时源是否可达（带 TTL 缓存）。"""
    now = time.time()
    if _LIVE_CACHE["ok"] is not None and (now - _LIVE_CACHE["ts"]) < _LIVE_TTL:
        return _LIVE_CACHE["ok"]
    ok = _nasdaq_info("AAPL", "stocks") is not None
    _LIVE_CACHE.update(ok=ok, ts=now)
    return ok


def reset_live_cache() -> None:
    """强制下次重新探活 + 清代理缓存 + 清 K 线缓存（配置变更后调用）。"""
    _LIVE_CACHE["ok"] = None
    _LIVE_CACHE["ts"] = 0.0
    _KLINE_CACHE.clear()
    global _PROXY_PROBED, _PROXY_URL
    _PROXY_PROBED = False
    _PROXY_URL = None

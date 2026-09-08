"""US Quant 数据源 provider。

Nasdaq、CBOE 和 Yahoo 请求函数仅供定时采集器使用。采集失败时
保持缺失，不生成合成行情。页面、策略和回测的公共读取函数只访问
``USStockDaily``，保证数据口径一致。
"""

from __future__ import annotations

import logging
import os
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
    "1d": 1, "5d": 5, "1mo": 22, "2mo": 44, "3mo": 66, "6mo": 126,
    "1y": 252, "2y": 504, "3y": 756, "5y": 1260,
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
    # CBOE 当前 CSV 为升序；显式排序兼容上游未来调整顺序，确保截取的是最新 N 日。
    items.sort(key=lambda item: item["date"])
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
        # Yahoo adjclose（复权收盘价）
        adj = result.get("indicators", {}).get("adjclose", [{}])[0] if "adjclose" in result.get("indicators", {}) else {}
        adjclose = adj.get("adjclose", []) if adj else []

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
                "adj_close": round(adjclose[i], 4) if i < len(adjclose) and adjclose[i] else None,
            })
        return items if items else None
    except Exception as exc:
        logger.debug(f"[us_quant] Yahoo failed for {symbol}: {exc}")
        return None


# ─── 公共只读接口 ─────────────────────────────────────────────────────────
def get_klines(symbol: str, range_str: str = "1mo") -> Optional[list[dict]]:
    """只从 ``USStockDaily`` 读取 K 线，不采集、不回退、不返回合成行情。

    外部数据源只允许由 ``us_quant.collector`` 的定时采集链路调用并先落库；
    页面、策略和回测统一通过本函数读取数据库快照。
    """
    days = max(_range_to_days(range_str), 2)
    try:
        from us_quant.collector import get_db_klines
        rows = get_db_klines(symbol)
    except Exception as exc:
        logger.exception("[us_quant] database K-line read failed for %s", symbol)
        raise
    if not rows:
        return None
    return rows[-days:]


def get_klines_batch(symbols: list[str], range_str: str = "1mo",
                      max_workers: int = 4) -> dict[str, Optional[list[dict]]]:
    """并行批量读取数据库 K 线；个别读库失败不影响其余标的。"""
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
    for s in syms:
        results.setdefault(s, None)
    return results


def get_quote(symbol: str) -> Optional[dict]:
    """从数据库最新两根日 K 生成收盘行情，不在读取路径访问外部报价源。"""
    k = get_klines(symbol, "5d")
    if not k or len(k) < 1:
        return None
    last = k[-1]["close"]
    prev = k[-2]["close"] if len(k) >= 2 else last
    return {"price": last, "prev_close": prev, "close": last,
            "currency": "USD", "exchange": "CBOE" if symbol == "^VIX" else "",
            "is_real_time": False, "source": "database", "as_of": k[-1].get("date")}


# ─── 实时源可用性（带 TTL 缓存）──────────────────────────────────────────
_LIVE_CACHE: dict = {"ok": None, "ts": 0.0}
_LIVE_TTL = 300.0


def cached_live_availability() -> Optional[bool]:
    """Return a fresh probe result without making a network request.

    ``None`` deliberately means that no recent probe result exists.  Read-only
    dashboard endpoints can use this to avoid turning a page load into an
    external availability check; the explicit system-status endpoint remains
    responsible for refreshing the probe when needed.
    """
    cached = _LIVE_CACHE.get("ok")
    if cached is None or (time.time() - _LIVE_CACHE.get("ts", 0.0)) >= _LIVE_TTL:
        return None
    return bool(cached)


def is_live_available() -> bool:
    """探活：Nasdaq 实时源是否可达（带 TTL 缓存）。"""
    cached = cached_live_availability()
    if cached is not None:
        return cached
    now = time.time()
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

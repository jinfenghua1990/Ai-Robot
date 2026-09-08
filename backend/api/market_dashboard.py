# -*- coding: utf-8 -*-
"""市场仪表盘聚合接口（Koyfin 风格总览）

数据源全部为国内直连（腾讯行情 / 新浪行情 / 东方财富要闻），快速稳定，不依赖外网代理。
一次性聚合：美股指数 / 全球指数 / 货币 / 市场要闻 / 指数对比K线 / 行业板块 / 全球回报 / 自选行情。
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter

router = APIRouter(prefix="/api/market-dashboard", tags=["market-dashboard"])

# ─── 常量 ─────────────────────────────────────────────────────────────────────

_TX_QUOTE = "https://qt.gtimg.cn/q={codes}"
_TX_KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{cnt},qfq"
_SINA_QUOTE = "https://hq.sinajs.cn/list={codes}"
_SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}
_EM_NEWS = (
    "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
    "?client=web&biz=web_news_col&column=350&order=1&needInteractData=0"
    "&page_index=1&page_size=8&req_trace=md{ts}"
)
# 新浪美股K线（指数 .DJI/.INX/.IXIC，个股/ETF 直接用代码）
_SINA_US_KLINE = "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20_t=/US_MinKService.getDailyK?symbol={sym}&___qn=3"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# 美股指数（腾讯代码, 显示代码, 中文名）——罗素2000 用追踪 ETF IWM（腾讯不支持 usRUT）
US_INDICES = [
    ("usDJI", "DJI", "道琼斯"),
    ("usINX", "SPX", "标普500"),
    ("usIXIC", "IXIC", "纳斯达克"),
    ("usNDX", "NDX", "纳斯达克100"),
    ("usIWM", "RUT", "罗素2000"),
]
# 腾讯美股指数代码 → 新浪美股K线代码
TX2SINA = {"usDJI": ".DJI", "usINX": ".INX", "usIXIC": ".IXIC", "usNDX": ".NDX", "usIWM": "IWM"}
# 全球指数（代码, 显示代码, 中文名）——美股用腾讯（新浪 int_ 美股数据陈旧），其余用新浪国际
GLOBAL_INDICES = [
    ("tx:usDJI", "US.DJI", "道琼斯"),
    ("tx:usINX", "US.SPX", "标普500"),
    ("tx:usIXIC", "US.IXIC", "纳斯达克"),
    ("tx:hkHSI", "HK.HSI", "恒生指数"),
    ("int_nikkei", "JP.N225", "日经225"),
    ("int_ftse", "UK.FTSE", "伦敦富时"),
    ("int_dax", "DE.DAX", "德国DAX"),
    ("int_cac", "FR.CAC", "法国CAC"),
]
# 货币（新浪代码, 显示名）
CURRENCIES = [
    ("fx_susdcny", "USD/CNY", "美元/人民币"),
    ("fx_sgbpusd", "GBP/USD", "英镑/美元"),
    ("fx_seurusd", "EUR/USD", "欧元/美元"),
    ("fx_susdjpy", "USD/JPY", "美元/日元"),
    ("fx_saudusd", "AUD/USD", "澳元/美元"),
    ("fx_susdcad", "USD/CAD", "美元/加元"),
]
# 行业板块 ETF（代码, 中文名）
SECTOR_ETFS = [
    ("XLK", "科技"), ("SMH", "半导体"), ("SOXX", "芯片"), ("XLC", "通信"),
    ("XLY", "消费"), ("XLF", "金融"), ("XLI", "工业"), ("XLV", "医疗"),
    ("XLE", "能源"), ("XLB", "材料"), ("XLP", "必需消费"), ("XLU", "公用事业"),
    ("XLRE", "房地产"),
]
# 全球回报：新浪美股K线（.INX/.DJI/.IXIC 数据自2004年）+ 腾讯港股K线
GLOBAL_RETURNS = [
    (".INX", "美国 · 标普500"),
    ("hkHSI", "香港 · 恒生指数"),
    (".DJI", "美国 · 道琼斯"),
    (".IXIC", "美国 · 纳斯达克"),
]

_cache: Dict[str, tuple[float, Any]] = {}
_TTL = 60


def _cached(key: str, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _get(url: str, timeout: int = 10, **kw) -> Optional[requests.Response]:
    headers = dict(_HEADERS)
    extra = kw.pop("headers", None)
    if extra:
        headers.update(extra)
    try:
        return requests.get(url, headers=headers, timeout=timeout, **kw)
    except Exception:
        return None


# ─── 腾讯行情解析 ─────────────────────────────────────────────────────────────

def _parse_tx_quote(line: str) -> Optional[dict]:
    """v_usDJI="200~名称~代码~现价~昨收~今开~成交量~...~时间~涨跌额~涨跌幅% ~最高~最低~..." """
    if '"' not in line:
        return None
    parts = line.split('"')
    if len(parts) < 2:
        return None
    fields = parts[1].split("~")
    if len(fields) < 36:
        return None
    return {
        "name": fields[1],
        "symbol": fields[2].lstrip("."),
        "price": _f(fields[3]),
        "prev_close": _f(fields[4]),
        "open": _f(fields[5]),
        "time": fields[30] or "",
        "change": _f(fields[31]),
        "change_pct": _f(fields[32]),
        "high": _f(fields[33]),
        "low": _f(fields[34]),
    }


def _tx_quotes(codes: List[str]) -> Dict[str, dict]:
    if not codes:
        return {}
    resp = _get(_TX_QUOTE.format(codes=",".join(codes)))
    if not resp or not resp.text:
        return {}
    try:
        text = resp.content.decode("gbk", errors="ignore")
    except Exception:
        text = resp.text
    out: Dict[str, dict] = {}
    for line in text.splitlines():
        m = re.match(r'v_(\w+)="', line)
        if not m:
            continue
        q = _parse_tx_quote(line)
        if q:
            out[m.group(1)] = q
    return out


def _tx_kline(sym: str, cnt: int = 320) -> Optional[List[dict]]:
    """腾讯日K：[date, open, close, high, low, volume]"""
    resp = _get(_TX_KLINE.format(sym=sym, cnt=cnt))
    if not resp:
        return None
    try:
        data = resp.json()
        node = (data.get("data") or {}).get(sym) or {}
        days = node.get("day") or node.get("qfqday") or []
    except Exception:
        return None
    out = []
    for row in days:
        if len(row) < 5:
            continue
        out.append({
            "date": row[0],
            "open": _f(row[1]),
            "close": _f(row[2]),
            "high": _f(row[3]),
            "low": _f(row[4]),
            "volume": _f(row[5]) if len(row) > 5 else None,
        })
    return out or None


# ─── 新浪行情解析 ─────────────────────────────────────────────────────────────

def _sina_quotes(codes: List[str], pat: str = r'var hq_str_(\w+)="(.*?)"') -> Dict[str, List[str]]:
    if not codes:
        return {}
    resp = _get(_SINA_QUOTE.format(codes=",".join(codes)), headers=_SINA_HEADERS)
    if not resp or not resp.text:
        return {}
    try:
        text = resp.content.decode("gbk", errors="ignore")
    except Exception:
        text = resp.text
    out: Dict[str, List[str]] = {}
    for m in re.finditer(pat, text):
        out[m.group(1)] = m.group(2).split(",")
    return out


def _sina_us_kline(sym: str, limit: Optional[int] = None) -> Optional[List[dict]]:
    """新浪美股日K（指数传 .DJI/.INX/.IXIC，个股/ETF 直接传代码）
    返回 [{date, open, close, high, low, volume}]，数据从 2004 年至今。"""
    resp = _get(_SINA_US_KLINE.format(sym=sym), timeout=12)
    if not resp or not resp.text:
        return None
    m = re.search(r"\(\[(.*)\]\)", resp.text, re.S)
    if not m:
        return None
    rows = []
    for it in re.finditer(r'\{"d":"([^"]+)","o":"([^"]*)","h":"([^"]*)","l":"([^"]*)","c":"([^"]*)","v":"([^"]*)"[^}]*\}', m.group(1)):
        d, o, h, l, c, v = it.groups()
        rows.append({
            "date": d, "open": _f(o), "close": _f(c),
            "high": _f(h), "low": _f(l), "volume": _f(v),
        })
    if not rows:
        return None
    if limit:
        rows = rows[-limit:]
    return rows


def _fetch_currencies() -> List[dict]:
    quotes = _sina_quotes([c for c, _, _ in CURRENCIES])
    rows = []
    for code, pair, name in CURRENCIES:
        f = quotes.get(code)
        if not f or len(f) < 13:
            rows.append({"code": code, "pair": pair, "name": name, "price": None, "change": None, "change_pct": None})
            continue
        rows.append({
            "code": code, "pair": pair, "name": name,
            "price": _f(f[1]),
            "change": _f(f[11]),
            "change_pct": _f(f[10]),
            "time": f[0],
        })
    return rows


def _fetch_global_indices() -> List[dict]:
    """全球指数实时：美股/港股用腾讯，其余用新浪国际（名称,现价,涨跌额,涨跌幅%）"""
    sina_codes = [c for c, _, _ in GLOBAL_INDICES if c.startswith("int_")]
    tx_codes = [c[3:] for c, _, _ in GLOBAL_INDICES if c.startswith("tx:")]
    s_quotes = _sina_quotes(sina_codes)
    t_quotes = _tx_quotes(tx_codes)
    rows = []
    for code, sym, name in GLOBAL_INDICES:
        if code.startswith("tx:"):
            q = t_quotes.get(code[3:])
            rows.append({
                "code": sym, "name": name,
                "price": q.get("price") if q else None,
                "change": q.get("change") if q else None,
                "change_pct": q.get("change_pct") if q else None,
            })
            continue
        f = s_quotes.get(code)
        if not f or len(f) < 4 or not f[1]:
            rows.append({"code": sym, "name": name, "price": None, "change": None, "change_pct": None})
            continue
        rows.append({
            "code": sym, "name": name,
            "price": _f(f[1]), "change": _f(f[2]), "change_pct": _f(f[3]),
        })
    return rows


# ─── 东财要闻 ─────────────────────────────────────────────────────────────────

def _fetch_news() -> List[dict]:
    resp = _get(_EM_NEWS.format(ts=int(time.time())))
    if not resp:
        return []
    try:
        data = resp.json()
        items = (data.get("data") or {}).get("list") or []
    except Exception:
        return []
    rows = []
    for it in items[:8]:
        rows.append({
            "title": it.get("title") or "",
            "summary": (it.get("summary") or "")[:120],
            "time": it.get("showTime") or "",
            "media": it.get("mediaName") or "",
            "url": it.get("url") or "",
        })
    return rows


# ─── 板块 ─────────────────────────────────────────────────────────────────────

def _fetch_sectors() -> List[dict]:
    """13 行业 ETF + SPY：当日行情（腾讯）+ 5d/20d/60d 区间回报（腾讯K线并行）"""
    etfs = [e for e, _ in SECTOR_ETFS] + ["SPY"]

    def _kl(sym):
        # 美股ETF用新浪K线（腾讯us前缀日K仅返回1根）
        return sym, _sina_us_kline(sym, 90)

    klines: Dict[str, Optional[List[dict]]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(_kl, s) for s in etfs]
        for f in as_completed(futs):
            try:
                sym, kl = f.result()
                klines[sym] = kl
            except Exception:
                pass

    quotes = _tx_quotes(["us" + s for s in etfs])
    rows = []
    for etf, name in SECTOR_ETFS:
        kl = klines.get(etf)
        q = quotes.get("us" + etf) or {}
        closes = [k["close"] for k in kl if k.get("close")] if kl else []
        ret = lambda n: (closes[-1] / closes[-n] - 1) * 100 if len(closes) >= n and closes[-n] else None
        rows.append({
            "etf": etf, "name": name,
            "price": q.get("price"),
            "change_pct": q.get("change_pct"),
            "ret_5d": ret(5),
            "ret_20d": ret(20),
            "ret_60d": ret(60),
        })
    return rows


# ─── 全球回报 ─────────────────────────────────────────────────────────────────

def _fetch_global_returns() -> List[dict]:
    """基于腾讯K线计算 1Y/3Y/5Y 区间回报（约 250/750/1250 个交易日）"""

    def _calc(item):
        sym, label = item
        # 美股指数（.INX/.DJI/.IXIC）用新浪K线（数据到2004年，足够5年），港股恒生用腾讯K线
        if sym.startswith("."):
            kl = _sina_us_kline(sym, 1280)
        else:
            kl = _tx_kline(sym, 1280)
        if not kl:
            return sym, label, None
        closes = [k["close"] for k in kl if k.get("close")]
        if len(closes) < 2:
            return sym, label, None
        last = closes[-1]

        def rr(n):
            if len(closes) > n and closes[-n - 1]:
                return (last / closes[-n - 1] - 1) * 100
            return None

        return sym, label, {"ret_1y": rr(250), "ret_3y": rr(750), "ret_5y": rr(1250), "price": last}

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(_calc, item) for item in GLOBAL_RETURNS]
        results = []
        for f in as_completed(futs):
            try:
                sym, label, r = f.result()
                results.append({"code": sym, "name": label, **(r or {})})
            except Exception:
                pass
    return results


# ─── 自选 ─────────────────────────────────────────────────────────────────────

def _fetch_watchlist() -> List[dict]:
    """US_WATCHLIST 自选 + 腾讯批量实时行情"""
    from us_quant.universe import get_universe_members
    symbols = get_universe_members("US_WATCHLIST")[:60]
    if not symbols:
        return []
    quotes = _tx_quotes(["us" + s for s in symbols])
    out = []
    for sym in symbols:
        q = quotes.get("us" + sym)
        if not q:
            continue
        out.append({
            "symbol": sym,
            "name": q.get("name") or "",
            "price": q.get("price"),
            "prev_close": q.get("prev_close"),
            "change": q.get("change"),
            "change_pct": q.get("change_pct"),
        })
    return out


# ─── 主聚合 ───────────────────────────────────────────────────────────────────

@router.get("/overview")
def get_overview():
    """市场仪表盘数据库快照；缺失分区不在 GET 时联网补采。"""

    def _build() -> dict:
        from api.global_market import _read_database_bars
        from db.session import get_db_session
        from db.models import PingAnNews
        from market_quant.repository import MarketInstrument
        from us_quant.universe import get_universe_members

        index_proxies = [
            ("DIA", "DJI", "道琼斯"),
            ("SPY", "SPX", "标普500"),
            ("QQQ", "IXIC", "纳斯达克"),
            ("QQQ", "NDX", "纳斯达克100"),
            ("IWM", "RUT", "罗素2000"),
        ]
        symbols = sorted({symbol for symbol, _, _ in index_proxies} | {etf for etf, _ in SECTOR_ETFS})
        watch_symbols = get_universe_members("US_WATCHLIST")[:60]
        all_bars = _read_database_bars("US", sorted(set(symbols + watch_symbols)), 300)

        def _ret(closes, periods):
            if len(closes) <= periods or not closes[-periods - 1]:
                return None
            return (closes[-1] / closes[-periods - 1] - 1) * 100

        indices = []
        for proxy, code, name in index_proxies:
            bars = all_bars.get(proxy, [])
            latest = bars[-1] if bars else {}
            closes = [row["close"] for row in bars if row.get("close") is not None]
            indices.append({
                "code": code, "name": name, "symbol": code,
                "price": latest.get("close"), "prev_close": latest.get("prev_close"),
                "open": latest.get("open"), "high": latest.get("high"), "low": latest.get("low"),
                "change": latest.get("change_amount"), "change_pct": latest.get("change_pct"),
                "time": latest.get("date"), "ret_20d": _ret(closes, 20),
                "source": "database", "status": "PROXY" if bars else "MISSING",
                "is_proxy": True, "proxy_symbol": proxy,
            })

        compare = []
        for proxy, code, name in index_proxies[:3]:
            compare.append({
                "code": code,
                "name": f"{name}（{proxy}代理ETF）",
                "klines": all_bars.get(proxy, []),
                "source": "database",
                "status": "PROXY" if all_bars.get(proxy) else "MISSING",
                "proxy_symbol": proxy,
            })

        sectors = []
        for etf, name in SECTOR_ETFS:
            bars = all_bars.get(etf, [])
            closes = [row["close"] for row in bars if row.get("close") is not None]
            latest = bars[-1] if bars else {}
            sectors.append({
                "etf": etf, "name": name,
                "price": latest.get("close"), "change_pct": latest.get("change_pct"),
                "ret_5d": _ret(closes, 5), "ret_20d": _ret(closes, 20),
                "ret_60d": _ret(closes, 60), "source": "database",
                "status": "READY" if bars else "MISSING",
            })

        instrument_names = {}
        news = []
        with get_db_session() as db:
            for row in db.query(MarketInstrument.symbol, MarketInstrument.name).filter(
                MarketInstrument.market == "US",
                MarketInstrument.symbol.in_(watch_symbols),
            ).all():
                instrument_names[str(row.symbol)] = row.name or ""
            for row in db.query(PingAnNews).order_by(
                PingAnNews.query_time.desc(), PingAnNews.id.desc()
            ).limit(8).all():
                news.append({
                    "title": row.news_title or "", "summary": row.news_summary or "",
                    "time": row.news_date or (row.query_time.isoformat() if row.query_time else ""),
                    "media": row.news_media or row.news_source or "", "url": "",
                    "source": "database", "upstream_source": row.source or "pingan",
                })

        watchlist = []
        for symbol in watch_symbols:
            bars = all_bars.get(symbol, [])
            latest = bars[-1] if bars else {}
            watchlist.append({
                "symbol": symbol, "name": instrument_names.get(symbol, ""),
                "price": latest.get("close"), "prev_close": latest.get("prev_close"),
                "change": latest.get("change_amount"), "change_pct": latest.get("change_pct"),
                "source": "database", "status": "READY" if bars else "MISSING",
                "data_as_of": latest.get("date"),
            })

        global_returns = []
        for proxy, _, name in index_proxies[:3]:
            bars = all_bars.get(proxy, [])
            closes = [row["close"] for row in bars if row.get("close") is not None]
            global_returns.append({
                "code": proxy, "name": f"美国 · {name}（代理ETF）",
                "price": closes[-1] if closes else None,
                "ret_1y": _ret(closes, 250), "ret_3y": None, "ret_5y": None,
                "source": "database", "status": "PROXY" if bars else "MISSING",
            })

        data_dates = [
            rows[-1]["date"] for rows in all_bars.values() if rows
        ]
        data_as_of = max(data_dates) if data_dates else None

        return {
            "indices": indices,
            "global_indices": [],
            "currencies": [],
            "news": news,
            "compare": compare,
            "sectors": sectors,
            "global_returns": global_returns,
            "watchlist": watchlist,
            "updated_at": data_as_of,
            "data_as_of": data_as_of,
            "source": "database",
            "status": "PARTIAL",
            "sections": {
                "indices": "PROXY",
                "global_indices": "MISSING",
                "currencies": "MISSING",
                "news": "READY" if news else "MISSING",
                "compare": "PROXY",
                "sectors": "READY" if any(row["status"] == "READY" for row in sectors) else "MISSING",
                "watchlist": "READY" if any(row["status"] == "READY" for row in watchlist) else "MISSING",
            },
            "limitations": [
                "指数使用 DIA/SPY/QQQ/IWM 代理ETF并已显式标记",
                "数据库尚无外汇和其他国家指数快照，未在查询时联网补采",
            ],
        }

    return _cached("md_overview", _build)

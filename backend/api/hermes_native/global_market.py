"""
Global Market API — 美股/港股独立页面后端接口

默认直连 Yahoo Finance；如需代理，设置环境变量 YAHOO_PROXY_URL，
例如 http://127.0.0.1:7897。
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

_TRACKING_DIR = Path(__file__).resolve().parent.parent
if str(_TRACKING_DIR) not in sys.path:
    sys.path.insert(0, str(_TRACKING_DIR))

_DATA_HOME = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/data")
_DB_ROOT = _DATA_HOME / "db"
for p in (_DB_ROOT,):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from api.hermes_native.db_connector import execute_query, execute_one

logger = logging.getLogger("global_market")

router = APIRouter(prefix="/api/global-market", tags=["global-market"])

# ─── 默认关注列表 ──────────────────────────────────────────────────────────────

DEFAULT_WATCHLIST = {
    "CN_A": [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "601318", "name": "中国平安"},
        {"code": "000858", "name": "五粮液"},
        {"code": "600036", "name": "招商银行"},
        {"code": "300750", "name": "宁德时代"},
        {"code": "002594", "name": "比亚迪"},
        {"code": "000333", "name": "美的集团"},
        {"code": "600900", "name": "长江电力"},
        {"code": "601888", "name": "中国中免"},
        {"code": "002475", "name": "立讯精密"},
        {"code": "600276", "name": "恒瑞医药"},
        {"code": "601012", "name": "隆基绿能"},
    ],
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

# ─── 指数代码 ──────────────────────────────────────────────────────────────────

MARKET_INDICES = {
    "HK": [
        {"code": "HSI", "name": "恒生指数", "query": "恒生指数最新点位涨跌幅"},
        {"code": "HSCEI", "name": "国企指数", "query": "恒生国企指数最新点位涨跌幅"},
        {"code": "HSTECH", "name": "恒生科技", "query": "恒生科技指数最新点位涨跌幅"},
    ],
    "US": [
        {"code": "DJI", "name": "道琼斯", "query": "道琼斯指数最新点位涨跌幅"},
        {"code": "SPX", "name": "标普500", "query": "标普500指数最新点位涨跌幅"},
        {"code": "IXIC", "name": "纳斯达克", "query": "纳斯达克指数最新点位涨跌幅"},
    ],
}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _normalize_pct(value: Any) -> Optional[float]:
    """将涨跌幅归一化为百分比形式（如 0.019 → 1.93, 1.93 → 1.93）"""
    v = _safe_float(value)
    if v is None:
        return None
    # 如果绝对值 < 1 且不为 0，认为是小数形式，乘以 100
    if v != 0 and abs(v) < 1:
        return round(v * 100, 4)
    return v


# ─── Yahoo Finance 辅助函数 ─────────────────────────────────────────────────

def _get_yahoo_proxies() -> Optional[dict[str, str]]:
    """从环境变量读取可选代理，默认直连。"""
    proxy_url = os.environ.get("YAHOO_PROXY_URL") or os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy_url:
        return {"http": proxy_url, "https": proxy_url}
    return None


def _yahoo_fetch(symbol: str, range_str: str = "5d") -> Optional[list[dict]]:
    """通过 Yahoo Finance API 获取 K 线数据"""
    import requests as _req
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_str, "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    try:
        resp = _req.get(url, params=params, headers=headers, proxies=_get_yahoo_proxies(), timeout=15)
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
            o, h, l, c, v = (
                opens[i] if i < len(opens) else None,
                highs[i] if i < len(highs) else None,
                lows[i] if i < len(lows) else None,
                closes[i] if i < len(closes) else None,
                volumes[i] if i < len(volumes) else None,
            )
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


# 指数 Yahoo 代码映射
INDEX_YAHOO_SYMBOLS = {
    "HK": {"HSI": "^HSI", "HSCEI": "^HSCE", "HSTECH": "^HSTECH"},
    "US": {"DJI": "^DJI", "SPX": "^GSPC", "IXIC": "^IXIC"},
}


# ─── 行情总览 ──────────────────────────────────────────────────────────────────

@router.get("/indices/{market}")
def get_indices(market: str):
    """获取市场主要指数行情（数据库 + Yahoo Finance）"""
    market = market.upper()
    indices = MARKET_INDICES.get(market, [])
    yahoo_map = INDEX_YAHOO_SYMBOLS.get(market, {})
    results = []

    for idx in indices:
        yahoo_sym = yahoo_map.get(idx["code"])
        if not yahoo_sym:
            results.append({"code": idx["code"], "name": idx["name"], "price": None, "change_pct": None})
            continue

        klines = _yahoo_fetch(yahoo_sym, range_str="5d")
        if klines:
            latest = klines[-1]
            results.append({
                "code": idx["code"],
                "name": idx["name"],
                "price": latest.get("close"),
                "change_pct": latest.get("change_pct"),
                "change_amount": latest.get("change_amount"),
                "volume": latest.get("volume", ""),
                "updated": latest.get("date", ""),
            })
        else:
            results.append({"code": idx["code"], "name": idx["name"], "price": None, "change_pct": None})

    return {"market": market, "indices": results}


@router.get("/quotes/{market}")
def get_quotes(market: str):
    """获取关注列表行情（数据库 kline_daily 为主）"""
    market = market.upper()
    watchlist = DEFAULT_WATCHLIST.get(market, [])
    results = []

    # 从数据库批量获取最新 K 线数据
    kline_map = {}
    try:
        codes = [s["code"] for s in watchlist]
        if codes:
            placeholders = ",".join(["%s"] * len(codes))
            # 获取每只股票最近 2 条记录（用于计算涨跌）
            rows = execute_query(
                f"""
                SELECT code, trade_date, open, high, low, close,
                       volume, amount, change_pct, turnover_rate, amplitude
                FROM kline_daily
                WHERE market = %s AND code IN ({placeholders})
                ORDER BY code, trade_date DESC
                """,
                (market, *codes),
            )
            # 每只取最近 2 条
            for r in rows:
                code = r["code"]
                if code not in kline_map:
                    kline_map[code] = []
                if len(kline_map[code]) < 2:
                    kline_map[code].append(r)
    except Exception as e:
        logger.warning(f"查询 {market} K线数据失败: {e}")

    for stock in watchlist:
        code = stock["code"]
        klines = kline_map.get(code, [])

        if klines:
            latest = klines[0]
            prev = klines[1] if len(klines) > 1 else None

            price = _safe_float(latest.get("close"))
            change_pct = _safe_float(latest.get("change_pct"))
            # 如果 DB 没有 change_pct，用 prev_close 计算
            if change_pct is None and prev:
                prev_close = _safe_float(prev.get("close"))
                if prev_close and prev_close > 0 and price:
                    change_pct = round((price - prev_close) / prev_close * 100, 2)

            change_amount = _safe_float(latest.get("change_amount"))
            if change_amount is None and prev and price:
                change_amount = round(price - _safe_float(prev.get("close")), 4) if _safe_float(prev.get("close")) else None

            results.append({
                "code": code,
                "name": stock["name"],
                "price": price,
                "change_pct": change_pct,
                "change_amount": change_amount,
                "volume": latest.get("volume"),
                "amount": latest.get("amount"),
                "high": _safe_float(latest.get("high")),
                "low": _safe_float(latest.get("low")),
                "open": _safe_float(latest.get("open")),
                "prev_close": _safe_float(prev.get("close")) if prev else None,
                "turnover_rate": _safe_float(latest.get("turnover_rate")),
                "updated": str(latest.get("trade_date", "")),
            })
        else:
            results.append({
                "code": code,
                "name": stock["name"],
                "price": None,
                "change_pct": None,
            })

    return {"market": market, "quotes": results, "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S")}


# ─── 选股监控 ──────────────────────────────────────────────────────────────────

@router.get("/watchlist/{market}")
def get_watchlist(market: str):
    """获取关注列表 + 实时行情 + K线指标"""
    market = market.upper()
    watchlist = DEFAULT_WATCHLIST.get(market, [])

    # 尝试从数据库获取最新K线数据
    kline_map = {}
    try:
        if market == "HK":
            codes_tuple = tuple(s["code"] for s in watchlist)
            if codes_tuple:
                placeholders = ",".join(["%s"] * len(codes_tuple))
                rows = execute_query(
                    f"""
                    SELECT DISTINCT ON (code) code, trade_date, open, high, low, close,
                           volume, amount, change_pct, turnover_rate, amplitude
                    FROM kline_daily
                    WHERE market = 'HK' AND code IN ({placeholders})
                    ORDER BY code, trade_date DESC
                    """,
                    codes_tuple,
                )
                for r in rows:
                    kline_map[r["code"]] = r
    except Exception as e:
        logger.warning(f"查询 HK K线数据失败: {e}")

    # 获取实时行情
    quotes_data = get_quotes(market)
    quote_map = {}
    for q in quotes_data.get("quotes", []):
        quote_map[q["code"]] = q

    results = []
    for stock in watchlist:
        code = stock["code"]
        q = quote_map.get(code, {})
        k = kline_map.get(code, {})

        price = q.get("price") or _safe_float(k.get("close"))
        change_pct = q.get("change_pct") or _safe_float(k.get("change_pct"))

        results.append({
            "code": code,
            "name": stock["name"],
            "price": _safe_float(price),
            "change_pct": _safe_float(change_pct),
            "open": q.get("open") or _safe_float(k.get("open")),
            "high": q.get("high") or _safe_float(k.get("high")),
            "low": q.get("low") or _safe_float(k.get("low")),
            "volume": q.get("volume") or k.get("volume"),
            "amount": q.get("amount") or k.get("amount"),
            "turnover_rate": _safe_float(k.get("turnover_rate")),
            "amplitude": _safe_float(k.get("amplitude")),
            "prev_close": q.get("prev_close"),
            "trade_date": str(k["trade_date"]) if k.get("trade_date") else "",
            "source": "realtime" if q.get("price") else "kline",
        })

    return {
        "market": market,
        "items": results,
        "total": len(results),
        "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }


# ─── K线历史数据 ──────────────────────────────────────────────────────────────

@router.get("/kline/{market}/{code}")
def get_kline(market: str, code: str, days: int = Query(default=30, le=120)):
    """获取个股K线历史数据"""
    market = market.upper()

    if market == "HK":
        try:
            rows = execute_query(
                """
                SELECT trade_date, open, high, low, close, volume, amount,
                       change_pct, turnover_rate, amplitude
                FROM kline_daily
                WHERE market = 'HK' AND code = %s
                ORDER BY trade_date DESC
                LIMIT %s
                """,
                (code, days),
            )
            return {
                "market": market,
                "code": code,
                "data": [
                    {
                        "trade_date": str(r["trade_date"]) if r.get("trade_date") else "",
                        "open": _safe_float(r.get("open")),
                        "high": _safe_float(r.get("high")),
                        "low": _safe_float(r.get("low")),
                        "close": _safe_float(r.get("close")),
                        "volume": _safe_float(r.get("volume")),
                        "amount": _safe_float(r.get("amount")),
                        "change_pct": _safe_float(r.get("change_pct")),
                        "turnover_rate": _safe_float(r.get("turnover_rate")),
                        "amplitude": _safe_float(r.get("amplitude")),
                    }
                    for r in reversed(rows)
                ],
                "source": "database",
            }
        except Exception as e:
            logger.warning(f"查询 HK K线失败: {e}")
            return {"market": market, "code": code, "data": [], "error": str(e)}

    if market == "US":
        # US market — DB 为主，Yahoo Finance 补充
        try:
            rows = execute_query(
                """
                SELECT trade_date, open, high, low, close, volume, amount,
                       change_pct, turnover_rate, amplitude
                FROM kline_daily
                WHERE market = 'US' AND code = %s
                ORDER BY trade_date DESC
                LIMIT %s
                """,
                (code, days),
            )
            if rows and len(rows) >= 5:
                return {
                    "market": market,
                    "code": code,
                    "data": [
                        {
                            "trade_date": str(r["trade_date"]) if r.get("trade_date") else "",
                            "open": _safe_float(r.get("open")),
                            "high": _safe_float(r.get("high")),
                            "low": _safe_float(r.get("low")),
                            "close": _safe_float(r.get("close")),
                            "volume": _safe_float(r.get("volume")),
                            "amount": _safe_float(r.get("amount")),
                            "change_pct": _safe_float(r.get("change_pct")),
                            "turnover_rate": _safe_float(r.get("turnover_rate")),
                            "amplitude": _safe_float(r.get("amplitude")),
                        }
                        for r in reversed(rows)
                    ],
                    "source": "database",
                }
        except Exception as e:
            logger.warning(f"查询 US K线 DB 失败: {e}")

        # DB 数据不足时尝试 Yahoo Finance 补充
        try:
            yahoo_items = _yahoo_fetch(code, range_str=f"{days}d")
            if yahoo_items:
                data = [
                    {
                        "trade_date": item.get("date", ""),
                        "open": item.get("open"),
                        "high": item.get("high"),
                        "low": item.get("low"),
                        "close": item.get("close"),
                        "volume": item.get("volume", 0),
                        "amount": None,
                        "change_pct": item.get("change_pct"),
                        "turnover_rate": None,
                        "amplitude": None,
                    }
                    for item in yahoo_items[-days:]
                ]
                if data:
                    return {"market": market, "code": code, "data": data, "source": "yahoo"}
        except Exception as e:
            logger.warning(f"Yahoo Finance 补充 {code} K线失败: {e}")

        return {"market": market, "code": code, "data": [], "note": "美股K线数据暂不可用"}

    # Default fallback
    return {"market": market, "code": code, "data": [], "note": "该市场K线数据暂不可用"}


# ─── 个股分析 (复用 ai_advice 引擎) ──────────────────────────────────────────

@router.get("/analysis/{market}/{code}")
def get_stock_analysis(market: str, code: str, name: str = Query(default=""), provider: str = Query(default="eastmoney")):
    """获取个股 AI 分析 — 复用现有的 4 个 provider"""
    market = market.upper()
    market_label = "港股" if market == "HK" else "美股"
    stock_label = f"{market_label} {code} {name}"

    # 获取最新价格：优先数据库，其次 Yahoo Finance
    price = None
    try:
        row = execute_one(
            f"SELECT close FROM kline_daily WHERE market=%s AND code=%s ORDER BY trade_date DESC LIMIT 1",
            (market, code),
        )
        if row:
            price = _safe_float(row.get("close"))
    except Exception:
        pass

    if price is None:
        # 尝试 Yahoo Finance（港股代码需要 .HK 后缀）
        yahoo_code = code
        if market == "HK":
            # 00700 → 0700.HK
            stripped = code.lstrip("0")
            yahoo_code = f"{stripped}.HK" if stripped else code
        yahoo_items = _yahoo_fetch(yahoo_code, range_str="5d")
        if yahoo_items:
            price = yahoo_items[-1].get("close")

    # 调用 provider
    try:
        from api.hermes_native.services.ai_advice import get_provider
        from api.hermes_native.services.ai_advice.base import StockInfo

        stock_info = StockInfo(
            code=code,
            name=name or code,
            price=price or 0,
            cost=0,
            profit_pct=0,
            score=0,
        )

        provider_instance = get_provider(provider)
        if provider_instance is None:
            return {"error": f"未知 provider: {provider}"}

        report = provider_instance.analyze(stock_info)
        return {
            "market": market,
            "code": code,
            "name": name,
            "price": price,
            "provider": provider,
            "provider_name": getattr(provider_instance, "name", provider),
            "sections": [
                {
                    "title": s.title,
                    "content": s.content,
                    "style": getattr(s, "style", "default"),
                }
                for s in report.sections
            ],
        }
    except Exception as e:
        logger.error(f"AI 分析失败 ({stock_label} / {provider}): {e}")
        return {
            "market": market,
            "code": code,
            "name": name,
            "price": price,
            "provider": provider,
            "error": str(e),
            "sections": [
                {"title": "分析异常", "content": f"AI 分析暂时不可用: {e}", "style": "warning"},
            ],
        }


@router.get("/analysis-providers")
def list_analysis_providers():
    """列出所有可用的 AI 分析 provider"""
    try:
        from api.hermes_native.services.ai_advice import list_providers
        providers = list_providers()
        return {"providers": providers}
    except Exception as e:
        return {"providers": [], "error": str(e)}


# ─── 市场概览（综合数据）──────────────────────────────────────────────────────

@router.get("/overview/{market}")
def get_overview(market: str):
    """获取市场概览：指数 + 关注列表行情 + 统计"""
    market = market.upper()
    market_label = "港股" if market == "HK" else "美股"

    # 获取指数
    indices_data = get_indices(market)

    # 获取关注列表行情
    quotes_data = get_quotes(market)
    quotes = quotes_data.get("quotes", [])

    # 统计
    up_count = sum(1 for q in quotes if (q.get("change_pct") or 0) > 0)
    down_count = sum(1 for q in quotes if (q.get("change_pct") or 0) < 0)
    flat_count = len(quotes) - up_count - down_count

    return {
        "market": market,
        "market_label": market_label,
        "indices": indices_data.get("indices", []),
        "quotes": quotes,
        "stats": {
            "total": len(quotes),
            "up": up_count,
            "down": down_count,
            "flat": flat_count,
        },
        "updated_at": quotes_data.get("updated_at", ""),
    }


# ─── 统一接口：为前端跨市场页面提供兼容数据 ────────────────────────────────────

@router.get("/unified/{market}/review")
def get_unified_review(market: str, date: Optional[str] = Query(default=None)):
    """
    统一复盘接口 — 为 MarketReview / MarketToday 提供兼容数据。
    A股调用时透传 market-review，港股/美股返回简化版。
    """
    market = market.upper()
    market_label = "港股" if market == "HK" else "美股"
    today_str = (date or datetime.now().strftime("%Y-%m-%d"))

    # 获取指数行情
    indices_data = get_indices(market)
    quotes_data = get_quotes(market)
    quotes = quotes_data.get("quotes", [])

    up = sum(1 for q in quotes if (q.get("change_pct") or 0) > 0)
    down = sum(1 for q in quotes if (q.get("change_pct") or 0) < 0)

    # 构建指数结构 (兼容 A股 market.indexs 格式)
    index_list = []
    for idx in indices_data.get("indices", []):
        cp = idx.get("change_pct")
        index_list.append({
            "name": idx.get("name", ""),
            "trade_date": today_str,
            "value": idx.get("price"),
            "change": cp,
            "trend": "up" if (cp or 0) > 0 else ("down" if (cp or 0) < 0 else "neutral"),
            "source": "yahoo",
        })

    return {
        "date": today_str,
        "resolved_date": today_str,
        "status": "最新",
        "summary": {
            "text": f"{market_label}今日共{len(quotes)}只关注标的，{up}涨{down}跌。",
            "markdown": f"## {market_label}市场简报\n\n关注{len(quotes)}只，上涨{up}只，下跌{down}只。",
        },
        "market": {
            "trade_date": today_str,
            "indices": index_list,
            "breadth": {"up": up, "down": down, "flat": len(quotes) - up - down},
            "limit_up": {"limit_up": 0, "broken": 0, "st_limit": 0, "touch_limit": 0, "failed": 0, "limit_down": 0},
        },
        "themes": {"mainline": [], "watch": [], "alive": []},
        "rotation": {"current": {"mainline": [], "watch": [], "alive": []}},
        "fund_flow": {"north_money": {}, "industry_inflow_top5": [], "industry_outflow_top5": [],
                      "concept_inflow_top5": [], "concept_outflow_top5": [],
                      "stock_inflow_top5": [], "stock_outflow_top5": []},
        "emotion": {"stage": "--", "display_stage": "--", "score": None, "explain": f"{market_label}情绪数据建设中"},
        "risk_warning": [],
        "tomorrow_plan": {"attack": [], "secondary": [], "defense": [], "position": ""},
        "cognition": {"stage": "--", "position": "", "risk_level": "", "warnings": []},
        "meta": {"status": "最新", "updated_at": quotes_data.get("updated_at", ""),
                 "source": "unified", "resolved_date": today_str},
    }


@router.get("/unified/{market}/realtime")
def get_unified_realtime(market: str):
    """
    统一实时接口 — 为 MarketToday (盘中实时) 提供兼容数据。
    """
    market = market.upper()
    market_label = "港股" if market == "HK" else "美股"

    indices_data = get_indices(market)
    quotes_data = get_quotes(market)

    return {
        "market": market,
        "market_label": market_label,
        "indices": indices_data.get("indices", []),
        "quotes": quotes_data.get("quotes", []),
        "updated_at": quotes_data.get("updated_at", ""),
    }


@router.get("/unified/{market}/monitor")
def get_unified_monitor(market: str):
    """
    统一选股监控接口 — 为 StockMonitorPage 提供兼容数据。
    返回关注列表 + 行情 + K线指标，格式兼容 ops/watchlist-with-leaders。
    """
    market = market.upper()
    watchlist_data = get_watchlist(market)

    items = []
    for w in watchlist_data.get("items", []):
        items.append({
            "code": w["code"],
            "name": w["name"],
            "market": market,
            "industry": "",
            "price": w.get("price"),
            "cost": None,
            "count": 0,
            "profitPct": None,
            "source": "monitor",
            "close": w.get("price"),
            "change_pct": w.get("change_pct"),
            "open": w.get("open"),
            "high": w.get("high"),
            "low": w.get("low"),
            "volume": w.get("volume"),
            "amount": w.get("amount"),
            "turnover_rate": w.get("turnover_rate"),
            "ma5": None, "ma10": None, "ma20": None,
            "volume_ratio": None, "rsi": None,
            "change5d": None, "change10d": None, "change20d": None,
            "deviation": None,
            "leader_level": "",
            "pattern": "",
            "score": None,
        })

    return {
        "items": items,
        "realtime_updated_at": watchlist_data.get("updated_at", ""),
        "realtime_source": "global-market-unified",
        "realtime_count": len(items),
    }


@router.get("/unified/{market}/positions")
def get_unified_positions(market: str):
    """
    统一持仓接口 — 为 PositionPage 提供兼容数据。
    返回模拟交易持仓（按市场过滤）。
    """
    market = market.upper()
    try:
        from api.hermes_native.services.miaoxiang_service import mock_positions
        positions = mock_positions()
        # 按市场过滤持仓
        filtered = [p for p in positions if (p.get("market") or "").upper() == market]
        return {"positions": filtered, "market": market, "total": len(filtered)}
    except Exception as e:
        logger.warning(f"获取 {market} 持仓失败: {e}")
        return {"positions": [], "market": market, "total": 0, "error": str(e)}


@router.get("/unified/{market}/strategies")
def get_unified_strategies(market: str):
    """
    统一策略信号接口 — 为 StrategyExecutionPage 提供兼容数据。
    """
    market = market.upper()
    market_label = "港股" if market == "HK" else "美股"
    return {
        "market": market,
        "market_label": market_label,
        "robots": {},
        "message": f"{market_label}策略信号数据建设中",
    }


@router.get("/unified/{market}/wave")
def get_unified_wave(market: str):
    """
    统一波段信号接口 — 为 StrategyExecutionPage 波段信号 Tab 提供兼容数据。
    """
    market = market.upper()
    market_label = "港股" if market == "HK" else "美股"
    return {
        "ok": True,
        "market": market,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "count": 0,
        "signals": [],
        "message": f"{market_label}波段信号数据建设中",
    }


# ─── 技术指标计算工具 ──────────────────────────────────────────────────────────

def _calc_ma(closes: list[float], period: int) -> Optional[float]:
    """计算移动平均线"""
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def _calc_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """计算 RSI 相对强弱指标"""
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


def _calc_change_pct(closes: list[float], periods: int) -> Optional[float]:
    """计算 N 日涨跌幅"""
    if len(closes) < periods + 1:
        return None
    old = closes[-(periods + 1)]
    new = closes[-1]
    if old == 0:
        return None
    return round((new - old) / old * 100, 2)


def _load_kline_for_codes(market: str, codes: list[str], days: int = 30) -> dict[str, list[dict]]:
    """从数据库批量加载 K 线数据，返回 {code: [rows]}"""
    result = {}
    if not codes:
        return result
    try:
        placeholders = ",".join(["%s"] * len(codes))
        rows = execute_query(
            f"""
            SELECT code, trade_date, open, high, low, close, volume, amount,
                   change_pct, turnover_rate, amplitude
            FROM kline_daily
            WHERE market = %s AND code IN ({placeholders})
            ORDER BY code, trade_date ASC
            """,
            (market, *codes),
        )
        for r in rows:
            code = r["code"]
            if code not in result:
                result[code] = []
            result[code].append(r)
        # 截取最后 N 条
        for code in result:
            result[code] = result[code][-days:]
    except Exception as e:
        logger.warning(f"批量加载 {market} K线失败: {e}")
    return result


# ─── 增强版选股监控（含技术指标）──────────────────────────────────────────────

@router.get("/watchlist-enhanced/{market}")
def get_watchlist_enhanced(market: str):
    """获取关注列表 + 实时行情 + K线技术指标（MA/RSI/区间涨跌幅）"""
    market = market.upper()
    watchlist = DEFAULT_WATCHLIST.get(market, [])
    codes = [s["code"] for s in watchlist]

    # 批量加载 K 线数据（从数据库）
    kline_data = _load_kline_for_codes(market, codes, days=30)

    # 获取实时行情
    quotes_data = get_quotes(market)
    quote_map = {}
    for q in quotes_data.get("quotes", []):
        quote_map[q["code"]] = q

    results = []
    for stock in watchlist:
        code = stock["code"]
        q = quote_map.get(code, {})
        klines = kline_data.get(code, [])
        closes = [_safe_float(k.get("close")) for k in klines if _safe_float(k.get("close")) is not None]

        # 最新 K 线
        last_k = klines[-1] if klines else {}

        price = q.get("price") or _safe_float(last_k.get("close"))
        change_pct = q.get("change_pct") or _safe_float(last_k.get("change_pct"))

        # 技术指标
        ma5 = _calc_ma(closes, 5)
        ma10 = _calc_ma(closes, 10)
        ma20 = _calc_ma(closes, 20)
        rsi = _calc_rsi(closes, 14)
        change5d = _calc_change_pct(closes, 5)
        change10d = _calc_change_pct(closes, 10)
        change20d = _calc_change_pct(closes, 20)

        # 振幅（实时可算；K线也有）
        amplitude = _safe_float(last_k.get("amplitude"))
        if not amplitude and q.get("high") and q.get("low") and q.get("prev_close"):
            pc = _safe_float(q["prev_close"])
            h = _safe_float(q["high"])
            l = _safe_float(q["low"])
            if pc and h is not None and l is not None and pc > 0:
                amplitude = round((h - l) / pc * 100, 2)

        # 均线偏离度（当前价与 MA20 的偏离）
        deviation = None
        if ma20 and price and ma20 > 0:
            deviation = round((price - ma20) / ma20 * 100, 2)

        results.append({
            "code": code,
            "name": stock["name"],
            "price": _safe_float(price),
            "change_pct": _safe_float(change_pct),
            "open": q.get("open") or _safe_float(last_k.get("open")),
            "high": q.get("high") or _safe_float(last_k.get("high")),
            "low": q.get("low") or _safe_float(last_k.get("low")),
            "volume": q.get("volume") or last_k.get("volume"),
            "amount": q.get("amount") or last_k.get("amount"),
            "turnover_rate": _safe_float(last_k.get("turnover_rate")),
            "amplitude": amplitude,
            "prev_close": q.get("prev_close"),
            "trade_date": str(last_k["trade_date"]) if last_k.get("trade_date") else "",
            "source": "realtime" if q.get("price") else ("kline" if last_k else "none"),
            # 技术指标
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "rsi": rsi,
            "change5d": change5d,
            "change10d": change10d,
            "change20d": change20d,
            "deviation": deviation,
            # K线迷你图数据（最近 20 天收盘价）
            "sparkline": [
                {"d": str(k["trade_date"]), "c": _safe_float(k.get("close"))}
                for k in klines[-20:]
            ] if klines else [],
        })

    return {
        "market": market,
        "items": results,
        "total": len(results),
        "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
    }


# ─── 市场过滤交易接口 ─────────────────────────────────────────────────────────

@router.get("/trading/{market}")
def get_trading_summary(market: str):
    """获取按市场过滤的模拟交易持仓 + 账户汇总"""
    market = market.upper()
    market_label = "港股" if market == "HK" else "美股"

    try:
        from api.hermes_native.services.miaoxiang_service import mock_positions, mock_balance

        # 获取全部持仓
        all_positions = mock_positions()

        # 获取账户余额
        balance_info = {}
        try:
            balance_info = mock_balance()
        except Exception as e:
            logger.warning(f"获取 {market} 账户余额失败: {e}")

        # 按市场过滤持仓 — 妙想返回的 secCode 可能带后缀，需要归一化
        watchlist_codes = {s["code"] for s in DEFAULT_WATCHLIST.get(market, [])}
        pos_list = all_positions if isinstance(all_positions, list) else all_positions.get("posList", [])

        filtered = []
        for p in pos_list:
            sec_code = str(p.get("secCode", "")).strip()
            # 归一化：去除后缀
            norm_code = sec_code.split(".")[0] if "." in sec_code else sec_code
            if norm_code in watchlist_codes:
                filtered.append(p)

        # 计算统计
        active = [p for p in filtered if (p.get("count", 0) or 0) > 0]
        closed = [p for p in filtered if (p.get("count", 0) or 0) <= 0]

        total_pos_value = 0
        total_profit = 0
        total_day_profit = 0
        for p in active:
            price_val = (p.get("price", 0) or 0) / (10 ** (p.get("priceDec", 2) or 2))
            count = p.get("count", 0) or 0
            total_pos_value += price_val * count
            total_profit += p.get("profit", 0) or 0
            total_day_profit += p.get("dayProfit", 0) or 0

        # 账户余额信息
        balance_data = balance_info.get("data", {}) if isinstance(balance_info, dict) else {}
        avail_balance = _safe_float(balance_data.get("availBalance")) or 0
        total_assets = _safe_float(balance_data.get("totalAssets")) or (avail_balance + total_pos_value)
        init_money = _safe_float(balance_data.get("initMoney")) or 1000000

        account_profit = total_assets - init_money if init_money else 0
        account_profit_pct = round(account_profit / init_money * 100, 2) if init_money else 0

        return {
            "market": market,
            "market_label": market_label,
            "positions": filtered,
            "active_positions": active,
            "closed_positions": closed,
            "summary": {
                "total_assets": round(total_assets, 2),
                "total_pos_value": round(total_pos_value, 2),
                "avail_balance": round(avail_balance, 2),
                "total_profit": round(total_profit, 2),
                "total_day_profit": round(total_day_profit, 2),
                "init_money": init_money,
                "account_profit": round(account_profit, 2),
                "account_profit_pct": account_profit_pct,
                "pos_count": len(active),
                "closed_count": len(closed),
            },
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        }

    except Exception as e:
        logger.warning(f"获取 {market} 交易汇总失败: {e}")
        return {
            "market": market,
            "market_label": market_label,
            "positions": [],
            "active_positions": [],
            "closed_positions": [],
            "summary": {
                "total_assets": 0, "total_pos_value": 0, "avail_balance": 0,
                "total_profit": 0, "total_day_profit": 0, "init_money": 0,
                "account_profit": 0, "account_profit_pct": 0,
                "pos_count": 0, "closed_count": 0,
            },
            "error": str(e),
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        }


# ─── 批量 K 线接口 ──────────────────────────────────────────────────────────

@router.get("/kline-batch/{market}")
def get_kline_batch(market: str, days: int = Query(default=20, le=60)):
    """批量获取关注列表的 K 线数据（用于迷你图）"""
    market = market.upper()
    watchlist = DEFAULT_WATCHLIST.get(market, [])
    codes = [s["code"] for s in watchlist]

    kline_data = _load_kline_for_codes(market, codes, days=days)

    result = {}
    for code in codes:
        klines = kline_data.get(code, [])
        result[code] = [
            {
                "d": str(k["trade_date"]) if k.get("trade_date") else "",
                "c": _safe_float(k.get("close")),
                "v": _safe_float(k.get("volume")),
            }
            for k in klines[-days:]
        ]

    return {"market": market, "data": result, "days": days}

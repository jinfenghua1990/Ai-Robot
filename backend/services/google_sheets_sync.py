"""Google Sheets 同步服务。

只使用 Google 官方 Sheets/ OAuth HTTP 接口，不保存 Google 密码。
授权后的 refresh token 存在本机可配置文件中，页面只返回连接状态和表格链接。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, quote

import httpx

from config import (
    GOOGLE_SHEETS_CLIENT_ID,
    GOOGLE_SHEETS_CLIENT_SECRET,
    GOOGLE_SHEETS_REDIRECT_URI,
    GOOGLE_SHEETS_TOKEN_FILE,
)

logger = logging.getLogger("airobot.google_sheets")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEET_NAMES = ("自选", "持仓", "指标", "信号", "说明")
_oauth_states: dict[str, tuple[float, str]] = {}


class GoogleSheetsError(RuntimeError):
    """可展示给前端的 Google Sheets 同步错误。"""


def _configured() -> bool:
    return bool(GOOGLE_SHEETS_CLIENT_ID and GOOGLE_SHEETS_CLIENT_SECRET)


def _token_path() -> Path:
    return Path(GOOGLE_SHEETS_TOKEN_FILE).expanduser()


def _read_token() -> dict[str, Any]:
    path = _token_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write_token(data: dict[str, Any]) -> None:
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _clear_token() -> None:
    try:
        _token_path().unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("删除 Google Sheets 授权文件失败: %s", exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def get_status() -> dict[str, Any]:
    """返回脱敏连接状态，不返回 access/refresh token。"""
    token = _read_token()
    spreadsheet_id = str(token.get("spreadsheet_id") or "")
    return {
        "configured": _configured(),
        "connected": bool(token.get("refresh_token") and spreadsheet_id),
        "spreadsheet_id": spreadsheet_id or None,
        "spreadsheet_url": token.get("spreadsheet_url") or (
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
            if spreadsheet_id else None
        ),
        "last_sync": token.get("last_sync"),
        "last_error": token.get("last_error"),
        "last_counts": token.get("last_counts") or {},
        "token_file_configured": _token_path().exists(),
    }


def build_authorization_url() -> str:
    """生成 Google OAuth 授权地址，并记录一次性 state。"""
    if not _configured():
        raise GoogleSheetsError("尚未配置 GOOGLE_SHEETS_CLIENT_ID / GOOGLE_SHEETS_CLIENT_SECRET")
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (time.time(), GOOGLE_SHEETS_REDIRECT_URI)
    # 清理超过 10 分钟的状态，避免长时间运行后内存增长。
    cutoff = time.time() - 600
    for key, (created_at, _) in list(_oauth_states.items()):
        if created_at < cutoff:
            _oauth_states.pop(key, None)
    params = {
        "client_id": GOOGLE_SHEETS_CLIENT_ID,
        "redirect_uri": GOOGLE_SHEETS_REDIRECT_URI,
        "response_type": "code",
        "scope": SHEETS_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def complete_authorization(code: str, state: str) -> dict[str, Any]:
    """用授权回调 code 换取 token，并保留旧的表格信息。"""
    state_info = _oauth_states.pop(state, None)
    if not state_info or time.time() - state_info[0] > 600:
        raise GoogleSheetsError("Google 授权状态已失效，请重新点击连接")
    if not code:
        raise GoogleSheetsError("Google 未返回授权 code")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_SHEETS_CLIENT_ID,
                "client_secret": GOOGLE_SHEETS_CLIENT_SECRET,
                "redirect_uri": state_info[1],
                "grant_type": "authorization_code",
            },
        )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error_description") or response.json().get("error")
        except ValueError:
            detail = response.text[:200]
        raise GoogleSheetsError(f"Google 授权换 token 失败: {detail or response.status_code}")
    payload = response.json()
    old = _read_token()
    merged = {
        **{k: old[k] for k in ("spreadsheet_id", "spreadsheet_url", "last_sync", "last_counts") if k in old},
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token") or old.get("refresh_token"),
        "expires_at": int(time.time()) + int(payload.get("expires_in", 3600)),
        "token_type": payload.get("token_type", "Bearer"),
        "last_error": None,
    }
    if not merged.get("refresh_token"):
        raise GoogleSheetsError("Google 未返回 refresh token，请重新授权并同意离线访问")
    _write_token(merged)
    return get_status()


async def _access_token() -> str:
    token = _read_token()
    access_token = token.get("access_token")
    if access_token and int(token.get("expires_at", 0)) > int(time.time()) + 60:
        return str(access_token)
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise GoogleSheetsError("尚未连接 Google Sheets")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": GOOGLE_SHEETS_CLIENT_ID,
                "client_secret": GOOGLE_SHEETS_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code >= 400:
        raise GoogleSheetsError("Google 登录已失效，请重新连接")
    payload = response.json()
    token.update({
        "access_token": payload.get("access_token"),
        "expires_at": int(time.time()) + int(payload.get("expires_in", 3600)),
        "token_type": payload.get("token_type", "Bearer"),
        "last_error": None,
    })
    _write_token(token)
    return str(payload.get("access_token"))


async def _sheets_request(method: str, path: str, access_token: str, **kwargs: Any) -> dict[str, Any]:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {access_token}"
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.request(method, f"{SHEETS_API_BASE}{path}", headers=headers, **kwargs)
    if response.status_code >= 400:
        try:
            message = response.json().get("error", {}).get("message")
        except ValueError:
            message = response.text[:200]
        raise GoogleSheetsError(f"Google Sheets API 失败: {message or response.status_code}")
    if not response.content:
        return {}
    return response.json()


def _number(value: Any) -> Any:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
        return int(number) if number.is_integer() else round(number, 6)
    except (TypeError, ValueError):
        return str(value)


def _market_label(market: str) -> str:
    return {"US": "美股", "HK": "港股", "CN": "A股", "A": "A股"}.get(str(market).upper(), market or "未知")


@lru_cache(maxsize=1)
def _us_names_cn() -> dict[str, str]:
    """复用前端中文名词典，避免 Google 表格只显示冗长英文全名。"""
    path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "usStockNames.js"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return {key: value for key, value in re.findall(r"\b([A-Z][A-Z0-9.]*)\s*:\s*'([^']*)'", text)}


def _display_name(market: str, symbol: str, fallback: str = "") -> str:
    if str(market).upper() == "US":
        return _us_names_cn().get(str(symbol).upper(), fallback or str(symbol))
    return fallback or str(symbol)


def _google_symbol(market: str, symbol: str, exchange: str = "") -> str:
    market = str(market).upper()
    symbol = str(symbol or "").strip().upper()
    if market == "US" and symbol:
        exchange = str(exchange or "").upper()
        exchange = exchange if exchange in {"NASDAQ", "NYSE", "AMEX", "NYSEARCA", "CBOE"} else "NASDAQ"
        return f"{exchange}:{symbol}"
    if market == "HK" and symbol:
        digits = symbol.replace(".HK", "")
        return f"HKG:{digits.lstrip('0') or '0'}"
    return ""


def _formula(row_number: int, column: str, attribute: str) -> str:
    return f'=IFERROR(GOOGLEFINANCE({column}{row_number},"{attribute}"),"")'


def _safe_date(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value or "")


def _collect_indicator_values(symbol_meta: dict[tuple[str, str], dict[str, Any]]) -> list[list[Any]]:
    """从本地日线批量计算同步所需的 RSI/MACD/KDJ/强 B/S 状态。

    只读数据库，不在同步任务中重新拉取行情；没有足够历史的标的保留一行空值，
    让 Google Sheets 明确知道是数据不足而不是把 0 当成有效指标。
    """
    headers = ["市场", "代码", "中文名称", "指标日期", "MA5", "MA20", "MA60", "RSI14",
               "MACD DIF", "MACD 柱体", "KDJ K", "KDJ D", "BS状态", "BS因子",
               "MA5/20金叉", "KDJ金叉", "MACD双确认", "站上MA60", "RSI45-70", "流动性达标", "数据状态"]
    symbols_by_market = defaultdict(list)
    for market, symbol in symbol_meta:
        if market in {"US", "HK"}:
            symbols_by_market[market].append(symbol)
    if not symbols_by_market:
        return [headers]

    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    try:
        from db.session import get_db_session
        with get_db_session() as db:
            if symbols_by_market.get("US"):
                from us_quant.repository import USStockDaily
                rows = (db.query(USStockDaily)
                        .filter(USStockDaily.symbol.in_(symbols_by_market["US"]))
                        .order_by(USStockDaily.symbol, USStockDaily.trade_date).all())
                for bar in rows:
                    grouped[("US", bar.symbol)].append(bar)
            if symbols_by_market.get("HK"):
                from market_quant.repository import MarketDailyBar
                rows = (db.query(MarketDailyBar)
                        .filter(MarketDailyBar.market == "HK",
                                MarketDailyBar.symbol.in_(symbols_by_market["HK"]))
                        .order_by(MarketDailyBar.symbol, MarketDailyBar.trade_date).all())
                for bar in rows:
                    grouped[("HK", bar.symbol)].append(bar)
    except Exception as exc:
        logger.debug("读取指标日线失败: %s", exc)

    try:
        from us_quant.bs_strategy import calculate_indicators, evaluate_strong_bs
    except Exception as exc:
        logger.debug("加载 B/S 指标计算失败: %s", exc)
        return [headers]

    values: list[list[Any]] = [headers]
    for key in sorted(symbol_meta):
        market, symbol = key
        if market not in {"US", "HK"}:
            continue
        bars = grouped.get(key, [])[-500:]
        # 两种日线模型字段一致，按严格数值过滤，避免 NULL 参与计算。
        clean = [bar for bar in bars if all(getattr(bar, field, None) is not None for field in ("open", "high", "low", "close"))]
        meta = symbol_meta[key]
        if len(clean) < 60:
            values.append([_market_label(market), symbol, meta.get("name", ""),
                           _safe_date(getattr(clean[-1], "trade_date", "")) if clean else ""] + [""] * 16 + ["历史不足60日"])
            continue
        opens = [float(bar.open) for bar in clean]
        highs = [float(bar.high) for bar in clean]
        lows = [float(bar.low) for bar in clean]
        closes = [float(bar.close) for bar in clean]
        volumes = [float(getattr(bar, "volume", 0) or 0) for bar in clean]
        indicators = calculate_indicators(highs, lows, closes)
        evaluated = evaluate_strong_bs(opens, highs, lows, closes, volumes,
                                        dates=[_safe_date(getattr(bar, "trade_date", "")) for bar in clean])
        index = len(closes) - 1
        macd = indicators["macd"]
        kdj = indicators["kdj"]
        rsi = indicators["rsi"]
        checks = evaluated.get("checks") or {}
        bs_status = {"strong_buy": "强B", "holding": "持有", "sell": "卖出", "watch": "观察"}.get(
            evaluated.get("status"), evaluated.get("status") or "未知")
        values.append([
            _market_label(market), symbol, meta.get("name", ""), _safe_date(clean[-1].trade_date),
            _number(indicators["ma5"][index]), _number(indicators["ma20"][index]), _number(indicators["ma60"][index]),
            _number(rsi[index]), _number(macd["dif"][index]), _number(macd["hist"][index]),
            _number(kdj["k"][index]), _number(kdj["d"][index]), bs_status,
            _number(evaluated.get("factor_value")),
            "是" if checks.get("ma_cross") else "否", "是" if checks.get("kdj_cross") else "否",
            "是" if checks.get("macd_double_positive") else "否", "是" if checks.get("above_ma60") else "否",
            "是" if checks.get("rsi_range") else "否", "是" if checks.get("liquidity") else "否", "有效",
        ])
    return values


def _collect_snapshot() -> dict[str, list[list[Any]]]:
    """从本地 JSON/数据库构建四个页签，失败的数据保留为空而非伪造数值。"""
    from api.shared import get_portfolio, get_watchlist
    from db.models import Watchlist
    from db.session import get_db_session

    now = _now_iso()
    watch_rows: dict[tuple[str, str], dict[str, Any]] = {}

    local = get_watchlist() or {}
    for item in local.get("stocks", []):
        symbol = str(item.get("code") or item.get("symbol") or "").strip()
        if not symbol:
            continue
        watch_rows[("CN", symbol)] = {
            "market": "CN", "symbol": symbol, "name": item.get("name") or "",
            "sector": "", "group": item.get("group") or item.get("group_name") or "默认",
            "note": item.get("note") or "", "exchange": "", "source": "AIROBOT自选",
        }

    try:
        with get_db_session() as db:
            db_rows = db.query(Watchlist).all()
            for item in db_rows:
                symbol = str(item.stock_code or "").strip()
                if symbol and ("CN", symbol) not in watch_rows:
                    watch_rows[("CN", symbol)] = {
                        "market": "CN", "symbol": symbol, "name": item.stock_name or "",
                        "sector": "", "group": item.group_name or "默认", "note": item.note or "",
                        "exchange": "", "source": "AIROBOT数据库",
                    }
    except Exception as exc:
        logger.debug("读取 A 股自选失败: %s", exc)

    # 美股/港股自选采用数据库股票池，不从外部重新拉行情。
    try:
        from market_quant.repository import MarketInstrument, MarketUniverseMembership
        with get_db_session() as db:
            memberships = (db.query(MarketUniverseMembership)
                           .filter(MarketUniverseMembership.market.in_(["US", "HK"]),
                                   MarketUniverseMembership.effective_to.is_(None),
                                   MarketUniverseMembership.universe_code.in_(["US_WATCHLIST", "HK_WATCHLIST"]))
                           .order_by(MarketUniverseMembership.market, MarketUniverseMembership.rank)
                           .all())
            symbols = list({(m.market, m.symbol) for m in memberships})
            instruments = (db.query(MarketInstrument)
                           .filter(MarketInstrument.market.in_([m for m, _ in symbols]),
                                   MarketInstrument.symbol.in_([s for _, s in symbols])).all()) if symbols else []
            instrument_map = {(i.market, i.symbol): i for i in instruments}
            for member in memberships:
                key = (str(member.market).upper(), str(member.symbol).upper())
                inst = instrument_map.get(key)
                watch_rows[key] = {
                    "market": key[0], "symbol": key[1], "name": getattr(inst, "name", "") or "",
                    "sector": getattr(inst, "sector", "") or getattr(inst, "industry", "") or "",
                    "group": "盈立自选", "note": "", "exchange": getattr(inst, "exchange", "") or "",
                    "source": "股票池数据库",
                }
    except Exception as exc:
        logger.debug("读取美股/港股自选失败: %s", exc)

    # 兼容旧版美股股票池表（USUniverseMembership）。新版优先使用 market_quant 表，
    # 但已有用户数据可能仍只存在旧表，不能因为表迁移而让同步页签变空。
    try:
        from us_quant.repository import USInstrument, USUniverseMembership
        with get_db_session() as db:
            memberships = (db.query(USUniverseMembership)
                           .filter(USUniverseMembership.universe_code == "US_WATCHLIST",
                                   USUniverseMembership.effective_to.is_(None)).all())
            symbols = [str(member.symbol).upper() for member in memberships if member.symbol]
            instruments = (db.query(USInstrument).filter(USInstrument.symbol.in_(symbols)).all()) if symbols else []
            instrument_map = {str(item.symbol).upper(): item for item in instruments}
            for member in memberships:
                symbol = str(member.symbol).upper()
                item = instrument_map.get(symbol)
                watch_rows.setdefault(("US", symbol), {
                    "market": "US", "symbol": symbol, "name": getattr(item, "name", "") or "",
                    "sector": getattr(item, "sector", "") or getattr(item, "industry", "") or "",
                    "group": "股票池", "note": "", "exchange": getattr(item, "exchange", "") or "",
                    "source": "US股票池数据库",
                })
    except Exception as exc:
        logger.debug("读取旧版美股自选失败: %s", exc)

    for item in watch_rows.values():
        item["name"] = _display_name(item.get("market", ""), item.get("symbol", ""), item.get("name", ""))

    watch_headers = ["市场", "代码", "中文名称", "行业/板块", "分组", "备注", "Google Finance代码",
                     "Google现价", "Google当日涨幅", "来源", "同步时间"]
    watch_values: list[list[Any]] = [watch_headers]
    for row_number, item in enumerate(watch_rows.values(), start=2):
        market = item["market"]
        google_code = _google_symbol(market, item["symbol"], item.get("exchange", ""))
        watch_values.append([
            _market_label(market), item["symbol"], item["name"], item["sector"], item["group"], item["note"],
            google_code,
            _formula(row_number, "G", "price") if google_code else "",
            _formula(row_number, "G", "changepct") if google_code else "",
            item["source"], now,
        ])

    positions: list[dict[str, Any]] = []
    portfolio = get_portfolio() or {}
    for item in portfolio.get("positions", []):
        positions.append({"market": str(item.get("market") or "CN").upper(), "symbol": item.get("symbol") or "",
                          "name": item.get("name") or "", "quantity": item.get("quantity"),
                          "avg_cost": item.get("avg_cost"), "last_price": item.get("last_price"),
                          "day_pnl": item.get("day_pnl"), "day_pnl_pct": item.get("day_pnl_pct"),
                          "hold_pnl": item.get("unrealized_pnl"), "hold_pnl_pct": item.get("profit_ratio"),
                          "market_value": item.get("market_value"), "pos_pct": item.get("pos_pct"),
                          "source": item.get("source") or "AIROBOT持仓"})
    try:
        from us_quant.repository import USRealPosition
        with get_db_session() as db:
            rows = db.query(USRealPosition).filter(USRealPosition.status == "ACTIVE").all()
            for item in rows:
                positions.append({"market": "US", "symbol": item.symbol, "name": item.name or "",
                                  "quantity": item.quantity, "avg_cost": item.cost_price, "last_price": item.last_price,
                                  "day_pnl": item.today_profit, "day_pnl_pct": None, "hold_pnl": item.hold_profit,
                                  "hold_pnl_pct": item.hold_profit_pct, "market_value": item.market_value,
                                  "pos_pct": None, "source": "盈立真实持仓"})
    except Exception as exc:
        logger.debug("读取美股持仓失败: %s", exc)

    for item in positions:
        item["name"] = _display_name(item.get("market", ""), item.get("symbol", ""), item.get("name", ""))

    indicator_meta = dict(watch_rows)
    for item in positions:
        market = str(item.get("market") or "").upper()
        symbol = str(item.get("symbol") or "").strip().upper()
        if market in {"US", "HK"} and symbol:
            indicator_meta.setdefault((market, symbol), {
                "market": market, "symbol": symbol, "name": item.get("name") or "",
            })
    indicator_values = _collect_indicator_values(indicator_meta)

    position_headers = ["市场", "代码", "中文名称", "数量", "成本价", "现价", "Google现价", "当日盈亏",
                        "当日涨幅", "持仓盈亏", "持仓收益率", "市值", "仓位%", "来源", "同步时间"]
    position_values: list[list[Any]] = [position_headers]
    for row_number, item in enumerate(positions, start=2):
        google_code = _google_symbol(item["market"], item["symbol"])
        position_values.append([
            _market_label(item["market"]), item["symbol"], item["name"], _number(item["quantity"]),
            _number(item["avg_cost"]), _number(item["last_price"]),
            _formula(row_number, "G", "price") if google_code else "",
            _number(item["day_pnl"]), _number(item["day_pnl_pct"]), _number(item["hold_pnl"]),
            _number(item["hold_pnl_pct"]), _number(item["market_value"]), _number(item["pos_pct"]),
            item["source"], now,
        ])
        # Google Finance 代码作为隐藏/辅助字段不覆盖用户看到的现价列；公式使用 G 列时需要代码。
        if google_code:
            position_values[-1][6] = f'=IFERROR(GOOGLEFINANCE("{google_code}","price"),"")'

    signal_values: list[list[Any]] = [["市场", "代码", "中文名称", "策略", "信号类型", "状态", "评分",
                                       "计划入场", "止损", "目标", "信号时间", "市场环境", "来源"]]
    try:
        from us_quant.repository import USSignal
        with get_db_session() as db:
            signals = db.query(USSignal).order_by(USSignal.signal_time.desc()).limit(300).all()
            for signal in signals:
                signal_values.append([
                    "美股", signal.symbol, _display_name("US", signal.symbol, signal.name or ""), signal.strategy or "", signal.signal_type or "",
                    signal.lifecycle_status or "", _number(signal.score), _number(signal.planned_entry),
                    _number(signal.planned_stop), _number(signal.planned_target), _safe_date(signal.signal_time),
                    signal.market_regime or "", "USSignal数据库",
                ])
    except Exception as exc:
        logger.debug("读取美股信号失败: %s", exc)

    meta_values = [
        ["项目", "AIROBOT → Google Sheets"],
        ["同步时间", now],
        ["同步范围", "本地数据库中的 A 股/港股/美股自选、持仓与美股信号"],
        ["价格说明", "美股/港股行可用 GOOGLEFINANCE 公式补充价格；策略指标仍以 AIROBOT 数据库为准"],
        ["数据限制", "Google Finance 覆盖的市场与行情延迟由 Google 负责，A 股通常不支持"],
        ["更新方式", "授权后可手动同步，并由 AIROBOT 每 15 分钟自动同步"],
    ]
    return {"自选": watch_values, "持仓": position_values, "指标": indicator_values,
            "信号": signal_values, "说明": meta_values}


def _csv_for_sheet(sheet: str) -> str:
    snapshot = _collect_snapshot()
    values = snapshot.get(sheet)
    if values is None:
        raise GoogleSheetsError(f"不支持的导出页签: {sheet}")
    buffer = io.StringIO()
    csv.writer(buffer).writerows(values)
    return "\ufeff" + buffer.getvalue()


async def _ensure_spreadsheet(access_token: str, token: dict[str, Any]) -> tuple[str, str]:
    spreadsheet_id = str(token.get("spreadsheet_id") or "")
    spreadsheet_url = str(token.get("spreadsheet_url") or "")
    if not spreadsheet_id:
        created = await _sheets_request(
            "POST", "", access_token,
            json={"properties": {"title": "AIROBOT 投资同步"}},
        )
        spreadsheet_id = str(created.get("spreadsheetId") or "")
        spreadsheet_url = created.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        if not spreadsheet_id:
            raise GoogleSheetsError("Google 未返回新建表格 ID")
        token["spreadsheet_id"] = spreadsheet_id
        token["spreadsheet_url"] = spreadsheet_url

    detail = await _sheets_request(
        "GET", f"/{quote(spreadsheet_id, safe='')}", access_token,
        params={"fields": "sheets.properties(sheetId,title)"},
    )
    current = {item["properties"]["title"]: item["properties"]["sheetId"] for item in detail.get("sheets", [])}
    requests: list[dict[str, Any]] = []
    if "Sheet1" in current and not any(name in current for name in SHEET_NAMES):
        requests.append({"updateSheetProperties": {"properties": {"sheetId": current["Sheet1"], "title": SHEET_NAMES[0]}, "fields": "title"}})
        current[SHEET_NAMES[0]] = current.pop("Sheet1")
    for name in SHEET_NAMES:
        if name not in current:
            requests.append({"addSheet": {"properties": {"title": name}}})
    if requests:
        await _sheets_request(
            "POST", f"/{quote(spreadsheet_id, safe='')}:batchUpdate", access_token,
            json={"requests": requests},
        )
    return spreadsheet_id, spreadsheet_url


async def _write_values(access_token: str, spreadsheet_id: str, sheet: str, values: list[list[Any]]) -> None:
    encoded_range = quote(f"'{sheet}'!A:Z", safe="")
    await _sheets_request(
        "POST", f"/{quote(spreadsheet_id, safe='')}/values/{encoded_range}:clear", access_token,
        json={},
    )
    update_range = quote(f"'{sheet}'!A1", safe="")
    await _sheets_request(
        "PUT", f"/{quote(spreadsheet_id, safe='')}/values/{update_range}", access_token,
        params={"valueInputOption": "USER_ENTERED"},
        json={"range": f"'{sheet}'!A1", "majorDimension": "ROWS", "values": values},
    )


async def sync_now() -> dict[str, Any]:
    """同步四个页签到 Google Sheets。"""
    if not _configured():
        raise GoogleSheetsError("尚未配置 Google Sheets OAuth 凭据")
    token = _read_token()
    try:
        access_token = await _access_token()
        snapshot = await __import__("asyncio").to_thread(_collect_snapshot)
        spreadsheet_id, spreadsheet_url = await _ensure_spreadsheet(access_token, token)
        for sheet in SHEET_NAMES:
            await _write_values(access_token, spreadsheet_id, sheet, snapshot[sheet])
        counts = {name: max(0, len(values) - 1) for name, values in snapshot.items()}
        token.update({"spreadsheet_id": spreadsheet_id, "spreadsheet_url": spreadsheet_url,
                      "last_sync": _now_iso(), "last_counts": counts, "last_error": None})
        _write_token(token)
        return {"ok": True, "spreadsheet_url": spreadsheet_url, "last_sync": token["last_sync"], "counts": counts}
    except Exception as exc:
        token["last_error"] = str(exc)
        _write_token(token)
        if isinstance(exc, GoogleSheetsError):
            raise
        raise GoogleSheetsError(f"同步失败: {exc}") from exc


async def sync_if_configured() -> dict[str, Any]:
    status = get_status()
    if not status["configured"] or not status["connected"]:
        return {"ok": False, "skipped": True, "reason": "未完成 Google Sheets 配置或授权"}
    return await sync_now()


def disconnect() -> None:
    _clear_token()


__all__ = [
    "GoogleSheetsError", "build_authorization_url", "complete_authorization", "disconnect",
    "get_status", "sync_now", "sync_if_configured", "_csv_for_sheet",
]

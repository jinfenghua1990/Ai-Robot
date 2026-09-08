"""Real daily-bar providers shared by the HK and US pipelines."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Callable

logger = logging.getLogger(__name__)


def _range_for_days(days: int) -> str:
    if days <= 30:
        return "1mo"
    if days <= 120:
        return "6mo"
    if days <= 260:
        return "1y"
    if days <= 520:
        return "2y"
    return "5y"


def _clean_rows(rows: list[dict] | None) -> list[dict]:
    result = []
    for row in rows or []:
        raw_date = row.get("date") or row.get("trade_date")
        try:
            trade_date = date.fromisoformat(str(raw_date)[:10])
        except (TypeError, ValueError):
            continue
        try:
            close = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        def number(key: str, fallback: float | None = None) -> float | None:
            value = row.get(key, fallback)
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return fallback

        volume = number("volume", 0) or 0
        result.append({
            "trade_date": trade_date,
            "open": number("open", close),
            "high": number("high", close),
            "low": number("low", close),
            "close": close,
            "adjusted_close": number("adj_close") or number("adjusted_close") or close,
            "volume": int(max(volume, 0)),
            "amount": number("amount") or close * max(volume, 0),
        })
    return sorted({item["trade_date"]: item for item in result}.values(), key=lambda item: item["trade_date"])


def _first_real_source(
    sources: list[tuple[str, Callable]],
    requested_days: int,
) -> tuple[str, list[dict]] | None:
    best: tuple[str, list[dict]] | None = None
    target = max(2, int(requested_days * 0.8))
    for source, loader in sources:
        try:
            rows = _clean_rows(loader())
        except Exception as exc:
            logger.debug("market provider %s failed: %s", source, exc)
            continue
        if len(rows) < 2:
            continue
        if best is None or len(rows) > len(best[1]):
            best = source, rows
        # A source that covers most of the requested window is sufficient;
        # short Nasdaq windows are deliberately followed by longer sources.
        if len(rows) >= target:
            return source, rows
    return best


def _fetch_yfinance(market: str, symbol: str, days: int) -> list[dict]:
    """Read real OHLCV through the installed yfinance client.

    This is intentionally an optional provider.  It is used only when the
    direct Yahoo/Sina request is unavailable; an import or network failure
    simply makes the caller try the next source.
    """
    import yfinance as yf

    provider_symbol = symbol
    if market == "HK":
        provider_symbol = f"{int(symbol):04d}.HK"
    frame = yf.download(
        provider_symbol,
        period=_range_for_days(days),
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if frame is None or frame.empty:
        return []

    def series(name: str):
        value = frame[name]
        # yfinance returns a one-column DataFrame for some versions when a
        # ticker is supplied; squeeze it without changing the data.
        return value.iloc[:, 0] if getattr(value, "ndim", 1) > 1 else value

    opens = series("Open")
    highs = series("High")
    lows = series("Low")
    closes = series("Close")
    adjusted = series("Adj Close") if "Adj Close" in frame else closes
    volumes = series("Volume")
    rows = []
    for index in frame.index:
        close = closes.loc[index]
        if close != close:  # NaN without importing numpy just for this check
            continue
        rows.append({
            "date": index.strftime("%Y-%m-%d"),
            "open": opens.loc[index],
            "high": highs.loc[index],
            "low": lows.loc[index],
            "close": close,
            "adj_close": adjusted.loc[index],
            "volume": volumes.loc[index],
        })
    return rows


def fetch_daily(market: str, symbol: str, days: int = 1260) -> tuple[str, list[dict]] | None:
    """Fetch real OHLCV only; synthetic bars are intentionally excluded."""

    market = market.upper()
    if market == "US":
        from us_quant.collector import (
            _get_source_akshare,
            _get_source_klines_gstock,
            _get_source_klines_sina,
            _get_source_nasdaq,
            _get_source_yahoo,
        )

        # 新浪接口返回该标的可用的完整历史。新股天然不足 requested_days，
        # 不能因此串行等待多个内容相同的慢速备用源。
        try:
            sina_rows = _clean_rows(_get_source_klines_sina(symbol, days))
        except Exception as exc:
            logger.debug("market provider sina failed: %s", exc)
            sina_rows = []
        if len(sina_rows) >= 2:
            return "sina", sina_rows

        return _first_real_source([
            ("gstock", lambda: _get_source_klines_gstock(symbol, days)),
            ("akshare", lambda: _get_source_akshare(symbol, days)),
            ("nasdaq", lambda: _get_source_nasdaq(symbol, days)),
            ("yahoo", lambda: _get_source_yahoo(symbol, days)),
            ("yfinance", lambda: _fetch_yfinance("US", symbol, days)),
        ], days)

    if market == "HK":
        from api.global_market import _to_yahoo_symbol, _yahoo_fetch

        yahoo_symbol = _to_yahoo_symbol("HK", symbol)
        range_str = _range_for_days(days)
        return _first_real_source([
            ("yahoo_sina", lambda: _yahoo_fetch(yahoo_symbol, range_str=range_str)),
            ("yfinance", lambda: _fetch_yfinance("HK", symbol, days)),
        ], days)

    raise ValueError(f"unsupported market: {market}")

"""Research-only Yahoo Finance adapter for Hong Kong and US equities.

This adapter normalizes Yahoo's multi-index response into the same OHLCV
column names used by the research layer. It is intentionally not part of the
live A-share production pipeline.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd


def yahoo_symbol(code: str, market: str) -> str:
    normalized = code.strip().upper()
    if market.lower() in {"hk", "hong_kong", "港股"}:
        return normalized if normalized.endswith(".HK") else f"{normalized.zfill(4)}.HK"
    if market.lower() in {"us", "usa", "美股"}:
        return normalized.removesuffix(".US")
    raise ValueError(f"unsupported Yahoo market: {market}")


def normalize_yahoo_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Return a flat, dated OHLCV table and reject incomplete rows."""
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "trade_date", "open", "high", "low", "close", "volume"])
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [column[0] for column in data.columns]
    data = data.rename(columns={"Date": "trade_date", "Datetime": "trade_date"})
    data = data.reset_index(names="trade_date") if "trade_date" not in data.columns else data
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"Yahoo response missing columns: {sorted(missing)}")
    result = data[["trade_date", "Open", "High", "Low", "Close", "Volume"]].rename(columns={
        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
    })
    result.insert(0, "symbol", symbol)
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    return result.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def fetch_daily(codes: Iterable[str], market: str, period: str = "2y") -> pd.DataFrame:
    """Fetch daily research data for HK or US symbols via yfinance."""
    import yfinance as yf

    symbols = [yahoo_symbol(code, market) for code in codes]
    rows = []
    for symbol in symbols:
        frame = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False, threads=False)
        rows.append(normalize_yahoo_frame(frame, symbol))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()

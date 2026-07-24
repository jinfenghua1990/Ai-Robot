"""data_api — reimplemented data layer for the (deprecated) market-review endpoint.

The original Hermes ``data_api`` read from robot-1's collected store under
``/Users/gino/.hermes`` (removed during the Hermes→AIROBOT migration). That store
is gone, so this module sources live A-share market data from public providers
(akshare) instead.

Design rules:
* Every function degrades gracefully — on any failure it returns an empty /
  neutral structure, so market-review never crashes and only falls back to its
  built-in mock when no real data is available.
* No dependency on ``/Users/gino/.hermes`` or any removed path.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import akshare as ak

logger = logging.getLogger("data_api")

_CN_A_INDICES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
]


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, "", []):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    f = _to_float(value)
    if f is None:
        return default
    try:
        return int(round(f))
    except Exception:
        return default


def _yesterday_str() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def _find_col(row: dict[str, Any], candidates: list[str]) -> Any:
    for c in candidates:
        if c in row and row[c] not in (None, ""):
            return row[c]
    return None


def get_index_data(trade_date: Optional[str] = None, market: str = "CN_A") -> list[dict[str, Any]]:
    """Return CN_A aggregate index snapshot (上证 / 深证 / 创业板)."""
    rows: list[dict[str, Any]] = []
    for code, name in _CN_A_INDICES:
        try:
            df = ak.stock_zh_index_daily(symbol=code)
            if df is None or getattr(df, "empty", True):
                continue
            df = df.sort_values("date")
            if len(df) < 1:
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            close = _to_float(last.get("close"), 0.0) or 0.0
            prev_close = _to_float(prev.get("close"), 0.0) or 0.0
            chg = (close - prev_close) / prev_close * 100 if prev_close else 0.0
            rows.append(
                {
                    "index_code": code.upper(),
                    "index_name": name,
                    "close": close,
                    "change_pct": round(chg, 2),
                    "trade_date": str(last.get("date")),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        except Exception as exc:  # pragma: no cover - network/provider failure
            logger.warning("get_index_data %s failed: %s", code, exc)
    return rows


def get_limit_up_pool(
    trade_date: Optional[str] = None, market: str = "CN_A", limit: int = 200
) -> dict[str, Any]:
    date = (trade_date or _yesterday_str()).replace("-", "")
    try:
        df = ak.stock_zt_pool_em(date=date)
        if df is None or getattr(df, "empty", True):
            df = ak.stock_zt_pool_em(date=_yesterday_str())
        if df is not None and not getattr(df, "empty", True):
            data: list[dict[str, Any]] = []
            for _, r in df.iterrows():
                data.append(
                    {
                        "stock_code": str(r.get("代码", "")),
                        "stock_name": str(r.get("名称", "")),
                        "change_pct": _to_float(r.get("涨跌幅")),
                        "first_limit_up_time": str(r.get("首次封板时间", "")) or None,
                        "last_limit_up_time": str(r.get("最后封板时间", "")) or None,
                        "broken_count": _to_int(r.get("炸板次数")),
                        "limit_up_count": _to_int(r.get("连板数")),
                        "industry": str(r.get("所属行业", "")),
                        "trade_date": date,
                    }
                )
            return {"data": data[:limit]}
    except Exception as exc:  # pragma: no cover - network/provider failure
        logger.warning("get_limit_up_pool failed: %s", exc)
    return {"data": []}


def get_limit_pool_summary(
    trade_date: Optional[str] = None, market: str = "CN_A"
) -> dict[str, Any]:
    pool = get_limit_up_pool(trade_date=trade_date, market=market).get("data", [])
    return {"date": trade_date, "limit_up_count": len(pool), "data": pool}


def get_market_sentiment(
    trade_date: Optional[str] = None, market: str = "CN_A"
) -> list[dict[str, Any]]:
    # robot-1's computed sentiment table is gone; market-review derives emotion
    # from build_market_stage() instead, so an empty list is the correct signal.
    return []

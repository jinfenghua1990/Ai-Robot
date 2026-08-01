from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy import bindparam, text

from .db import engine
from .domain import Bar, MarketContext
from .factors import _ret


def _number(value, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_name(value: object) -> str:
    return str(value or "").upper().replace(" ", "").replace("　", "")


def is_st(name: object) -> bool:
    value = _clean_name(name)
    return value.startswith("ST") or value.startswith("*ST")


class MarketData:
    """Read-only adapter over the existing Ai-Robot database.

    No legacy ORM model or strategy service is imported here.  The new app
    consumes only raw daily bars, stock metadata and sector flow data.
    """

    def resolve_date(self, requested: date | None = None) -> date | None:
        sql = "SELECT MAX(trade_date) AS trade_date FROM stock_daily_kline"
        params = {}
        if requested:
            sql += " WHERE trade_date <= :requested"
            params["requested"] = requested
        with engine.connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
        return row["trade_date"] if row and row["trade_date"] else None

    def load_universe(self, trade_date: date) -> list[dict]:
        sql = text("""
            SELECT k.ts_code, k.close, k.volume,
                   COALESCE(s.name, '') AS name,
                   COALESCE(s.sector, k.sector, '') AS sector
            FROM stock_daily_kline k
            LEFT JOIN (
              SELECT DISTINCT ON (ts_code) ts_code, name, sector
              FROM stock_flow
              WHERE trade_date = :trade_date
              ORDER BY ts_code, id DESC
            ) s ON s.ts_code = k.ts_code
            WHERE k.trade_date = :trade_date
              AND COALESCE(k.close, 0) > 0
              AND COALESCE(k.volume, 0) > 0
            ORDER BY k.ts_code
        """)
        with engine.connect() as conn:
            rows = [dict(row._mapping) for row in conn.execute(sql, {"trade_date": trade_date})]
        result = []
        filtered_st = 0
        for row in rows:
            if is_st(row.get("name")):
                filtered_st += 1
                continue
            row["close"] = _number(row.get("close"))
            row["volume"] = _number(row.get("volume"))
            row["name"] = row.get("name") or row["ts_code"]
            row["sector"] = row.get("sector") or "未分类"
            result.append(row)
        self.last_filtered_st_count = filtered_st
        return result

    def load_history(self, codes: Iterable[str], trade_date: date, lookback_days: int = 240) -> dict[str, list[Bar]]:
        code_list = list(dict.fromkeys(codes))
        if not code_list:
            return {}
        start = trade_date - timedelta(days=lookback_days)
        stmt = text("""
            SELECT ts_code, trade_date, open, high, low, close, volume, amount, pct_chg, sector
            FROM stock_daily_kline
            WHERE ts_code IN :codes
              AND trade_date BETWEEN :start_date AND :trade_date
            ORDER BY ts_code, trade_date
        """).bindparams(bindparam("codes", expanding=True))
        with engine.connect() as conn:
            rows = conn.execute(stmt, {
                "codes": code_list, "start_date": start, "trade_date": trade_date,
            }).mappings().all()
        metadata = {item["ts_code"]: item for item in self.load_universe(trade_date)}
        result = {code: [] for code in code_list}
        for row in rows:
            meta = metadata.get(row["ts_code"], {})
            result.setdefault(row["ts_code"], []).append(Bar(
                code=row["ts_code"],
                trade_date=row["trade_date"],
                open=_number(row.get("open")), high=_number(row.get("high")),
                low=_number(row.get("low")), close=_number(row.get("close")),
                volume=_number(row.get("volume")), amount=_number(row.get("amount")),
                pct_chg=_number(row.get("pct_chg")),
                name=meta.get("name", ""), sector=row.get("sector") or meta.get("sector", "未分类"),
            ))
        return {
            code: bars[-120:]
            for code, bars in result.items()
            if bars and bars[-1].trade_date == trade_date
        }

    def load_sector_flow(self, trade_date: date) -> dict[str, dict[str, float | None]]:
        latest = None
        with engine.connect() as conn:
            latest = conn.execute(text(
                "SELECT MAX(trade_date) FROM sector_flow WHERE trade_date <= :trade_date"
            ), {"trade_date": trade_date}).scalar()
            if not latest:
                return {}
            rows = [dict(row._mapping) for row in conn.execute(text("""
                SELECT sector, net_flow, heat_score, rise_ratio, avg_chg
                FROM sector_flow WHERE trade_date = :trade_date
            """), {"trade_date": latest})]
        raw_flow = [_number(row.get("net_flow"), 0.0) for row in rows]
        ordered = sorted(raw_flow)
        result = {}
        for row in rows:
            flow = _number(row.get("net_flow"), 0.0)
            below = sum(value < flow for value in ordered)
            equal = sum(value == flow for value in ordered)
            percentile = 100 * (below + equal / 2) / len(ordered) if len(ordered) > 1 else 50.0
            rise = _number(row.get("rise_ratio"), 0.0)
            heat = _number(row.get("heat_score"), 0.0)
            avg_chg = _number(row.get("avg_chg"), 0.0)
            result[row["sector"]] = {
                "net_flow": flow,
                "net_flow_percentile": percentile,
                "strength": max(0.0, min(100.0, rise * 0.55 + max(0.0, min(100.0, heat)) * 0.25 + max(0.0, min(100.0, 50 + avg_chg * 10)) * 0.20)),
                "data_date": latest,
            }
        return result

    def market_context(self, trade_date: date, universe: list[dict], history: dict[str, list[Bar]]) -> MarketContext:
        changes = []
        limit_up = 0
        limit_down = 0
        returns = []
        for item in universe:
            bars = history.get(item["ts_code"], [])
            if not bars:
                continue
            bar = bars[-1]
            change = bar.pct_chg * 100 if abs(bar.pct_chg) <= 1 else bar.pct_chg
            changes.append(change)
            limit_up += change >= 9.5
            limit_down += change <= -9.5
            r20 = _ret([value.close for value in bars], 20)
            if r20 is not None:
                returns.append(r20)
        breadth = sum(value > 0 for value in changes) / len(changes) if changes else 0.0
        market_return = sum(returns) / len(returns) if returns else None
        balance = (limit_up - limit_down) / (limit_up + limit_down + 10)
        if breadth >= 0.68 and (market_return is None or market_return >= 0):
            state, sentiment = "STRONG", "偏强"
        elif breadth < 0.32 or balance <= -0.35 or (market_return is not None and market_return <= -0.08):
            state, sentiment = "WEAK", "偏弱"
        else:
            state, sentiment = "RANGE", "震荡"
        return MarketContext(
            trade_date, breadth, int(limit_up), int(limit_down), market_return,
            sentiment, state, "stock_daily_kline全市场截面代理",
        )

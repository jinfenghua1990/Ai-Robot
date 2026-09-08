"""Market-history persistence, quality checks and factor input loading."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.session import get_db_session
from quant_vnext.contracts import DailyBar, MarketContext
from .identity import normalize_market, normalize_symbol
from .providers import fetch_daily
from .repository import MarketDailyBar, MarketDataQualityRun, MarketInstrument

logger = logging.getLogger(__name__)

PRODUCTION_DAYS = 756
RESEARCH_DAYS = 1260
MIN_HISTORY_DAYS = 120
MIN_CROSS_SECTION = 20


def _history_is_current(
    existing_count: int,
    latest: date | None,
    target_date: date,
    force: bool,
) -> bool:
    return bool(
        not force
        and latest is not None
        and latest >= target_date
        and existing_count >= MIN_HISTORY_DAYS
    )


def backfill_symbol(
    market: str,
    symbol: str,
    days: int = RESEARCH_DAYS,
    force: bool = False,
    target_date: date | None = None,
) -> dict:
    market = normalize_market(market)
    symbol = normalize_symbol(market, symbol)
    if target_date is None:
        from .calendar import latest_completed_session
        target_date = latest_completed_session(market)
    with get_db_session() as db:
        existing_count = db.query(MarketDailyBar).filter(
            MarketDailyBar.market == market,
            MarketDailyBar.symbol == symbol,
        ).count()
        latest = db.query(func.max(MarketDailyBar.trade_date)).filter(
            MarketDailyBar.market == market,
            MarketDailyBar.symbol == symbol,
        ).scalar()
    if _history_is_current(existing_count, latest, target_date, force):
        return {
            "market": market, "symbol": symbol, "status": "cached",
            "rows": existing_count, "latest": latest.isoformat(),
        }

    # 已有足够研究历史时只拉小窗口补最新交易日；历史不足才全量回填。
    fetch_days = days
    if latest and existing_count >= MIN_HISTORY_DAYS and not force:
        fetch_days = min(days, max(10, (target_date - latest).days + 7))
    fetched = fetch_daily(market, symbol, fetch_days)
    if not fetched:
        return {"market": market, "symbol": symbol, "status": "failed", "rows": 0, "error": "no_real_data"}
    source, rows = fetched
    now = datetime.now()
    inserted = 0
    with get_db_session() as db:
        for row in rows:
            if row["trade_date"] > target_date:
                continue
            status = "VALID"
            reason = None
            if not row.get("high") or not row.get("low") or row["high"] < row["low"]:
                status, reason = "INVALID", "invalid_ohlc"
            if row["volume"] < 0:
                status, reason = "INVALID", "negative_volume"
            stmt = pg_insert(MarketDailyBar.__table__).values(
                market=market,
                symbol=symbol,
                trade_date=row["trade_date"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                adjusted_close=row["adjusted_close"],
                volume=row["volume"],
                amount=row["amount"],
                source=source,
                source_timestamp=now,
                is_adjusted=False,
                quality_status=status,
                quality_reason=reason,
            ).on_conflict_do_update(
                index_elements=["market", "symbol", "trade_date"],
                set_={
                    "open": row["open"], "high": row["high"], "low": row["low"],
                    "close": row["close"], "adjusted_close": row["adjusted_close"],
                    "volume": row["volume"], "amount": row["amount"],
                    "source": source, "source_timestamp": now,
                    "quality_status": status, "quality_reason": reason,
                },
            )
            db.execute(stmt)
            inserted += 1
        db.commit()
    return {
        "market": market, "symbol": symbol, "status": "updated",
        "rows": inserted, "source": source, "target_date": target_date.isoformat(),
    }


def backfill_market(
    market: str,
    symbols: Iterable[str],
    days: int = RESEARCH_DAYS,
    max_workers: int = 4,
    target_date: date | None = None,
) -> dict:
    market = normalize_market(market)
    symbol_list = list(dict.fromkeys(normalize_symbol(market, item) for item in symbols))
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(symbol_list) or 1))) as pool:
        futures = {
            pool.submit(backfill_symbol, market, symbol, days, False, target_date): symbol
            for symbol in symbol_list
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                logger.exception("backfill failed %s %s", market, symbol)
                results.append({"market": market, "symbol": symbol, "status": "failed", "error": str(exc)})
    return {
        "market": market,
        "total": len(symbol_list),
        "updated": sum(item.get("status") == "updated" for item in results),
        "cached": sum(item.get("status") == "cached" for item in results),
        "failed": sum(item.get("status") == "failed" for item in results),
        "results": results,
    }


def latest_trade_date(market: str, symbols: Iterable[str] | None = None) -> date | None:
    market = normalize_market(market)
    with get_db_session() as db:
        query = db.query(func.max(MarketDailyBar.trade_date)).filter(
            MarketDailyBar.market == market,
            MarketDailyBar.quality_status == "VALID",
        )
        if symbols:
            query = query.filter(MarketDailyBar.symbol.in_(list(symbols)))
        return query.scalar()


def history_status(market: str, symbols: Iterable[str]) -> dict:
    market = normalize_market(market)
    symbol_list = list(symbols)
    with get_db_session() as db:
        rows = db.query(
            MarketDailyBar.symbol,
            func.count(MarketDailyBar.id),
            func.max(MarketDailyBar.trade_date),
        ).filter(
            MarketDailyBar.market == market,
            MarketDailyBar.symbol.in_(symbol_list),
            MarketDailyBar.quality_status == "VALID",
        ).group_by(MarketDailyBar.symbol).all()
    by_symbol = {row[0]: {"rows": int(row[1]), "latest": row[2].isoformat() if row[2] else None} for row in rows}
    return {
        "market": market,
        "expected": len(symbol_list),
        "with_history": len(by_symbol),
        "min_rows": min((item["rows"] for item in by_symbol.values()), default=0),
        "max_rows": max((item["rows"] for item in by_symbol.values()), default=0),
        "missing": [symbol for symbol in symbol_list if symbol not in by_symbol],
        "items": by_symbol,
    }


def load_history(market: str, symbols: Iterable[str], trade_date: date, lookback: int = PRODUCTION_DAYS) -> dict[str, list[DailyBar]]:
    market = normalize_market(market)
    symbol_list = list(dict.fromkeys(symbols))
    if not symbol_list:
        return {}
    with get_db_session() as db:
        instruments = db.query(MarketInstrument).filter(
            MarketInstrument.market == market,
            MarketInstrument.symbol.in_(symbol_list),
        ).all()
        sector_by_symbol = {row.symbol: row.sector or row.industry or "" for row in instruments}
        rows = db.query(MarketDailyBar).filter(
            MarketDailyBar.market == market,
            MarketDailyBar.symbol.in_(symbol_list),
            MarketDailyBar.trade_date <= trade_date,
            MarketDailyBar.quality_status == "VALID",
        ).order_by(MarketDailyBar.symbol, MarketDailyBar.trade_date.desc()).all()

    grouped: dict[str, list[DailyBar]] = {symbol: [] for symbol in symbol_list}
    counts: dict[str, int] = {}
    for row in rows:
        count = counts.get(row.symbol, 0)
        if count >= lookback:
            continue
        # The stored OHLC is the actual market price because ``is_adjusted``
        # is false in the current ingestion contract. Keep adjusted_close
        # available in the table, but do not mix adjusted close with raw
        # high/low/open for production factors.
        input_close = row.adjusted_close if row.is_adjusted and row.adjusted_close is not None else row.close
        grouped[row.symbol].append(DailyBar(
            ts_code=row.symbol,
            trade_date=row.trade_date,
            open=float(row.open or 0),
            high=float(row.high or 0),
            low=float(row.low or 0),
            close=float(input_close or 0),
            volume=float(row.volume or 0),
            amount=float(row.amount or 0),
            pct_chg=0.0,
            sector=sector_by_symbol.get(row.symbol, ""),
        ))
        counts[row.symbol] = count + 1
    for symbol in grouped:
        grouped[symbol].reverse()
    return grouped


def market_context(history: dict[str, list[DailyBar]], trade_date: date, market: str, benchmark: str = "") -> MarketContext:
    latest = [bars[-1] for bars in history.values() if bars and bars[-1].trade_date == trade_date]
    breadth = sum(
        1 for bars in history.values()
        if bars and len(bars) >= 2 and bars[-1].close > bars[-2].close
    ) / len(latest) if latest else 0.0
    returns = []
    for bars in history.values():
        if len(bars) >= 21 and bars[-21].close:
            returns.append(bars[-1].close / bars[-21].close - 1)
    return MarketContext(
        trade_date=trade_date,
        breadth=breadth,
        market_return_20d=sum(returns) / len(returns) if returns else None,
        market_data_available=bool(latest),
        market=normalize_market(market),
        benchmark=benchmark,
    )

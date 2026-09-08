"""
US Quant — 因子计算值存储
将 compute_all_factors 的结果写入 USFactorScore 表
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.session import get_db_session
from us_quant.repository import USFactorScore, USStockDaily
from us_quant.factors import compute_all_factors, FACTOR_REGISTRY
from us_quant.bs_strategy import STRATEGY_META

logger = logging.getLogger(__name__)


def missing_factor_symbols(symbols: list[str], target_date: date) -> list[str]:
    """返回指定交易日尚无任何持久化因子的标的。"""
    expected = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if not expected:
        return []
    with get_db_session() as db:
        existing = {
            row[0] for row in db.query(USFactorScore.symbol).filter(
                USFactorScore.symbol.in_(expected),
                USFactorScore.trade_date == target_date,
            ).distinct().all()
        }
    return [symbol for symbol in expected if symbol not in existing]


def store_factors_for_symbol(
    symbol: str,
    trade_date: date,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    opens: list[float],
    volumes: list[float],
    db_session,
) -> int:
    """计算并存储单只股票单个交易日的所有因子值

    Args:
        symbol: 股票代码
        trade_date: 交易日
        closes/highs/lows/opens/volumes: 历史数据（用于因子计算）
        db_session: 数据库会话

    Returns:
        stored_count: 成功存储的因子数量
    """
    try:
        factor_values = compute_all_factors(
            closes=closes,
            highs=highs,
            lows=lows,
            opens=opens,
            volumes=volumes,
        )
    except Exception as exc:
        logger.debug(f"[factor_storage] {symbol} {trade_date} 因子计算失败: {exc}")
        return 0

    rows = []
    for key, meta in FACTOR_REGISTRY.items():
        value = factor_values.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        rows.append({
            "symbol": symbol,
            "trade_date": trade_date,
            "factor_name": key,
            "factor_category": meta.get("category", "未分类"),
            "factor_value": round(number, 6),
            "score_version": "1.0.0",
            "params": {"inputs": meta.get("params", [])},
        })

    if not rows:
        return 0

    insert_stmt = pg_insert(USFactorScore.__table__).values(rows)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["symbol", "trade_date", "factor_name"],
        set_={
            "factor_category": insert_stmt.excluded.factor_category,
            "factor_value": insert_stmt.excluded.factor_value,
            "score_version": insert_stmt.excluded.score_version,
            "params": insert_stmt.excluded.params,
        },
    )
    try:
        db_session.execute(stmt)
        db_session.commit()
    except Exception as exc:
        db_session.rollback()
        logger.warning("[factor_storage] %s %s 因子入库失败: %s", symbol, trade_date, exc)
        return 0

    logger.debug(f"[factor_storage] {symbol} {trade_date}: 存储 {len(rows)} 个因子")
    return len(rows)


def store_factors_for_latest(
    symbol: str,
    klines: list[dict],
    db_session,
) -> int:
    """为最新交易日存储因子值

    Args:
        symbol: 股票代码
        klines: 按日期升序排列的K线数据 [{"date","open","high","low","close","volume"}, ...]
        db_session: 数据库会话

    Returns:
        stored_count: 成功存储的因子数量
    """
    if len(klines) < 30:
        logger.debug(f"[factor_storage] {symbol}: K线数据不足30条，跳过")
        return 0

    complete = [
        item for item in klines
        if all(item.get(field) is not None for field in ("open", "high", "low", "close"))
    ]
    closes = [float(k["close"]) for k in complete]
    highs = [float(k["high"]) for k in complete]
    lows = [float(k["low"]) for k in complete]
    opens = [float(k["open"]) for k in complete]
    volumes = [float(k.get("volume") or 0) for k in complete]

    if len(closes) < 30:
        return 0

    latest_date_str = complete[-1]["date"]
    from datetime import datetime
    try:
        trade_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
    except (ValueError, KeyError):
        return 0

    return store_factors_for_symbol(
        symbol=symbol,
        trade_date=trade_date,
        closes=closes,
        highs=highs,
        lows=lows,
        opens=opens,
        volumes=volumes,
        db_session=db_session,
    )


def store_latest_factors_from_db(
    symbols: Optional[list[str]] = None,
    target_date: Optional[date] = None,
) -> dict:
    """从已落库日线计算指定交易日因子，供盘后任务和缺口补算复用。"""
    symbol_list = list(dict.fromkeys(s.strip().upper() for s in (symbols or []) if s.strip()))
    with get_db_session() as db:
        target_query = db.query(func.max(USStockDaily.trade_date)).filter(
            or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
        )
        if symbol_list:
            target_query = target_query.filter(USStockDaily.symbol.in_(symbol_list))
        effective_date = target_date or target_query.scalar()
        if effective_date is None:
            return {
                "target_date": None, "symbols": 0, "stored_rows": 0,
                "stale": [], "insufficient": [], "failed": [],
            }

        query = db.query(USStockDaily).filter(
            USStockDaily.trade_date <= effective_date,
            or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
        )
        if symbol_list:
            query = query.filter(USStockDaily.symbol.in_(symbol_list))
        bars = query.order_by(USStockDaily.symbol, USStockDaily.trade_date).all()

        grouped = defaultdict(list)
        for bar in bars:
            grouped[bar.symbol].append({
                "date": bar.trade_date.isoformat(),
                "open": float(bar.open) if bar.open is not None else None,
                "high": float(bar.high) if bar.high is not None else None,
                "low": float(bar.low) if bar.low is not None else None,
                "close": float(bar.close) if bar.close is not None else None,
                "volume": float(bar.volume or 0),
            })

        expected = symbol_list or sorted(grouped)
        stored_rows = 0
        processed = 0
        stale = []
        insufficient = []
        failed = []
        for symbol in expected:
            history = grouped.get(symbol, [])
            if not history or history[-1]["date"] != effective_date.isoformat():
                stale.append(symbol)
                continue
            if len(history) < 30:
                insufficient.append(symbol)
                continue
            count = store_factors_for_latest(symbol, history, db)
            if count:
                processed += 1
                stored_rows += count
            else:
                failed.append(symbol)

    return {
        "target_date": effective_date.isoformat(),
        "symbols": processed,
        "stored_rows": stored_rows,
        "stale": stale,
        "insufficient": insufficient,
        "failed": failed,
    }


def store_bs_strategy_factor_from_db(
    symbols: Optional[list[str]] = None,
    target_date: Optional[date] = None,
) -> dict:
    """仅补算强 B/S 状态因子，供首次部署快速回填，后续由常规盘后因子任务更新。"""
    from us_quant.bs_strategy import strong_bs_factor

    symbol_list = list(dict.fromkeys(s.strip().upper() for s in (symbols or []) if s.strip()))
    with get_db_session() as db:
        target_query = db.query(func.max(USStockDaily.trade_date)).filter(
            or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
        )
        if symbol_list:
            target_query = target_query.filter(USStockDaily.symbol.in_(symbol_list))
        effective_date = target_date or target_query.scalar()
        if effective_date is None:
            return {"target_date": None, "symbols": 0, "stale": []}
        query = db.query(USStockDaily).filter(
            USStockDaily.trade_date <= effective_date,
            or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
        )
        if symbol_list:
            query = query.filter(USStockDaily.symbol.in_(symbol_list))
        bars = query.order_by(USStockDaily.symbol, USStockDaily.trade_date).all()
        grouped = defaultdict(list)
        for bar in bars:
            if all(value is not None for value in (bar.open, bar.high, bar.low, bar.close)):
                grouped[bar.symbol].append(bar)
        rows, stale = [], []
        for symbol in symbol_list or sorted(grouped):
            history = grouped.get(symbol, [])[-500:]
            if len(history) < 60 or history[-1].trade_date != effective_date:
                stale.append(symbol)
                continue
            value = strong_bs_factor(
                [float(bar.close) for bar in history],
                [float(bar.high) for bar in history],
                [float(bar.low) for bar in history],
                [float(bar.open) for bar in history],
                [float(bar.volume or 0) for bar in history],
            )
            rows.append({
                "symbol": symbol,
                "trade_date": effective_date,
                "factor_name": STRATEGY_META["key"],
                "factor_category": "独立策略因子",
                "factor_value": value,
                "score_version": STRATEGY_META["version"],
                "params": {"route": STRATEGY_META["route"]},
            })
        if rows:
            insert_stmt = pg_insert(USFactorScore.__table__).values(rows)
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=["symbol", "trade_date", "factor_name"],
                set_={
                    "factor_category": insert_stmt.excluded.factor_category,
                    "factor_value": insert_stmt.excluded.factor_value,
                    "score_version": insert_stmt.excluded.score_version,
                    "params": insert_stmt.excluded.params,
                },
            )
            db.execute(stmt)
            db.commit()
    return {"target_date": effective_date.isoformat(), "symbols": len(rows), "stale": stale}


def get_latest_factor_values(symbol: str) -> dict | None:
    """读取单只股票最近一次已持久化的因子快照。"""
    symbol = symbol.strip().upper()
    with get_db_session() as db:
        latest_bar = db.query(func.max(USStockDaily.trade_date)).filter(
            USStockDaily.symbol == symbol,
            or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
        ).scalar()
        latest = db.query(func.max(USFactorScore.trade_date)).filter(
            USFactorScore.symbol == symbol,
        ).scalar()
        if latest is None:
            return None
        rows = db.query(USFactorScore).filter(
            USFactorScore.symbol == symbol,
            USFactorScore.trade_date == latest,
        ).order_by(USFactorScore.factor_name).all()
    values = {row.factor_name: float(row.factor_value) for row in rows}
    return {
        "symbol": symbol,
        "trade_date": latest.isoformat(),
        "data_trade_date": latest_bar.isoformat() if latest_bar else None,
        "is_current": latest_bar == latest and STRATEGY_META["key"] in values,
        "values": values,
    }

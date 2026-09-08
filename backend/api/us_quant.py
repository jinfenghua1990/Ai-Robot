"""US Quant System V2.1.1 — FastAPI 路由

所有 API 前缀: /api/us-quant
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from db.session import get_db_session

from us_quant.contracts import IndexQuote, MarketRegime, Signal
from us_quant.market_regime import assess_market_regime
from us_quant.sector_rotation import SECTOR_ETFS, score_sector, rank_sectors
from us_quant.strategies import score_breakout, score_pullback, score_earnings_gap
from us_quant.factors import compute_all_factors
from us_quant.strategy_registry import run_all_strategies
from us_quant.filters import check_hard_filters
from us_quant.states import determine_stock_state
from us_quant.risk import check_risk_veto, calculate_position_size
from us_quant.scanner import scan_premarket, check_intraday_trigger, create_signal
from sqlalchemy import func, literal

from us_quant.repository import ensure_schema
from us_quant.indicators import ema, sma, ma_bias
from services.indicators import (
    calc_kdj as calc_kdj_series,
    calc_macd as calc_macd_series,
    calc_rsi as calc_rsi_series,
)
from us_quant.repository import (
    USStrategyScore, USSignal, USScanRun, USBacktestResult, USBacktestTrade,
    USUniverseMembership, USWatchlistSectorPreference,
)
from us_quant.backtest import run_backtest_batch, resolve_backtest_pool
from us_quant.cache import scanner_cache, make_cache_key
from us_quant.strategy_registry import list_strategies, get_strategy
from us_quant.universe import run_full_rebalance as run_rebalance, UNIVERSE_DEFINITIONS as get_universe_definitions
from us_quant.universe import (
    list_universes, get_universe, get_universe_members,
    uniques_for_scanner, pool_stats, get_scanner_limit,
    remove_universe_member, add_universe_member, normalize_symbol,
    UNIVERSE_DEFINITIONS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/us-quant", tags=["us-quant"])

_WATCHLIST_REALTIME_CACHE: dict[str, dict] = {}
_WATCHLIST_REALTIME_LOCK = threading.Lock()
_WATCHLIST_REALTIME_TTL = 4.0


def _last_indicator_value(values: list) -> float | None:
    return next((float(value) for value in reversed(values) if value is not None), None)


def _latest_rsi(closes: list[float], period: int = 14) -> float | None:
    """Use the shared Wilder RSI implementation used by sector rotation."""
    return _last_indicator_value(calc_rsi_series(closes, period))


def _latest_macd(closes: list[float]) -> dict:
    """Return the latest shared MACD values without misaligning EMA origins."""
    dif_values, dea_values, macd_values = calc_macd_series(closes)
    dif = _last_indicator_value(dif_values)
    dea = _last_indicator_value(dea_values)
    histogram = _last_indicator_value(macd_values)
    if dif is None or dea is None:
        status = "N/A"
    elif dif > dea:
        status = "多头"
    elif dif < dea:
        status = "空头"
    else:
        status = "中性"
    return {
        "dif": round(dif, 4) if dif is not None else None,
        "dea": round(dea, 4) if dea is not None else None,
        "hist": round(histogram, 4) if histogram is not None else None,
        "macd": round(histogram, 4) if histogram is not None else None,
        "status": status,
    }


def _latest_kdj(highs: list[float], lows: list[float], closes: list[float]) -> dict:
    """Return KDJ from complete OHLC ranges, matching sector candidate metrics."""
    k_values, d_values, j_values = calc_kdj_series(highs, lows, closes)
    k = _last_indicator_value(k_values)
    d = _last_indicator_value(d_values)
    j = _last_indicator_value(j_values)
    if k is None or d is None:
        status = "N/A"
    elif k >= 80 and d >= 80:
        status = "超买"
    elif k <= 20 and d <= 20:
        status = "超卖"
    elif k > d:
        status = "金叉偏强"
    elif k < d:
        status = "死叉偏弱"
    else:
        status = "中性"
    return {
        "k": round(k, 2) if k is not None else None,
        "d": round(d, 2) if d is not None else None,
        "j": round(j, 2) if j is not None else None,
        "status": status,
    }


def _unified_snapshot_to_legacy(snapshot: dict) -> dict:
    """Adapt the new seven-dimension snapshot for old US page consumers."""
    rows = []
    for item in snapshot.get("signals") or []:
        dimensions = item.get("dimension_scores") or item.get("dimensions") or {}
        trend = dimensions.get("trend") or {}
        position = dimensions.get("position") or {}
        failed = item.get("failed_dimensions") or []
        rows.append({
            "symbol": item.get("symbol") or item.get("ts_code"),
            "name": item.get("name") or item.get("symbol"),
            "price": item.get("current_price"),
            "factor_score": item.get("factor_score"),
            "breakout_score": trend.get("score"),
            "pullback_score": position.get("score"),
            "primary_strategy": "统一七维因子",
            "hard_filter_pass": item.get("data_quality") == "VALID",
            "hard_filter_reasons": failed,
            "state": item.get("trading_state"),
            "state_label": item.get("lifecycle"),
            "dimension_scores": dimensions,
            "resonance_count": item.get("resonance_count", 0),
            "resonance_dimensions": item.get("resonance_dimensions", []),
            "failed_dimensions": failed,
            "data_quality": item.get("data_quality"),
            "risk_veto": item.get("risk_veto", False),
            "rank": item.get("rank"),
        })
    meta = {
        "status": snapshot.get("status"),
        "trade_date": snapshot.get("trade_date"),
        "source": "market_scan_snapshot",
        "pool_source": snapshot.get("universe"),
        "pool_total": snapshot.get("pool_total", 0),
        "scanned_count": snapshot.get("valid_count", 0),
        "candidate_count": snapshot.get("candidate_count", 0),
        "signal_count": snapshot.get("triggered_count", 0),
        "completed_at": snapshot.get("updated_at"),
    }
    return {
        "results": rows,
        "candidates": rows,
        "count": len(rows),
        "trade_date": snapshot.get("trade_date"),
        "scanned": snapshot.get("valid_count", 0),
        "pool_total": snapshot.get("pool_total", 0),
        "updated_at": snapshot.get("updated_at"),
        "scan_run": meta,
        "data_quality": snapshot.get("data_quality"),
    }


def _selection_history_from_runs(runs, symbols: list[str]) -> dict[str, dict]:
    """Summarize candidate continuity from already persisted post-market runs.

    ``runs`` must be newest first.  A missing row is deliberately treated as a
    break: the UI should not infer continuity from a gap in the persisted
    snapshot history.
    """
    recent_runs = list(runs or [])
    if not recent_runs or not symbols:
        return {}

    result = {}
    for symbol in symbols:
        selected_flags = []
        for run in recent_runs:
            payload = getattr(run, "payload", None) or {}
            if not isinstance(payload, dict):
                payload = {}
            signal = next(
                (
                    item for item in (payload.get("signals") or [])
                    if (item.get("symbol") or item.get("ts_code")) == symbol
                ),
                None,
            )
            resonance = (signal or {}).get("resonance") or {}
            selected_flags.append(bool(
                signal
                and resonance.get("eligible")
                and not signal.get("risk_veto")
            ))

        consecutive_days = 0
        for selected in selected_flags:
            if not selected:
                break
            consecutive_days += 1
        if not consecutive_days:
            continue

        window = min(5, len(recent_runs))
        start_run = recent_runs[consecutive_days - 1]
        result[symbol] = {
            "consecutive_days": consecutive_days,
            "selected_in_recent_scans": sum(selected_flags[:window]),
            "recent_scan_days": window,
            "streak_start_date": start_run.trade_date.isoformat() if start_run.trade_date else None,
        }
    return result


def _recent_snapshot_runs(snapshot: dict, limit: int = 20):
    """Read the persisted, same-universe post-market snapshots once per page."""
    universe = snapshot.get("universe")
    if not universe:
        return []
    try:
        from market_quant.repository import MarketScanRun

        with get_db_session() as db:
            return (
                db.query(MarketScanRun)
                .filter(
                    MarketScanRun.market == "US",
                    MarketScanRun.universe_code == universe,
                    MarketScanRun.status == "SUCCESS",
                )
                .order_by(MarketScanRun.trade_date.desc(), MarketScanRun.completed_at.desc())
                .limit(limit)
                .all()
            )
    except Exception as exc:
        logger.warning("[us-quant] recent post-market snapshots unavailable: %s", exc)
        return []


def _selection_history(snapshot: dict, symbols: list[str]) -> dict[str, dict]:
    """Read the recent, same-universe snapshots used for continuity badges."""
    if not symbols:
        return {}
    return _selection_history_from_runs(_recent_snapshot_runs(snapshot), symbols)


def _signal_by_symbol(run) -> dict[str, dict]:
    payload = getattr(run, "payload", None) or {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(item.get("symbol") or item.get("ts_code")).upper(): item
        for item in (payload.get("signals") or [])
        if item.get("symbol") or item.get("ts_code")
    }


def _is_selected_signal(item: dict | None) -> bool:
    return bool(
        item
        and (item.get("resonance") or {}).get("eligible")
        and not item.get("risk_veto")
    )


def _as_number(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _candidate_changes_from_runs(runs, current_items: list[dict]) -> tuple[dict[str, dict], dict]:
    """Describe today's candidates against the previous saved post-market run."""
    current = {
        str(item.get("symbol") or item.get("ts_code")).upper(): item
        for item in current_items
        if item.get("symbol") or item.get("ts_code")
    }
    base = {
        "available": False,
        "baseline_trade_date": None,
        "new_count": 0,
        "upgraded_count": 0,
        "strengthened_count": 0,
        "dropped": [],
    }
    if len(runs or []) < 2:
        return (
            {symbol: {"kind": "current", "label": "本轮入选", "detail": "等待上一份盘后快照"} for symbol in current},
            base,
        )

    previous_run = runs[1]
    previous = _signal_by_symbol(previous_run)
    changes: dict[str, dict] = {}
    counts = {"new": 0, "upgraded": 0, "strengthened": 0}
    for symbol, item in current.items():
        prior = previous.get(symbol)
        previous_date = previous_run.trade_date.isoformat() if previous_run.trade_date else None
        if not _is_selected_signal(prior):
            change = {"kind": "new", "label": "新入选", "detail": "上一盘后未入选", "previous_trade_date": previous_date}
        elif item.get("trading_state") == "TRIGGERED" and prior.get("trading_state") != "TRIGGERED":
            change = {"kind": "upgraded", "label": "观察升级为触发", "detail": "盘后状态升级", "previous_trade_date": previous_date}
        else:
            factor_delta = (_as_number(item.get("factor_score")) or 0) - (_as_number(prior.get("factor_score")) or 0)
            current_resonance = _as_number(item.get("resonance_count") or (item.get("resonance") or {}).get("count")) or 0
            previous_resonance = _as_number(prior.get("resonance_count") or (prior.get("resonance") or {}).get("count")) or 0
            resonance_delta = current_resonance - previous_resonance
            if factor_delta >= 1 or resonance_delta >= 1:
                details = []
                if factor_delta >= 1:
                    details.append(f"评分 +{factor_delta:.1f}")
                if resonance_delta >= 1:
                    details.append(f"共振 +{int(resonance_delta)}")
                change = {"kind": "strengthened", "label": "信号增强", "detail": " · ".join(details), "previous_trade_date": previous_date}
            else:
                change = {"kind": "continued", "label": "连续入选", "detail": "盘后条件保持", "previous_trade_date": previous_date}
        changes[symbol] = change
        if change["kind"] in counts:
            counts[change["kind"]] += 1

    dropped = [
        {
            "symbol": symbol,
            "name": item.get("name"),
            "previous_state": item.get("trading_state"),
        }
        for symbol, item in previous.items()
        if _is_selected_signal(item) and symbol not in current
    ]
    return changes, {
        "available": True,
        "baseline_trade_date": previous_run.trade_date.isoformat() if previous_run.trade_date else None,
        "new_count": counts["new"],
        "upgraded_count": counts["upgraded"],
        "strengthened_count": counts["strengthened"],
        "dropped": dropped[:8],
    }


def _daily_return_series(rows, lookback: int = 21) -> dict[str, dict[date, float]]:
    """Build a compact, real-DB close-to-close return series for correlation."""
    closes: dict[str, list[tuple[date, float]]] = {}
    for row in rows:
        close = _as_number(getattr(row, "close", None))
        if close is None or close <= 0:
            continue
        values = closes.setdefault(row.symbol, [])
        if len(values) < lookback:
            values.append((row.trade_date, close))
    output = {}
    for symbol, values in closes.items():
        values.reverse()  # query is newest first; daily returns need chronological order
        output[symbol] = {
            trade_date: close / previous_close - 1
            for (previous_date, previous_close), (trade_date, close) in zip(values, values[1:])
            if previous_close > 0
        }
    return output


def _pearson_correlation(left: dict[date, float], right: dict[date, float], min_common: int = 15) -> float | None:
    dates = sorted(set(left).intersection(right))
    if len(dates) < min_common:
        return None
    x_values = [left[item] for item in dates]
    y_values = [right[item] for item in dates]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    denominator = math.sqrt(
        sum((x - x_mean) ** 2 for x in x_values) * sum((y - y_mean) ** 2 for y in y_values)
    )
    return numerator / denominator if denominator else None


def _correlation_groups(return_series: dict[str, dict[date, float]], threshold: float = 0.75) -> tuple[list[dict], list[dict]]:
    """Return high-correlation pairs and connected components, with no sector inference."""
    symbols = sorted(return_series)
    pairs = []
    parents = {symbol: symbol for symbol in symbols}

    def find(symbol):
        while parents[symbol] != symbol:
            parents[symbol] = parents[parents[symbol]]
            symbol = parents[symbol]
        return symbol

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for index, left in enumerate(symbols):
        for right in symbols[index + 1:]:
            correlation = _pearson_correlation(return_series[left], return_series[right])
            if correlation is None or correlation < threshold:
                continue
            pairs.append({"left": left, "right": right, "correlation": round(correlation, 3)})
            union(left, right)

    grouped: dict[str, list[str]] = {}
    for symbol in symbols:
        grouped.setdefault(find(symbol), []).append(symbol)
    groups = []
    for members in grouped.values():
        if len(members) < 2:
            continue
        member_set = set(members)
        group_pairs = [pair for pair in pairs if pair["left"] in member_set and pair["right"] in member_set]
        groups.append({
            "symbols": members,
            "average_correlation": round(sum(pair["correlation"] for pair in group_pairs) / len(group_pairs), 3),
        })
    return pairs, groups


def _portfolio_guard(candidate_items: list[dict]) -> dict:
    """Give a non-binding diversification prompt from stored 20-session returns."""
    candidate_symbols = sorted({
        str(item.get("symbol") or item.get("ts_code")).upper()
        for item in candidate_items
        if item.get("symbol") or item.get("ts_code")
    })
    result = {
        "available": True,
        "source": "database_market_daily_bars",
        "correlation_window": 20,
        "threshold": 0.75,
        "policy": {"max_new_positions": 3, "max_correlated_new_positions": 2, "mode": "提示，不自动下单"},
        "active_positions": 0,
        "groups": [],
        "by_symbol": {symbol: {"already_held": False, "correlated_symbols": [], "group_size": 1} for symbol in candidate_symbols},
    }
    if not candidate_symbols:
        return result
    try:
        from market_quant.repository import MarketDailyBar
        from us_quant.repository import USRealPosition

        with get_db_session() as db:
            holdings = [str(row.symbol).upper() for row in db.query(USRealPosition).filter(
                USRealPosition.status == "ACTIVE",
            ).all() if row.symbol]
            symbols = sorted(set(candidate_symbols).union(holdings))
            latest_bar_date = db.query(func.max(MarketDailyBar.trade_date)).filter(
                MarketDailyBar.market == "US",
                MarketDailyBar.quality_status == "VALID",
            ).scalar()
            if latest_bar_date is None:
                result.update({"available": False, "error": "相关性历史待补齐"})
                return result
            rows = db.query(MarketDailyBar).filter(
                MarketDailyBar.market == "US",
                MarketDailyBar.symbol.in_(symbols),
                # 只需要最近 21 个交易日；保留 60 个自然日以覆盖节假日，避免页面读全量历史。
                MarketDailyBar.trade_date >= latest_bar_date - timedelta(days=60),
                MarketDailyBar.quality_status == "VALID",
            ).order_by(MarketDailyBar.symbol, MarketDailyBar.trade_date.desc()).all()
        series = _daily_return_series(rows, lookback=21)
        pairs, groups = _correlation_groups(series)
        holding_set = set(holdings)
        by_symbol = result["by_symbol"]
        for symbol in candidate_symbols:
            by_symbol[symbol]["already_held"] = symbol in holding_set
            related = []
            for pair in pairs:
                if pair["left"] == symbol:
                    related.append({"symbol": pair["right"], "correlation": pair["correlation"], "held": pair["right"] in holding_set})
                elif pair["right"] == symbol:
                    related.append({"symbol": pair["left"], "correlation": pair["correlation"], "held": pair["left"] in holding_set})
            by_symbol[symbol]["correlated_symbols"] = related
            if related:
                by_symbol[symbol]["group_size"] = len({symbol, *(item["symbol"] for item in related)})
        result.update({
            "active_positions": len(holdings),
            "groups": [
                {**group, "candidate_symbols": [symbol for symbol in group["symbols"] if symbol in candidate_symbols]}
                for group in groups
                if any(symbol in candidate_symbols for symbol in group["symbols"])
            ],
        })
    except Exception as exc:
        logger.warning("[us-quant] portfolio correlation guard unavailable: %s", exc)
        result.update({"available": False, "error": "相关性数据暂不可用"})
    return result


def _decision_review(snapshot: dict) -> dict:
    """Summarize only mature, stored outcomes; this never feeds today's score."""
    trade_date = snapshot.get("trade_date")
    try:
        as_of = date.fromisoformat(str(trade_date)[:10])
    except (TypeError, ValueError):
        return {"available": False, "reason": "缺少盘后交易日"}
    try:
        from market_quant.repository import MarketSignalOutcome

        with get_db_session() as db:
            rows = db.query(MarketSignalOutcome).filter(
                MarketSignalOutcome.market == "US",
                MarketSignalOutcome.trading_state == "TRIGGERED",
                MarketSignalOutcome.signal_date >= as_of - timedelta(days=365),
                MarketSignalOutcome.signal_date <= as_of,
            ).order_by(MarketSignalOutcome.signal_date.desc(), MarketSignalOutcome.symbol).all()
    except Exception as exc:
        logger.warning("[us-quant] decision review unavailable: %s", exc)
        return {"available": False, "reason": "历史复盘数据暂不可用"}

    horizons = []
    for days in (1, 3, 5, 10, 20):
        values = [_as_number(getattr(row, f"return_{days}d")) for row in rows]
        values = [value for value in values if value is not None]
        if not values:
            continue
        ordered = sorted(values)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        horizons.append({
            "days": days,
            "count": len(values),
            "win_rate": round(sum(value > 0 for value in values) / len(values) * 100, 1),
            "average_return": round(sum(values) / len(values) * 100, 2),
            "median_return": round(median * 100, 2),
        })
    return {
        "available": bool(horizons),
        "source": "market_signal_outcomes",
        "as_of": as_of.isoformat(),
        "window_start": (as_of - timedelta(days=365)).isoformat(),
        "strategy": "盘后触发",
        "horizons": horizons,
        "note": "只统计已成熟的历史盘后触发样本，不参与当日评分或自动下单。",
    }


def _decision_payload(snapshot: dict | None, regime_data: dict | None = None) -> dict:
    """Return the small, decision-oriented subset of a persisted US snapshot.

    A high factor score is not a buy decision by itself.  The dashboard must
    distinguish rows that are actually ``TRIGGERED`` from factor-qualified rows
    still waiting for a trigger, and must not promote risk-vetoed rows merely
    because they rank highly by factor score.
    """
    unavailable = {
        "available": False,
        "buyable": [],
        "watch": [],
        "counts": {"buyable": 0, "watch": 0, "qualified": 0, "risk_blocked": 0},
        "data_quality": (snapshot or {}).get("data_quality") or {
            "status": "NOT_READY", "message": "等待盘后统一因子快照",
        },
    }
    if not snapshot or snapshot.get("status") != "SUCCESS":
        return unavailable

    rows = snapshot.get("signals") or []
    buyable = [
        item for item in rows
        if item.get("trading_state") == "TRIGGERED" and not item.get("risk_veto")
    ]
    watch = [
        item for item in rows
        if (item.get("resonance") or {}).get("eligible")
        and item.get("trading_state") != "TRIGGERED"
        and not item.get("risk_veto")
    ]
    candidate_items = buyable + watch
    candidate_symbols = [
        item.get("symbol") or item.get("ts_code")
        for item in candidate_items
        if item.get("symbol") or item.get("ts_code")
    ]
    recent_runs = _recent_snapshot_runs(snapshot)
    selection_history = _selection_history_from_runs(recent_runs, candidate_symbols)
    selection_changes, changes = _candidate_changes_from_runs(recent_runs, candidate_items)
    # Only unified persisted snapshots have a market-quant universe.  Keeping
    # the legacy fixture/read path free of extra DB work preserves its contract.
    portfolio_guard = _portfolio_guard(candidate_items) if snapshot.get("universe") else {
        "available": False, "error": "等待统一盘后快照",
    }
    review = _decision_review(snapshot) if snapshot.get("universe") else {
        "available": False, "reason": "等待统一盘后快照",
    }

    def row(item: dict) -> dict:
        dimensions = item.get("dimension_scores") or item.get("dimensions") or {}
        symbol = item.get("symbol") or item.get("ts_code")
        symbol_key = str(symbol).upper() if symbol else ""
        return {
            "symbol": symbol,
            "name": item.get("name"),
            "price": item.get("current_price"),
            "factor_score": item.get("factor_score"),
            "rank": item.get("rank"),
            "lifecycle": item.get("lifecycle"),
            "trading_state": item.get("trading_state"),
            "resonance_count": item.get("resonance_count") or (item.get("resonance") or {}).get("count", 0),
            "trend_score": (dimensions.get("trend") or {}).get("score"),
            "position_score": (dimensions.get("position") or {}).get("score"),
            "strength_score": (dimensions.get("strength") or {}).get("score"),
            "risk_veto": bool(item.get("risk_veto")),
            "reason": (item.get("resonance") or {}).get("reason"),
            # 连续入选只统计同一候选池的已落库盘后快照；没有快照时保持缺失，前端不猜测。
            "selection_history": selection_history.get(symbol_key),
            # 与上一份已落库盘后快照比较；缺少基线时明确展示，不补造变化。
            "selection_change": selection_changes.get(symbol_key),
            # 行业字段不完整时仍可用实际日线相关性做组合重合提示。
            "portfolio_risk": (portfolio_guard.get("by_symbol") or {}).get(symbol_key),
        }

    regime = regime_data or {}
    return {
        "available": True,
        "trade_date": snapshot.get("trade_date"),
        "completed_at": snapshot.get("updated_at"),
        "pool_total": snapshot.get("pool_total", 0),
        "valid_count": snapshot.get("valid_count", 0),
        "data_quality": snapshot.get("data_quality"),
        "market_gate": {
            "allow_new_positions": regime.get("allow_new_positions"),
            "label": regime.get("label"),
            "reason": regime.get("reason"),
        },
        "buyable": [row(item) for item in buyable[:20]],
        "watch": [row(item) for item in watch[:20]],
        "changes": changes,
        "portfolio_guard": portfolio_guard,
        "review": review,
        "counts": {
            "buyable": len(buyable),
            "watch": len(watch),
            "qualified": len(buyable) + len(watch),
            "risk_blocked": sum(bool(item.get("risk_veto")) for item in rows),
        },
    }

def _save_scanner_to_db(candidates: list[dict]):
    """scanner symbols fallback 实时计算后落库 USStrategyScore，下次访问直接读 DB。"""
    try:
        from db.session import get_db_session
        from us_quant.repository import USStrategyScore
        today = date.today()
        with get_db_session() as db:
            existing_count = db.query(USStrategyScore).filter(
                USStrategyScore.trade_date == today
            ).count()
            if existing_count and existing_count >= len(candidates):
                return  # 已落库足够数据，不覆盖
            # 写入每个候选项
            written = 0
            for c in candidates:
                symbol = c.get("symbol")
                if not symbol:
                    continue
                entry = {
                    "symbol": symbol,
                    "price": c.get("price"),
                    "change_pct": c.get("change_pct"),
                    "rsi": c.get("rsi"),
                    "macd": c.get("macd"),
                    "kdj": c.get("kdj"),
                    "ema10": c.get("ema10"),
                    "ema20": c.get("ema20"),
                    "ma50": c.get("ma50"),
                    "breakout_score": c.get("breakout_score"),
                    "pullback_score": c.get("pullback_score"),
                    "factor_scores": c.get("factor_scores"),
                    "best_factor_key": c.get("best_factor_key"),
                    "best_factor_score": c.get("best_factor_score"),
                    "state": c.get("state"),
                    "state_label": c.get("state_label"),
                    "stop_loss": c.get("stop_loss"),
                }
                row = USStrategyScore(
                    trade_date=today,
                    symbol=symbol,
                    breakout_score=c.get("breakout_score"),
                    pullback_score=c.get("pullback_score"),
                    primary_strategy=c.get("best_factor_key"),
                    hard_filter_pass=c.get("hard_filter_pass", False),
                    state=c.get("state"),
                    state_label=c.get("state_label"),
                    score_details=entry,
                    strategy_version="2.0.0",
                )
                db.add(row)
                written += 1
            db.commit()
            if written:
                logger.debug(f"[us-quant] _save_scanner_to_db: saved {written} symbols")
    except Exception as exc:
        logger.debug("[us-quant] _save_scanner_to_db skipped: %s", exc)


# 盘后派生快照构建器：只读已入库日线，仅供定时采集任务调用。
def _index_quote_from_db(symbol: str, rows: list[dict], target_session: date) -> IndexQuote | None:
    if len(rows) < 50 or rows[-1].get("date") != target_session.isoformat():
        return None
    closes = [float(row["close"]) for row in rows if row.get("close") is not None]
    if len(closes) < 50:
        return None
    price = closes[-1]
    previous = closes[-2]
    return IndexQuote(
        symbol=symbol,
        name=symbol,
        price=price,
        change_pct=round((price / previous - 1) * 100, 2) if previous else 0.0,
        ma20=round(sum(closes[-20:]) / 20, 4),
        ma50=round(sum(closes[-50:]) / 50, 4),
    )


def _read_us_market_breadth(target_session: date) -> dict:
    """从已入库股票的实际涨跌和近一年高点计算市场宽度。"""
    from us_quant.repository import USInstrument, USStockDaily

    base_filters = (
        USInstrument.is_active.is_(True),
        USInstrument.is_etf.is_not(True),
        func.coalesce(USStockDaily.source, "") != "synthetic",
    )
    with get_db_session() as db:
        dates = [row[0] for row in db.query(USStockDaily.trade_date).join(
            USInstrument, USInstrument.symbol == USStockDaily.symbol,
        ).filter(
            *base_filters,
            USStockDaily.trade_date <= target_session,
            USStockDaily.close.isnot(None),
        ).distinct().order_by(USStockDaily.trade_date.desc()).limit(2).all()]
        if len(dates) < 2 or dates[0] != target_session:
            return {"status": "MISSING", "reason": "数据库缺少目标交易日市场宽度样本"}

        current_rows = db.query(USStockDaily.symbol, USStockDaily.close).join(
            USInstrument, USInstrument.symbol == USStockDaily.symbol,
        ).filter(
            *base_filters,
            USStockDaily.trade_date == dates[0],
            USStockDaily.close.isnot(None),
        ).all()
        previous_rows = db.query(USStockDaily.symbol, USStockDaily.close).join(
            USInstrument, USInstrument.symbol == USStockDaily.symbol,
        ).filter(
            *base_filters,
            USStockDaily.trade_date == dates[1],
            USStockDaily.close.isnot(None),
        ).all()
        high_rows = db.query(
            USStockDaily.symbol,
            func.max(USStockDaily.high),
        ).join(
            USInstrument, USInstrument.symbol == USStockDaily.symbol,
        ).filter(
            *base_filters,
            USStockDaily.trade_date >= target_session - timedelta(days=400),
            USStockDaily.trade_date <= target_session,
            USStockDaily.high.isnot(None),
        ).group_by(USStockDaily.symbol).all()

    current = {symbol: float(close) for symbol, close in current_rows}
    previous = {symbol: float(close) for symbol, close in previous_rows}
    highs = {symbol: float(high) for symbol, high in high_rows}
    comparable = sorted(set(current) & set(previous))
    high_comparable = sorted(set(current) & set(highs))
    if len(comparable) < 50 or len(high_comparable) < 50:
        return {
            "status": "INSUFFICIENT",
            "reason": f"市场宽度样本不足（涨跌 {len(comparable)} / 新高 {len(high_comparable)}）",
        }
    advancers = sum(current[symbol] > previous[symbol] for symbol in comparable)
    new_highs = sum(current[symbol] >= highs[symbol] * 0.98 for symbol in high_comparable)
    return {
        "status": "READY",
        "advancers_pct": round(advancers / len(comparable) * 100, 4),
        "new_high_pct": round(new_highs / len(high_comparable) * 100, 4),
        "sample_count": len(comparable),
        "previous_session": dates[1].isoformat(),
    }


def build_regime_snapshot_from_db(target_session: date) -> dict:
    """只用同一交易日的数据库日线计算市场环境。"""
    from us_quant.data_provider import get_klines_batch

    required = ["SPY", "QQQ", "IWM", "RSP", "^VIX"]
    rows_by_symbol = get_klines_batch(required, "3mo")
    missing = [symbol for symbol in required if not rows_by_symbol.get(symbol)]
    stale = [
        symbol for symbol in required
        if rows_by_symbol.get(symbol)
        and rows_by_symbol[symbol][-1].get("date") != target_session.isoformat()
    ]
    if missing or stale:
        return {
            "status": "MISSING" if missing else "STALE",
            "source": "database",
            "target_session": target_session.isoformat(),
            "missing_symbols": missing,
            "stale_symbols": stale,
        }

    quotes = {
        symbol: _index_quote_from_db(symbol, rows_by_symbol[symbol], target_session)
        for symbol in ["SPY", "QQQ", "IWM", "RSP"]
    }
    invalid = [symbol for symbol, quote in quotes.items() if quote is None]
    if invalid:
        return {
            "status": "INSUFFICIENT", "source": "database",
            "target_session": target_session.isoformat(), "insufficient_symbols": invalid,
        }

    breadth = _read_us_market_breadth(target_session)
    if breadth.get("status") != "READY":
        return {"source": "database", "target_session": target_session.isoformat(), **breadth}

    vix = float(rows_by_symbol["^VIX"][-1]["close"])
    regime = assess_market_regime(
        spy=quotes["SPY"], qqq=quotes["QQQ"], iwm=quotes["IWM"], rsp=quotes["RSP"],
        vix=vix,
        advancers_pct=breadth["advancers_pct"],
        new_high_pct=breadth["new_high_pct"],
    )
    return {
        "status": "READY",
        "source": "database",
        "target_session": target_session.isoformat(),
        "data_as_of": target_session.isoformat(),
        "regime": regime.regime,
        "score": regime.score,
        "label": regime.label,
        "allow_new_positions": regime.allow_new_positions,
        "reason": regime.reason,
        "multipliers": {
            "breakout": regime.breakout_mult,
            "pullback": regime.pullback_mult,
            "earnings_gap": regime.earnings_gap_mult,
        },
        "indices": {
            symbol: {
                "price": quote.price, "change_pct": quote.change_pct,
                "ma20": quote.ma20, "ma50": quote.ma50,
            }
            for symbol, quote in quotes.items()
        },
        "vix": vix,
        "breadth": breadth,
    }


def build_sector_snapshot_from_db(target_session: date) -> dict:
    """只用同一交易日的数据库 ETF 日线计算行业排名。"""
    from us_quant.data_provider import get_klines_batch

    symbols = [item[0] for item in SECTOR_ETFS]
    rows_by_symbol = get_klines_batch(symbols + ["SPY"], "3mo")
    required = symbols + ["SPY"]
    missing = [symbol for symbol in required if not rows_by_symbol.get(symbol)]
    stale = [
        symbol for symbol in required
        if rows_by_symbol.get(symbol)
        and rows_by_symbol[symbol][-1].get("date") != target_session.isoformat()
    ]
    insufficient = [symbol for symbol in required if 0 < len(rows_by_symbol.get(symbol) or []) < 60]
    if missing or stale or insufficient:
        return {
            "status": "MISSING" if missing else "STALE" if stale else "INSUFFICIENT",
            "source": "database",
            "target_session": target_session.isoformat(),
            "missing_symbols": missing,
            "stale_symbols": stale,
            "insufficient_symbols": insufficient,
            "sectors": [],
        }

    spy_closes = [float(row["close"]) for row in rows_by_symbol["SPY"] if row.get("close") is not None]
    results = []
    for etf_symbol, etf_name, industry in SECTOR_ETFS:
        rows = rows_by_symbol[etf_symbol]
        closes = [float(row["close"]) for row in rows if row.get("close") is not None]
        volumes = [float(row.get("volume") or 0) for row in rows]
        ma20_values = sma(closes, 20)
        ma50_values = sma(closes, 50)
        average_volume = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else None
        results.append(score_sector(
            etf_symbol=etf_symbol,
            etf_name=etf_name,
            industry=industry,
            closes_5d=closes[-5:],
            closes_20d=closes[-20:],
            closes_60d=closes[-60:],
            spy_closes_20d=spy_closes[-20:],
            spy_closes_60d=spy_closes[-60:],
            volumes_20d=volumes[-5:],
            avg_volume_20d=average_volume,
            ma20=ma20_values[-1] if ma20_values else None,
            ma50=ma50_values[-1] if ma50_values else None,
            current_price=closes[-1],
        ))
    ranked = rank_sectors(results)
    return {
        "status": "READY",
        "source": "database",
        "target_session": target_session.isoformat(),
        "data_as_of": target_session.isoformat(),
        "sectors": [{
            "etf_symbol": item.etf_symbol,
            "etf_name": item.etf_name,
            "industry": item.industry,
            "total_score": item.total_score,
            "ret_5d": item.ret_5d,
            "ret_20d": item.ret_20d,
            "ret_60d": item.ret_60d,
            "rel_strength_20d": item.rel_strength_20d,
            "rel_strength_60d": item.rel_strength_60d,
            "ma_trend": item.ma_trend,
            "volume_activity": item.volume_activity,
            "rank": item.rank,
            "grade": item.grade,
        } for item in ranked],
    }


# ─── API 端点 ─────────────────────────────────────────────────────────────────

def _read_regime_snapshot() -> dict:
    """Read the latest persisted market regime without live fallback."""
    from market_quant.calendar import latest_completed_session
    from us_quant.repository import USMarketRegime, USStockDaily

    expected = latest_completed_session("US")
    required_symbols = ["SPY", "QQQ", "IWM", "RSP", "^VIX"]
    with get_db_session() as db:
        row = db.query(USMarketRegime).order_by(
            USMarketRegime.trade_date.desc(), USMarketRegime.id.desc()
        ).first()
        component_rows = db.query(
            USStockDaily.symbol, func.max(USStockDaily.trade_date),
        ).filter(
            USStockDaily.symbol.in_(required_symbols),
            USStockDaily.close.isnot(None),
            func.coalesce(USStockDaily.source, "") != "synthetic",
        ).group_by(USStockDaily.symbol).all()
    component_dates = {symbol: value for symbol, value in component_rows}
    if not row:
        return {
            "regime": "UNKNOWN", "score": 0, "label": "数据不足",
            "allow_new_positions": False,
            "reason": "数据库暂无市场环境快照，请等待采集任务入库",
            "multipliers": {"breakout": 0.0, "pullback": 0.0, "earnings_gap": 0.0},
            "indices": {}, "vix": None, "updated_at": None,
            "data_as_of": None, "expected_session": expected.isoformat(),
            "source": "database", "status": "MISSING",
        }

    stale_components = [
        symbol for symbol in required_symbols
        if component_dates.get(symbol) != expected
    ]
    status = "READY" if row.trade_date == expected and not stale_components else "STALE"
    actual_dates = [value for value in component_dates.values() if value]
    data_as_of = min(actual_dates).isoformat() if actual_dates else None
    multipliers = {
        "breakout": float(row.breakout_mult) if row.breakout_mult is not None else 1.0,
        "pullback": float(row.pullback_mult) if row.pullback_mult is not None else 1.0,
        "earnings_gap": float(row.earnings_gap_mult) if row.earnings_gap_mult is not None else 1.0,
    } if status == "READY" else {"breakout": 0.0, "pullback": 0.0, "earnings_gap": 0.0}
    return {
        "regime": row.regime,
        "score": float(row.score) if row.score is not None else 0,
        "label": row.label,
        "allow_new_positions": bool(row.allow_new_positions) if status == "READY" else False,
        "reason": row.reason if status == "READY" else (
            f"市场环境快照日 {row.trade_date.isoformat()} 与目标交易日 {expected.isoformat()} 不一致；"
            f"底层数据未齐：{', '.join(stale_components) or '无'}"
        ),
        "multipliers": multipliers,
        "indices": {
            "SPY": {"price": float(row.spy_price) if row.spy_price is not None else None,
                    "change_pct": None, "ma20": None, "ma50": None},
            "QQQ": {"price": float(row.qqq_price) if row.qqq_price is not None else None,
                    "change_pct": None, "ma20": None, "ma50": None},
        },
        "vix": float(row.vix) if row.vix is not None else None,
        "updated_at": row.created_at.isoformat() if row.created_at else None,
        "data_as_of": data_as_of,
        "snapshot_date": row.trade_date.isoformat(),
        "component_dates": {
            symbol: component_dates[symbol].isoformat() if component_dates.get(symbol) else None
            for symbol in required_symbols
        },
        "expected_session": expected.isoformat(),
        "source": "database",
        "status": status,
    }


def _read_sector_snapshot() -> dict:
    """Read the latest persisted sector ranking without live fallback."""
    from market_quant.calendar import latest_completed_session
    from us_quant.repository import USSectorScore

    expected = latest_completed_session("US")
    with get_db_session() as db:
        latest = db.query(func.max(USSectorScore.trade_date)).scalar()
        rows = (
            db.query(USSectorScore)
            .filter(USSectorScore.trade_date == latest)
            .order_by(USSectorScore.rank, USSectorScore.etf_symbol)
            .all()
            if latest else []
        )
    status = "READY" if latest == expected else "STALE" if rows else "MISSING"
    return {
        "sectors": [{
            "etf_symbol": row.etf_symbol,
            "etf_name": row.etf_name,
            "industry": row.industry,
            "total_score": float(row.total_score) if row.total_score is not None else None,
            "ret_5d": float(row.ret_5d) if row.ret_5d is not None else None,
            "ret_20d": float(row.ret_20d) if row.ret_20d is not None else None,
            "ret_60d": float(row.ret_60d) if row.ret_60d is not None else None,
            "rel_strength_20d": float(row.rel_strength_20d) if row.rel_strength_20d is not None else None,
            "rel_strength_60d": float(row.rel_strength_60d) if row.rel_strength_60d is not None else None,
            "ma_trend": float(row.ma_trend) if row.ma_trend is not None else None,
            "volume_activity": float(row.volume_activity) if row.volume_activity is not None else None,
            "rank": row.rank,
            "grade": row.grade,
        } for row in rows],
        "updated_at": rows[0].created_at.isoformat() if rows and rows[0].created_at else None,
        "data_as_of": latest.isoformat() if latest else None,
        "expected_session": expected.isoformat(),
        "source": "database",
        "status": status,
        "message": (
            f"数据库行业轮动快照停留在 {latest.isoformat()}"
            if status == "STALE" else
            "数据库暂无行业轮动快照，请等待采集任务入库"
            if status == "MISSING" else None
        ),
    }


@router.get("/regime")
async def get_regime():
    """获取数据库中的市场环境快照。"""
    return jsonable_encoder(await asyncio.to_thread(_read_regime_snapshot))

    # Legacy live-calculation implementation retained temporarily below; the
    # query endpoint returns above and never invokes it.
    # ── DB 优先：读 us_market_regime 表最近一条 ──
    try:
        from db.connection import SessionLocal
        from us_quant.repository import USMarketRegime
        with SessionLocal() as db:
            row = db.query(USMarketRegime).order_by(
                USMarketRegime.trade_date.desc()
            ).first()
            if row and row.trade_date >= (date.today() - timedelta(days=2)):
                return jsonable_encoder({
                    "regime": row.regime,
                    "score": float(row.score) if row.score is not None else 0,
                    "label": row.label,
                    "allow_new_positions": row.allow_new_positions,
                    "reason": row.reason,
                    "multipliers": {
                        "breakout": float(row.breakout_mult) if row.breakout_mult is not None else 1.0,
                        "pullback": float(row.pullback_mult) if row.pullback_mult is not None else 1.0,
                        "earnings_gap": float(row.earnings_gap_mult) if row.earnings_gap_mult is not None else 1.0,
                    },
                    "indices": {
                        "SPY": {"price": float(row.spy_price) if row.spy_price else 0, "change_pct": 0, "ma20": None, "ma50": None},
                        "QQQ": {"price": float(row.qqq_price) if row.qqq_price else 0, "change_pct": 0, "ma20": None, "ma50": None},
                    },
                    "vix": float(row.vix) if row.vix is not None else None,
                    "updated_at": row.created_at.isoformat() if row.created_at else datetime.utcnow().isoformat(),
                })
    except Exception:
        pass  # DB 读取失败 → fallback 实时计算

    # ── fallback：实时拉取 ETF K线计算 ──
    from us_quant.data_provider import get_klines_batch
    _batch = get_klines_batch(["SPY", "QQQ", "IWM", "RSP", "^VIX"], "2mo")
    indices = {
        "SPY": _batch.get("SPY"),
        "QQQ": _batch.get("QQQ"),
        "IWM": _batch.get("IWM"),
        "RSP": _batch.get("RSP"),
        "^VIX": _batch.get("^VIX"),
    }

    def _make_quote(symbol, klines, name) -> IndexQuote:
        if not klines or len(klines) < 2:
            return IndexQuote(symbol=symbol, name=name, price=0, change_pct=0)
        closes = [k["close"] for k in klines if k.get("close")]
        prices = [k["close"] for k in klines if k.get("close")]
        price = prices[-1] if prices else 0
        change_pct = (prices[-1] - prices[-2]) / prices[-2] * 100 if len(prices) >= 2 else 0
        ma20 = sum(closes[-20:]) / min(20, len(closes)) if len(closes) >= 20 else None
        ma50 = sum(closes[-50:]) / min(50, len(closes)) if len(closes) >= 50 else None
        return IndexQuote(
            symbol=symbol, name=name, price=price,
            change_pct=round(change_pct, 2),
            ma20=round(ma20, 2) if ma20 else None,
            ma50=round(ma50, 2) if ma50 else None,
        )

    spy_quote = _make_quote("SPY", indices["SPY"], "SPY")
    qqq_quote = _make_quote("QQQ", indices["QQQ"], "QQQ")
    iwm_quote = _make_quote("IWM", indices["IWM"], "IWM")
    rsp_quote = _make_quote("RSP", indices["RSP"], "RSP")

    # VIX
    vix = None
    if indices["^VIX"]:
        closes = [k["close"] for k in indices["^VIX"] if k.get("close")]
        if closes:
            vix = closes[-1]

    regime = assess_market_regime(
        spy=spy_quote, qqq=qqq_quote, iwm=iwm_quote, rsp=rsp_quote, vix=vix,
    )

    return jsonable_encoder({
        "regime": regime.regime,
        "score": regime.score,
        "label": regime.label,
        "allow_new_positions": regime.allow_new_positions,
        "reason": regime.reason,
        "multipliers": {
            "breakout": regime.breakout_mult,
            "pullback": regime.pullback_mult,
            "earnings_gap": regime.earnings_gap_mult,
        },
        "indices": {
            "SPY": {"price": spy_quote.price, "change_pct": spy_quote.change_pct, "ma20": spy_quote.ma20, "ma50": spy_quote.ma50},
            "QQQ": {"price": qqq_quote.price, "change_pct": qqq_quote.change_pct, "ma20": qqq_quote.ma20, "ma50": qqq_quote.ma50},
            "IWM": {"price": iwm_quote.price, "change_pct": iwm_quote.change_pct, "ma20": iwm_quote.ma20, "ma50": iwm_quote.ma50},
            "RSP": {"price": rsp_quote.price, "change_pct": rsp_quote.change_pct, "ma20": rsp_quote.ma20, "ma50": rsp_quote.ma50},
        },
        "vix": vix,
        "updated_at": datetime.utcnow().isoformat(),
    })


@router.get("/sectors")
async def get_sectors():
    """获取数据库中的行业轮动快照。"""
    return jsonable_encoder(await asyncio.to_thread(_read_sector_snapshot))

    # Legacy live-calculation implementation retained temporarily below; the
    # query endpoint returns above and never invokes it.
    # ── DB 优先：读 us_sector_scores 表最近一日 ──
    try:
        from db.connection import SessionLocal
        from us_quant.repository import USSectorScore
        with SessionLocal() as db:
            latest_date = db.query(USSectorScore.trade_date).order_by(
                USSectorScore.trade_date.desc()
            ).first()
            if latest_date and latest_date[0] >= (date.today() - timedelta(days=3)):
                rows = db.query(USSectorScore).filter(
                    USSectorScore.trade_date == latest_date[0]
                ).order_by(USSectorScore.rank).all()
                if rows:
                    return jsonable_encoder({
                        "sectors": [
                            {
                                "etf_symbol": r.etf_symbol,
                                "etf_name": r.etf_name,
                                "industry": r.industry,
                                "total_score": float(r.total_score) if r.total_score is not None else 0,
                                "ret_5d": float(r.ret_5d) if r.ret_5d is not None else 0,
                                "ret_20d": float(r.ret_20d) if r.ret_20d is not None else 0,
                                "ret_60d": float(r.ret_60d) if r.ret_60d is not None else 0,
                                "rel_strength_20d": float(r.rel_strength_20d) if r.rel_strength_20d is not None else 0,
                                "rel_strength_60d": float(r.rel_strength_60d) if r.rel_strength_60d is not None else 0,
                                "ma_trend": float(r.ma_trend) if r.ma_trend is not None else 0,
                                "volume_activity": float(r.volume_activity) if r.volume_activity is not None else 0,
                                "rank": r.rank,
                                "grade": r.grade,
                            }
                            for r in rows
                        ],
                        "updated_at": rows[0].created_at.isoformat() if rows[0].created_at else datetime.utcnow().isoformat(),
                    })
    except Exception:
        pass  # DB 读取失败 → fallback 实时计算

    # ── fallback：实时拉取 ETF K线计算 ──
    results = []
    today = date.today()

    # 一次性并行拉取所有行业 ETF + SPY（避免串行 13+ 次请求，首屏从数十秒降到数秒）
    from us_quant.data_provider import get_klines_batch
    _etf_symbols = [e[0] for e in SECTOR_ETFS]
    _klines_map = get_klines_batch(_etf_symbols + ["SPY"], "3mo")
    spy_klines = _klines_map.get("SPY")
    spy_closes = [k["close"] for k in spy_klines if k.get("close")] if spy_klines else []
    spy_closes_20d = spy_closes[-20:] if len(spy_closes) >= 20 else spy_closes
    spy_closes_60d = spy_closes[-60:] if len(spy_closes) >= 60 else spy_closes

    for etf_symbol, etf_name, industry in SECTOR_ETFS:
        klines = _klines_map.get(etf_symbol)
        if not klines:
            results.append(score_sector(etf_symbol, etf_name, industry, rank=0))
            continue

        closes = [k["close"] for k in klines if k.get("close")]
        volumes = [k["volume"] for k in klines if k.get("volume")]

        closes_5d = closes[-5:] if len(closes) >= 5 else closes
        closes_20d = closes[-20:] if len(closes) >= 20 else closes
        closes_60d = closes[-60:] if len(closes) >= 60 else closes

        # 均线
        ma20_vals = sma(closes, 20) if len(closes) >= 20 else []
        ma50_vals = sma(closes, 50) if len(closes) >= 50 else []
        current_price = closes[-1] if closes else None

        # 平均成交量
        avg_vol = sum(volumes) / len(volumes) if volumes else None

        sector = score_sector(
            etf_symbol=etf_symbol, etf_name=etf_name, industry=industry,
            closes_5d=closes_5d, closes_20d=closes_20d, closes_60d=closes_60d,
            spy_closes_20d=spy_closes_20d, spy_closes_60d=spy_closes_60d,
            volumes_20d=volumes[-20:] if len(volumes) >= 20 else volumes,
            avg_volume_20d=avg_vol,
            ma20=ma20_vals[-1] if ma20_vals else None,
            ma50=ma50_vals[-1] if ma50_vals else None,
            current_price=current_price,
        )
        results.append(sector)

    ranked = rank_sectors(results)
    sector_dicts = [
        {
            "etf_symbol": s.etf_symbol,
            "etf_name": s.etf_name,
            "industry": s.industry,
            "total_score": s.total_score,
            "ret_5d": s.ret_5d,
            "ret_20d": s.ret_20d,
            "ret_60d": s.ret_60d,
            "rel_strength_20d": s.rel_strength_20d,
            "rel_strength_60d": s.rel_strength_60d,
            "ma_trend": s.ma_trend,
            "volume_activity": s.volume_activity,
            "rank": s.rank,
            "grade": s.grade,
        }
        for s in ranked
    ]
    return jsonable_encoder({
        "sectors": sector_dicts,
        "updated_at": datetime.utcnow().isoformat(),
    })


@router.get("/scanner")
def get_scanner(
    symbols: str = Query("", description="逗号分隔的股票代码（与 universe 互斥；留空则从池取）"),
    universe: str = Query("", description="股票池：CORE_A / CORE_B / ALL / RESEARCH_DYNAMIC"),
    market_mult: float = 1.0,
    sector_mult: float = 1.0,
    refresh: bool = Query(False, description="强制刷新缓存"),
):
    """扫描并评分股票。V2.2: 缓存 2 分钟，refresh=true 强制刷新。"""
    # 防御：/overview 等内部直接函数调用时，FastAPI 不会解析 Query 默认值
    def _to_float(v: object, default: float = 1.0) -> float:
        if isinstance(v, (int, float)):
            return float(v)
        inner = getattr(v, "default", None)
        if isinstance(inner, (int, float)):
            return float(inner)
        return default

    market_mult = _to_float(market_mult)
    sector_mult = _to_float(sector_mult)
    cache_key = make_cache_key(scanner=True, symbols=symbols, universe=universe)

    # 统一生产策略中心只读取最近一次数据库快照；打开页面不再现场
    # 拉取几百只股票，也不再把旧三策略命中数当作生产评分。
    requested_universe = universe.strip().upper() if isinstance(universe, str) else ""
    if not symbols.strip() and requested_universe in {"", "CORE", "CORE_A", "CORE_B", "RESEARCH", "RESEARCH_DYNAMIC"}:
        try:
            from market_quant.service import get_latest_snapshot
            unified = get_latest_snapshot("US", "RESEARCH" if requested_universe == "RESEARCH_DYNAMIC" else requested_universe or "CORE", 100)
            if unified.get("status") == "SUCCESS":
                adapted = _unified_snapshot_to_legacy(unified)
                scanner_cache.set(cache_key, adapted, ttl=120)
                return jsonable_encoder(adapted)
        except Exception as exc:
            logger.warning("[us-quant] unified snapshot unavailable: %s", exc)
        if os.getenv("MARKET_QUANT_LEGACY_FALLBACK", "0").lower() not in {"1", "true", "yes"}:
            return jsonable_encoder({
                "candidates": [],
                "results": [],
                "count": 0,
                "pool": requested_universe or "CORE",
                "pool_total": 0,
                "scanned": 0,
                "status": unified.get("status", "NOT_READY") if "unified" in locals() else "NOT_READY",
                "data_quality": unified.get("data_quality") if "unified" in locals() else {"status": "NOT_READY"},
                "message": "等待美股统一因子快照，不在页面打开时现场采集",
            })

    # ── 缓存检查 ──
    if not refresh:
        cached = scanner_cache.get(cache_key)
        if cached is not None:
            return jsonable_encoder(cached)

    # ── 解析候选 ──
    if symbols.strip():
        # ── DB 优先：持仓等技术指标先查 us_strategy_scores 表，避免实时拉 K线 ──
        code_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        try:
            with get_db_session() as db:
                # 不强制要求 USScanRun 存在；每个代码读取数据库最新一条，
                # 旧快照继续展示但由状态字段明确标记，不现场补采。
                db_rows = db.query(USStrategyScore).filter(
                    USStrategyScore.symbol.in_(code_list),
                ).order_by(USStrategyScore.trade_date.desc()).all()
                if db_rows:
                    # 去重：每个 symbol 只取最新一条
                    seen_syms = set()
                    db_map = {}
                    for r in db_rows:
                        if r.symbol not in seen_syms:
                            seen_syms.add(r.symbol)
                            db_map[r.symbol] = r
                    candidates = []
                    for sym in code_list:
                        r = db_map.get(sym)
                        if not r:
                            continue
                        detail = r.score_details if isinstance(r.score_details, dict) else {}
                        candidates.append({
                            **detail,
                            "symbol": r.symbol,
                            "name": r.name,
                            "breakout_score": float(r.breakout_score) if r.breakout_score is not None else detail.get("breakout_score"),
                            "pullback_score": float(r.pullback_score) if r.pullback_score is not None else detail.get("pullback_score"),
                            "primary_strategy": r.primary_strategy,
                            "state": r.state,
                            "state_label": r.state_label,
                        })
                    if candidates:
                        from market_quant.calendar import latest_completed_session
                        latest = db_rows[0].trade_date
                        missing = [sym for sym in code_list if sym not in db_map]
                        result = {"candidates": candidates, "results": candidates, "count": len(candidates),
                                  "pool": None, "scanned": len(candidates), "source": "database",
                                  "trade_date": latest.isoformat(),
                                  "status": "PARTIAL" if missing else
                                            "READY" if latest == latest_completed_session("US") else "STALE",
                                  "missing_symbols": missing}
                        scanner_cache.set(cache_key, result, ttl=120)
                        return jsonable_encoder(result)
        except Exception as exc:
            logger.debug("[us-quant] scanner DB fallback failed: %s", exc)
        return jsonable_encoder({
            "candidates": [], "results": [], "count": 0, "pool": None,
            "scanned": 0, "source": "database", "status": "MISSING",
            "missing_symbols": code_list,
            "message": "数据库暂无这些股票的策略快照，请等待采集任务入库",
        })
    elif universe.strip():
        uni = universe.strip().upper()
        if uni == "ALL":
            code_list = uniques_for_scanner(["CORE_A", "CORE_B"])
        else:
            code_list = get_universe_members(uni)
        limit = get_scanner_limit(uni) if uni != "ALL" else 120
        code_list = code_list[:limit]
        pool_source = uni
    else:
        return jsonable_encoder({"candidates": [], "count": 0, "message": "请提供股票代码或选择股票池", "pool": None})

    if not code_list:
        return jsonable_encoder({"candidates": [], "count": 0, "message": "股票池候选为空", "pool": pool_source})

    # 非统一快照股票池也只读取最近一次已入库评分，不在 GET 中抓取 K 线或写库。
    with get_db_session() as db:
        rows = db.query(USStrategyScore).filter(
            USStrategyScore.symbol.in_(code_list),
        ).order_by(USStrategyScore.trade_date.desc()).all()
    by_symbol = {}
    for row in rows:
        by_symbol.setdefault(row.symbol, row)
    candidates = []
    for symbol in code_list:
        row = by_symbol.get(symbol)
        if not row:
            continue
        detail = row.score_details if isinstance(row.score_details, dict) else {}
        candidates.append({
            **detail,
            "symbol": row.symbol,
            "name": row.name,
            "breakout_score": float(row.breakout_score) if row.breakout_score is not None else detail.get("breakout_score"),
            "pullback_score": float(row.pullback_score) if row.pullback_score is not None else detail.get("pullback_score"),
            "primary_strategy": row.primary_strategy,
            "state": row.state,
            "state_label": row.state_label,
        })
    latest = rows[0].trade_date if rows else None
    missing = [symbol for symbol in code_list if symbol not in by_symbol]
    if latest:
        from market_quant.calendar import latest_completed_session
        status = "PARTIAL" if missing else "READY" if latest == latest_completed_session("US") else "STALE"
    else:
        status = "MISSING"
    return jsonable_encoder({
        "candidates": candidates, "results": candidates, "count": len(candidates),
        "pool": pool_source, "pool_total": len(code_list), "scanned": len(candidates),
        "trade_date": latest.isoformat() if latest else None,
        "source": "database", "status": status, "missing_symbols": missing,
        "message": "数据库策略快照不完整，请等待采集任务补齐" if missing else None,
    })

    # Legacy live scanner retained temporarily below; the query endpoint returns above.
    # 并行批量拉取 K 线（单次最多 30 只，避免 Nasdaq 限流）
    from us_quant.data_provider import get_klines_batch
    max_scan = min(len(code_list), 30)
    _klines_map = get_klines_batch(code_list[:max_scan], "3mo")
    candidates = []

    for symbol in code_list[:max_scan]:
        try:
            klines = _klines_map.get(symbol)
            if not klines:
                continue

            closes = [k["close"] for k in klines if k.get("close")]
            highs = [k["high"] for k in klines if k.get("high")]
            lows = [k["low"] for k in klines if k.get("low")]
            opens = [k["open"] for k in klines if k.get("open")]
            volumes = [k["volume"] for k in klines if k.get("volume")]
            price = closes[-1] if closes else None

            if not price:
                continue

            # 技术指标
            ema10_vals = ema(closes, 10)
            ema20_vals = ema(closes, 20)
            ma50_vals = sma(closes, 50)
            rsi_val = _latest_rsi(closes, 14)
            macd_val = _latest_macd(closes)
            kdj_val = _latest_kdj(highs, lows, closes)

            ema10 = ema10_vals[-1] if ema10_vals else None
            ema20 = ema20_vals[-1] if ema20_vals else None
            ma50 = ma50_vals[-1] if ma50_vals else None

            # 硬过滤
            hf = check_hard_filters(price=price)

            # 平台突破评分
            high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
            base_high = max(closes[-20:]) if len(closes) >= 20 else max(closes)
            base_low = min(closes[-20:]) if len(closes) >= 20 else min(closes)
            base_days = 20
            rel_vol = (volumes[-1] / (sum(volumes[-5:]) / 5)) if len(volumes) >= 5 else 1.0
            change_today = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0

            bs = score_breakout(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                high_52w=high_52w, base_high=base_high, base_low=base_low,
                base_days=base_days, rel_volume=rel_vol,
                change_pct_today=change_today,
                market_mult=market_mult,
            )

            # 趋势回踩评分
            prior_uptrend = bool(ema10 and ema20 and ma50 and ema10 > ema20 > ma50)
            pullback_pct = None
            if len(closes) >= 10:
                peak = max(closes[-10:])
                pullback_pct = (peak - price) / peak * 100

            ps = score_pullback(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                prior_uptrend=prior_uptrend, first_pullback=True,
                pullback_pct=pullback_pct, volume_contracted=True,
                no_consecutive_bearish=True,
                market_mult=market_mult,
            )

            # 7状态
            state = determine_stock_state(
                price=price, ma20=ema20, ma50=ma50,
                rsi=rsi_val,
            )

            # ── 因子策略评分 ──
            factor_scores = {}
            best_factor_key = None
            best_factor_score = 0
            try:
                # 计算因子值
                factor_values = compute_all_factors(
                    closes=closes, highs=highs, lows=lows,
                    opens=opens, volumes=volumes,
                )
                # 构造策略参数
                factor_strategy_args = dict(
                    price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                    closes=closes, highs=highs, lows=lows, volumes=volumes,
                    high_52w=high_52w, volume_ratio=rel_vol,
                    rsi_14=rsi_val,
                    market_mult=market_mult, sector_mult=sector_mult,
                )
                # 注入因子值
                factor_strategy_args.update(factor_values)
                # 补充动量等计算
                if len(closes) >= 63:
                    factor_strategy_args["momentum_12_1"] = (closes[-1] - closes[-63]) / closes[-63] if closes[-63] > 0 else 0
                if len(closes) >= 126:
                    factor_strategy_args["momentum_6m"] = (closes[-1] - closes[-126]) / closes[-126] if closes[-126] > 0 else 0
                if len(closes) >= 252:
                    factor_strategy_args["momentum_risk_adjusted"] = (closes[-1] - closes[-252]) / closes[-252] if closes[-252] > 0 else 0
                if len(closes) >= 5:
                    factor_strategy_args["reversal_1w"] = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0
                if len(closes) >= 21:
                    factor_strategy_args["reversal_1m"] = (closes[-1] - closes[-21]) / closes[-21] if closes[-21] > 0 else 0
                # 量价指标
                if len(closes) >= 20 and volumes and len(volumes) >= 20:
                    # CMF 近似
                    cmf_val = 0
                    for i in range(1, 21):
                        if highs[-i] > lows[-i] and volumes[-i] > 0:
                            mf = ((closes[-i] - lows[-i]) - (highs[-i] - closes[-i])) / (highs[-i] - lows[-i]) * volumes[-i]
                            cmf_val += mf
                    total_vol = sum(volumes[-20:]) if volumes else 1
                    factor_strategy_args["cmf_val"] = cmf_val / total_vol if total_vol > 0 else 0
                    factor_strategy_args["cmf"] = factor_strategy_args["cmf_val"]
                # 价格/均线比
                if ema20:
                    factor_strategy_args["price_to_ma_20"] = price / ema20 if ema20 > 0 else 1
                if ma50:
                    factor_strategy_args["price_to_ma_50"] = price / ma50 if ma50 > 0 else 1
                # 季节效应
                month = datetime.now().month
                weekday = datetime.now().weekday()
                factor_strategy_args["seasonality_month"] = {1: 0.4, 2: 0.1, 3: 0.0, 4: 0.0, 5: -0.1, 6: -0.1, 7: 0.0, 8: -0.1, 9: -0.2, 10: 0.1, 11: 0.3, 12: 0.4}.get(month, 0.0)
                factor_strategy_args["seasonality_day_of_week"] = {0: -0.2, 1: 0.0, 2: 0.0, 3: 0.1, 4: 0.3, 5: 0.0, 6: 0.0}.get(weekday, 0.0)
                # 运行所有因子策略
                all_scores = run_all_strategies(**factor_strategy_args)
                for s in all_scores:
                    sk = s['key']
                    factor_scores[sk] = {
                        'score': s['score'],
                        'hard_pass': s['hard_pass'],
                        'fail_reasons': s['hard_fail_reasons'],
                        'name': s['name'],
                    }
                    if s.get('hard_pass') and s['score'] > best_factor_score:
                        best_factor_key = sk
                        best_factor_score = s['score']
            except Exception as fexc:
                logger.warning(f"[us-quant] factor strategy scoring error {symbol}: {fexc}")

            # 计算关键位
            stop_loss = None
            if ma50 and price:
                stop_loss = round(min(ma50 * 0.97, price * 0.95), 2)
            elif price:
                stop_loss = round(price * 0.95, 2)

            candidates.append({
                "symbol": symbol,
                "price": round(price, 2),
                "change_pct": round(change_today, 2),
                "rsi": round(rsi_val, 1) if rsi_val else None,
                "macd": macd_val,
                "kdj": kdj_val,
                "ema10": round(ema10, 2) if ema10 else None,
                "ema20": round(ema20, 2) if ema20 else None,
                "ma50": round(ma50, 2) if ma50 else None,
                "hard_filter_pass": hf.passed,
                "hard_filter_reasons": hf.reasons,
                "breakout_score": bs.total if bs.hard_pass else None,
                "breakout_details": bs.details,
                "pullback_score": ps.total if ps.hard_pass else None,
                "pullback_details": ps.details,
                "factor_scores": factor_scores,
                "best_factor_key": best_factor_key,
                "best_factor_score": round(best_factor_score, 1) if best_factor_key else None,
                "state": state.state,
                "state_label": state.label,
                "state_signal": state.signal,
                "stop_loss": stop_loss,
                "ma_bias": round(ma_bias(price, ma50), 2) if ma50 else None,
            })
        except Exception as exc:
            logger.warning(f"Scanner error for {symbol}: {exc}")
            continue

    candidates.sort(key=lambda x: max(
        x.get("breakout_score") or 0,
        x.get("pullback_score") or 0,
    ), reverse=True)

    # 计算排名
    for i, c in enumerate(candidates):
        c["rank"] = i + 1

    result = {
        "candidates": candidates,
        "count": len(candidates),
        "pool": pool_source,
        "pool_total": len(code_list),
        "scanned": max_scan,
        "updated_at": datetime.utcnow().isoformat(),
    }
    # ── 异步落库：实时计算后保存到 USStrategyScore，下次访问直接读 DB ──
    _save_scanner_to_db(candidates)
    # 缓存结果（2 分钟）
    scanner_cache.set(cache_key, result, ttl=120)
    return jsonable_encoder(result)


@router.get("/overview")
async def get_overview():
    """获取综合仪表盘数据"""
    from us_quant.data_provider import cached_live_availability, _get_proxies
    regime_data, sectors_data = await asyncio.gather(
        get_regime(),
        get_sectors(),
    )

    unified_snapshot = None
    try:
        from market_quant.service import get_latest_snapshot
        # 取全量候选（limit=500，不被截断），保证 scanner_count 与 scanner 页口径一致；
        # 下方仅把预览数组裁到 Top8，候选总数保持真实值。
        unified_snapshot = get_latest_snapshot("US", "CORE", 500)
    except Exception as exc:
        logger.warning("[us-quant] overview unified snapshot unavailable: %s", exc)

    # 优先读取最近一次盘后成功快照，避免打开总览时现场扫描。
    if unified_snapshot and unified_snapshot.get("status") not in {None, "NOT_READY"}:
        scanner_data = _unified_snapshot_to_legacy(unified_snapshot)
        # 总览页只预览 Top8 候选卡片，但候选总数（count）保留真实全量，避免与 scanner 页双口径。
        scanner_data["candidates"] = (scanner_data.get("candidates") or [])[:8]
        scanner_data["results"] = (scanner_data.get("results") or [])[:8]
    else:
        with get_db_session() as db:
            snapshot = _scan_snapshot(db)
        if snapshot["scan_run"] is not None:
            scanner_data = snapshot
        else:
            # 首次尚无新快照时返回空状态，不在页面打开时现场请求数据。
            scanner_data = {
                "candidates": [], "count": 0, "scan_run": None,
                "data_quality": {"status": "NOT_READY", "message": "等待盘后统一因子快照"},
            }

    decision = _decision_payload(unified_snapshot, regime_data)
    # 总览是盘后快照的只读入口，不应为了展示状态字段同步探测外网。
    # 没有新鲜探测结果时保留 ``live=False`` 的兼容字段，并明确标注未探测。
    live_cached = cached_live_availability()
    live = bool(live_cached)
    return jsonable_encoder({
        "regime": regime_data,
        "sectors": sectors_data["sectors"],
        "scanner": scanner_data.get("candidates", []),
        "scanner_count": scanner_data["count"],
        "scan": scanner_data.get("scan_run"),
        "data_quality": scanner_data.get("data_quality"),
        "updated_at": (scanner_data.get("scan_run") or {}).get("completed_at") or datetime.utcnow().isoformat(),
        "decision": decision,
        "system": {
            "status": "running",
            "mode": "SHADOW",
            "allow_live": False,
            "version": "2.1.1",
            "data_provider": "database",
            "live": live,
            "live_probe": "cached" if live_cached is not None else "not_checked",
            "proxy": (_get_proxies() or {}).get("https"),
            "broker": "none",
            "trading_enabled": False,
            "unified_snapshot": bool(unified_snapshot and unified_snapshot.get("status") not in {None, "NOT_READY"}),
            "legacy_regime_note": "市场环境卡片为兼容展示；生产评分只读取统一真实历史快照",
        },
    })


@router.get("/system/status")
def get_system_status():
    """获取系统状态；不在 GET 中探测外部数据源。"""
    from us_quant.data_provider import cached_live_availability, _get_proxies
    live_cached = cached_live_availability()
    proxies = _get_proxies()
    with get_db_session() as db:
        latest_scan = _scan_snapshot(db).get("scan_run")
    return jsonable_encoder({
        "status": "running",
        "mode": "SHADOW",
        "allow_live": False,
        "version": "2.1.1",
        "data_provider": "database",
        "live": bool(live_cached),
        "live_probe": "cached" if live_cached is not None else "not_checked",
        "source": "database",
        "proxy": proxies["https"] if proxies else None,
        "broker": "none",
        "trading_enabled": False,
        "last_scan": latest_scan,
        "uptime": datetime.utcnow().isoformat(),
    })


@router.get("/signals")
def get_signals(status: str = "ACTIVE"):
    """获取交易信号"""
    # 防御：refresh_signal_cache 等内部直调时 status 可能是 Query 对象
    if not isinstance(status, str):
        status = getattr(status, "default", "ACTIVE")
    try:
        with get_db_session() as db:
            from us_quant.repository import USSignal
            query = db.query(USSignal)
            if status != "ALL":
                query = query.filter(USSignal.lifecycle_status == status)
            rows = query.order_by(USSignal.created_at.desc()).limit(50).all()
            return jsonable_encoder({
                "signals": [
                    {
                        "id": r.id,
                        "symbol": r.symbol,
                        "name": r.name,
                        "strategy": r.strategy,
                        "signal_type": r.signal_type,
                        "lifecycle_status": r.lifecycle_status,
                        "score": float(r.score) if r.score else None,
                        "planned_entry": float(r.planned_entry) if r.planned_entry else None,
                        "planned_stop": float(r.planned_stop) if r.planned_stop else None,
                        "expected_rr": float(r.expected_rr) if r.expected_rr else None,
                        "risk_veto": r.risk_veto,
                        "market_regime": r.market_regime,
                        "signal_time": r.signal_time.isoformat() if r.signal_time else None,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ],
                "count": len(rows),
            })
    except Exception as exc:
        return jsonable_encoder({"signals": [], "count": 0, "error": str(exc)})


# ─── 预设美股扫描池（从数据库读取，universe.py 管理）───────────────────────

def _get_scan_pool() -> list[str]:
    """从数据库读取扫描池；缺失时显式返回空，不内置假池。"""
    try:
        from us_quant.universe import get_core_pool_symbols, get_all_pool_symbols
        pool = get_core_pool_symbols("CORE_A_300")
        if pool:
            return pool
        pool = get_all_pool_symbols()
        if pool:
            return pool
    except Exception:
        pass
    return []


# ─── 持仓技术指标计算 + 落库（供前端持仓 tab 直接读取，避免每次实时拉 K线）───

def compute_position_indicators(symbols: list[str]) -> dict:
    """为指定美股列表计算技术指标并落库到 USStrategyScore。

    数据流：USStockDaily 表只读 → 计算指标 → 落库；缺失数据交给定时采集任务补齐。
    用途：前端持仓 tab 的 scanner?symbols=xxx 调用直接读 DB，毫秒级返回。

    Args:
        symbols: 美股代码列表，如 ["AAPL", "MSFT"]

    Returns:
        {"total": int, "stored": int, "failed": int, "details": [...]}
    """
    if not symbols:
        return {"total": 0, "stored": 0, "failed": 0, "details": []}

    from us_quant.data_provider import get_klines
    stored = 0
    failed = 0
    details = []

    for symbol in symbols:
        sym = symbol.strip().upper()
        if not sym:
            continue
        try:
            # 1. 只从数据库读取 K 线；接口本身不触发任何外部采集。
            klines = get_klines(sym, "3mo")
            if not klines or len(klines) < 30:
                failed += 1
                details.append({
                    "symbol": sym,
                    "error": "数据库K线不足，请等待自动采集任务补齐",
                    "source": "database",
                })
                continue

            data_date = date.fromisoformat(str(klines[-1]["date"])[:10])

            closes = [k["close"] for k in klines if k.get("close")]
            highs = [k["high"] for k in klines if k.get("high")]
            lows = [k["low"] for k in klines if k.get("low")]
            volumes = [k["volume"] for k in klines if k.get("volume")]
            price = closes[-1] if closes else None
            if not price:
                failed += 1
                details.append({"symbol": sym, "error": "无有效收盘价"})
                continue

            # 2. 计算技术指标
            ema10_vals = ema(closes, 10)
            ema20_vals = ema(closes, 20)
            ma50_vals = sma(closes, 50)
            rsi_val = _latest_rsi(closes, 14)
            macd_val = _latest_macd(closes)
            kdj_val = _latest_kdj(highs, lows, closes)

            ema10 = ema10_vals[-1] if ema10_vals else None
            ema20 = ema20_vals[-1] if ema20_vals else None
            ma50 = ma50_vals[-1] if ma50_vals else None

            # 3. 策略评分（突破 + 回踩）
            high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
            base_high = max(closes[-20:]) if len(closes) >= 20 else max(closes)
            base_low = min(closes[-20:]) if len(closes) >= 20 else min(closes)
            rel_vol = (volumes[-1] / (sum(volumes[-5:]) / 5)) if len(volumes) >= 5 else 1.0
            change_today = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0

            bs = score_breakout(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                high_52w=high_52w, base_high=base_high, base_low=base_low,
                base_days=20, rel_volume=rel_vol, change_pct_today=change_today,
            )
            prior_uptrend = bool(ema10 and ema20 and ma50 and ema10 > ema20 > ma50)
            pullback_pct = None
            if len(closes) >= 10:
                peak = max(closes[-10:])
                pullback_pct = (peak - price) / peak * 100
            ps = score_pullback(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                prior_uptrend=prior_uptrend, first_pullback=True,
                pullback_pct=pullback_pct, volume_contracted=True,
                no_consecutive_bearish=True,
            )

            # 4. 状态判定
            state = determine_stock_state(price=price, ma20=ema20, ma50=ma50, rsi=rsi_val)

            # 5. 确定主策略
            primary = None
            max_score = 0
            if bs.hard_pass and bs.total > max_score:
                primary = "breakout"
                max_score = bs.total
            if ps.hard_pass and ps.total > max_score:
                primary = "pullback"
                max_score = ps.total

            # 5.5 无策略硬信号时，输出技术综合分（仅持仓展示用，不改变策略语义）
            if primary is None:
                composite = 50.0
                if ema10 and ema20 and ma50:
                    if ema10 > ema20 > ma50:
                        composite += 18
                    elif ema10 < ema20 < ma50:
                        composite -= 15
                    else:
                        composite += 4
                if rsi_val is not None:
                    if 45 <= rsi_val <= 68:
                        composite += 8
                    elif rsi_val > 75:
                        composite -= 6
                    elif rsi_val < 28:
                        composite += 3
                if macd_val.get("status") == "多头":
                    composite += 8
                elif macd_val.get("status") == "空头":
                    composite -= 6
                if kdj_val.get("status") in ("金叉", "金叉偏强"):
                    composite += 5
                elif kdj_val.get("status") in ("死叉", "死叉偏弱"):
                    composite -= 4
                primary = "overall"
                max_score = round(max(0.0, min(100.0, composite)), 1)

            # 6. 构建 entry（包含 MACD / KDJ，前端 buildUSRow 直接消费）
            entry = {
                "symbol": sym,
                "price": round(price, 2),
                "change_pct": round(change_today, 2),
                "rsi": round(rsi_val, 1) if rsi_val else None,
                "ema10": round(ema10, 2) if ema10 else None,
                "ema20": round(ema20, 2) if ema20 else None,
                "ma50": round(ma50, 2) if ma50 else None,
                "macd": {
                    "dif": macd_val.get("dif"),
                    "dea": macd_val.get("dea"),
                    "hist": macd_val.get("hist"),
                    "status": macd_val.get("status"),
                },
                "kdj": {
                    "k": kdj_val.get("k"),
                    "d": kdj_val.get("d"),
                    "j": kdj_val.get("j"),
                    "status": kdj_val.get("status"),
                },
                "breakout_score": round(bs.total, 1) if bs.hard_pass else None,
                "pullback_score": round(ps.total, 1) if ps.hard_pass else None,
                "best_factor_key": primary,
                "best_factor_score": round(max_score, 1) if primary else None,
                "primary_strategy": primary,
                "state": state.state,
                "state_label": state.label,
                "stop_loss": round(min(ma50 * 0.97, price * 0.95), 2) if ma50 else round(price * 0.95, 2),
            }

            # 7. 落库到 USStrategyScore（先删旧 → 写新）
            with get_db_session() as db:
                db.query(USStrategyScore).filter(
                    USStrategyScore.trade_date == data_date,
                    USStrategyScore.symbol == sym,
                ).delete()
                row = USStrategyScore(
                    trade_date=data_date,
                    symbol=sym,
                    breakout_score=round(bs.total, 1) if bs.hard_pass else None,
                    pullback_score=round(ps.total, 1) if ps.hard_pass else None,
                    primary_strategy=primary,
                    hard_filter_pass=bs.hard_pass or ps.hard_pass,
                    state=state.state,
                    state_label=state.label,
                    score_details=entry,
                    strategy_version="2.0.0",
                )
                db.add(row)
                db.commit()

            stored += 1
            details.append({"symbol": sym, "state": state.label, "score": max_score})
        except Exception as exc:
            failed += 1
            details.append({"symbol": sym, "error": str(exc)[:200]})
            logger.warning(f"[us-quant] compute_position_indicators {sym}: {exc}")

    logger.info(f"[us-quant] position indicators: {stored} stored, {failed} failed, {len(symbols)} total")
    return {"total": len(symbols), "stored": stored, "failed": failed, "details": details}


@router.post("/position-indicators/compute")
def api_compute_position_indicators():
    """手动触发持仓技术指标计算（定时任务也会调用）。

    读取 us_real_positions 表中的持仓股票 → 计算指标 → 落库 → 返回结果。
    """
    try:
        from us_quant.repository import USRealPosition
        with get_db_session() as db:
            rows = db.query(USRealPosition).filter(
                USRealPosition.status == "ACTIVE"
            ).all()
            symbols = [r.symbol for r in rows if r.symbol]
        if not symbols:
            return jsonable_encoder({"ok": False, "error": "无活跃持仓"})
        result = compute_position_indicators(symbols)
        return jsonable_encoder({"ok": True, **result})
    except Exception as exc:
        logger.error(f"[us-quant] position indicators compute error: {exc}", exc_info=True)
        return jsonable_encoder({"ok": False, "error": str(exc)})


# ─── 自动扫描（预设池+落库）───────────────────────────────────────────────────

def run_us_quant_scan(trade_date: Optional[str] = None, force: bool = False) -> dict:
    """盘后扫描并落库；同一交易日成功后幂等返回，避免定时重试重复写信号。"""
    # 生产扫描统一走 market_quant；旧 USStrategyScore/USSignal 表继续保留
    # 供历史页面和回测读取，但不再产生第二套选股结果。
    legacy_fallback = os.getenv("MARKET_QUANT_LEGACY_FALLBACK", "0").lower() in {"1", "true", "yes"}
    if not legacy_fallback:
        from market_quant.service import get_latest_snapshot, run_market_snapshot
        if not force:
            latest = get_latest_snapshot("US", "CORE", 100)
            if latest.get("status") == "SUCCESS" and latest.get("trade_date") == (trade_date or latest.get("trade_date")):
                return {
                    "status": "already_completed",
                    **_unified_snapshot_to_legacy(latest),
                }
        unified = run_market_snapshot("US", "CORE", 100, True)
        return {
            "status": "completed" if unified.get("status") == "SUCCESS" else unified.get("status", "not_ready"),
            **_unified_snapshot_to_legacy(unified),
            "data_quality": unified.get("data_quality"),
        }

    # 旧策略实现只作为显式兼容开关保留，默认不参与生产扫描。
    from us_quant.data_provider import get_klines_batch, get_quote
    from datetime import date as dt_date

    scan_date = trade_date or datetime.utcnow().strftime("%Y-%m-%d")
    scan_day = dt_date.fromisoformat(scan_date)
    symbols = _get_scan_pool()
    started_at = datetime.utcnow()
    with get_db_session() as db:
        scan_run = db.query(USScanRun).filter(USScanRun.trade_date == scan_day).first()
        if scan_run and scan_run.status == "COMPLETED" and not force:
            return {
                "status": "already_completed",
                "trade_date": scan_date,
                "count": scan_run.candidate_count or 0,
                "scored": scan_run.scanned_count or 0,
                "total": scan_run.pool_total or len(symbols),
                "updated_at": scan_run.completed_at.isoformat() if scan_run.completed_at else None,
            }
        if not scan_run:
            scan_run = USScanRun(trade_date=scan_day, started_at=started_at)
            db.add(scan_run)
        scan_run.status = "RUNNING"
        scan_run.source = "postmarket"
        scan_run.pool_source = "CORE_A_300"
        scan_run.pool_total = len(symbols)
        scan_run.started_at = started_at
        scan_run.completed_at = None
        scan_run.error = None
        db.commit()

    try:
        klines_map = get_klines_batch(symbols, "3mo")
    except Exception as exc:
        with get_db_session() as db:
            run = db.query(USScanRun).filter(USScanRun.trade_date == scan_day).first()
            if run:
                run.status = "FAILED"
                run.error = str(exc)[:500]
                run.completed_at = datetime.utcnow()
                db.commit()
        raise
    candidates = []
    scored = 0
    signal_count = 0

    for symbol in symbols:
        try:
            klines = klines_map.get(symbol)
            if not klines or len(klines) < 30:
                continue

            closes = [k["close"] for k in klines if k.get("close")]
            highs = [k["high"] for k in klines if k.get("high")]
            lows = [k["low"] for k in klines if k.get("low")]
            opens = [k["open"] for k in klines if k.get("open")]
            volumes = [k["volume"] for k in klines if k.get("volume")]
            price = closes[-1] if closes else None
            if not price:
                continue

            ema10_vals = ema(closes, 10)
            ema20_vals = ema(closes, 20)
            ma50_vals = sma(closes, 50)
            rsi_val = _latest_rsi(closes, 14)
            macd_val = _latest_macd(closes)
            kdj_val = _latest_kdj(highs, lows, closes)

            ema10 = ema10_vals[-1] if ema10_vals else None
            ema20 = ema20_vals[-1] if ema20_vals else None
            ma50 = ma50_vals[-1] if ma50_vals else None

            # 突破评分
            high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
            base_high = max(closes[-20:]) if len(closes) >= 20 else max(closes)
            base_low = min(closes[-20:]) if len(closes) >= 20 else min(closes)
            rel_vol = (volumes[-1] / (sum(volumes[-5:]) / 5)) if len(volumes) >= 5 else 1.0
            change_today = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0

            bs = score_breakout(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                high_52w=high_52w, base_high=base_high, base_low=base_low,
                base_days=20, rel_volume=rel_vol, change_pct_today=change_today,
            )

            # 回踩评分
            prior_uptrend = bool(ema10 and ema20 and ma50 and ema10 > ema20 > ma50)
            pullback_pct = None
            if len(closes) >= 10:
                peak = max(closes[-10:])
                pullback_pct = (peak - price) / peak * 100

            ps = score_pullback(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                prior_uptrend=prior_uptrend, first_pullback=True,
                pullback_pct=pullback_pct, volume_contracted=True,
                no_consecutive_bearish=True,
            )

            # 状态
            state = determine_stock_state(price=price, ma20=ema20, ma50=ma50, rsi=rsi_val)

            # ── 因子策略评分 ──
            factor_scores = {}
            best_factor_key = None
            best_factor_score = 0
            try:
                factor_values = compute_all_factors(
                    closes=closes, highs=highs, lows=lows,
                    opens=opens, volumes=volumes,
                )
                factor_strategy_args = dict(
                    price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                    closes=closes, highs=highs, lows=lows, volumes=volumes,
                    high_52w=high_52w, volume_ratio=rel_vol,
                    rsi_14=rsi_val,
                    market_mult=1.0, sector_mult=1.0,
                )
                factor_strategy_args.update(factor_values)
                if len(closes) >= 63:
                    factor_strategy_args["momentum_12_1"] = (closes[-1] - closes[-63]) / closes[-63] if closes[-63] > 0 else 0
                if len(closes) >= 126:
                    factor_strategy_args["momentum_6m"] = (closes[-1] - closes[-126]) / closes[-126] if closes[-126] > 0 else 0
                if len(closes) >= 252:
                    factor_strategy_args["momentum_risk_adjusted"] = (closes[-1] - closes[-252]) / closes[-252] if closes[-252] > 0 else 0
                if len(closes) >= 5:
                    factor_strategy_args["reversal_1w"] = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0
                if len(closes) >= 21:
                    factor_strategy_args["reversal_1m"] = (closes[-1] - closes[-21]) / closes[-21] if closes[-21] > 0 else 0
                if len(closes) >= 20 and volumes and len(volumes) >= 20:
                    cmf_val = 0
                    for i in range(1, 21):
                        if highs[-i] > lows[-i] and volumes[-i] > 0:
                            mf = ((closes[-i] - lows[-i]) - (highs[-i] - closes[-i])) / (highs[-i] - lows[-i]) * volumes[-i]
                            cmf_val += mf
                    total_vol = sum(volumes[-20:]) if volumes else 1
                    factor_strategy_args["cmf_val"] = cmf_val / total_vol if total_vol > 0 else 0
                    factor_strategy_args["cmf"] = factor_strategy_args["cmf_val"]
                if ema20:
                    factor_strategy_args["price_to_ma_20"] = price / ema20 if ema20 > 0 else 1
                if ma50:
                    factor_strategy_args["price_to_ma_50"] = price / ma50 if ma50 > 0 else 1
                month = datetime.now().month
                weekday = datetime.now().weekday()
                factor_strategy_args["seasonality_month"] = {1: 0.4, 2: 0.1, 3: 0.0, 4: 0.0, 5: -0.1, 6: -0.1, 7: 0.0, 8: -0.1, 9: -0.2, 10: 0.1, 11: 0.3, 12: 0.4}.get(month, 0.0)
                factor_strategy_args["seasonality_day_of_week"] = {0: -0.2, 1: 0.0, 2: 0.0, 3: 0.1, 4: 0.3, 5: 0.0, 6: 0.0}.get(weekday, 0.0)
                all_scores = run_all_strategies(**factor_strategy_args)
                for s in all_scores:
                    sk = s['key']
                    factor_scores[sk] = {
                        'score': s['score'],
                        'hard_pass': s['hard_pass'],
                        'fail_reasons': s['hard_fail_reasons'],
                        'name': s['name'],
                    }
                    if s.get('hard_pass') and s['score'] > best_factor_score:
                        best_factor_key = sk
                        best_factor_score = s['score']
            except Exception as fexc:
                logger.warning(f"[us-quant] scan factor strategy scoring error {symbol}: {fexc}")

            # 确定主策略
            primary = None
            max_score = 0
            if bs.hard_pass and bs.total > max_score:
                primary = "breakout"
                max_score = bs.total
            if ps.hard_pass and ps.total > max_score:
                primary = "pullback"
                max_score = ps.total

            if not primary:
                continue

            scored += 1
            entry = {
                "symbol": symbol,
                "price": round(price, 2),
                "change_pct": round(change_today, 2),
                "rsi": round(rsi_val, 1) if rsi_val else None,
                "ema10": round(ema10, 2) if ema10 else None,
                "ema20": round(ema20, 2) if ema20 else None,
                "ma50": round(ma50, 2) if ma50 else None,
                "macd": {
                    "dif": macd_val.get("dif"),
                    "dea": macd_val.get("dea"),
                    "hist": macd_val.get("hist"),
                    "status": macd_val.get("status"),
                },
                "kdj": {
                    "k": kdj_val.get("k"),
                    "d": kdj_val.get("d"),
                    "j": kdj_val.get("j"),
                    "status": kdj_val.get("status"),
                },
                "breakout_score": round(bs.total, 1) if bs.hard_pass else None,
                "pullback_score": round(ps.total, 1) if ps.hard_pass else None,
                "factor_scores": factor_scores,
                "best_factor_key": best_factor_key,
                "best_factor_score": round(best_factor_score, 1) if best_factor_key else None,
                "primary_strategy": primary,
                "state": state.state,
                "state_label": state.label,
                "stop_loss": round(min(ma50 * 0.97, price * 0.95), 2) if ma50 else round(price * 0.95, 2),
            }
            candidates.append(entry)

            # 落库到 USStrategyScore
            try:
                with get_db_session() as db:
                    # 先删旧记录
                    db.query(USStrategyScore).filter(
                        USStrategyScore.trade_date == scan_date,
                        USStrategyScore.symbol == symbol,
                    ).delete()
                    row = USStrategyScore(
                        trade_date=scan_date,
                        symbol=symbol,
                        breakout_score=round(bs.total, 1) if bs.hard_pass else None,
                        pullback_score=round(ps.total, 1) if ps.hard_pass else None,
                        primary_strategy=primary,
                        hard_filter_pass=bs.hard_pass or ps.hard_pass,
                        state=state.state,
                        state_label=state.label,
                        score_details=entry,
                        strategy_version="1.0.0",
                    )
                    db.add(row)
                    db.commit()
            except Exception as db_err:
                logger.warning(f"[us-quant] save strategy score failed {symbol}: {db_err}")

            # 高分（>=70）自动生成信号
            if max_score >= 70:
                signal_count += 1
                try:
                    with get_db_session() as db:
                        stop_loss = round(min(ma50 * 0.97, price * 0.95), 2) if ma50 else round(price * 0.95, 2)
                        target = round(price * 1.15, 2)
                        rr = round((target - price) / (price - stop_loss), 2) if (price - stop_loss) > 0 else 0

                        signal = USSignal(
                            symbol=symbol,
                            strategy=primary,
                            strategy_version="1.0.0",
                            signal_type="ENTRY",
                            lifecycle_status="DISCOVERED",
                            score=max_score,
                            signal_time=datetime.utcnow(),
                            expires_at=datetime.utcnow() + timedelta(days=3),
                            planned_entry=price,
                            planned_stop=stop_loss,
                            planned_target=target,
                            expected_rr=rr,
                        )
                        db.add(signal)
                        db.commit()
                except Exception as sig_err:
                    logger.warning(f"[us-quant] create signal failed {symbol}: {sig_err}")

        except Exception as exc:
            logger.warning(f"[us-quant] scan error {symbol}: {exc}")
            continue

    candidates.sort(key=lambda x: max(
        x.get("breakout_score") or 0,
        x.get("pullback_score") or 0,
    ), reverse=True)
    for i, c in enumerate(candidates):
        c["rank"] = i + 1

    # 没有任何可用日线时不能伪装成“扫描完成”。页面应明确显示失败，等待下一次重试。
    usable_klines = sum(1 for value in klines_map.values() if value)
    if usable_klines == 0:
        error = "没有获取到可用美股日线数据"
        with get_db_session() as db:
            scan_run = db.query(USScanRun).filter(USScanRun.trade_date == scan_day).first()
            if scan_run:
                scan_run.status = "FAILED"
                scan_run.error = error
                scan_run.scanned_count = 0
                scan_run.candidate_count = 0
                scan_run.signal_count = 0
                scan_run.completed_at = datetime.utcnow()
                db.commit()
        raise RuntimeError(error)

    completed_at = datetime.utcnow()
    with get_db_session() as db:
        scan_run = db.query(USScanRun).filter(USScanRun.trade_date == scan_day).first()
        if scan_run:
            scan_run.status = "COMPLETED"
            scan_run.scanned_count = len(klines_map)
            scan_run.candidate_count = len(candidates)
            scan_run.signal_count = signal_count
            scan_run.completed_at = completed_at
            db.commit()

    return {
        "status": "completed",
        "trade_date": scan_date,
        "candidates": candidates,
        "count": len(candidates),
        "scored": scored,
        "total": len(symbols),
        "updated_at": completed_at.isoformat(),
        "scan_run": {
            "status": "COMPLETED",
            "trade_date": scan_date,
            "scanned_count": len(klines_map),
            "candidate_count": len(candidates),
            "signal_count": signal_count,
            "completed_at": completed_at.isoformat(),
        },
    }


# ─── API: 触发自动扫描 ────────────────────────────────────────────────────────

@router.get("/scan")
def api_scan_snapshot():
    """读取最近一次扫描快照；GET 不触发计算或写库。"""
    with get_db_session() as db:
        snapshot = _scan_snapshot(db)
    return jsonable_encoder({"status": "ok", "source": "database", "result": snapshot})


@router.post("/scan")
async def api_scan(force: bool = False):
    """显式触发预设池扫描并落库。"""
    try:
        # 扫描包含批量行情读取和逐股计算，必须放到线程池，避免阻塞其他页面/API。
        result = await asyncio.to_thread(run_us_quant_scan, force=force)
        return jsonable_encoder({
            "status": "ok",
            "result": result,
        })
    except Exception as exc:
        return jsonable_encoder({"status": "error", "error": str(exc)})


def _latest_us_scan_run(db, trade_day=None):
    query = db.query(USScanRun).filter(USScanRun.status == "COMPLETED")
    if trade_day:
        query = query.filter(USScanRun.trade_date == trade_day)
    return query.order_by(USScanRun.trade_date.desc(), USScanRun.completed_at.desc()).first()


def _scan_snapshot(db, trade_day=None):
    try:
        from market_quant.service import get_latest_snapshot
        unified = get_latest_snapshot("US", "CORE", 100)
        if unified.get("status") not in {None, "NOT_READY"} and (trade_day is None or unified.get("trade_date") == trade_day.isoformat()):
            return _unified_snapshot_to_legacy(unified)
    except Exception as exc:
        logger.debug("[us-quant] read unified snapshot failed: %s", exc)
    scan_run = _latest_us_scan_run(db, trade_day)
    if not scan_run:
        return {"results": [], "candidates": [], "count": 0, "trade_date": None, "scan_run": None}

    rows = db.query(USStrategyScore).filter(
        USStrategyScore.trade_date == scan_run.trade_date,
        USStrategyScore.hard_filter_pass == True,
    ).order_by(
        (func.coalesce(USStrategyScore.breakout_score, 0) +
         func.coalesce(USStrategyScore.pullback_score, 0)).desc()
    ).limit(100).all()
    results = []
    for i, row in enumerate(rows, 1):
        detail = row.score_details if isinstance(row.score_details, dict) else {}
        results.append({
            **detail,
            "symbol": row.symbol,
            "breakout_score": float(row.breakout_score) if row.breakout_score is not None else detail.get("breakout_score"),
            "pullback_score": float(row.pullback_score) if row.pullback_score is not None else detail.get("pullback_score"),
            "primary_strategy": row.primary_strategy,
            "state": row.state,
            "state_label": row.state_label,
            "rank": i,
        })
    meta = {
        "status": scan_run.status,
        "trade_date": scan_run.trade_date.isoformat(),
        "source": scan_run.source,
        "pool_source": scan_run.pool_source,
        "pool_total": scan_run.pool_total or 0,
        "scanned_count": scan_run.scanned_count or 0,
        "candidate_count": scan_run.candidate_count or len(results),
        "signal_count": scan_run.signal_count or 0,
        "started_at": scan_run.started_at.isoformat() if scan_run.started_at else None,
        "completed_at": scan_run.completed_at.isoformat() if scan_run.completed_at else None,
    }
    return {
        "results": results,
        "candidates": results,
        "count": len(results),
        "trade_date": meta["trade_date"],
        "scanned": meta["scanned_count"],
        "pool_total": meta["pool_total"],
        "updated_at": meta["completed_at"],
        "scan_run": meta,
    }


# ─── API: 获取策略扫描结果 ────────────────────────────────────────────────────

@router.get("/scan-results")
def get_scan_results(trade_date: str = ""):
    """读取盘后扫描快照；未指定日期时返回最近一次成功运行。"""
    try:
        with get_db_session() as db:
            day = datetime.strptime(trade_date, "%Y-%m-%d").date() if trade_date else None
            return jsonable_encoder(_scan_snapshot(db, day))
    except Exception as exc:
        return jsonable_encoder({"results": [], "count": 0, "error": str(exc)})


# ─── 工具：清理 NaN/inf（JSON 不可序列化，否则 500）─────────────────────────────

def _sanitize(obj):
    """递归把 NaN/inf 转成 None，避免 jsonable_encoder 抛 ValueError。"""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


# ─── API: 触发回测 ────────────────────────────────────────────────────────────

@router.post("/backtest")
async def api_backtest(
    symbols: str = "",
    strategy: str = "ALL",
    start_date: str = "",
    end_date: str = "",
    pool_source: str = "",
):
    """从数据库运行回测并持久化结果；写操作只允许通过 POST 触发。"""
    try:
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
        results = await asyncio.to_thread(
            run_backtest_batch,
            symbols=sym_list,
            strategy=strategy,
            start_date=start_date or None,
            end_date=end_date or None,
            save_to_db=True,
            pool_source=pool_source or None,
        )
        return jsonable_encoder(_sanitize({
            "status": "ok",
            "results": [
                {
                    "symbol": r.symbol,
                    "strategy": r.strategy,
                    "total_trades": r.total_trades,
                    "winning_trades": r.winning_trades,
                    "losing_trades": r.losing_trades,
                    "win_rate": r.win_rate,
                    "total_pnl": r.total_pnl,
                    "total_pnl_pct": r.total_pnl_pct,
                    "profit_factor": r.profit_factor,
                    "max_drawdown_pct": r.max_drawdown_pct,
                    "sharpe_ratio": r.sharpe_ratio,
                    "avg_bars_held": r.avg_bars_held,
                }
                for r in results
            ],
"count": len(results),
        }))
    except Exception as exc:
        return jsonable_encoder({"status": "error", "error": str(exc)})


# ─── API: 查看回测结果 ────────────────────────────────────────────────────────

@router.get("/backtest/results")
def get_backtest_results(limit: int = 20):
    """获取最近的回测结果"""
    try:
        with get_db_session() as db:
            rows = db.query(USBacktestResult).order_by(
                USBacktestResult.run_at.desc()
            ).limit(limit).all()
            return jsonable_encoder(_sanitize({
                "results": [
                    {
                        "run_id": r.run_id,
                        "symbol": r.symbol,
                        "strategy": r.strategy,
                        "total_trades": r.total_trades,
                        "win_rate": float(r.win_rate) if r.win_rate else None,
                        "total_pnl_pct": float(r.total_pnl_pct) if r.total_pnl_pct else None,
                        "profit_factor": float(r.profit_factor) if r.profit_factor else None,
                        "max_drawdown_pct": float(r.max_drawdown_pct) if r.max_drawdown_pct else None,
                        "sharpe_ratio": float(r.sharpe_ratio) if r.sharpe_ratio else None,
                        "run_at": r.run_at.isoformat() if r.run_at else None,
                    }
                    for r in rows
                ],
                "count": len(rows),
            }))
    except Exception as exc:
        return jsonable_encoder({"results": [], "count": 0, "error": str(exc)})


# ─── API: 查看回测交易详情 ────────────────────────────────────────────────────

@router.get("/backtest/trades")
def get_backtest_trades(run_id: str = ""):
    """获取指定 run_id 的回测交易明细"""
    if not run_id:
        return jsonable_encoder({"trades": [], "error": "请提供 run_id"})
    try:
        with get_db_session() as db:
            rows = db.query(USBacktestTrade).filter(
                USBacktestTrade.run_id == run_id
            ).order_by(USBacktestTrade.entry_date).all()
            return jsonable_encoder({
                "trades": [
                    {
                        "symbol": r.symbol,
                        "strategy": r.strategy,
                        "entry_date": r.entry_date,
                        "entry_price": float(r.entry_price) if r.entry_price else None,
                        "exit_date": r.exit_date,
                        "exit_price": float(r.exit_price) if r.exit_price else None,
                        "direction": r.direction,
                        "shares": r.shares,
                        "pnl": float(r.pnl) if r.pnl else None,
                        "pnl_pct": float(r.pnl_pct) if r.pnl_pct else None,
                        "bars_held": r.bars_held,
                        "exit_reason": r.exit_reason,
                    }
                    for r in rows
                ],
                "count": len(rows),
            })
    except Exception as exc:
        return jsonable_encoder({"trades": [], "count": 0, "error": str(exc)})


# ═══════════════════════════════════════════════════════════════════════════
# 股票池 API（US_Quant_Stock_Universe_V2.0）
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/universes")
def get_universes():
    """列出所有股票池（含当前成员数量与目标数量）。"""
    return jsonable_encoder({
        "universes": list_universes(),
        "stats": pool_stats(),
    })


@router.get("/universe/{code}")
def get_universe_detail(code: str):
    """获取单个股票池的完整信息（定义 + 成员列表）。"""
    entry = get_universe(code)
    if not entry:
        return jsonable_encoder({"error": f"未知股票池: {code}"})
    return jsonable_encoder(entry)


@router.get("/universe/{code}/members")
def get_universe_members_api(code: str):
    """获取单个股票池的成员符号列表。"""
    members = get_universe_members(code)
    defn = UNIVERSE_DEFINITIONS.get(code.upper(), {})
    return jsonable_encoder({
        "universe": code.upper(),
        "name": defn.get("name", ""),
        "members": members,
        "count": len(members),
        "target": defn.get("target_count"),
    })


# ─── 美股/港股自选清单（像 A 股自选股一样渲染卡片）────────────────────────────

@router.get("/klines")
def us_klines(
    symbol: str = Query(...),
    days: int = Query(60, ge=2, le=500),
    end_date: Optional[date] = Query(None),
):
    """单只美股截至指定决策日的近 N 日 K 线（详情抽屉趋势图用）。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return jsonable_encoder({"ok": False, "error": "symbol required", "klines": []})
    try:
        from db.session import get_db_session
        from us_quant.repository import USStockDaily
        with get_db_session() as db:
            filters = [
                USStockDaily.symbol == symbol,
                func.coalesce(USStockDaily.source, "") != "synthetic",
            ]
            if end_date is not None:
                filters.append(USStockDaily.trade_date <= end_date)
            rows = db.query(USStockDaily).filter(*filters).order_by(USStockDaily.trade_date.desc()).limit(days).all()
            rows = list(reversed(rows))
        klines = [
            {"date": r.trade_date.strftime("%Y-%m-%d"),
             "open": float(r.open) if r.open else None,
             "high": float(r.high) if r.high else None,
             "low": float(r.low) if r.low else None,
             "close": float(r.close) if r.close else None,
             "volume": int(r.volume) if r.volume else 0}
            for r in rows
        ]
        return jsonable_encoder({"symbol": symbol, "end_date": end_date, "klines": klines, "count": len(klines)})
    except Exception as exc:
        logger.error(f"[us-quant] klines error {symbol}: {exc}")
        return jsonable_encoder({"error": str(exc), "symbol": symbol, "klines": []})


@router.get("/watchlist/realtime/stream")
async def us_watchlist_realtime_stream(market: str = Query("US"), interval: float = Query(5, ge=2, le=60)):
    """自选行情 SSE 流；每帧只读取数据库最新已落库日线。

    帧格式: {market, server_time, data: {SYM: {price, change_pct, quote_time}}}
    外部行情采集与本读取接口彻底分离，前端按 quote_time 判断新鲜度。
    """
    market = market.upper()

    async def _frame():
        while True:
            try:
                payload = await asyncio.to_thread(_get_watchlist_realtime_frame, market)
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("[us-quant] realtime stream 帧异常: %s", exc)
            await asyncio.sleep(interval)

    return StreamingResponse(_frame(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Content-Encoding": "identity"})


def _parse_sina_watchlist_line(line: str, market: str) -> tuple[str, dict] | None:
    if '="' not in line:
        return None
    head = line.split("=", 1)[0]
    fields = line.split('"')[1].split(",")
    if len(fields) < 9:
        return None
    try:
        if market == "US":
            symbol = head.replace("var hq_str_gb_", "").upper()
            # 新浪美股字段：1=现价，2=涨跌幅%，3=时间，4=涨跌额。
            quote = {"price": float(fields[1]), "change_pct": float(fields[2]), "quote_time": fields[3]}
        else:
            symbol = head.split("_hk", 1)[1].upper()
            quote = {
                "price": float(fields[6]),
                "change_pct": float(fields[8]),
                "quote_time": (fields[17] + " " + fields[18]) if len(fields) > 18 else "",
            }
    except (ValueError, IndexError):
        return None
    return symbol, quote


def _fetch_watchlist_realtime_frame(market: str) -> dict:
    members = _unique_symbols(get_universe_members(f"{market}_WATCHLIST"))
    if not members:
        return {"market": market, "server_time": _now_iso(), "source": "database", "data": {}}

    with get_db_session() as db:
        if market == "US":
            from us_quant.repository import USStockDaily
            ranked = db.query(
                USStockDaily.symbol.label("symbol"),
                USStockDaily.trade_date.label("trade_date"),
                USStockDaily.close.label("close"),
                func.row_number().over(
                    partition_by=USStockDaily.symbol,
                    order_by=USStockDaily.trade_date.desc(),
                ).label("row_no"),
            ).filter(
                USStockDaily.symbol.in_(members),
                USStockDaily.close.isnot(None),
                USStockDaily.source.is_(None) | (USStockDaily.source != "synthetic"),
            ).subquery()
        else:
            from market_quant.repository import MarketDailyBar
            ranked = db.query(
                MarketDailyBar.symbol.label("symbol"),
                MarketDailyBar.trade_date.label("trade_date"),
                MarketDailyBar.close.label("close"),
                func.row_number().over(
                    partition_by=MarketDailyBar.symbol,
                    order_by=MarketDailyBar.trade_date.desc(),
                ).label("row_no"),
            ).filter(
                MarketDailyBar.market == market,
                MarketDailyBar.symbol.in_(members),
                MarketDailyBar.close.isnot(None),
                MarketDailyBar.quality_status == "VALID",
            ).subquery()
        rows = db.query(
            ranked.c.symbol, ranked.c.trade_date, ranked.c.close,
        ).filter(ranked.c.row_no <= 2).order_by(
            ranked.c.symbol, ranked.c.trade_date.asc(),
        ).all()

    grouped: dict[str, list] = {symbol: [] for symbol in members}
    for row in rows:
        grouped.setdefault(row.symbol, []).append(row)
    data = {}
    for symbol, bars in grouped.items():
        if not bars:
            continue
        latest = bars[-1]
        previous = bars[-2] if len(bars) >= 2 else latest
        price = float(latest.close)
        prev_close = float(previous.close)
        data[symbol] = {
            "price": price,
            "change_pct": round((price / prev_close - 1) * 100, 4) if prev_close else None,
            "quote_time": latest.trade_date.isoformat(),
            "source": "database",
        }
    return {"market": market, "server_time": _now_iso(), "source": "database", "data": data}


def _get_watchlist_realtime_frame(market: str) -> dict:
    now = time.monotonic()
    cached = _WATCHLIST_REALTIME_CACHE.get(market)
    if cached and now - cached["created_at"] < _WATCHLIST_REALTIME_TTL:
        return cached["payload"]
    with _WATCHLIST_REALTIME_LOCK:
        cached = _WATCHLIST_REALTIME_CACHE.get(market)
        if cached and now - cached["created_at"] < _WATCHLIST_REALTIME_TTL:
            return cached["payload"]
        try:
            payload = _fetch_watchlist_realtime_frame(market)
        except Exception as exc:
            logger.debug("[us-quant] realtime %s 失败: %s", market, exc)
            payload = {"market": market, "server_time": _now_iso(), "data": {}}
        _WATCHLIST_REALTIME_CACHE[market] = {"created_at": time.monotonic(), "payload": payload}
        return payload


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


@router.get("/watchlist/search")
def us_watchlist_search(market: str = Query(..., description="US / HK"), q: str = Query(..., min_length=1, max_length=64)):
    """美股/港股名称代码模糊搜索（供顶栏快捷添加使用）"""
    from sqlalchemy import or_
    from db.session import get_db_session
    market = market.upper()
    pattern = f"%{q}%"
    try:
        with get_db_session() as db:
            if market == "US":
                from us_quant.repository import USInstrument
                rows = db.query(USInstrument).filter(
                    USInstrument.is_active.is_(True),
                    or_(USInstrument.symbol.ilike(pattern), USInstrument.name.ilike(pattern)),
                ).limit(8).all()
            else:
                from market_quant.repository import MarketInstrument
                rows = db.query(MarketInstrument).filter(
                    MarketInstrument.market == market,
                    MarketInstrument.is_active.is_(True),
                    or_(MarketInstrument.symbol.ilike(pattern), MarketInstrument.name.ilike(pattern)),
                ).limit(8).all()
    except Exception as exc:
        logger.debug("[us-quant] watchlist/search db 查询失败: %s", exc)
        rows = []
    results = [
        {"code": r.symbol, "name": r.name or "", "market": market}
        for r in rows
    ]
    return jsonable_encoder({"results": results, "market": market})


@router.get("/watchlist/detail")
def us_watchlist_detail(market: str = Query("US", description="US / HK")):
    """自选清单明细：只读入库行情与指标，保证页面打开不触发外网采集。

    实时更新由独立 SSE 流处理；初始渲染统一以数据库内最新日线为准。
    """
    market = market.upper()
    universe = f"{market}_WATCHLIST"
    members = _unique_symbols(get_universe_members(universe))

    # 美股整页只使用一个决策日。先读取盘后板块快照，再把个股日线和指标
    # 全部截到该日；实时流仅在浏览器中覆盖价格和涨跌幅。
    decision_date = None
    context_map: dict = {}
    sector_contexts: list[dict] = []
    if market == "US":
        try:
            from api.us_sector_rotation import get_sector_context_by_name
            context = get_sector_context_by_name(include_all=True)
            raw_date = context.get("trade_date")
            decision_date = date.fromisoformat(str(raw_date)) if raw_date else None
            context_map = context.get("sectors") or {}
            sector_contexts = sorted(context_map.values(), key=lambda row: (row.get("rank") or 9999, row.get("sector") or ""))
        except Exception as exc:
            logger.warning("[us-quant] watchlist sector context unavailable: %s", exc)

    # 名称/板块、统一决策日收盘价，以及真实持仓。
    name_map: dict = {}
    bar_map: dict = {}
    position_map: dict = {}
    try:
        from market_quant.repository import MarketInstrument, MarketDailyBar
        with get_db_session() as db:
            if members:
                market_instruments = db.query(MarketInstrument).filter(
                    MarketInstrument.market == market,
                    MarketInstrument.symbol.in_(members),
                ).all()
                name_map = {item.symbol: (item.name, item.sector, bool(item.is_etf)) for item in market_instruments}

            if market == "US":
                from us_quant.repository import USInstrument, USRealPosition, USStockDaily

                if members:
                    instruments = db.query(USInstrument).filter(USInstrument.symbol.in_(members)).all()
                    for item in instruments:
                        old_name, old_sector, old_is_etf = name_map.get(item.symbol, (None, None, False))
                        name_map[item.symbol] = (
                            item.name or old_name,
                            item.sector or old_sector,
                            bool(item.is_etf) or old_is_etf,
                        )
                    positions = db.query(USRealPosition).filter(
                        USRealPosition.status == "ACTIVE",
                        USRealPosition.symbol.in_(members),
                    ).all()
                    position_map = {item.symbol: item for item in positions}

                filters = [USStockDaily.symbol.in_(members), USStockDaily.close.is_not(None)]
                if decision_date is not None:
                    filters.append(USStockDaily.trade_date <= decision_date)
                latest_bars = db.query(
                    USStockDaily.symbol.label("symbol"),
                    USStockDaily.trade_date.label("trade_date"),
                    USStockDaily.close.label("close"),
                    func.row_number().over(
                        partition_by=USStockDaily.symbol,
                        order_by=USStockDaily.trade_date.desc(),
                    ).label("row_no"),
                ).filter(*filters).subquery()
            else:
                filters = [
                    MarketDailyBar.market == market,
                    MarketDailyBar.symbol.in_(members),
                    MarketDailyBar.quality_status == "VALID",
                ]
                latest_bars = db.query(
                    MarketDailyBar.symbol.label("symbol"),
                    MarketDailyBar.trade_date.label("trade_date"),
                    MarketDailyBar.close.label("close"),
                    func.row_number().over(
                        partition_by=MarketDailyBar.symbol,
                        order_by=MarketDailyBar.trade_date.desc(),
                    ).label("row_no"),
                ).filter(*filters).subquery()
            bars = db.query(
                latest_bars.c.symbol,
                latest_bars.c.trade_date,
                latest_bars.c.close,
            ).filter(
                latest_bars.c.row_no <= 2,
            ).order_by(
                latest_bars.c.symbol,
                latest_bars.c.trade_date.desc(),
            ).all()
            for b in bars:
                bar_map.setdefault(b.symbol, []).append(b)
    except Exception as exc:
        logger.debug("[us-quant] watchlist/detail db 查询失败: %s", exc)

    indicator_map = _watchlist_indicators(members, market=market, decision_date=decision_date)
    enriched = []
    for sym in members:
        price = None
        change_pct = None
        # DB 日线按 trade_date desc，[0] 为最新交易日。
        bl = bar_map.get(sym) or []
        closes_b = [float(b.close) for b in bl if b.close is not None]
        if closes_b:
            price = closes_b[0]
            if len(closes_b) >= 2 and closes_b[1]:
                change_pct = round((closes_b[0] - closes_b[1]) / closes_b[1] * 100, 2)

        nm, sec, is_etf = name_map.get(sym, (None, None, False))
        position = position_map.get(sym)
        position_payload = None
        if position:
            position_payload = {
                "quantity": float(position.quantity) if position.quantity is not None else 0,
                "cost_price": float(position.cost_price) if position.cost_price is not None else None,
                "market_value": float(position.market_value) if position.market_value is not None else None,
                "hold_profit": float(position.hold_profit) if position.hold_profit is not None else None,
                "hold_profit_pct": float(position.hold_profit_pct) if position.hold_profit_pct is not None else None,
                "today_profit": float(position.today_profit) if position.today_profit is not None else None,
            }
        indicators = indicator_map.get(sym) or {
            "as_of": None,
            "data_status": "MISSING",
            "data_reason": "无可用日线",
            "history_bars": 0,
        }
        sector_rotation = context_map.get(sec) if market == "US" and not is_etf else None
        has_position = bool(position_payload)
        technical_action = _watchlist_trade_action(indicators, has_position)
        opportunity = _watchlist_opportunity(
            indicators,
            sector_rotation,
            has_position=has_position,
            is_reference=is_etf,
            trade_action=technical_action,
        )
        trade_action = _watchlist_effective_action(
            technical_action,
            opportunity,
            has_position=has_position,
        )
        item = {
            "symbol": sym,
            "name": nm or "",
            "sector": sec or "",
            "is_etf": is_etf,
            "price": price,
            "change_pct": change_pct,
            "bar_as_of": bl[0].trade_date if bl else None,
            "indicators": indicators,
            "position": position_payload,
            "sector_rotation": sector_rotation,
            "trade_action": trade_action,
            "opportunity": opportunity,
        }
        enriched.append(item)

    quality_counts = {key: 0 for key in ("CURRENT", "STALE", "INSUFFICIENT", "MISSING", "ERROR")}
    for item in enriched:
        status = item["indicators"].get("data_status", "MISSING")
        quality_counts[status] = quality_counts.get(status, 0) + 1

    return jsonable_encoder({
        "market": market,
        "universe": universe,
        "members": enriched,
        "count": len(enriched),
        "decision_date": decision_date,
        "sector_context_date": decision_date,
        "sector_contexts": sector_contexts,
        "data_quality": quality_counts,
        "sector_rise_formula": "25%全行业20日上涨广度 + 20%全行业20日中位收益 + 15%站上MA20 + 10%站上MA60 + 15%ETF评分 + 15%ETF相对SPY强度；ETF弱势或数据缺失直接关闭机会门",
    })


def _unique_symbols(symbols) -> list[str]:
    return list(dict.fromkeys(symbols or []))


def _watchlist_trade_action(indicators, has_position: bool) -> dict:
    """把技术信号翻译成与持仓状态一致的动作语义。"""
    indicators = indicators or {}
    data_status = indicators.get("data_status", "CURRENT")
    if data_status != "CURRENT":
        label = {
            "STALE": "数据过期",
            "INSUFFICIENT": "数据不足",
            "ERROR": "计算失败",
        }.get(data_status, "暂无数据")
        return {
            "action": "blocked", "action_label": label, "action_color": "#94a3b8",
            "action_strength": 0, "action_reasons": [indicators.get("data_reason") or label],
            "raw_action": indicators.get("action"), "has_position": has_position,
        }

    raw_action = indicators.get("action") or "watch"
    payload = {
        "action": raw_action,
        "action_label": indicators.get("action_label") or raw_action,
        "action_color": indicators.get("action_color") or "#94a3b8",
        "action_strength": indicators.get("action_strength") or 0,
        "action_reasons": indicators.get("action_reasons") or [],
        "raw_action": raw_action,
        "has_position": has_position,
    }
    if not has_position and raw_action in {"reduce", "sell", "stop"}:
        payload.update({
            "action": "avoid", "action_label": "回避·等待修复", "action_color": "#f97316",
            "action_reasons": ["当前未持仓，不显示减仓或卖出动作", *payload["action_reasons"]],
        })
    elif not has_position and raw_action == "hold":
        payload.update({
            "action": "watch", "action_label": "等待突破", "action_color": "#94a3b8",
            "action_reasons": ["当前未持仓，持有信号仅作为观察条件", *payload["action_reasons"]],
        })
    return payload


def _watchlist_entry_risks(indicators) -> list[str]:
    """只阻断追高型新开仓，不影响已有持仓的风控退出。"""
    indicators = indicators or {}
    risks = []
    kdj_j = (indicators.get("kdj") or {}).get("j")
    if kdj_j is not None and kdj_j >= 100:
        risks.append(f"KDJ-J {kdj_j:.1f} 超买，等待回踩")
    price, ma20, rsi = indicators.get("price"), indicators.get("ma20"), indicators.get("rsi")
    if price is not None and ma20 and rsi is not None:
        ma20_bias = (price / ma20 - 1) * 100
        if rsi >= 70 and ma20_bias >= 10:
            risks.append(f"RSI {rsi:.1f} 且偏离MA20 {ma20_bias:.1f}%，不追高")
    return risks


def _watchlist_opportunity(
    indicators,
    sector_context,
    has_position: bool = False,
    is_reference: bool = False,
    trade_action: dict | None = None,
) -> dict:
    indicators = indicators or {}
    data_status = indicators.get("data_status", "CURRENT" if indicators else "MISSING")
    if data_status != "CURRENT":
        status = "DATA_STALE" if data_status == "STALE" else "DATA_INSUFFICIENT"
        label = "个股数据过期" if data_status == "STALE" else "个股数据不足"
        return {"status": status, "label": label, "sector_gate": False}
    if is_reference:
        return {"status": "REFERENCE", "label": "ETF参考", "sector_gate": False}

    trade_action = trade_action or _watchlist_trade_action(indicators, has_position)
    if has_position and trade_action["raw_action"] in {"reduce", "sell", "stop"}:
        return {"status": "RISK", "label": trade_action["action_label"], "sector_gate": bool((sector_context or {}).get("is_rising"))}
    if not sector_context:
        return {"status": "SECTOR_UNQUALIFIED", "label": "非行业研究池", "sector_gate": False}

    sector_status = sector_context.get("status") or ("OPEN" if sector_context.get("is_rising") else "CLOSED")
    if sector_status in {"SAMPLE_TOO_SMALL", "DATA_INSUFFICIENT", "ETF_MISSING"}:
        label = {
            "SAMPLE_TOO_SMALL": "板块样本不足",
            "DATA_INSUFFICIENT": "板块数据不足",
            "ETF_MISSING": "ETF数据缺失",
        }[sector_status]
        return {"status": "DATA_INSUFFICIENT", "label": label, "sector_gate": False}
    if sector_status != "OPEN":
        return {"status": "SECTOR_CLOSED", "label": "板块未通过", "sector_gate": False}
    if not has_position and trade_action["action"] == "avoid":
        return {"status": "AVOID", "label": "回避·等待修复", "sector_gate": True}
    entry_risks = _watchlist_entry_risks(indicators) if not has_position else []
    if trade_action["action"] in {"buy", "scoop"} and entry_risks:
        return {
            "status": "STOCK_WAIT", "label": "板块通过·等待回踩", "sector_gate": True,
            "entry_risks": entry_risks,
        }
    if trade_action["action"] == "buy":
        return {"status": "READY", "label": "个股机会成立", "sector_gate": True}
    if trade_action["action"] == "scoop":
        return {"status": "READY", "label": "板块通过·低吸观察", "sector_gate": True}
    return {"status": "STOCK_WAIT", "label": "板块通过·等待个股", "sector_gate": True}


def _watchlist_effective_action(trade_action: dict, opportunity: dict, has_position: bool = False) -> dict:
    """将技术方向与板块机会门合并成页面唯一可执行建议。"""
    payload = dict(trade_action or {})
    if has_position:
        return payload

    status = (opportunity or {}).get("status")
    if status in {"READY", "AVOID"}:
        return payload

    reasons = list(payload.get("action_reasons") or [])
    if status == "STOCK_WAIT":
        entry_risks = list((opportunity or {}).get("entry_risks") or [])
        reason = entry_risks or ["板块机会门已打开，但个股技术信号尚未确认"]
        payload.update({
            "action": "watch",
            "action_label": "等待回踩" if entry_risks else "等待个股",
            "action_color": "#f59e0b",
            "action_reasons": [*reason, *reasons],
        })
        return payload

    if status == "REFERENCE":
        payload.update({
            "action": "watch", "action_label": "ETF参考", "action_color": "#3b82f6",
            "action_reasons": ["ETF仅用于验证板块强弱，不作为行业个股机会", *reasons],
        })
        return payload

    label = (opportunity or {}).get("label") or "板块机会未确认"
    payload.update({
        "action": "blocked", "action_label": label, "action_color": "#94a3b8",
        "action_reasons": [f"{label}，不执行个股买入信号", *reasons],
    })
    return payload


def _continuous_watchlist_klines(klines: list[dict]) -> tuple[list[dict], int]:
    """仅修正明显拆并股跳变，保留财报跳空等真实行情。"""
    if len(klines) < 2:
        return klines, 0
    factors = [1.0] * len(klines)
    cumulative = 1.0
    adjustment_count = 0
    for index in range(len(klines) - 1, 0, -1):
        previous_close = klines[index - 1]["close"]
        current_open = klines[index].get("open") or klines[index]["close"]
        current_close = klines[index]["close"]
        open_ratio = current_open / previous_close if previous_close else 1.0
        intraday_move = current_close / current_open - 1 if current_open else 0.0
        if (open_ratio <= 0.55 or open_ratio >= 1.80) and abs(intraday_move) <= 0.25:
            cumulative *= open_ratio
            adjustment_count += 1
        factors[index - 1] = cumulative
    adjusted = []
    for index, row in enumerate(klines):
        factor = factors[index]
        adjusted.append({
            **row,
            "open": (row.get("open") or row["close"]) * factor,
            "high": (row.get("high") or row["close"]) * factor,
            "low": (row.get("low") or row["close"]) * factor,
            "close": row["close"] * factor,
        })
    return adjusted, adjustment_count


def _watchlist_indicators(symbols: list[str], days: int = 120, market: str = "US", decision_date: date | None = None) -> dict:
    """批量从 DB 读 K 线计算技术指标，避免逐个实时拉取。

    market: US → us_stock_daily；HK → market_daily_bars。
    返回 {symbol: {rsi, ema10, ema20, ma50, macd, kdj, state_label, score, stop_loss}}
    数据不足的标的返回空，由前端显示为“—”。
    结果缓存 10 分钟（指标日内基本稳定，实时价另走行情源）。
    """
    import concurrent.futures
    from us_quant.cache import TTLCache

    _WATCHLIST_IND_CACHE: TTLCache = globals().get("_watchlist_ind_cache")
    if not _WATCHLIST_IND_CACHE:
        _WATCHLIST_IND_CACHE = TTLCache(default_ttl=600)
        globals()["_watchlist_ind_cache"] = _WATCHLIST_IND_CACHE

    syms = list(dict.fromkeys(symbols))
    if not syms:
        return {}
    _key = f"{market}:{decision_date or 'latest'}:" + ",".join(sorted(syms))
    cached = _WATCHLIST_IND_CACHE.get(_key)
    if cached is not None:
        return cached

    # 一次性读完整自选池历史，避免每只股票单独查询；更不能在页面访问时
    # 因数据缺失触发 collect_symbol 的外网补采。
    db_klines: dict[str, list[dict]] = {sym: [] for sym in syms}
    with get_db_session() as db:
        history_limit = max(days, 260)
        if market == "HK":
            from market_quant.repository import MarketDailyBar
            hk_filters = [
                MarketDailyBar.market == "HK",
                MarketDailyBar.symbol.in_(syms),
                MarketDailyBar.quality_status == "VALID",
            ]
            if decision_date is not None:
                hk_filters.append(MarketDailyBar.trade_date <= decision_date)
            ranked = db.query(
                MarketDailyBar.symbol.label("symbol"),
                MarketDailyBar.trade_date.label("trade_date"),
                MarketDailyBar.open.label("open"),
                MarketDailyBar.high.label("high"),
                MarketDailyBar.low.label("low"),
                MarketDailyBar.close.label("close"),
                MarketDailyBar.volume.label("volume"),
                literal(None).label("turnover"),
                func.row_number().over(
                    partition_by=MarketDailyBar.symbol,
                    order_by=MarketDailyBar.trade_date.desc(),
                ).label("row_no"),
            ).filter(*hk_filters).subquery()
        else:
            from us_quant.repository import USStockDaily
            us_filters = [
                USStockDaily.symbol.in_(syms),
                USStockDaily.close.is_not(None),
                func.coalesce(USStockDaily.source, "") != "synthetic",
            ]
            if decision_date is not None:
                us_filters.append(USStockDaily.trade_date <= decision_date)
            ranked = db.query(
                USStockDaily.symbol.label("symbol"),
                USStockDaily.trade_date.label("trade_date"),
                USStockDaily.open.label("open"),
                USStockDaily.high.label("high"),
                USStockDaily.low.label("low"),
                USStockDaily.close.label("close"),
                USStockDaily.volume.label("volume"),
                USStockDaily.turnover.label("turnover"),
                func.row_number().over(
                    partition_by=USStockDaily.symbol,
                    order_by=USStockDaily.trade_date.desc(),
                ).label("row_no"),
            ).filter(*us_filters).subquery()
        bars = db.query(
            ranked.c.symbol,
            ranked.c.trade_date,
            ranked.c.open,
            ranked.c.high,
            ranked.c.low,
            ranked.c.close,
            ranked.c.volume,
            ranked.c.turnover,
        ).filter(
            ranked.c.row_no <= history_limit,
        ).order_by(
            ranked.c.symbol,
            ranked.c.trade_date.asc(),
        ).all()
    for b in bars:
        db_klines.setdefault(b.symbol, []).append({
            "date": b.trade_date.strftime("%Y-%m-%d"),
            "open": float(b.open) if b.open is not None else None,
            "high": float(b.high) if b.high is not None else None,
            "low": float(b.low) if b.low is not None else None,
            "close": float(b.close) if b.close is not None else None,
            "volume": float(b.volume) if b.volume is not None else 0,
            "turnover": float(b.turnover) if b.turnover is not None else None,
        })

    def _calc(sym: str) -> tuple[str, dict | None]:
        try:
            raw_klines = db_klines.get(sym, [])
            as_of = raw_klines[-1]["date"] if raw_klines else None
            expected = decision_date.isoformat() if decision_date else as_of
            if not raw_klines:
                return sym, {"as_of": None, "decision_date": expected, "data_status": "MISSING", "data_reason": "无可用日线", "history_bars": 0}
            if len(raw_klines) < 20:
                return sym, {"as_of": as_of, "decision_date": expected, "data_status": "INSUFFICIENT", "data_reason": f"仅有 {len(raw_klines)} 根有效日线", "history_bars": len(raw_klines)}
            klines, adjustment_count = _continuous_watchlist_klines(raw_klines)
            closes = [k["close"] for k in klines if k.get("close")]
            highs = [k["high"] for k in klines]
            lows = [k["low"] for k in klines]
            volumes = [k.get("volume") or 0 for k in klines]
            ema10_vals = ema(closes, 10)
            ema20_vals = ema(closes, 20)
            ma5_vals = sma(closes, 5)
            ma20_vals = sma(closes, 20)
            ma60_vals = sma(closes, 60)
            ma50_vals = sma(closes, 50)
            ma200_vals = sma(closes, 200) if len(closes) >= 200 else []
            rsi_val = _latest_rsi(closes, 14)
            macd_val = _latest_macd(closes)
            kdj_val = _latest_kdj(highs, lows, closes)
            price = closes[-1]
            ema10 = ema10_vals[-1] if ema10_vals else None
            ema20 = ema20_vals[-1] if ema20_vals else None
            ma5 = ma5_vals[-1] if ma5_vals else None
            ma20 = ma20_vals[-1] if ma20_vals else None
            ma60 = ma60_vals[-1] if ma60_vals else None
            ma50 = ma50_vals[-1] if ma50_vals else None
            ma200 = ma200_vals[-1] if ma200_vals else None
            # 52周高低（美股一年约 252 交易日，取近 252 根）
            win = closes[-252:] if len(closes) >= 252 else closes
            hi_52w = max(win)
            lo_52w = min(win)
            pct_from_high = round((price - hi_52w) / hi_52w * 100, 2) if hi_52w else None
            pct_from_low = round((price - lo_52w) / lo_52w * 100, 2) if lo_52w else None
            rel_vol = None
            if len(volumes) >= 6 and sum(volumes[-6:-1]) > 0:
                rel_vol = round(volumes[-1] / (sum(volumes[-6:-1]) / 5), 2)
            chg_5d = round((closes[-1] - closes[-6]) / closes[-6] * 100, 2) if len(closes) >= 6 and closes[-6] else None
            chg_20d = round((closes[-1] - closes[-21]) / closes[-21] * 100, 2) if len(closes) >= 21 and closes[-21] else None
            chg_60d = round((closes[-1] - closes[-61]) / closes[-61] * 100, 2) if len(closes) >= 61 and closes[-61] else None
            state = determine_stock_state(
                price=price, ma20=ema20, ma50=ma50, rsi=rsi_val,
                high_52w=hi_52w if hi_52w else None,
                volume_ratio=rel_vol,
                change_pct_5d=chg_5d, change_pct_20d=chg_20d,
            )
            score = 50.0
            if ema10 and ema20 and ma50:
                if ema10 > ema20 > ma50:
                    score += 18
                elif ema10 < ema20 < ma50:
                    score -= 15
                else:
                    score += 4
            if rsi_val is not None:
                if 45 <= rsi_val <= 68:
                    score += 8
                elif rsi_val > 75:
                    score -= 6
                elif rsi_val < 28:
                    score += 3
            if macd_val.get("status") == "多头":
                score += 8
            elif macd_val.get("status") == "空头":
                score -= 6
            if kdj_val.get("status") in ("金叉", "金叉偏强"):
                score += 5
            elif kdj_val.get("status") in ("死叉", "死叉偏弱"):
                score -= 4
            # 均线结构
            if ma5 and ma20 and ma60:
                if ma5 > ma20 > ma60:
                    ma_struct = "多头排列"
                elif ma5 < ma20 < ma60:
                    ma_struct = "空头排列"
                else:
                    ma_struct = "纠缠"
            else:
                ma_struct = None
            # 支撑/阻力（近 20 日高低）
            support = round(min(lows[-20:]), 2) if len(lows) >= 20 else None
            resistance = round(max(highs[-20:]), 2) if len(highs) >= 20 else None
            # ATR（14）
            atr_val = None
            if len(closes) >= 15:
                trs = []
                for i in range(1, len(closes)):
                    hl = highs[i] - lows[i]
                    hc = abs(highs[i] - closes[i - 1])
                    lc = abs(lows[i] - closes[i - 1])
                    trs.append(max(hl, hc, lc))
                atr_val = round(sum(trs[-14:]) / 14, 2) if trs else None
            if as_of != expected:
                indicator_status = "STALE"
                indicator_reason = f"最新日线 {as_of}，决策日 {expected}"
            elif len(klines) < 60:
                indicator_status = "INSUFFICIENT"
                indicator_reason = f"仅有 {len(klines)} 根有效日线，完整技术判断至少需要 60 根"
            else:
                indicator_status = "CURRENT"
                indicator_reason = None
            ind_result = {
                "as_of": as_of,
                "decision_date": expected,
                "data_status": indicator_status,
                "data_reason": indicator_reason,
                "history_bars": len(klines),
                "corporate_action_adjustments": adjustment_count,
                "price": round(price, 2),
                "rsi": round(rsi_val, 1) if rsi_val is not None else None,
                "ema10": round(ema10, 2) if ema10 else None,
                "ema20": round(ema20, 2) if ema20 else None,
                "ma5": round(ma5, 2) if ma5 else None,
                "ma20": round(ma20, 2) if ma20 else None,
                "ma60": round(ma60, 2) if ma60 else None,
                "ma20_slope": round((ma20 / ma20_vals[-6] - 1) * 100, 2) if ma20 and len(ma20_vals) >= 6 and ma20_vals[-6] else None,
                "above_ma20": price >= ma20 if ma20 else None,
                "ma50": round(ma50, 2) if ma50 else None,
                "ma200": round(ma200, 2) if ma200 else None,
                "ma_struct": ma_struct,
                "macd": macd_val,
                "kdj": kdj_val,
                "state": state.state,
                "state_label": state.label,
                "score": round(max(0.0, min(100.0, score)), 1),
                "stop_loss": round(min(ma50 * 0.97, price * 0.95), 2) if ma50 else round(price * 0.95, 2),
                "stop_dist": round((price - min(ma50 * 0.97, price * 0.95)) / price * 100, 2) if ma50 else 5.0,
                "high_52w": round(hi_52w, 2),
                "low_52w": round(lo_52w, 2),
                "pct_from_high": pct_from_high,
                "pct_from_low": pct_from_low,
                "rel_vol": rel_vol,
                "turnover": klines[-1].get("turnover"),
                "chg_5d": chg_5d,
                "chg_20d": chg_20d,
                "chg_60d": chg_60d,
                "support": support,
                "resistance": resistance,
                "atr": atr_val,
                "amplitude": round((highs[-1] - lows[-1]) / lows[-1] * 100, 2) if len(highs) >= 1 and lows[-1] else None,
            }
            # 操作方向（买入/持有/减仓/卖出/观望/止损 + 理由）
            from us_quant.action import summarize_action
            merged = {**ind_result, "price": price}
            ind_result.update(summarize_action(merged))
            # 具体买卖信号提醒（金叉/死叉/超买超卖/破位/放量）
            from us_quant.action import build_signal_alerts
            ind_result["alerts"] = build_signal_alerts(closes, highs, lows, volumes, merged)
            return sym, ind_result
        except Exception as exc:
            logger.debug(f"[us-quant] watchlist indicator {sym} failed: {exc}")
            return sym, {"as_of": None, "decision_date": decision_date.isoformat() if decision_date else None, "data_status": "ERROR", "data_reason": str(exc), "history_bars": 0}

    result: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_calc, s): s for s in symbols}
        for f in concurrent.futures.as_completed(futs):
            sym, ind = f.result()
            if ind:
                result[sym] = ind
    _WATCHLIST_IND_CACHE.set(_key, result, ttl=600)
    return result


@router.get("/watchlist/sector-preferences")
def us_watchlist_sector_preferences(market: str = Query("US")):
    market = market.upper()
    with get_db_session() as db:
        all_rows = db.query(USWatchlistSectorPreference).filter(
            USWatchlistSectorPreference.market == market,
        ).order_by(USWatchlistSectorPreference.sector).all()
    return jsonable_encoder({
        "market": market,
        "hot_sectors": [row.sector for row in all_rows if row.is_hot],
        "preference_count": len(all_rows),
    })


@router.post("/watchlist/sector-preferences")
def us_watchlist_save_sector_preferences(payload: dict):
    """持久化热门板块；支持单个切换及浏览器旧设置一次性迁移。"""
    market = str(payload.get("market") or "US").upper()
    sector = str(payload.get("sector") or "").strip()
    sectors = [str(item).strip() for item in payload.get("sectors") or [] if str(item).strip()]
    with get_db_session() as db:
        if sector:
            row = db.query(USWatchlistSectorPreference).filter(
                USWatchlistSectorPreference.market == market,
                USWatchlistSectorPreference.sector == sector,
            ).first()
            if not row:
                row = USWatchlistSectorPreference(market=market, sector=sector)
                db.add(row)
            row.is_hot = bool(payload.get("is_hot", True))
        elif sectors:
            existing = {
                row.sector: row for row in db.query(USWatchlistSectorPreference).filter(
                    USWatchlistSectorPreference.market == market,
                ).all()
            }
            for name in sectors:
                row = existing.get(name)
                if not row:
                    row = USWatchlistSectorPreference(market=market, sector=name)
                    db.add(row)
                row.is_hot = True
        else:
            return jsonable_encoder({"ok": False, "error": "sector or sectors required"})
        db.commit()
        hot = [row[0] for row in db.query(USWatchlistSectorPreference.sector).filter(
            USWatchlistSectorPreference.market == market,
            USWatchlistSectorPreference.is_hot.is_(True),
        ).order_by(USWatchlistSectorPreference.sector).all()]
    return jsonable_encoder({"ok": True, "market": market, "hot_sectors": hot})


@router.post("/watchlist/remove")
def us_watchlist_remove(payload: dict):
    """从自选清单移除一只股票（软删除，与 A 股自选股移除一致）。"""
    market = str(payload.get("market") or "US").upper()
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonable_encoder({"ok": False, "error": "symbol required"})
    universe = f"{market}_WATCHLIST"
    try:
        n = remove_universe_member(universe, symbol)
        return jsonable_encoder({"ok": True, "removed": n, "symbol": symbol})
    except Exception as e:
        return jsonable_encoder({"ok": False, "error": str(e)})


@router.post("/watchlist/add")
def us_watchlist_add(payload: dict):
    """向自选清单新增一只股票（手动添加，幂等）。支持美股 / 港股。

    港股代码归一化为 5 位数字（如 700 / 00700.HK → 00700），与 market_instruments 对齐。
    若代码在 market_instruments 中不存在则拒绝（避免脏数据）。
    """
    market = str(payload.get("market") or "US").upper()
    raw = str(payload.get("symbol") or "").strip()
    if not raw:
        return jsonable_encoder({"ok": False, "error": "symbol required"})
    symbol = normalize_symbol(raw, market)
    universe = f"{market}_WATCHLIST"

    # 校验代码是否存在于该市场的标的表。
    try:
        with get_db_session() as db:
            if market == "US":
                from us_quant.repository import USInstrument
                inst = db.query(USInstrument).filter(
                    USInstrument.symbol == symbol,
                    USInstrument.is_active.is_(True),
                ).first()
            else:
                from market_quant.repository import MarketInstrument
                inst = db.query(MarketInstrument).filter(
                    MarketInstrument.market == market,
                    MarketInstrument.symbol == symbol,
                ).first()
            if not inst:
                return jsonable_encoder({
                    "ok": False,
                    "error": f"未找到代码 {symbol}（市场 {market}），请确认输入正确",
                    "symbol": symbol,
                })
    except Exception as e:
        logger.debug("[us-quant] watchlist/add 校验失败(放行): %s", e)

    try:
        res = add_universe_member(universe, symbol, market)
        return jsonable_encoder(res)
    except Exception as e:
        return jsonable_encoder({"ok": False, "error": str(e), "symbol": symbol})


_SAMPLE_SYMBOLS = {
    "US": ["AAPL", "MSFT", "NVDA", "TSLA", "META", "GOOGL", "AMZN"],
    "HK": ["00700", "09988", "03690", "01810", "01299", "00941", "02883"],
}


@router.post("/watchlist/sample")
def us_watchlist_sample(payload: dict):
    """一键导入该市场的一批代表性示例股票（幂等）。

    - 仅当目标自选池为空时导入（避免覆盖用户已有数据）
    - market_instruments 中不存在的代码自动跳过
    """
    market = str(payload.get("market") or "US").upper()
    symbols = _SAMPLE_SYMBOLS.get(market, [])
    universe = f"{market}_WATCHLIST"
    try:
        from market_quant.repository import MarketInstrument
        from sqlalchemy import func as _func
        with get_db_session() as db:
            cur = db.query(_func.count()).select_from(USUniverseMembership).filter(
                USUniverseMembership.universe_code == universe,
                USUniverseMembership.effective_to.is_(None),
            ).scalar()
            if cur:
                return jsonable_encoder({"ok": False, "skipped": True,
                                         "error": f"{universe} 已有 {cur} 只自选，示例导入仅限空池"})
            known = {r[0] for r in db.query(MarketInstrument.symbol).filter(
                MarketInstrument.market == market).all()}
        added, skipped = [], []
        for raw in symbols:
            sym = normalize_symbol(raw, market)
            if sym not in known:
                skipped.append(sym)
                continue
            res = add_universe_member(universe, sym, market)
            if res.get("ok"):
                added.append(sym)
        return jsonable_encoder({"ok": True, "added": added, "skipped": skipped,
                                 "universe": universe})
    except Exception as e:
        logger.debug("[us-quant] sample import 失败: %s", e)
        return jsonable_encoder({"ok": False, "error": str(e)})



# ─── API: 策略注册表（V2.2 插件化）────────────────────────────────────────────

@router.get("/strategies")
def api_strategies():
    """列出所有已注册的扫描策略（插件化注册表）"""
    return jsonable_encoder({
        "strategies": list_strategies(),
        "count": len(list_strategies()),
    })


# ─── API: 股票池再平衡（V2.2）─────────────────────────────────────────────────

@router.get("/rebalance")
def api_rebalance():
    """触发股票池全量重平衡（研究池刷新 → Core A → Core B）"""
    report = run_rebalance()
    return jsonable_encoder(report)


# ─── API: 因子库（V2.3 因子研究）──────────────────────────────────────────────

@router.get("/factors")
async def api_factors(category: str = ""):
    """列出所有已注册因子（含类别统计，可选按类别过滤）。"""
    from us_quant.factors import FACTOR_REGISTRY

    items = [
        {
            "key": key,
            "name": meta.get("name", ""),
            "category": meta.get("category", ""),
            "params": meta.get("params", []),
            "kind": meta.get("kind", "factor"),
            "route": meta.get("route"),
            "description": meta.get("description", ""),
            "version": meta.get("version"),
        }
        for key, meta in FACTOR_REGISTRY.items()
    ]
    if category:
        items = [i for i in items if i["category"] == category]
    strategies = [item for item in items if item["kind"] == "strategy"]
    factors = [item for item in items if item["kind"] != "strategy"]
    cats = {}
    for i in factors:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
    return jsonable_encoder({
        "count": len(factors),
        "strategy_count": len(strategies),
        "categories": cats,
        "factors": factors,
        "strategies": strategies,
    })


@router.get("/factors/values")
async def api_factor_values(symbol: str = Query("", description="美股代码，如 AAPL")):
    """只读取盘后已落库因子；缺口由定时任务补算，查询接口不采集、不写库。"""
    symbol = symbol.strip().upper()
    if not symbol:
        return jsonable_encoder({"ok": False, "error": "缺少 symbol 参数"})
    try:
        from us_quant.factor_storage import get_latest_factor_values

        snapshot = await asyncio.to_thread(get_latest_factor_values, symbol)
        if snapshot is None:
            return jsonable_encoder({
                "ok": False,
                "status": "MISSING",
                "source": "database",
                "error": f"数据库中没有 {symbol} 的可用因子，请等待自动任务补齐",
            })
        values = snapshot["values"]
        return jsonable_encoder({
            "ok": True,
            "status": "READY" if snapshot.get("is_current") else "STALE",
            "symbol": symbol,
            "trade_date": snapshot["trade_date"],
            "data_trade_date": snapshot.get("data_trade_date"),
            "source": "database",
            "count": len(values),
            "values": values,
        })
    except Exception as exc:
        logger.warning("[us-quant] factors/values error %s: %s", symbol, exc)
        return jsonable_encoder({"ok": False, "error": str(exc)})


# ─── 信号回验（历史信号 vs 实际前瞻收益）───────────────────────────────────
# 衡量方式：信号不是“断言会跌/会涨”，而是概率判断。用大批量历史样本的
# 统计命中率衡量：某类信号出现后 N 个交易日的涨跌占比 / 平均收益 / 最大亏损，
# 并与全样本基准对比。样本每日自动积累（USStrategyScore 每日快照）。

@router.get("/signals/validation")
def api_signal_validation(
    horizon: int = Query(5, ge=1, le=30, description="前瞻交易日数，默认 5"),
):
    """信号回验：历史信号快照 → N 日后实际收益 → 分组命中率统计。

    信号分组（同一快照可属多组）：
    - macd_dead_cross  死叉（dif < dea）——看空信号，下跌占比为命中率
    - macd_golden_cross 金叉（dif >= dea）——看多信号，上涨占比为命中率
    - rsi_oversold     RSI < 30 超卖
    - rsi_overbought   RSI > 70 超买
    - score_high       综合评分 >= 70
    - score_mid        50 <= 评分 < 70
    - score_low        评分 < 50
    """
    from statistics import mean, median
    from us_quant.repository import USStockDaily

    cache_key = make_cache_key(scanner=True, signal_validation=True, horizon=horizon)
    cached = scanner_cache.get(cache_key)
    if cached is not None:
        return jsonable_encoder(cached)

    try:
        with get_db_session() as db:
            rows = db.query(USStrategyScore).all()
            syms = sorted({r.symbol for r in rows})
            kline_map: dict = {}
            if syms:
                krows = db.query(USStockDaily).filter(
                    USStockDaily.symbol.in_(syms)
                ).order_by(USStockDaily.symbol, USStockDaily.trade_date).all()
                for k in krows:
                    kline_map.setdefault(k.symbol, []).append(k)

        # 信号标签定义（用于输出顺序与中文名）
        GROUP_META = [
            ("macd_dead_cross", "MACD 死叉", "看空"),
            ("macd_golden_cross", "MACD 金叉", "看多"),
            ("rsi_oversold", "RSI 超卖", "看多"),
            ("rsi_overbought", "RSI 超买", "看空"),
            ("score_high", "综合评分 ≥70", "看多"),
            ("score_mid", "综合评分 50-70", "中性"),
            ("score_low", "综合评分 <50", "看空"),
        ]
        buckets: dict = {k: [] for k, _, _ in GROUP_META}
        all_rets: list = []
        resolved = 0
        for r in rows:
            d = r.score_details if isinstance(r.score_details, dict) else {}
            price = d.get("price")
            if not price:
                continue
            kl = kline_map.get(r.symbol) or []
            fwd = None
            cnt = 0
            for k in kl:
                if k.trade_date > r.trade_date:
                    cnt += 1
                    if cnt == horizon:
                        fwd = float(k.close) / float(price) - 1
                        break
            if fwd is None:
                continue  # 历史不足，等积累
            resolved += 1
            all_rets.append(fwd)
            macd = d.get("macd") or {}
            rsi = d.get("rsi")
            score = d.get("best_factor_score")
            if macd.get("dif") is not None and macd.get("dea") is not None:
                buckets["macd_golden_cross" if macd["dif"] >= macd["dea"] else "macd_dead_cross"].append(fwd)
            if rsi is not None:
                if rsi < 30:
                    buckets["rsi_oversold"].append(fwd)
                elif rsi > 70:
                    buckets["rsi_overbought"].append(fwd)
            if score is not None:
                if score >= 70:
                    buckets["score_high"].append(fwd)
                elif score >= 50:
                    buckets["score_mid"].append(fwd)
                else:
                    buckets["score_low"].append(fwd)

        baseline = None
        if all_rets:
            baseline = {
                "count": len(all_rets),
                "up_ratio": round(sum(v > 0 for v in all_rets) / len(all_rets), 4),
                "down_ratio": round(sum(v < 0 for v in all_rets) / len(all_rets), 4),
                "mean_ret": round(mean(all_rets), 4),
                "median_ret": round(median(all_rets), 4),
                "max_loss": round(min(all_rets), 4),
            }

        signals_out = []
        for key, label, direction in GROUP_META:
            vals = buckets[key]
            if not vals:
                signals_out.append({"key": key, "label": label, "direction": direction,
                                    "count": 0, "up_ratio": None, "down_ratio": None,
                                    "mean_ret": None, "median_ret": None, "max_loss": None})
                continue
            signals_out.append({
                "key": key,
                "label": label,
                "direction": direction,
                "count": len(vals),
                "up_ratio": round(sum(v > 0 for v in vals) / len(vals), 4),
                "down_ratio": round(sum(v < 0 for v in vals) / len(vals), 4),
                "mean_ret": round(mean(vals), 4),
                "median_ret": round(median(vals), 4),
                "max_loss": round(min(vals), 4),
            })

        result = {
            "ok": True,
            "horizon": horizon,
            "resolved": resolved,
            "total_snapshots": len(rows),
            "baseline": baseline,
            "signals": signals_out,
            "note": "样本每日自动积累：信号快照落库 N 个交易日后自动回填实际收益；样本 < 30 时命中率仅供参考。",
        }
        scanner_cache.set(cache_key, result, ttl=300)
        return jsonable_encoder(result)
    except Exception as exc:
        logger.error("[us-quant] signal validation error: %s", exc, exc_info=True)
        return jsonable_encoder({"ok": False, "error": str(exc)})

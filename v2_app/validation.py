from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from statistics import mean, pstdev

from sqlalchemy import text

from .data import MarketData
from .db import engine
from .engine import V2Engine
from .factors import BASE_FACTOR_NAMES, DIMENSION_LABELS, FACTOR_BY_NAME


def _corr(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    lx, rx = mean(left), mean(right)
    ld = sum((x - lx) ** 2 for x in left) ** 0.5
    rd = sum((x - rx) ** 2 for x in right) ** 0.5
    return round(sum((a - lx) * (b - rx) for a, b in zip(left, right)) / (ld * rd), 6) if ld and rd else None


def _rank(values: list[float]) -> list[float]:
    order = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and order[end + 1][1] == order[index][1]:
            end += 1
        rank = (index + end + 2) / 2
        for pos in range(index, end + 1):
            result[order[pos][0]] = rank
        index = end + 1
    return result


def _forward_window(bars, trade_date: date, horizon: int):
    ordered = [bar for bar in bars if bar.trade_date >= trade_date]
    if len(ordered) <= horizon or not ordered[0].close:
        return None
    entry = ordered[0].close
    future = ordered[:horizon + 1]
    returns = future[horizon].close / entry - 1
    max_profit = max((bar.high / entry - 1 for bar in future), default=None)
    max_loss = min((bar.low / entry - 1 for bar in future), default=None)
    running_high = future[0].high
    drawdown = 0.0
    for bar in future:
        running_high = max(running_high, bar.high)
        drawdown = min(drawdown, bar.low / running_high - 1 if running_high else 0)
    return returns, max_profit, max_loss, drawdown


def _research_dates(target: date, days: int) -> list[date]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT trade_date FROM stock_daily_kline
            WHERE trade_date <= :target
            ORDER BY trade_date DESC LIMIT :limit
        """), {"target": target, "limit": days + 80}).scalars().all()
    # Leave the most recent completed sessions out of the signal-date set so
    # every selected date has room for the requested 20-day forward outcome.
    # This prevents the validation window from quietly counting fewer
    # effective dates than it reports.
    rows = list(rows)
    return sorted(rows[20:20 + max(1, days)])


def _quantile_means(pairs: list[tuple[float, float]], direction: int, buckets: int = 5) -> list[float]:
    if len(pairs) < buckets * 2:
        return []
    ordered = sorted(pairs, key=lambda item: item[0])
    result = []
    for index in range(buckets):
        start = index * len(ordered) // buckets
        end = (index + 1) * len(ordered) // buckets
        values = [item[1] for item in ordered[start:end]]
        result.append(mean(values) if values else 0.0)
    if direction < 0:
        result.reverse()
    return result


def _monotonicity(quantiles: list[float]) -> float | None:
    if len(quantiles) < 2:
        return None
    return sum(quantiles[index + 1] >= quantiles[index] for index in range(len(quantiles) - 1)) / (len(quantiles) - 1)


def run_validation(data: MarketData, engine_v2: V2Engine, days: int = 20, limit: int = 300) -> dict:
    target = data.resolve_date()
    if not target:
        return {"trade_date": None, "rows": [], "sample_count": 0, "horizons": {}}
    limit = max(30, min(limit, 1000))
    universe = data.load_universe(target)[:limit]
    codes = [item["ts_code"] for item in universe]
    history = data.load_history(codes, target, lookback_days=max(280, days * 3 + 120))
    dates = _research_dates(target, days)
    factor_observations: dict[str, list[tuple[float, float]]] = defaultdict(list)
    factor_daily_pairs: dict[str, dict[date, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    factor_state_pairs: dict[str, dict[str, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    factor_outcomes: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    factor_quantile_scores: dict[str, list[list[float]]] = defaultdict(list)
    factor_total_counts: dict[str, int] = defaultdict(int)
    factor_missing_counts: dict[str, int] = defaultdict(int)
    factor_outlier_counts: dict[str, int] = defaultdict(int)
    # Keep rolling correlation memory bounded.  Candidate factors are
    # compared with the 31 established V2 factors per signal date instead of
    # materialising every candidate-candidate observation pair.
    factor_corr_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    horizon_values: dict[int, list[float]] = defaultdict(list)
    state_values: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    outcome_rows_map = {}

    for trade_date in dates:
        visible = {
            code: [bar for bar in bars if bar.trade_date <= trade_date]
            for code, bars in history.items()
        }
        visible = {code: bars for code, bars in visible.items() if bars and bars[-1].trade_date == trade_date}
        if len(visible) < 30:
            continue
        visible_universe = [item for item in universe if item["ts_code"] in visible]
        market = data.market_context(trade_date, visible_universe, visible)
        result = engine_v2.run(
            visible,
            market,
            data.load_sector_flow(trade_date),
            display_limit=None,
            include_candidate_factors=True,
        )
        for code, values in result["raw"].items():
            for name in FACTOR_BY_NAME:
                factor_total_counts[name] += 1
                value = values.get(name)
                if value is None:
                    factor_missing_counts[name] += 1
                    continue
                # Outliers are measured cross-sectionally by date, after the
                # raw formula has been calculated and before normalization.
        # The separate all-value map keeps quality metrics independent from
        # the availability of future returns.
        all_values_by_factor: dict[str, list[float]] = defaultdict(list)
        for values in result["raw"].values():
            for name, value in values.items():
                if value is not None:
                    all_values_by_factor[name].append(float(value))
        for name, values in all_values_by_factor.items():
            if len(values) >= 10:
                ordered = sorted(values)
                low = ordered[max(0, int(len(ordered) * 0.01) - 1)]
                high = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
                factor_outlier_counts[name] += sum(value < low or value > high for value in values)
        date_factor_pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
        date_factor_values: dict[str, list[float]] = defaultdict(list)
        for signal in result["all_signals"]:
            bars = history[signal.code]
            values = {name: value for name, value in result["raw"].get(signal.code, {}).items() if value is not None}
            for horizon in (1, 3, 5, 10, 20):
                outcome = _forward_window(bars, trade_date, horizon)
                if not outcome:
                    continue
                forward, max_profit, max_loss, drawdown = outcome
                horizon_values[horizon].append(forward)
                state_values[signal.trading_state][horizon].append(forward)
                if horizon == 5:
                    for name, value in values.items():
                        pair = (float(value), forward)
                        date_factor_pairs[name].append(pair)
                        factor_daily_pairs[name][trade_date].append(pair)
                        factor_state_pairs[name][market.state].append(pair)
                        factor_outcomes[name].append((float(value), max_profit or 0.0, max_loss or 0.0, drawdown or 0.0))
                        date_factor_values[name].append(float(value))

                key = (signal.code, trade_date)
                outcome_row = outcome_rows_map.setdefault(key, {
                    "code": signal.code, "signal_date": trade_date,
                    "trading_state": signal.trading_state, "returns": {},
                    "max_profit": None, "max_loss": None, "max_drawdown": None,
                })
                outcome_row["returns"][str(horizon)] = forward
                if horizon == 20:
                    outcome_row["max_profit"] = max_profit
                    outcome_row["max_loss"] = max_loss
                    outcome_row["max_drawdown"] = drawdown

        reference_names = sorted(name for name in date_factor_values if name in BASE_FACTOR_NAMES)
        all_factor_names = sorted(date_factor_values)
        for left in reference_names:
            for right in all_factor_names:
                if right == left or (right in BASE_FACTOR_NAMES and right < left):
                    continue
                value = _corr(date_factor_values[left], date_factor_values[right])
                if value is not None:
                    factor_corr_samples[(left, right)].append(value)

        for name, pairs in date_factor_pairs.items():
            quantiles = _quantile_means(pairs, FACTOR_BY_NAME[name].direction)
            if quantiles:
                factor_quantile_scores[name].append(quantiles)

    # ``factor_observations`` above also contains all-value quality samples
    # with a temporary zero return.  Rebuild it from actual forward pairs so
    # IC and return statistics never include non-outcome placeholders.
    factor_observations = defaultdict(list)
    for name, by_date in factor_daily_pairs.items():
        factor_observations[name] = [pair for pairs in by_date.values() for pair in pairs]

    correlations = {}
    for (left, right), samples in factor_corr_samples.items():
        value = mean(samples) if samples else None
        correlations.setdefault(left, {})[right] = value
        correlations.setdefault(right, {})[left] = value

    rows = []
    for name in sorted(FACTOR_BY_NAME):
        pairs = factor_observations.get(name, [])
        factors = [item[0] for item in pairs]
        returns = [item[1] for item in pairs]
        daily_ics = []
        daily_rank_ics = []
        for daily_pairs in factor_daily_pairs.get(name, {}).values():
            if len(daily_pairs) < 30:
                continue
            daily_left = [item[0] for item in daily_pairs]
            daily_right = [item[1] for item in daily_pairs]
            daily_ics.append(_corr(daily_left, daily_right))
            daily_rank_ics.append(_corr(_rank(daily_left), _rank(daily_right)))
        direction = FACTOR_BY_NAME[name].direction
        daily_ics = [value * direction for value in daily_ics if value is not None]
        daily_rank_ics = [value * direction for value in daily_rank_ics if value is not None]
        rank_ic = mean(daily_rank_ics) if daily_rank_ics else None
        ic = mean(daily_ics) if daily_ics else (_corr(factors, returns) * direction if factors and returns and _corr(factors, returns) is not None else None)
        icir = rank_ic / pstdev(daily_rank_ics) if rank_ic is not None and len(daily_rank_ics) >= 2 and pstdev(daily_rank_ics) else None
        quantile_rows = factor_quantile_scores.get(name, [])
        quantile_means = [mean([row[index] for row in quantile_rows]) for index in range(5)] if quantile_rows else []
        monotonicity = mean([_monotonicity(row) for row in quantile_rows if _monotonicity(row) is not None]) if quantile_rows else None
        top_quantile_return = quantile_means[-1] if quantile_means else None
        bottom_quantile_return = quantile_means[0] if quantile_means else None
        missing_rate = factor_missing_counts.get(name, 0) / max(1, factor_total_counts.get(name, 0))
        outlier_rate = factor_outlier_counts.get(name, 0) / max(1, factor_total_counts.get(name, 0))
        state_metrics = {}
        for state, state_pairs in factor_state_pairs.get(name, {}).items():
            state_left = [item[0] for item in state_pairs]
            state_right = [item[1] for item in state_pairs]
            state_rank_ic = _corr(_rank(state_left), _rank(state_right)) if len(state_pairs) >= 3 else None
            state_metrics[state] = {
                "sample_count": len(state_pairs),
                "mean_forward_return": mean(state_right) if state_right else None,
                "rank_ic": state_rank_ic * direction if state_rank_ic is not None else None,
            }
        related = []
        for other, value in correlations.get(name, {}).items():
            if value is not None:
                related.append(abs(value))
        correlation_mean_abs = mean(related) if related else None
        outcomes = factor_outcomes.get(name, [])
        max_profit = max((item[1] for item in outcomes), default=None)
        max_loss = min((item[2] for item in outcomes), default=None)
        max_drawdown = min((item[3] for item in outcomes), default=None)
        cost_adjusted_return = top_quantile_return - 0.002 if top_quantile_return is not None else None
        reasons = []
        # All current V2 formulas are evaluated only from bars available at
        # the signal date.  Keep this as an explicit validation field so a
        # future formula can never enter production merely because its
        # performance statistics look good.
        future_function = False
        price_basis = "raw"
        if not pairs or len(pairs) < 200:
            reasons.append("样本不足200")
        if missing_rate > 0.15:
            reasons.append(f"缺失率{missing_rate:.1%}过高")
        if outlier_rate > 0.10:
            reasons.append(f"异常值比例{outlier_rate:.1%}过高")
        if rank_ic is None or rank_ic < 0.01:
            reasons.append("Rank IC方向或稳定性不足")
        if icir is None or icir < 0.10:
            reasons.append("ICIR不足")
        if monotonicity is None or monotonicity < 0.60:
            reasons.append("分层收益单调性不足")
        if cost_adjusted_return is None or cost_adjusted_return <= 0:
            reasons.append("扣除20bp研究成本后收益不足")
        production_gate = (
            len(pairs) >= 200 and missing_rate <= 0.15 and outlier_rate <= 0.10
            and rank_ic is not None and rank_ic >= 0.01
            and icir is not None and icir >= 0.10
            and monotonicity is not None and monotonicity >= 0.60
            and cost_adjusted_return is not None and cost_adjusted_return > 0
            and len(dates) >= 120
            and not future_function
        )
        if production_gate:
            recommended_status = "production"
            validation_status = "passed"
        elif len(pairs) >= 200 and missing_rate <= 0.30 and not (rank_ic is None or rank_ic < -0.02):
            recommended_status = "observation"
            validation_status = "observation"
        else:
            recommended_status = "candidate"
            validation_status = "failed" if pairs else "insufficient"
        rows.append({
            "factor_name": name,
            "factor_label": FACTOR_BY_NAME[name].label,
            "category": FACTOR_BY_NAME[name].category,
            "category_label": DIMENSION_LABELS.get(FACTOR_BY_NAME[name].category, FACTOR_BY_NAME[name].category),
            "source": FACTOR_BY_NAME[name].source,
            "formula": FACTOR_BY_NAME[name].formula,
            "period": FACTOR_BY_NAME[name].period,
            "direction": FACTOR_BY_NAME[name].direction,
            "horizon": 5,
            "sample_count": len(pairs),
            "ic": ic,
            "rank_ic": rank_ic,
            "icir": icir,
            "mean_forward_return": mean(returns) if returns else None,
            "cost_adjusted_return": cost_adjusted_return,
            "missing_rate": missing_rate,
            "outlier_rate": outlier_rate,
            "monotonicity": monotonicity,
            "max_profit": max_profit,
            "max_loss": max_loss,
            "max_drawdown": max_drawdown,
            "market_state_json": json.dumps(state_metrics, ensure_ascii=False),
            "correlation_mean_abs": correlation_mean_abs,
            "future_function": future_function,
            "price_basis": price_basis,
            "quantile_returns": quantile_means,
            "top_quantile_return": top_quantile_return,
            "bottom_quantile_return": bottom_quantile_return,
            "validation_status": validation_status,
            "recommended_status": recommended_status,
            "validation_reason": "；".join(reasons) if reasons else "满足当前生产准入条件",
            "passed": production_gate,
        })
    horizons = {}
    for horizon in (1, 3, 5, 10, 20):
        values = horizon_values[horizon]
        horizons[str(horizon)] = {
            "count": len(values),
            "mean": mean(values) if values else None,
            "win_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "max_profit": max(values) if values else None,
            "max_loss": min(values) if values else None,
            "states": {
                state: {
                    "count": len(state_values[state][horizon]),
                    "mean": mean(state_values[state][horizon]) if state_values[state][horizon] else None,
                    "win_rate": sum(value > 0 for value in state_values[state][horizon]) / len(state_values[state][horizon]) if state_values[state][horizon] else None,
                }
                for state in ("WATCH", "READY", "TRIGGERED", "NO_CHASE", "INVALID")
            },
        }
    return {
        "trade_date": target,
        "research_days": len(dates),
        "requested_research_days": days,
        "research_universe_count": len(history),
        "sample_count": sum(len(values) for values in horizon_values.values()),
        "rows": rows,
        "correlation": correlations,
        "horizons": horizons,
        "outcomes": list(outcome_rows_map.values()),
    }


def persist_validation(result: dict) -> int:
    rows = result.get("rows") or []
    outcomes = result.get("outcomes") or []
    with engine.begin() as conn:
        for row in rows:
            validation_row = {
                **row,
                "quantile_returns_json": json.dumps(row.get("quantile_returns") or [], ensure_ascii=False),
                "research_universe": result.get("research_universe_count"),
                "research_days": result.get("research_days"),
            }
            conn.execute(text("""
                INSERT INTO v2_factor_validation
                (factor_name, horizon, sample_count, ic, rank_ic, icir, mean_forward_return,
                   cost_adjusted_return, missing_rate, outlier_rate, monotonicity,
                   quantile_returns_json, top_quantile_return, bottom_quantile_return,
                   max_profit, max_loss, max_drawdown, market_state_json,
                   correlation_mean_abs, future_function, price_basis, passed,
                   validation_status, recommended_status,
                   validation_reason, research_universe, research_days)
                VALUES (:factor_name, :horizon, :sample_count, :ic, :rank_ic, :icir, :mean_forward_return,
                        :cost_adjusted_return, :missing_rate, :outlier_rate, :monotonicity,
                        :quantile_returns_json, :top_quantile_return, :bottom_quantile_return,
                        :max_profit, :max_loss, :max_drawdown, :market_state_json,
                        :correlation_mean_abs, :future_function, :price_basis, :passed,
                        :validation_status, :recommended_status,
                        :validation_reason, :research_universe, :research_days)
            """), validation_row)
        for row in outcomes:
            returns = row.get("returns", {})
            conn.execute(text("""
                INSERT INTO v2_signal_outcomes
                  (code, signal_date, trading_state, return_1d, return_3d, return_5d,
                   return_10d, return_20d, max_profit, max_loss, max_drawdown)
                VALUES (:code, :signal_date, :trading_state, :return_1d, :return_3d, :return_5d,
                        :return_10d, :return_20d, :max_profit, :max_loss, :max_drawdown)
                ON CONFLICT (code, signal_date) DO UPDATE SET
                  trading_state=EXCLUDED.trading_state, return_1d=EXCLUDED.return_1d,
                  return_3d=EXCLUDED.return_3d, return_5d=EXCLUDED.return_5d,
                  return_10d=EXCLUDED.return_10d, return_20d=EXCLUDED.return_20d,
                  max_profit=EXCLUDED.max_profit, max_loss=EXCLUDED.max_loss,
                  max_drawdown=EXCLUDED.max_drawdown, created_at=NOW()
            """), {
                "code": row["code"], "signal_date": row["signal_date"],
                "trading_state": row["trading_state"],
                "return_1d": returns.get("1"), "return_3d": returns.get("3"),
                "return_5d": returns.get("5"), "return_10d": returns.get("10"),
                "return_20d": returns.get("20"), "max_profit": row.get("max_profit"),
                "max_loss": row.get("max_loss"), "max_drawdown": row.get("max_drawdown"),
            })
    return len(rows) + len(outcomes)

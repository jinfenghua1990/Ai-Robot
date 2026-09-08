"""DB-only scoring and state transition for the independent stage pool."""

from collections import defaultdict
from datetime import date, datetime
import json
from math import ceil
from statistics import median

from sqlalchemy import func, text

from db.models import StockDailyKline, StockUniverse
from db.session import get_db_session
from industry_stage.models import (
    TAXONOMY_VERSION,
    IndustryStageDailyBasic,
    IndustryStageMembership,
    IndustryStageRun,
    IndustryStageSectorDaily,
    IndustryStageStockDaily,
    IndustryStageTaxonomy,
)


STATE_INACTIVE = "INACTIVE"
STATE_CANDIDATE = "CANDIDATE"
STATE_ACTIVE = "ACTIVE"
STATE_COOLING = "COOLING"
MIN_COMPLETE_MARKET_ROWS = 4000


def adaptive_candidate_cap(universe_count: int) -> int:
    if universe_count <= 50:
        return 8
    if universe_count <= 150:
        return 15
    if universe_count <= 300:
        return 20
    return 30


def transition_state(
    previous_state: str | None,
    previous_streak: int,
    previous_weak_streak: int,
    *,
    strong_now: bool,
    weak_now: bool,
) -> tuple[str, int, int]:
    """Three-session confirmation in both directions; cash is a valid state."""
    previous = previous_state or STATE_INACTIVE
    streak = max(0, int(previous_streak or 0))
    weak_streak = max(0, int(previous_weak_streak or 0))

    if previous == STATE_ACTIVE:
        if weak_now:
            return STATE_COOLING, streak, 1
        return STATE_ACTIVE, streak + 1, 0

    if previous == STATE_COOLING:
        if strong_now:
            return STATE_ACTIVE, 1, 0
        if weak_now:
            weak_streak += 1
            if weak_streak >= 3:
                return STATE_INACTIVE, 0, weak_streak
            return STATE_COOLING, streak, weak_streak
        return STATE_COOLING, streak, 0

    if strong_now:
        streak += 1
        if streak >= 3:
            return STATE_ACTIVE, streak, 0
        return STATE_CANDIDATE, streak, 0

    return STATE_INACTIVE, 0, 0


def _safe_float(value):
    return float(value) if value is not None else None


def _pct(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (float(current) / float(previous) - 1) * 100


def _median(values):
    clean = [float(value) for value in values if value is not None]
    return median(clean) if clean else None


def _percentile_map(rows, key: str) -> dict:
    clean = sorted(
        ((str(row["ts_code"] if "ts_code" in row else row["l1_code"]), float(row[key]))
         for row in rows if row.get(key) is not None),
        key=lambda item: item[1],
    )
    if not clean:
        return {}
    if len(clean) == 1:
        return {clean[0][0]: 100.0}

    result = {}
    index = 0
    denominator = len(clean) - 1
    while index < len(clean):
        end = index
        while end + 1 < len(clean) and clean[end + 1][1] == clean[index][1]:
            end += 1
        percentile = ((index + end) / 2) / denominator * 100
        for offset in range(index, end + 1):
            result[clean[offset][0]] = percentile
        index = end + 1
    return result


_STOCK_METRICS_SQL = text("""
    WITH selected_dates AS (
        SELECT trade_date
        FROM stock_daily_kline
        WHERE trade_date <= :target
        GROUP BY trade_date
        HAVING COUNT(*) >= :min_market_rows
        ORDER BY trade_date DESC
        LIMIT 61
    ),
    bars AS (
        SELECT
            k.ts_code,
            k.trade_date,
            k.close,
            k.pct_chg,
            k.amount,
            k.volume,
            ROW_NUMBER() OVER (PARTITION BY k.ts_code ORDER BY k.trade_date DESC) AS rn
        FROM stock_daily_kline k
        JOIN selected_dates d ON d.trade_date = k.trade_date
        WHERE k.close > 0 AND k.volume > 0
    )
    SELECT
        ts_code,
        COUNT(*) AS history_count,
        MAX(close) FILTER (WHERE rn = 1) AS close,
        MAX(close) FILTER (WHERE rn = 6) AS close_5,
        MAX(close) FILTER (WHERE rn = 21) AS close_20,
        MAX(close) FILTER (WHERE rn = 61) AS close_60,
        MAX(pct_chg) FILTER (WHERE rn = 1) AS day_change_pct,
        AVG(close) FILTER (WHERE rn <= 20) AS ma20,
        AVG(close) FILTER (WHERE rn <= 60) AS ma60,
        MAX(close) FILTER (WHERE rn <= 60) AS high_close_60,
        AVG(amount) FILTER (WHERE rn <= 20) AS amount_20d,
        MAX(volume) FILTER (WHERE rn = 1) AS latest_volume,
        AVG(volume) FILTER (WHERE rn BETWEEN 2 AND 21) AS previous_volume_20d
    FROM bars
    GROUP BY ts_code
""")


def _load_stock_metrics(db, target: date) -> dict:
    result = {}
    for row in db.execute(_STOCK_METRICS_SQL, {
        "target": target,
        "min_market_rows": MIN_COMPLETE_MARKET_ROWS,
    }).mappings():
        close = _safe_float(row["close"])
        history_count = int(row["history_count"] or 0)
        ma20 = _safe_float(row["ma20"])
        ma60 = _safe_float(row["ma60"])
        previous_volume = _safe_float(row["previous_volume_20d"])
        latest_volume = _safe_float(row["latest_volume"])
        result[row["ts_code"]] = {
            "history_count": history_count,
            "close": close,
            "day_change_pct": _safe_float(row["day_change_pct"]),
            "ret_5d": _pct(close, row["close_5"]),
            "ret_20d": _pct(close, row["close_20"]),
            "ret_60d": _pct(close, row["close_60"]),
            "ma20": ma20,
            "ma60": ma60,
            "above_ma20": close >= ma20 if close is not None and ma20 is not None and history_count >= 20 else None,
            "above_ma60": close >= ma60 if close is not None and ma60 is not None and history_count >= 60 else None,
            "drawdown_60d": _pct(close, row["high_close_60"]),
            "amount_20d": _safe_float(row["amount_20d"]),
            "kline_volume_ratio": latest_volume / previous_volume if latest_volume is not None and previous_volume else None,
        }
    return result


def _score_stocks(stocks: list[dict], grouped: dict[str, list[dict]]) -> None:
    market_ret20 = _percentile_map(stocks, "ret_20d")
    market_ret60 = _percentile_map(stocks, "ret_60d")
    market_amount = _percentile_map(stocks, "amount_20d")
    market_volume = _percentile_map(stocks, "volume_ratio")

    for sector_stocks in grouped.values():
        sector_ret20 = _percentile_map(sector_stocks, "ret_20d")
        for stock in sector_stocks:
            code = stock["ts_code"]
            trend = 100.0 if stock.get("above_ma20") and stock.get("above_ma60") else (
                50.0 if stock.get("above_ma20") or stock.get("above_ma60") else 0.0
            )
            risk_penalty = max(0.0, min(10.0, (-float(stock.get("drawdown_60d") or 0) - 12) * 0.8))
            components = {
                "market_ret_20d": market_ret20.get(code, 0.0),
                "market_ret_60d": market_ret60.get(code, 0.0),
                "sector_ret_20d": sector_ret20.get(code, 0.0),
                "trend": trend,
                "volume": market_volume.get(code, 0.0),
                "liquidity": market_amount.get(code, 0.0),
                "risk_penalty": risk_penalty,
            }
            stock["score"] = round(
                components["market_ret_20d"] * 0.25
                + components["market_ret_60d"] * 0.20
                + components["sector_ret_20d"] * 0.15
                + components["trend"] * 0.20
                + components["volume"] * 0.10
                + components["liquidity"] * 0.10
                - risk_penalty,
                2,
            )
            stock["score_components"] = components


def _sector_stats(grouped: dict[str, list[dict]]) -> list[dict]:
    sectors = []
    for l1_code, stocks in grouped.items():
        valid = [stock for stock in stocks if stock.get("ret_20d") is not None]
        sectors.append({
            "l1_code": l1_code,
            "l1_name": stocks[0]["l1_name"],
            "universe_count": len(stocks),
            "valid_count": len(valid),
            "ret_20d_median": _median(stock.get("ret_20d") for stock in valid),
            "ret_60d_median": _median(stock.get("ret_60d") for stock in valid),
            "breadth_ma20": (
                sum(stock.get("above_ma20") is True for stock in valid) / len(valid) * 100 if valid else None
            ),
            "breadth_ma60": (
                sum(stock.get("above_ma60") is True for stock in valid) / len(valid) * 100 if valid else None
            ),
            "advance_ratio": (
                sum((stock.get("day_change_pct") or 0) > 0 for stock in valid) / len(valid) * 100 if valid else None
            ),
            "turnover_median": _median(stock.get("turnover_rate") for stock in valid),
            "drawdown_median": _median(stock.get("drawdown_60d") for stock in valid),
            "activity_value": _median(stock.get("amount_20d") for stock in valid),
            "total_mv": sum(float(stock.get("total_mv") or 0) for stock in stocks) or None,
        })

    p20 = _percentile_map(sectors, "ret_20d_median")
    p60 = _percentile_map(sectors, "ret_60d_median")
    activity = _percentile_map(sectors, "activity_value")
    for sector in sectors:
        code = sector["l1_code"]
        components = {
            "ret_20d": p20.get(code, 0.0),
            "ret_60d": p60.get(code, 0.0),
            "breadth_ma20": float(sector.get("breadth_ma20") or 0),
            "breadth_ma60": float(sector.get("breadth_ma60") or 0),
            "advance_ratio": float(sector.get("advance_ratio") or 0),
            "activity": activity.get(code, 0.0),
        }
        sector["score"] = round(
            components["ret_20d"] * 0.25
            + components["ret_60d"] * 0.25
            + components["breadth_ma20"] * 0.20
            + components["breadth_ma60"] * 0.15
            + components["advance_ratio"] * 0.05
            + components["activity"] * 0.10,
            2,
        )
        sector["score_components"] = components
    sectors.sort(key=lambda item: (-item["score"], item["l1_code"]))
    for rank, sector in enumerate(sectors, 1):
        sector["rank"] = rank
    return sectors


def _is_selectable(stock: dict) -> bool:
    name = str(stock.get("stock_name") or "").upper()
    return bool(
        stock.get("history_count", 0) >= 61
        and stock.get("ret_20d") is not None
        and stock.get("ret_60d") is not None
        and stock["ret_20d"] > 0
        and stock.get("above_ma20") is True
        and stock.get("above_ma60") is True
        and stock.get("drawdown_60d") is not None
        and stock["drawdown_60d"] > -20
        and stock.get("score", 0) >= 58
        and "ST" not in name
        and "退" not in name
    )


def build_snapshot(target: date, *, require_daily_basic: bool) -> dict:
    """Build one completed-day snapshot from local DB only."""
    started_at = datetime.now()
    with get_db_session() as db:
        taxonomy = db.query(IndustryStageTaxonomy).filter(
            IndustryStageTaxonomy.version == TAXONOMY_VERSION,
            IndustryStageTaxonomy.is_active.is_(True),
        ).all()
        memberships = db.query(IndustryStageMembership).filter(
            IndustryStageMembership.version == TAXONOMY_VERSION,
            IndustryStageMembership.is_current.is_(True),
        ).all()
        basics = db.query(IndustryStageDailyBasic).filter(
            IndustryStageDailyBasic.trade_date == target,
        ).all()
        metrics_by_code = _load_stock_metrics(db, target)

        l1_count = sum(row.level == "L1" for row in taxonomy)
        l2_count = sum(row.level == "L2" for row in taxonomy)
        membership_by_code = {row.ts_code: row for row in memberships}
        basic_by_code = {row.ts_code: row for row in basics}

        active_universe_codes = {
            row[0] for row in db.query(StockUniverse.ts_code).filter(
                StockUniverse.is_active.is_(True),
            ).all()
        }
        membership_codes = set(membership_by_code)
        matched_membership = len(active_universe_codes.intersection(membership_codes))
        membership_coverage = (
            matched_membership / len(active_universe_codes) * 100 if active_universe_codes else 0
        )
        matched_basic = len(membership_codes.intersection(basic_by_code))
        daily_basic_coverage = matched_basic / len(membership_codes) * 100 if membership_codes else 0

        grouped = defaultdict(list)
        all_stocks = []
        for code, membership in membership_by_code.items():
            metrics = metrics_by_code.get(code)
            if not metrics:
                metrics = {"history_count": 0}
            basic = basic_by_code.get(code)
            stock = {
                **metrics,
                "ts_code": code,
                "stock_name": membership.stock_name,
                "l1_code": membership.l1_code,
                "l1_name": membership.l1_name,
                "l2_code": membership.l2_code,
                "l2_name": membership.l2_name,
                "total_mv": _safe_float(basic.total_mv) if basic else None,
                "circ_mv": _safe_float(basic.circ_mv) if basic else None,
                "turnover_rate": _safe_float(basic.turnover_rate) if basic else None,
                "volume_ratio": (
                    _safe_float(basic.volume_ratio) if basic and basic.volume_ratio is not None
                    else metrics.get("kline_volume_ratio")
                ),
            }
            grouped[membership.l1_code].append(stock)
            all_stocks.append(stock)

        _score_stocks(all_stocks, grouped)
        sectors = _sector_stats(grouped)

        db.query(IndustryStageStockDaily).filter(IndustryStageStockDaily.trade_date == target).delete(
            synchronize_session=False,
        )
        db.query(IndustryStageSectorDaily).filter(IndustryStageSectorDaily.trade_date == target).delete(
            synchronize_session=False,
        )
        db.query(IndustryStageRun).filter(IndustryStageRun.trade_date == target).delete(
            synchronize_session=False,
        )

        selected_rows = []
        sector_rows = []
        for sector in sectors:
            code = sector["l1_code"]
            previous = db.query(IndustryStageSectorDaily).filter(
                IndustryStageSectorDaily.l1_code == code,
                IndustryStageSectorDaily.trade_date < target,
            ).order_by(IndustryStageSectorDaily.trade_date.desc()).first()
            strong_now = bool(
                sector["score"] >= 62
                and (sector.get("breadth_ma20") or 0) >= 52
                and (sector.get("ret_20d_median") or 0) > 0
            )
            weak_now = bool(
                sector["score"] < 48
                or (sector.get("breadth_ma20") or 0) < 38
                or (sector.get("ret_20d_median") or 0) < -2
            )
            state, state_streak, weak_streak = transition_state(
                previous.state if previous else None,
                previous.state_streak if previous else 0,
                previous.weak_streak if previous else 0,
                strong_now=strong_now,
                weak_now=weak_now,
            )

            cap = adaptive_candidate_cap(sector["universe_count"])
            selected = []
            if state in {STATE_CANDIDATE, STATE_ACTIVE, STATE_COOLING}:
                selected = sorted(
                    (stock for stock in grouped[code] if _is_selectable(stock)),
                    key=lambda stock: (-stock["score"], -(stock.get("ret_20d") or -999), stock["ts_code"]),
                )[:cap]
            core_limit = min(10, max(1, ceil(cap / 3)))
            core_count = 0
            for rank, stock in enumerate(selected, 1):
                tier = "CORE" if rank <= core_limit and stock["score"] >= 75 else "CANDIDATE"
                core_count += tier == "CORE"
                reason = (
                    f"行业{state}｜20日{stock.get('ret_20d', 0):+.1f}%｜"
                    f"60日{stock['ret_60d']:+.1f}%｜位于MA20/MA60上方"
                )
                selected_rows.append(IndustryStageStockDaily(
                    trade_date=target,
                    l1_code=stock["l1_code"],
                    l1_name=stock["l1_name"],
                    l2_code=stock["l2_code"],
                    l2_name=stock["l2_name"],
                    ts_code=stock["ts_code"],
                    stock_name=stock["stock_name"],
                    rank=rank,
                    tier=tier,
                    score=stock["score"],
                    close=stock.get("close"),
                    day_change_pct=stock.get("day_change_pct"),
                    ret_5d=stock.get("ret_5d"),
                    ret_20d=stock.get("ret_20d"),
                    ret_60d=stock.get("ret_60d"),
                    above_ma20=stock.get("above_ma20"),
                    above_ma60=stock.get("above_ma60"),
                    volume_ratio=stock.get("volume_ratio"),
                    turnover_rate=stock.get("turnover_rate"),
                    amount_20d=stock.get("amount_20d"),
                    total_mv=stock.get("total_mv"),
                    circ_mv=stock.get("circ_mv"),
                    drawdown_60d=stock.get("drawdown_60d"),
                    reason=reason,
                ))

            sector_rows.append(IndustryStageSectorDaily(
                trade_date=target,
                l1_code=code,
                l1_name=sector["l1_name"],
                rank=sector["rank"],
                score=sector["score"],
                state=state,
                state_streak=state_streak,
                weak_streak=weak_streak,
                universe_count=sector["universe_count"],
                valid_count=sector["valid_count"],
                selected_count=len(selected),
                core_count=core_count,
                max_candidates=cap,
                ret_20d_median=sector.get("ret_20d_median"),
                ret_60d_median=sector.get("ret_60d_median"),
                breadth_ma20=sector.get("breadth_ma20"),
                breadth_ma60=sector.get("breadth_ma60"),
                advance_ratio=sector.get("advance_ratio"),
                turnover_median=sector.get("turnover_median"),
                drawdown_median=sector.get("drawdown_median"),
                total_mv=sector.get("total_mv"),
                score_components_json=json.dumps(sector["score_components"], ensure_ascii=False),
            ))

        taxonomy_ok = l1_count == 31 and l2_count == 134
        quality_ok = taxonomy_ok and membership_coverage >= 98
        if require_daily_basic:
            quality_ok = quality_ok and daily_basic_coverage >= 95
        status = "READY" if quality_ok and require_daily_basic else "BACKFILL" if quality_ok else "INSUFFICIENT"
        messages = []
        if not taxonomy_ok:
            messages.append(f"taxonomy L1={l1_count}, L2={l2_count}")
        if membership_coverage < 98:
            messages.append(f"membership coverage={membership_coverage:.2f}%")
        if require_daily_basic and daily_basic_coverage < 95:
            messages.append(f"daily basic coverage={daily_basic_coverage:.2f}%")

        db.add_all(sector_rows)
        db.add_all(selected_rows)
        db.add(IndustryStageRun(
            trade_date=target,
            status=status,
            taxonomy_version=TAXONOMY_VERSION,
            l1_count=l1_count,
            l2_count=l2_count,
            membership_count=len(membership_codes),
            membership_coverage=round(membership_coverage, 2),
            daily_basic_count=len(basic_by_code),
            daily_basic_coverage=round(daily_basic_coverage, 2),
            sector_count=len(sector_rows),
            selected_stock_count=len(selected_rows),
            message="; ".join(messages),
            started_at=started_at,
            completed_at=datetime.now(),
        ))
        db.commit()

    return {
        "trade_date": target.isoformat(),
        "status": status,
        "sector_count": len(sector_rows),
        "selected_stock_count": len(selected_rows),
        "membership_coverage": round(membership_coverage, 2),
        "daily_basic_coverage": round(daily_basic_coverage, 2),
    }


def build_recent_snapshots(target: date, days: int = 10) -> dict:
    with get_db_session() as db:
        dates = [row[0] for row in db.query(StockDailyKline.trade_date).filter(
            StockDailyKline.trade_date <= target,
        ).group_by(StockDailyKline.trade_date).having(
            func.count(StockDailyKline.id) >= MIN_COMPLETE_MARKET_ROWS,
        ).order_by(StockDailyKline.trade_date.desc()).limit(days).all()]
    results = []
    for trade_date in reversed(dates):
        results.append(build_snapshot(trade_date, require_daily_basic=trade_date == target))
    return {"target": target.isoformat(), "days_built": len(results), "results": results}

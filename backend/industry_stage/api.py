"""Read-only API for the independent industry-stage V2 page."""

from collections import defaultdict
from datetime import date, datetime
import json

from fastapi import APIRouter, Query
from sqlalchemy import and_, func

from db.session import get_db_session
from industry_stage.market_clock import (
    PHASE_BREAK,
    PHASE_PREOPEN,
    PHASE_TRADING,
    REALTIME_FRESH_SECONDS,
    REALTIME_REFRESH_SECONDS,
    market_phase,
)
from industry_stage.models import (
    TAXONOMY_VERSION,
    IndustryStageDailyBasic,
    IndustryStageMembership,
    IndustryStageRealtimeQuote,
    IndustryStageRealtimeState,
    IndustryStageRun,
    IndustryStageSectorDaily,
    IndustryStageStockDaily,
    IndustryStageTaxonomy,
)


router = APIRouter(prefix="/api/industry-stage/v2", tags=["industry-stage-v2"])


def _round(value, digits=2):
    return round(float(value), digits) if value is not None else None


def _resolve_run(db, trade_date: date | None):
    query = db.query(IndustryStageRun)
    if trade_date is not None:
        return query.filter(IndustryStageRun.trade_date == trade_date).first()
    return query.order_by(IndustryStageRun.trade_date.desc()).first()


def _stock_payload(stock):
    return {
        "ts_code": stock.ts_code,
        "code": stock.ts_code.split(".")[0],
        "name": stock.stock_name,
        "rank": stock.rank,
        "tier": stock.tier,
        "score": _round(stock.score),
        "close": _round(stock.close),
        "day_change_pct": _round(stock.day_change_pct),
        "ret_5d": _round(stock.ret_5d),
        "ret_20d": _round(stock.ret_20d),
        "ret_60d": _round(stock.ret_60d),
        "above_ma20": stock.above_ma20,
        "above_ma60": stock.above_ma60,
        "volume_ratio": _round(stock.volume_ratio),
        "turnover_rate": _round(stock.turnover_rate),
        "amount_20d": _round(stock.amount_20d),
        "total_mv": _round(stock.total_mv),
        "circ_mv": _round(stock.circ_mv),
        "drawdown_60d": _round(stock.drawdown_60d),
        "reason": stock.reason,
        "l2_code": stock.l2_code,
        "l2_name": stock.l2_name,
    }


def _sector_payload(row):
    try:
        components = json.loads(row.score_components_json or "{}")
    except (TypeError, ValueError):
        components = {}
    return {
        "l1_code": row.l1_code,
        "l1_name": row.l1_name,
        "rank": row.rank,
        "score": _round(row.score),
        "state": row.state,
        "state_streak": row.state_streak,
        "weak_streak": row.weak_streak,
        "universe_count": row.universe_count,
        "valid_count": row.valid_count,
        "selected_count": row.selected_count,
        "core_count": row.core_count,
        "max_candidates": row.max_candidates,
        "ret_20d_median": _round(row.ret_20d_median),
        "ret_60d_median": _round(row.ret_60d_median),
        "breadth_ma20": _round(row.breadth_ma20),
        "breadth_ma60": _round(row.breadth_ma60),
        "advance_ratio": _round(row.advance_ratio),
        "turnover_median": _round(row.turnover_median),
        "drawdown_median": _round(row.drawdown_median),
        "total_mv": _round(row.total_mv),
        "score_components": {key: _round(value) for key, value in components.items()},
    }


def _realtime_quote_payload(row, now: datetime):
    age_seconds = max(0, int((now - row.snapshot_time).total_seconds()))
    return {
        "ts_code": row.ts_code,
        "code": row.ts_code.split(".")[0],
        "name": row.stock_name,
        "price": _round(row.price),
        "previous_close": _round(row.previous_close),
        "day_change_pct": _round(row.day_change_pct),
        "amount_wan": _round(row.amount_wan),
        "turnover_rate": _round(row.turnover_rate),
        "volume_ratio": _round(row.volume_ratio),
        "snapshot_time": row.snapshot_time.isoformat(),
        "age_seconds": age_seconds,
        "is_stale": age_seconds > REALTIME_FRESH_SECONDS,
        "source": row.source,
    }


@router.get("/overview")
def get_overview(trade_date: date | None = Query(default=None)):
    with get_db_session() as db:
        run = _resolve_run(db, trade_date)
        if run is None:
            return {
                "status": "MISSING",
                "version": "industry-stage-v2",
                "message": "独立行业阶段池尚未生成离线快照",
                "sectors": [],
            }
        target = run.trade_date
        sector_rows = db.query(IndustryStageSectorDaily).filter(
            IndustryStageSectorDaily.trade_date == target,
        ).order_by(IndustryStageSectorDaily.rank).all()
        stock_rows = db.query(IndustryStageStockDaily).filter(
            IndustryStageStockDaily.trade_date == target,
        ).order_by(IndustryStageStockDaily.l1_code, IndustryStageStockDaily.rank).all()
        taxonomy_rows = db.query(IndustryStageTaxonomy).filter(
            IndustryStageTaxonomy.version == TAXONOMY_VERSION,
            IndustryStageTaxonomy.is_active.is_(True),
        ).all()

        aggregate_rows = db.query(
            IndustryStageMembership.l1_code,
            IndustryStageMembership.l2_code,
            IndustryStageMembership.l2_name,
            func.count(func.distinct(IndustryStageMembership.ts_code)),
            func.sum(IndustryStageDailyBasic.total_mv),
        ).outerjoin(
            IndustryStageDailyBasic,
            and_(
                IndustryStageDailyBasic.ts_code == IndustryStageMembership.ts_code,
                IndustryStageDailyBasic.trade_date == target,
            ),
        ).filter(
            IndustryStageMembership.version == TAXONOMY_VERSION,
            IndustryStageMembership.is_current.is_(True),
        ).group_by(
            IndustryStageMembership.l1_code,
            IndustryStageMembership.l2_code,
            IndustryStageMembership.l2_name,
        ).all()

        selected_by_l2 = defaultdict(list)
        selected_by_l1 = defaultdict(list)
        for stock in stock_rows:
            payload = _stock_payload(stock)
            selected_by_l2[(stock.l1_code, stock.l2_code)].append(payload)
            selected_by_l1[stock.l1_code].append(payload)

        l1_by_industry_code = {
            row.industry_code: row for row in taxonomy_rows if row.level == "L1"
        }
        l2_by_l1 = defaultdict(list)
        for row in taxonomy_rows:
            if row.level != "L2":
                continue
            parent = l1_by_industry_code.get(row.parent_code)
            if parent:
                l2_by_l1[parent.index_code].append({
                    "l2_code": row.index_code,
                    "l2_name": row.industry_name,
                    "universe_count": 0,
                    "total_mv": None,
                    "stocks": selected_by_l2.get((parent.index_code, row.index_code), []),
                })

        l2_lookup = {
            (l1_code, item["l2_code"]): item
            for l1_code, items in l2_by_l1.items()
            for item in items
        }
        for l1_code, l2_code, l2_name, universe_count, total_mv in aggregate_rows:
            item = l2_lookup.get((l1_code, l2_code))
            if item is None:
                item = {
                    "l2_code": l2_code,
                    "l2_name": l2_name,
                    "universe_count": 0,
                    "total_mv": None,
                    "stocks": selected_by_l2.get((l1_code, l2_code), []),
                }
                l2_by_l1[l1_code].append(item)
                l2_lookup[(l1_code, l2_code)] = item
            item["universe_count"] = int(universe_count or 0)
            item["total_mv"] = _round(total_mv)

        sectors = []
        for row in sector_rows:
            payload = _sector_payload(row)
            payload["stocks"] = selected_by_l1.get(row.l1_code, [])
            payload["children"] = sorted(
                l2_by_l1.get(row.l1_code, []),
                key=lambda item: (-(item.get("total_mv") or 0), item["l2_code"]),
            )
            sectors.append(payload)

        state_counts = defaultdict(int)
        for sector in sectors:
            state_counts[sector["state"]] += 1
        return {
            "status": run.status,
            "version": "industry-stage-v2",
            "trade_date": target.isoformat(),
            "data_as_of": target.isoformat(),
            "message": run.message,
            "taxonomy": {
                "name": "申万行业分类 2021",
                "version": run.taxonomy_version,
                "source": "Tushare index_classify/index_member_all",
                "l1_count": run.l1_count,
                "l2_count": run.l2_count,
            },
            "quality": {
                "membership_count": run.membership_count,
                "membership_coverage": _round(run.membership_coverage),
                "daily_basic_count": run.daily_basic_count,
                "daily_basic_coverage": _round(run.daily_basic_coverage),
                "sector_count": run.sector_count,
            },
            "summary": {
                "selected_stock_count": run.selected_stock_count,
                "active_sector_count": state_counts["ACTIVE"],
                "candidate_sector_count": state_counts["CANDIDATE"],
                "cooling_sector_count": state_counts["COOLING"],
                "inactive_sector_count": state_counts["INACTIVE"],
            },
            "rules": {
                "adaptive_caps": ["≤50: 8", "51–150: 15", "151–300: 20", ">300: 30"],
                "core_limit": "每行业最多 10 只，且得分不低于 75",
                "state_confirmation": "连续 3 个完成交易日确认升级或退出",
                "execution": "研究池，不连接自动交易",
            },
            "sectors": sectors,
        }


@router.get("/sectors/{l1_code}")
def get_sector(l1_code: str, trade_date: date | None = Query(default=None)):
    overview = get_overview(trade_date)
    for sector in overview.get("sectors", []):
        if sector["l1_code"] == l1_code:
            return {
                "status": overview["status"],
                "trade_date": overview.get("trade_date"),
                "sector": sector,
            }
    return {
        "status": "MISSING",
        "trade_date": overview.get("trade_date"),
        "message": f"未找到行业 {l1_code}",
        "sector": None,
    }


@router.get("/realtime")
def get_realtime():
    """Read the independently collected intraday layer; never performs external I/O."""
    now = datetime.now()
    with get_db_session() as db:
        state = db.query(IndustryStageRealtimeState).filter(
            IndustryStageRealtimeState.trade_date == now.date(),
        ).first()
        quote_rows = db.query(IndustryStageRealtimeQuote).filter(
            IndustryStageRealtimeQuote.trade_date == now.date(),
        ).order_by(IndustryStageRealtimeQuote.ts_code).all()

    phase = market_phase(now, state.is_market_day if state else None)
    quotes = [_realtime_quote_payload(row, now) for row in quote_rows]
    fresh_count = sum(not quote["is_stale"] for quote in quotes)
    latest_snapshot = state.snapshot_time if state else None
    age_seconds = (
        max(0, int((now - latest_snapshot).total_seconds()))
        if latest_snapshot else None
    )

    if phase == PHASE_TRADING:
        if state and state.status == "CLOSED":
            effective_status = "CLOSED"
        elif fresh_count:
            effective_status = "DEGRADED" if state and state.status == "FAILED" else (state.status if state else "READY")
        elif state and state.status == "FAILED":
            effective_status = "FAILED"
        elif quote_rows:
            effective_status = "STALE"
        else:
            effective_status = state.status if state else "WAITING"
    else:
        effective_status = "CLOSED"

    is_live = phase == PHASE_TRADING and fresh_count > 0 and effective_status not in {"CLOSED", "FAILED", "STALE"}
    if phase == PHASE_TRADING and effective_status != "CLOSED":
        refresh_after_seconds = REALTIME_REFRESH_SECONDS
    elif phase in {PHASE_PREOPEN, PHASE_BREAK}:
        refresh_after_seconds = 60
    else:
        refresh_after_seconds = 300

    return {
        "status": effective_status,
        "market_phase": phase,
        "is_live": is_live,
        "trade_date": now.date().isoformat(),
        "pool_trade_date": state.pool_trade_date.isoformat() if state and state.pool_trade_date else None,
        "snapshot_time": latest_snapshot.isoformat() if latest_snapshot else None,
        "age_seconds": age_seconds,
        "expected_count": state.expected_count if state else 0,
        "quote_count": state.quote_count if state else 0,
        "fresh_count": fresh_count,
        "coverage": _round(state.coverage) if state else 0,
        "source": state.source if state else "tencent_realtime",
        "message": state.message if state else "等待独立实时采集器落库",
        "refresh_after_seconds": refresh_after_seconds,
        "quotes": quotes,
    }


@router.get("/history")
def get_history(limit: int = Query(default=10, ge=1, le=30)):
    with get_db_session() as db:
        dates = [row[0] for row in db.query(IndustryStageRun.trade_date).order_by(
            IndustryStageRun.trade_date.desc(),
        ).limit(limit).all()]
        rows = db.query(IndustryStageSectorDaily).filter(
            IndustryStageSectorDaily.trade_date.in_(dates),
        ).order_by(IndustryStageSectorDaily.trade_date.desc(), IndustryStageSectorDaily.rank).all() if dates else []
        by_date = defaultdict(list)
        for row in rows:
            by_date[row.trade_date.isoformat()].append(_sector_payload(row))
        return {
            "status": "READY" if dates else "MISSING",
            "dates": [value.isoformat() for value in dates],
            "history": [{"trade_date": value.isoformat(), "sectors": by_date[value.isoformat()]} for value in dates],
        }

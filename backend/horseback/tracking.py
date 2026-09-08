"""回马枪候选的独立 20 个交易日跟踪。

只跟踪已经完成实时确认且具有真实快照价的形态合格结果。跟踪数据与
strategy_track 完全隔离，避免 BS 卖点等其他策略规则污染回马枪统计。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
)

from db.connection import Base, engine
from db.models import HorsebackResult, HorsebackRun, StockDailyKline
from db.session import get_db_session


TRACK_DAYS = 20
ADMISSION_STATUSES = frozenset({"SELECTED", "WATCHING"})
ACTIVE_STATUS = "active"
HISTORY_STATUSES = frozenset({"completed", "archived"})


class HorsebackTrack(Base):
    """回马枪一次入池快照及其 20 日跟踪状态。"""

    __tablename__ = "horseback_tracks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pool_date = Column(Date, nullable=False, index=True)
    source_run_id = Column(String(36), nullable=False, index=True)
    source_mode = Column(String(16), nullable=False)
    strategy_version = Column(String(32), nullable=False)
    structure_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(50))

    admission_status = Column(String(24), nullable=False, index=True)
    score = Column(Integer)
    entry_price = Column(Numeric(12, 4), nullable=False)
    entry_price_source = Column(String(32), nullable=False, default="realtime_snapshot")
    entry_snapshot_at = Column(DateTime, nullable=False)
    source_options_json = Column(Text, nullable=False, default="{}")
    last_limit_date = Column(Date)
    days_since_limit = Column(Integer)
    suggested_buy = Column(Numeric(12, 4))
    stop_loss = Column(Numeric(12, 4))
    track_days = Column(Integer, nullable=False, default=TRACK_DAYS)

    status = Column(String(20), nullable=False, default=ACTIVE_STATUS, index=True)
    completed_date = Column(Date)
    archive_reason = Column(String(80))
    latest_day = Column(Integer, nullable=False, default=0)
    latest_trade_date = Column(Date)
    latest_close = Column(Numeric(12, 4))
    latest_daily_pct = Column(Numeric(10, 4))
    latest_return_pct = Column(Numeric(10, 4))
    max_return_pct = Column(Numeric(10, 4))
    min_return_pct = Column(Numeric(10, 4))
    max_drawdown_pct = Column(Numeric(10, 4))
    final_return_pct = Column(Numeric(10, 4))

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("pool_date", "ts_code", name="uq_horseback_track_pool_code"),
        Index("ix_horseback_track_status_pool", "status", "pool_date"),
    )


class HorsebackTrackDaily(Base):
    """回马枪跟踪池 D1-D20 的逐日行情。"""

    __tablename__ = "horseback_track_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracker_id = Column(
        Integer,
        ForeignKey("horseback_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trade_date = Column(Date, nullable=False, index=True)
    day_n = Column(Integer, nullable=False)
    open = Column(Numeric(12, 4))
    high = Column(Numeric(12, 4))
    low = Column(Numeric(12, 4))
    close = Column(Numeric(12, 4), nullable=False)
    daily_pct = Column(Numeric(10, 4))
    cum_return_pct = Column(Numeric(10, 4))
    drawdown_pct = Column(Numeric(10, 4))
    volume = Column(Numeric(20, 4))
    amount = Column(Numeric(20, 4))
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tracker_id", "trade_date", name="uq_horseback_track_daily_tracker_date"),
        UniqueConstraint("tracker_id", "day_n", name="uq_horseback_track_daily_tracker_day"),
    )


class TrackingRunNotFound(LookupError):
    pass


class TrackingRunNotReady(ValueError):
    pass


class TrackingRunUnsupported(ValueError):
    pass


def ensure_schema() -> None:
    """幂等创建独立跟踪表。"""

    Base.metadata.create_all(
        bind=engine,
        tables=[HorsebackTrack.__table__, HorsebackTrackDaily.__table__],
    )


def _float(value):
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


def _iso(value):
    return value.isoformat() if value else None


def _loads(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _source_options(run: HorsebackRun) -> dict:
    return {
        "min_consolidation_days": run.min_consolidation_days,
        "max_consolidation_days": run.max_consolidation_days,
        "min_limit_count": run.min_limit_count,
        "max_limit_count": run.max_limit_count,
        "min_score": run.min_score,
        "max_candidates": run.max_candidates,
        "live_rise_pct_min": run.live_rise_pct_min,
        "live_volume_ratio_min": run.live_volume_ratio_min,
        "allow_gem": bool(run.allow_gem),
        "allow_star": bool(run.allow_star),
    }


def _entry_snapshot(run: HorsebackRun, result: HorsebackResult) -> tuple[date, datetime | None, float]:
    """返回真实 Day0 日期、快照时间和价格；不把历史收盘价冒充实时入池价。"""

    price = _float(result.realtime_price)
    if price is None or price <= 0:
        raise TrackingRunUnsupported(f"{result.ts_code} 缺少有效实时快照价")
    snapshot_at = result.realtime_at or run.realtime_at or run.completed_at
    if not snapshot_at:
        raise TrackingRunUnsupported(f"{result.ts_code} 缺少实时快照时间")
    return snapshot_at.date(), snapshot_at, price


def _performance(entry_price: float, close: float, peak_price: float) -> tuple[float, float, float]:
    """累计收益、当前回撤和更新后的峰值。"""

    new_peak = max(peak_price, close)
    cumulative = round((close / entry_price - 1) * 100, 4)
    drawdown = round((close / new_peak - 1) * 100, 4)
    return cumulative, drawdown, new_peak


def _serialize_daily(row: HorsebackTrackDaily) -> dict:
    return {
        "id": row.id,
        "tracker_id": row.tracker_id,
        "trade_date": _iso(row.trade_date),
        "day_n": row.day_n,
        "open": _float(row.open),
        "high": _float(row.high),
        "low": _float(row.low),
        "close": _float(row.close),
        "daily_pct": _float(row.daily_pct),
        "cum_return_pct": _float(row.cum_return_pct),
        "drawdown_pct": _float(row.drawdown_pct),
        "volume": _float(row.volume),
        "amount": _float(row.amount),
    }


def _serialize_track(db, row: HorsebackTrack, include_daily: bool = True) -> dict:
    payload = {
        "id": row.id,
        "pool_date": _iso(row.pool_date),
        "source_run_id": row.source_run_id,
        "source_mode": row.source_mode,
        "strategy_version": row.strategy_version,
        "structure_date": _iso(row.structure_date),
        "ts_code": row.ts_code,
        "name": row.name or row.ts_code,
        "admission_status": row.admission_status,
        "score": row.score,
        "entry_price": _float(row.entry_price),
        "entry_price_source": row.entry_price_source,
        "entry_snapshot_at": _iso(row.entry_snapshot_at),
        "source_options": _loads(row.source_options_json, {}),
        "last_limit_date": _iso(row.last_limit_date),
        "days_since_limit": row.days_since_limit,
        "suggested_buy": _float(row.suggested_buy),
        "stop_loss": _float(row.stop_loss),
        "track_days": row.track_days,
        "status": row.status,
        "completed_date": _iso(row.completed_date),
        "archive_reason": row.archive_reason,
        "latest_day": row.latest_day,
        "latest_trade_date": _iso(row.latest_trade_date),
        "latest_close": _float(row.latest_close),
        "latest_daily_pct": _float(row.latest_daily_pct),
        "latest_return_pct": _float(row.latest_return_pct),
        "max_return_pct": _float(row.max_return_pct),
        "min_return_pct": _float(row.min_return_pct),
        "max_drawdown_pct": _float(row.max_drawdown_pct),
        "final_return_pct": _float(row.final_return_pct),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }
    if include_daily:
        daily = (
            db.query(HorsebackTrackDaily)
            .filter(HorsebackTrackDaily.tracker_id == row.id)
            .order_by(HorsebackTrackDaily.day_n.asc())
            .all()
        )
        payload["daily"] = [_serialize_daily(item) for item in daily]
    return payload


def _summary(db) -> dict:
    active = db.query(HorsebackTrack).filter(HorsebackTrack.status == ACTIVE_STATUS).all()
    completed = db.query(HorsebackTrack).filter(HorsebackTrack.status == "completed").all()
    archived_count = (
        db.query(func.count(HorsebackTrack.id))
        .filter(HorsebackTrack.status == "archived")
        .scalar()
        or 0
    )
    active_returns = [_float(row.latest_return_pct) for row in active if row.latest_return_pct is not None]
    completed_returns = [_float(row.final_return_pct) for row in completed if row.final_return_pct is not None]
    completed_by_admission = {}
    for admission_status in sorted(ADMISSION_STATUSES):
        values = [
            _float(row.final_return_pct)
            for row in completed
            if row.admission_status == admission_status and row.final_return_pct is not None
        ]
        completed_by_admission[admission_status] = {
            "samples": len(values),
            "avg_return": round(sum(values) / len(values), 2) if values else None,
            "win_rate": round(sum(value > 0 for value in values) / len(values) * 100, 1) if values else None,
        }
    return {
        "active": len(active),
        "selected_active": sum(row.admission_status == "SELECTED" for row in active),
        "watching_active": sum(row.admission_status == "WATCHING" for row in active),
        "completed": len(completed),
        "archived": archived_count,
        "active_avg_return": round(sum(active_returns) / len(active_returns), 2) if active_returns else None,
        "completed_avg_return": round(sum(completed_returns) / len(completed_returns), 2) if completed_returns else None,
        "completed_win_rate": (
            round(sum(value > 0 for value in completed_returns) / len(completed_returns) * 100, 1)
            if completed_returns
            else None
        ),
        "completed_samples": len(completed_returns),
        "completed_by_admission": completed_by_admission,
    }


def list_tracks(status: str = ACTIVE_STATUS, limit: int = 500, offset: int = 0) -> dict:
    allowed = {ACTIVE_STATUS, "completed", "archived", "history", "all"}
    if status not in allowed:
        raise ValueError(f"不支持的状态: {status}")
    with get_db_session() as db:
        query = db.query(HorsebackTrack)
        if status == "history":
            query = query.filter(HorsebackTrack.status.in_(sorted(HISTORY_STATUSES)))
        elif status != "all":
            query = query.filter(HorsebackTrack.status == status)
        query = query.order_by(desc(HorsebackTrack.pool_date), desc(HorsebackTrack.score), HorsebackTrack.ts_code)
        total = query.count()
        rows = query.offset(offset).limit(limit).all()
        return {
            "rows": [_serialize_track(db, row) for row in rows],
            "total": total,
            "summary": _summary(db),
            "contract": {
                "track_days": TRACK_DAYS,
                "admission": "形态达标且取得真实实时快照价的 SELECTED/WATCHING",
                "day_zero": "实时快照日期；历史结构扫描不会把当前价格回填成历史价格",
                "completion": "第 20 个有本地日线的后续交易日自然完成",
                "win_rate": "D20 最终累计收益大于 0 的完成样本占比；SELECTED/WATCHING 分层保留",
                "execution": "研究跟踪，不自动下单",
            },
        }


def sync_completed_run(run_id: str | None = None) -> dict:
    """把指定或最新的已完成实时回马枪任务幂等加入跟踪池。"""

    from horseback import STRATEGY_VERSION

    with get_db_session() as db:
        query = db.query(HorsebackRun).filter(HorsebackRun.status == "COMPLETED")
        if run_id:
            run = query.filter(HorsebackRun.id == run_id).first()
            if not run:
                if db.query(HorsebackRun.id).filter(HorsebackRun.id == run_id).first():
                    raise TrackingRunNotReady("该回马枪任务尚未完成")
                raise TrackingRunNotFound("回马枪任务不存在")
        else:
            run = (
                query.filter(HorsebackRun.strategy_version == STRATEGY_VERSION)
                .order_by(HorsebackRun.created_at.desc())
                .first()
            )
            if not run:
                raise TrackingRunNotFound("没有可同步的已完成回马枪任务")

        if (run.mode or "live") == "replay":
            raise TrackingRunUnsupported("旧版 replay 没有真实实时入池价，不能加入 20 日跟踪")

        candidates = (
            db.query(HorsebackResult)
            .filter(
                HorsebackResult.run_id == run.id,
                HorsebackResult.structure_eligible.is_(True),
                HorsebackResult.status.in_(sorted(ADMISSION_STATUSES)),
                HorsebackResult.realtime_price.isnot(None),
                HorsebackResult.realtime_price > 0,
            )
            .order_by(desc(HorsebackResult.score), HorsebackResult.ts_code)
            .all()
        )

        added = []
        duplicates = []
        options_json = json.dumps(_source_options(run), ensure_ascii=False, sort_keys=True)
        for result in candidates:
            pool_date, snapshot_at, entry_price = _entry_snapshot(run, result)
            existing = (
                db.query(HorsebackTrack)
                .filter(
                    HorsebackTrack.pool_date == pool_date,
                    HorsebackTrack.ts_code == result.ts_code,
                )
                .first()
            )
            if existing:
                duplicates.append(result.ts_code)
                continue
            row = HorsebackTrack(
                pool_date=pool_date,
                source_run_id=run.id,
                source_mode=run.mode or "live",
                strategy_version=run.strategy_version,
                structure_date=run.as_of_date,
                ts_code=result.ts_code,
                name=result.name,
                admission_status=result.status,
                score=result.score,
                entry_price=entry_price,
                entry_price_source="realtime_snapshot",
                entry_snapshot_at=snapshot_at,
                source_options_json=options_json,
                last_limit_date=result.last_limit_date,
                days_since_limit=result.days_since_limit,
                suggested_buy=result.suggested_buy,
                stop_loss=result.stop_loss,
                track_days=TRACK_DAYS,
                status=ACTIVE_STATUS,
                latest_day=0,
            )
            db.add(row)
            db.flush()
            added.append({
                "id": row.id,
                "ts_code": row.ts_code,
                "name": row.name or row.ts_code,
                "admission_status": row.admission_status,
                "entry_price": _float(row.entry_price),
            })
        db.commit()
        return {
            "run_id": run.id,
            "strategy_version": run.strategy_version,
            "source_mode": run.mode or "live",
            "structure_date": _iso(run.as_of_date),
            "pool_date": _iso(_entry_snapshot(run, candidates[0])[0]) if candidates else None,
            "eligible_with_snapshot": len(candidates),
            "added": added,
            "duplicates": duplicates,
            "total_added": len(added),
            "total_duplicates": len(duplicates),
        }


def daily_update() -> dict:
    """用本地 stock_daily_kline 幂等推进所有 active 样本到 D20。"""

    updated = []
    completed = []
    errors = []
    with get_db_session() as db:
        trackers = (
            db.query(HorsebackTrack)
            .filter(HorsebackTrack.status == ACTIVE_STATUS)
            .order_by(HorsebackTrack.pool_date, HorsebackTrack.id)
            .all()
        )
        for track in trackers:
            try:
                existing = (
                    db.query(HorsebackTrackDaily)
                    .filter(HorsebackTrackDaily.tracker_id == track.id)
                    .order_by(HorsebackTrackDaily.day_n)
                    .all()
                )
                existing_dates = {row.trade_date for row in existing}
                last_day = max((row.day_n for row in existing), default=0)
                remaining = max((track.track_days or TRACK_DAYS) - last_day, 0)
                if remaining == 0:
                    track.status = "completed"
                    track.completed_date = track.latest_trade_date
                    track.final_return_pct = track.latest_return_pct
                    db.commit()
                    continue

                query = db.query(StockDailyKline).filter(
                    StockDailyKline.ts_code == track.ts_code,
                    StockDailyKline.trade_date > track.pool_date,
                    StockDailyKline.close.isnot(None),
                )
                if existing_dates:
                    query = query.filter(~StockDailyKline.trade_date.in_(existing_dates))
                bars = query.order_by(StockDailyKline.trade_date.asc()).limit(remaining).all()
                if not bars:
                    continue

                entry_price = float(track.entry_price)
                prior_closes = [float(row.close) for row in existing if row.close is not None]
                peak_price = max([entry_price, *prior_closes])
                cur_max = _float(track.max_return_pct)
                cur_min = _float(track.min_return_pct)
                cur_drawdown = _float(track.max_drawdown_pct)
                added_days = 0

                for bar in bars:
                    last_day += 1
                    close = float(bar.close)
                    cumulative, drawdown, peak_price = _performance(entry_price, close, peak_price)
                    daily_pct = _float(bar.pct_chg)
                    daily = HorsebackTrackDaily(
                        tracker_id=track.id,
                        trade_date=bar.trade_date,
                        day_n=last_day,
                        open=_float(bar.open),
                        high=_float(bar.high),
                        low=_float(bar.low),
                        close=close,
                        daily_pct=daily_pct,
                        cum_return_pct=cumulative,
                        drawdown_pct=drawdown,
                        volume=_float(bar.volume),
                        amount=_float(bar.amount),
                    )
                    db.add(daily)
                    cur_max = cumulative if cur_max is None else max(cur_max, cumulative)
                    cur_min = cumulative if cur_min is None else min(cur_min, cumulative)
                    cur_drawdown = drawdown if cur_drawdown is None else min(cur_drawdown, drawdown)
                    track.latest_day = last_day
                    track.latest_trade_date = bar.trade_date
                    track.latest_close = close
                    track.latest_daily_pct = daily_pct
                    track.latest_return_pct = cumulative
                    track.max_return_pct = cur_max
                    track.min_return_pct = cur_min
                    track.max_drawdown_pct = cur_drawdown
                    added_days += 1

                if last_day >= (track.track_days or TRACK_DAYS):
                    track.status = "completed"
                    track.completed_date = track.latest_trade_date
                    track.final_return_pct = track.latest_return_pct
                    completed.append({
                        "id": track.id,
                        "ts_code": track.ts_code,
                        "name": track.name or track.ts_code,
                        "final_return_pct": _float(track.final_return_pct),
                    })
                updated.append({
                    "id": track.id,
                    "ts_code": track.ts_code,
                    "name": track.name or track.ts_code,
                    "days_added": added_days,
                    "latest_day": track.latest_day,
                    "latest_return_pct": _float(track.latest_return_pct),
                })
                db.commit()
            except Exception as exc:
                db.rollback()
                errors.append({"id": track.id, "ts_code": track.ts_code, "error": str(exc)})
    return {
        "updated": updated,
        "completed": completed,
        "errors": errors,
        "total_updated": len(updated),
        "total_completed": len(completed),
        "total_errors": len(errors),
    }


def archive_track(tracker_id: int, reason: str = "MANUAL") -> dict:
    with get_db_session() as db:
        row = db.query(HorsebackTrack).filter(HorsebackTrack.id == tracker_id).first()
        if not row:
            raise LookupError("跟踪记录不存在")
        if row.status != ACTIVE_STATUS:
            raise ValueError(f"当前状态为 {row.status}，不能再次归档")
        row.status = "archived"
        row.completed_date = row.latest_trade_date or date.today()
        row.archive_reason = reason[:80]
        row.final_return_pct = row.latest_return_pct
        db.commit()
        db.refresh(row)
        return _serialize_track(db, row)

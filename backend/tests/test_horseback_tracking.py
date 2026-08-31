from contextlib import contextmanager
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.connection import Base
from db.models import HorsebackResult, HorsebackRun, StockDailyKline
from horseback import tracking


@pytest.fixture()
def tracking_session(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=test_engine,
        tables=[
            HorsebackRun.__table__,
            HorsebackResult.__table__,
            StockDailyKline.__table__,
            tracking.HorsebackTrack.__table__,
            tracking.HorsebackTrackDaily.__table__,
        ],
    )
    session_factory = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    @contextmanager
    def test_session():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(tracking, "get_db_session", test_session)
    return session_factory


def _seed_run(session_factory):
    with session_factory() as db:
        db.add(HorsebackRun(
            id="run-track-1",
            status="COMPLETED",
            source="ifind_mcp",
            strategy_version="1.1.6-live.2",
            mode="historical_live",
            requested_end_date=date(2026, 8, 28),
            as_of_date=date(2026, 8, 28),
            window_start=date(2026, 8, 17),
            window_end=date(2026, 8, 28),
            completed_at=datetime(2026, 8, 31, 15, 10),
        ))
        db.add_all([
            HorsebackResult(
                id=1,
                run_id="run-track-1",
                ts_code="600001.SH",
                name="测试一号",
                status="WATCHING",
                score=88,
                kline_count=80,
                structure_eligible=True,
                realtime_price=10,
                realtime_at=datetime(2026, 8, 31, 15, 5),
                components_json="[]",
                hard_failures_json="[]",
            ),
            HorsebackResult(
                id=2,
                run_id="run-track-1",
                ts_code="600002.SH",
                name="未达标",
                status="NOT_SELECTED",
                score=60,
                kline_count=80,
                structure_eligible=False,
                realtime_price=9,
                realtime_at=datetime(2026, 8, 31, 15, 5),
                components_json="[]",
                hard_failures_json="[]",
            ),
            HorsebackResult(
                id=3,
                run_id="run-track-1",
                ts_code="600003.SH",
                name="无快照",
                status="WATCHING",
                score=82,
                kline_count=80,
                structure_eligible=True,
                realtime_price=None,
                realtime_at=None,
                components_json="[]",
                hard_failures_json="[]",
            ),
        ])
        db.commit()


def test_sync_uses_real_snapshot_day_zero_and_is_idempotent(tracking_session):
    _seed_run(tracking_session)

    first = tracking.sync_completed_run("run-track-1")
    second = tracking.sync_completed_run("run-track-1")

    assert first["structure_date"] == "2026-08-28"
    assert first["pool_date"] == "2026-08-31"
    assert first["total_added"] == 1
    assert first["added"][0]["ts_code"] == "600001.SH"
    assert first["added"][0]["admission_status"] == "WATCHING"
    assert second["total_added"] == 0
    assert second["duplicates"] == ["600001.SH"]

    with tracking_session() as db:
        row = db.query(tracking.HorsebackTrack).one()
        assert row.structure_date == date(2026, 8, 28)
        assert row.pool_date == date(2026, 8, 31)
        assert float(row.entry_price) == 10


def test_daily_update_uses_post_pool_dates_and_completes_at_track_days(tracking_session):
    _seed_run(tracking_session)
    tracking.sync_completed_run("run-track-1")
    with tracking_session() as db:
        row = db.query(tracking.HorsebackTrack).one()
        row.track_days = 2
        db.add_all([
            StockDailyKline(
                id=101,
                ts_code="600001.SH",
                trade_date=date(2026, 9, 1),
                open=10,
                high=11.2,
                low=9.9,
                close=11,
                pct_chg=10,
            ),
            StockDailyKline(
                id=102,
                ts_code="600001.SH",
                trade_date=date(2026, 9, 2),
                open=11,
                high=11.1,
                low=10.4,
                close=10.5,
                pct_chg=-4.5455,
            ),
        ])
        db.commit()

    result = tracking.daily_update()
    repeated = tracking.daily_update()

    assert result["total_updated"] == 1
    assert result["total_completed"] == 1
    assert result["total_errors"] == 0
    assert repeated["total_updated"] == 0

    payload = tracking.list_tracks(status="completed")
    assert payload["total"] == 1
    assert payload["summary"]["completed_samples"] == 1
    assert payload["summary"]["completed_win_rate"] == 100.0
    assert payload["summary"]["completed_by_admission"]["WATCHING"] == {
        "samples": 1,
        "avg_return": 5.0,
        "win_rate": 100.0,
    }
    row = payload["rows"][0]
    assert row["latest_day"] == 2
    assert row["latest_return_pct"] == 5.0
    assert row["max_return_pct"] == 10.0
    assert row["max_drawdown_pct"] == pytest.approx(-4.5455)
    assert [daily["day_n"] for daily in row["daily"]] == [1, 2]


def test_replay_run_cannot_enter_live_tracking(tracking_session):
    _seed_run(tracking_session)
    with tracking_session() as db:
        run = db.query(HorsebackRun).one()
        run.mode = "replay"
        db.commit()

    with pytest.raises(tracking.TrackingRunUnsupported, match="replay"):
        tracking.sync_completed_run("run-track-1")

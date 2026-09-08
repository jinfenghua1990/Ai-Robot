from datetime import datetime

from collectors import scheduler, scheduler_jobs
from services import watchlist_signal_runner
from collectors.scheduler_jobs import (
    _is_before_a_share_daily_close,
    _is_before_a_share_postmarket_ready,
    _has_today_data,
    _prioritize_orderbook_codes,
)


def test_orderbook_pool_keeps_positions_first_and_caps_size():
    selected = _prioritize_orderbook_codes(
        [
            ["600000", "000001", "BAD"],
            ["000001", "300001", "600000"],
            ["688001"],
        ],
        limit=3,
    )

    assert selected == ["600000", "000001", "300001"]


def test_orderbook_pool_skips_invalid_codes_and_deduplicates():
    selected = _prioritize_orderbook_codes(
        [[None, "00700", "700", " 000001 ", "000001"], ["300750"]],
        limit=80,
    )

    assert selected == ["000001", "300750"]


def test_daily_backfill_waits_for_a_share_close():
    assert _is_before_a_share_daily_close(datetime(2026, 8, 12, 9, 20))
    assert _is_before_a_share_daily_close(datetime(2026, 8, 12, 11, 45))
    assert _is_before_a_share_daily_close(datetime(2026, 8, 12, 15, 9))
    assert not _is_before_a_share_daily_close(datetime(2026, 8, 12, 15, 10))
    assert not _is_before_a_share_daily_close(datetime(2026, 8, 15, 10, 0))


def test_startup_backfill_waits_for_postmarket_handoff():
    assert _is_before_a_share_postmarket_ready(datetime(2026, 8, 12, 15, 10))
    assert _is_before_a_share_postmarket_ready(datetime(2026, 8, 12, 15, 29))
    assert not _is_before_a_share_postmarket_ready(datetime(2026, 8, 12, 15, 30))
    assert not _is_before_a_share_postmarket_ready(datetime(2026, 8, 15, 10, 0))


def test_daily_data_requires_kline_after_flows_are_ready(monkeypatch):
    monkeypatch.setattr(
        "collectors.scheduler_jobs._today_daily_data_counts",
        lambda: (48, 5882, 0),
    )

    assert not _has_today_data()


def test_daily_pipeline_skips_overlapping_trigger(monkeypatch):
    calls = []

    monkeypatch.setattr(scheduler, "_collect_and_analyze_locked", lambda: calls.append(True) or True)
    assert scheduler._daily_pipeline_lock.acquire(blocking=False)
    try:
        assert not scheduler._collect_and_analyze()
    finally:
        scheduler._daily_pipeline_lock.release()

    assert scheduler._collect_and_analyze()
    assert calls == [True]


def test_watchlist_signal_compute_skips_overlapping_trigger(monkeypatch):
    calls = []

    monkeypatch.setattr(
        watchlist_signal_runner,
        "_compute_for_date_locked",
        lambda target_date: calls.append(target_date) or True,
    )
    assert watchlist_signal_runner._COMPUTE_LOCK.acquire(blocking=False)
    try:
        assert not watchlist_signal_runner.compute_for_date("2026-08-12")
    finally:
        watchlist_signal_runner._COMPUTE_LOCK.release()

    assert watchlist_signal_runner.compute_for_date("2026-08-12")
    assert calls == ["2026-08-12"]

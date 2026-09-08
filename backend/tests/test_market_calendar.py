from datetime import datetime
from zoneinfo import ZoneInfo

from market_quant.calendar import latest_completed_session
from collectors import scheduler_jobs


def test_us_friday_close_is_not_skipped_on_saturday_beijing_time():
    now = datetime(2026, 8, 8, 5, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert latest_completed_session("US", now).isoformat() == "2026-08-07"


def test_us_session_waits_for_provider_delay_after_standard_time_close():
    too_early = datetime(2026, 12, 12, 5, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    ready = datetime(2026, 12, 12, 6, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert latest_completed_session("US", too_early).isoformat() == "2026-12-10"
    assert latest_completed_session("US", ready).isoformat() == "2026-12-11"


def test_market_backfill_targets_prioritize_stale_symbols(monkeypatch):
    from market_quant import history

    monkeypatch.setattr(history, "history_status", lambda _market, _members: {
        "items": {
            "CURRENT": {"rows": 30, "latest": "2026-08-07"},
            "STALE": {"rows": 1260, "latest": "2026-08-06"},
        },
    })

    targets = scheduler_jobs._market_backfill_targets(
        "US", ["CURRENT", "STALE", "MISSING"], 2,
        latest_completed_session(
            "US", datetime(2026, 8, 8, 5, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        ),
    )

    assert targets == ["MISSING", "STALE"]

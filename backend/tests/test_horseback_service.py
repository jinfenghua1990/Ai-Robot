from datetime import date, datetime, timedelta
from types import SimpleNamespace

from horseback.scoring import apply_realtime_entry_gate
from horseback.service import (
    MODE_HISTORICAL_LIVE,
    MODE_LEGACY_REPLAY,
    MODE_LIVE,
    _apply_candidate_limit,
    _gate_context,
    _has_required_daily_coverage,
    _quote_coverage,
    _run_mode,
    _uses_realtime_confirmation,
)


def test_scan_limit_zero_keeps_all_eligible_candidates():
    candidates = [{"ts_code": f"60000{index}.SH"} for index in range(3)]

    assert _apply_candidate_limit(candidates, 0) == candidates
    assert _apply_candidate_limit(candidates, 2) == candidates[:2]


def test_past_date_uses_v115_historical_structure_with_current_realtime_confirmation():
    today = date(2026, 8, 31)

    assert _run_mode(None, today) == MODE_LIVE
    assert _run_mode(today, today) == MODE_LIVE
    assert _run_mode(date(2026, 8, 28), today) == MODE_HISTORICAL_LIVE
    assert _uses_realtime_confirmation(MODE_HISTORICAL_LIVE)
    assert not _uses_realtime_confirmation(MODE_LEGACY_REPLAY)


def test_daily_coverage_requires_95_percent_of_previous_complete_day():
    assert _has_required_daily_coverage(95, 100)
    assert not _has_required_daily_coverage(94, 100)
    assert not _has_required_daily_coverage(0, 100)
    assert _has_required_daily_coverage(1, 0)


def test_quote_coverage_counts_only_requested_symbols_with_quotes():
    processed, missing = _quote_coverage(
        ["600000.SH", "000001.SZ", "600519.SH"],
        {"600000.SH": {}, "600519.SH": {}, "EXTRA.SH": {}},
    )

    assert (processed, missing) == (2, 1)


def test_post_close_gate_uses_previous_day_as_ma5_cross_baseline():
    today = date(2026, 8, 28)
    closes = [9.0] * 70 + [10.5, 10.0, 10.0, 10.0, 10.0, 10.4]
    bars = [
        {"date": today - timedelta(days=len(closes) - index - 1), "close": close, "volume": 100.0}
        for index, close in enumerate(closes)
    ]
    row = SimpleNamespace(
        status="NOT_SELECTED",
        structure_eligible=True,
        close=10.4,
        ma5=10.08,
        suggested_buy=11.0,
        stop_loss=9.0,
    )

    context = _gate_context(row, bars, today, datetime(2026, 8, 28, 17, 0))
    gated = apply_realtime_entry_gate(
        context,
        {"price": 10.4, "change_pct": 3.1, "volume": 150.0, "at": "2026-08-28 17:00:00"},
        datetime(2026, 8, 28, 17, 0),
    )

    assert context["close"] == 10.0
    assert context["ma5"] == 10.1
    assert context["last_four_closes"] == [10.0, 10.0, 10.0, 10.0]
    assert gated["first_ma5_break"] is True
    assert gated["status"] == "SELECTED"

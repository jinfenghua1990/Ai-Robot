from contextlib import contextmanager
from datetime import date, datetime

import pytest
from fastapi import HTTPException

from api import quality
from api.quality import _check_config_availability, _check_realtime_freshness, _resolve_trade_date


class _ScalarQuery:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self.value


class _FakeDb:
    def __init__(self, value):
        self.value = value

    def query(self, *_args):
        return _ScalarQuery(self.value)


class _Model:
    trade_date = object()


def test_static_strategy_config_does_not_expire_with_age():
    status = _check_config_availability(3)

    assert status["status"] == "fresh"
    assert status["delay_days"] == 0


def test_missing_strategy_config_is_reported_as_error():
    status = _check_config_availability(0)

    assert status["status"] == "error"


def test_default_quality_date_uses_latest_available_snapshot():
    latest = date(2026, 8, 7)

    assert _resolve_trade_date(_FakeDb(latest), None, _Model) == latest


def test_invalid_quality_date_returns_bad_request():
    with pytest.raises(HTTPException) as exc_info:
        _resolve_trade_date(_FakeDb(None), "2026/08/07", _Model)

    assert exc_info.value.status_code == 400


def test_missing_review_preserves_not_found_status(monkeypatch):
    @contextmanager
    def fake_session():
        yield _FakeDb(None)

    monkeypatch.setattr(quality, "get_db_session", fake_session)

    with pytest.raises(HTTPException) as exc_info:
        quality.handle_review(999, "approve")

    assert exc_info.value.status_code == 404


def test_realtime_freshness_uses_last_trading_day_on_weekend():
    status = _check_realtime_freshness(
        data_date=date(2026, 8, 7),
        snapshot_time=datetime(2026, 8, 7, 15, 5),
        expected_date=date(2026, 8, 7),
        now=datetime(2026, 8, 9, 18, 0),
        is_trading_hours=False,
    )

    assert status["status"] == "fresh"
    assert status["expected_date"] == "2026-08-07"

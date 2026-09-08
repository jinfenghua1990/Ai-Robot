from datetime import date, datetime

from collectors import scheduler
from collectors import scheduler_jobs
from horseback import service


class _FixedShanghaiDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 8, 28, 10, 5, tzinfo=tz)


def _patch_failed_run_context(monkeypatch, attempt_count, starts):
    monkeypatch.setattr(scheduler, "datetime", _FixedShanghaiDatetime)
    monkeypatch.setattr(scheduler_jobs, "_is_trading_day", lambda _day: True)
    monkeypatch.setattr(service, "recover_orphaned_runs", lambda: 0)
    monkeypatch.setattr(
        service,
        "get_latest_run",
        lambda include_results=False: {
            "id": "failed-run",
            "requested_end_date": date(2026, 8, 28).isoformat(),
            "status": "FAILED",
        },
    )
    monkeypatch.setattr(service, "get_today_run_attempt_count", lambda _day: attempt_count)
    monkeypatch.setattr(service, "start_run", lambda **kwargs: starts.append(kwargs) or {"id": "retry-run"})


def test_refresh_job_retries_one_failed_today_run(monkeypatch):
    starts = []
    _patch_failed_run_context(monkeypatch, attempt_count=1, starts=starts)

    scheduler._horseback_refresh_job()

    assert len(starts) == 1
    assert starts[0]["requested_end_date"] is None
    assert starts[0]["min_score"] == 75


def test_refresh_job_does_not_exceed_one_automatic_retry(monkeypatch):
    starts = []
    _patch_failed_run_context(monkeypatch, attempt_count=2, starts=starts)

    scheduler._horseback_refresh_job()

    assert starts == []

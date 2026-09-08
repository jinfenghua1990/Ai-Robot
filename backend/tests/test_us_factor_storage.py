from datetime import date

from sqlalchemy import Float, UniqueConstraint
from sqlalchemy.dialects import postgresql

from us_quant import factor_storage
from us_quant.collector import _required_fetch_days
from us_quant.repository import USFactorScore


def test_us_factor_table_has_natural_unique_key_and_wide_float_value():
    keys = {
        tuple(column.name for column in constraint.columns)
        for constraint in USFactorScore.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("symbol", "trade_date", "factor_name") in keys
    assert isinstance(USFactorScore.__table__.c.factor_value.type, Float)


def test_factor_storage_uses_one_batch_upsert_and_filters_nonfinite(monkeypatch):
    monkeypatch.setattr(
        factor_storage,
        "FACTOR_REGISTRY",
        {
            "good": {"category": "test", "params": ["closes"]},
            "bad": {"category": "test", "params": []},
        },
    )
    monkeypatch.setattr(
        factor_storage,
        "compute_all_factors",
        lambda **_kwargs: {"good": 12_609_564_403_600.115, "bad": float("inf")},
    )

    class Session:
        def __init__(self):
            self.statements = []
            self.commits = 0

        def execute(self, statement):
            self.statements.append(statement)

        def commit(self):
            self.commits += 1

        def rollback(self):
            raise AssertionError("unexpected rollback")

    session = Session()
    stored = factor_storage.store_factors_for_symbol(
        "AAPL", date(2026, 8, 7),
        closes=[1.0] * 30,
        highs=[1.1] * 30,
        lows=[0.9] * 30,
        opens=[1.0] * 30,
        volumes=[100.0] * 30,
        db_session=session,
    )

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert stored == 1
    assert session.commits == 1
    assert len(session.statements) == 1
    assert "ON CONFLICT (symbol, trade_date, factor_name) DO UPDATE" in sql


def test_us_collector_backfills_full_history_before_incremental_updates():
    target = date(2026, 8, 7)

    assert _required_fetch_days(20, date(2026, 8, 6), target, False) == 365
    assert _required_fetch_days(252, date(2026, 8, 6), target, False) == 8
    assert _required_fetch_days(365, target, target, True) == 365

from datetime import date, timedelta
from types import SimpleNamespace

from market_quant.outcomes import calculate_signal_outcome


def _bar(day, close, high=None, low=None):
    return SimpleNamespace(
        trade_date=day,
        close=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
    )


def test_signal_outcome_uses_future_sessions_and_keeps_unmatured_horizons_missing():
    start = date(2026, 8, 3)
    bars = [
        _bar(start, 100, 101, 99),
        _bar(start + timedelta(days=1), 104, 105, 102),
        _bar(start + timedelta(days=2), 102, 106, 100),
        _bar(start + timedelta(days=3), 110, 111, 101),
    ]

    outcome = calculate_signal_outcome(start, bars)

    assert round(outcome["return_1d"], 4) == 0.04
    assert round(outcome["return_3d"], 4) == 0.1
    assert outcome["return_5d"] is None
    assert round(outcome["max_profit"], 4) == 0.11
    assert round(outcome["max_loss"], 4) == 0.0
    # Drawdown starts after the saved signal close and follows the rolling high.
    assert round(outcome["max_drawdown"], 4) == round(101 / 111 - 1, 4)


def test_signal_outcome_never_uses_same_day_as_one_day_return():
    signal_day = date(2026, 8, 3)
    outcome = calculate_signal_outcome(signal_day, [_bar(signal_day, 100)])

    assert outcome["return_1d"] is None
    assert outcome["max_profit"] is None
    assert outcome["max_loss"] is None
    assert outcome["max_drawdown"] is None

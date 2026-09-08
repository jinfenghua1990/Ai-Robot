from services.medium_term_strategy import _evaluate_bars


def _bars(closes):
    return [{'close': close} for close in closes]


def test_medium_term_requires_trend_structure_and_sufficient_history():
    assert _evaluate_bars(_bars([10.0] * 79)) is None

    rising = [10 + index * 0.08 for index in range(80)]
    result = _evaluate_bars(_bars(rising), sector_change_pct=1.2)

    assert result['eligible'] is True
    assert result['gates'] == {
        'structure': True,
        'ma60_slope': True,
        'momentum_20d': True,
        'drawdown_20d': True,
    }


def test_medium_term_rejects_overheated_or_broken_trend():
    overheated = [10 + index * 0.6 for index in range(80)]
    result = _evaluate_bars(_bars(overheated), sector_change_pct=1.2)
    assert result['eligible'] is False
    assert result['gates']['momentum_20d'] is False

    broken = [20 - index * 0.08 for index in range(80)]
    result = _evaluate_bars(_bars(broken), sector_change_pct=-1)
    assert result['eligible'] is False
    assert result['gates']['structure'] is False

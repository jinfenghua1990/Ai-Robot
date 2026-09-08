from api.stock_tracker import _summarize_returns


def test_tracker_return_summary_has_clear_equal_weight_metrics():
    summary = _summarize_returns([10, -5, 0])

    assert summary == {
        "count": 3,
        "positive_count": 1,
        "negative_count": 1,
        "flat_count": 1,
        "average_return_pct": 1.67,
        "win_rate_pct": 33.33,
    }


def test_tracker_return_summary_handles_empty_pool():
    assert _summarize_returns([]) == {
        "count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "flat_count": 0,
        "average_return_pct": None,
        "win_rate_pct": None,
    }

from datetime import date, datetime, timedelta

import pytest

from horseback.scoring import (
    ScoreMetrics,
    ScoreOptions,
    apply_realtime_entry_gate,
    evaluate_candidate,
    is_main_board_candidate,
    score_metrics,
)


def _bars(count=80, limit_days_ago=5, future_count=0):
    start = date(2026, 1, 2)
    rows = []
    for index in range(count + future_count):
        close = 10 + index * 0.03
        pct_chg = 1.0
        if index == count - 1 - limit_days_ago:
            pct_chg = 10.0
            close *= 1.1
        if index >= count:
            close = 1.0
            pct_chg = -90.0
        rows.append({
            "date": start + timedelta(days=index),
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": 1_000 if index < count - 5 else 700,
            "pct_chg": pct_chg,
        })
    return rows


def test_v115_score_weights_sum_to_100_when_every_rule_passes():
    score, components = score_metrics(ScoreMetrics(
        ma20=12.0,
        ma60=11.0,
        ma60_prior=10.9,
        close=12.0,
        pre_limit_rise_pct=20.0,
        pullback_pct=-10.0,
        volume_ratio_5_5=0.8,
        ma_convergence_pct=5.0,
        support_distance_pct=0.0,
        close_strength=True,
    ))

    assert score == 100
    assert sum(item["points"] for item in components) == 100


def test_historical_cutoff_ignores_future_bars():
    base = _bars()
    with_future = _bars(future_count=5)
    cutoff = base[-1]["date"]

    expected = evaluate_candidate("600000.SH", "浦发银行", base, cutoff, ScoreOptions(min_score=50))
    actual = evaluate_candidate("600000.SH", "浦发银行", with_future, cutoff, ScoreOptions(min_score=50))

    assert actual["as_of_date"] == cutoff.isoformat()
    assert actual["kline_count"] == len(base)
    assert actual["score"] == expected["score"]
    assert actual["close"] == expected["close"]
    assert actual["suggested_buy"] == expected["suggested_buy"]


def test_selection_requires_last_limit_inside_configured_window():
    eligible = evaluate_candidate(
        "600000.SH", "浦发银行", _bars(limit_days_ago=5), date(2026, 3, 22), ScoreOptions(min_score=50)
    )
    too_recent = evaluate_candidate(
        "600000.SH", "浦发银行", _bars(limit_days_ago=2), date(2026, 3, 22), ScoreOptions(min_score=50)
    )

    assert eligible["days_since_limit"] == 5
    assert too_recent["status"] == "NOT_SELECTED"
    assert any("3–12" in reason for reason in too_recent["hard_failures"])


def test_v115_requires_strict_consolidation_bounds():
    with pytest.raises(ValueError, match="必须小于"):
        ScoreOptions(min_consolidation_days=2, max_consolidation_days=2)


def test_insufficient_history_is_explicitly_invalid():
    result = evaluate_candidate(
        "600000.SH", "浦发银行", _bars(count=62, limit_days_ago=5), date(2026, 3, 22), ScoreOptions()
    )

    assert result["status"] == "INVALID"
    assert result["score"] is None
    assert result["kline_count"] == 62
    assert "至少 63 根" in result["hard_failures"][0]


@pytest.mark.parametrize("symbol,name", [
    ("000001.SZ", "平安银行"),
    ("002594.SZ", "比亚迪"),
    ("003000.SZ", "劲仔食品"),
    ("600000.SH", "浦发银行"),
    ("605499.SH", "东鹏饮料"),
])
def test_main_board_filter_accepts_only_a_share_main_board(symbol, name):
    assert is_main_board_candidate(symbol, name)


@pytest.mark.parametrize("symbol,name", [
    ("300750.SZ", "宁德时代"),
    ("688981.SH", "中芯国际"),
    ("830799.BJ", "艾融软件"),
    ("600000.SH", "*ST浦发"),
    ("600000.SH", "退市浦发"),
])
def test_main_board_filter_rejects_other_boards_and_risk_names(symbol, name):
    assert not is_main_board_candidate(symbol, name)


def test_trigger_and_stop_match_v115_formula():
    rows = _bars(limit_days_ago=5)
    result = evaluate_candidate(
        "600000.SH", "浦发银行", rows, rows[-1]["date"], ScoreOptions(min_score=50)
    )
    latest = rows[-5:]

    assert result["suggested_buy"] == pytest.approx(max(row["high"] for row in latest), abs=1e-4)
    assert result["stop_loss"] == pytest.approx(
        min(result["ma20"] * 0.97, min(row["low"] for row in latest) * 0.99),
        abs=1e-4,
    )


def _structure_result():
    return {
        "status": "SELECTED",
        "structure_eligible": True,
        "close": 10.0,
        "ma5": 10.2,
        "last_four_closes": [9.8, 10.0, 10.1, 10.2],
        "avg_daily_volume5": 100.0,
        "suggested_buy": 11.5,
        "stop_loss": 9.0,
    }


def test_v115_live_gate_requires_all_three_realtime_conditions():
    result = apply_realtime_entry_gate(
        _structure_result(),
        {"price": 12.0, "change_pct": 3.01, "volume": 30.0, "open": 11.0, "high": 12.1, "low": 10.9, "at": "2026-08-28 10:30:00"},
        datetime(2026, 8, 28, 10, 30),
    )

    assert result["status"] == "SELECTED"
    assert result["realtime_volume_ratio"] == pytest.approx(1.2)
    assert result["first_ma5_break"] is True
    assert "形态达标" in result["realtime_gate"]


def test_missing_realtime_quote_keeps_structure_candidate_in_observation_pool():
    result = apply_realtime_entry_gate(_structure_result(), None, datetime(2026, 8, 28, 10, 30))

    assert result["status"] == "NOT_SELECTED"
    assert result["realtime_gate"] == "实时行情未返回"

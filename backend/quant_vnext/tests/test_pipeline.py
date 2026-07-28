from datetime import date, timedelta

import pytest

from quant_vnext.contracts import DailyBar, MarketContext
from quant_vnext.pipeline import QuantPipeline
from quant_vnext.research import evaluate_forward_returns
from quant_vnext.validation import factor_ic, rank_ic
from quant_vnext.snapshot_json import dumps
from quant_vnext.backtest import walk_forward


def bars(code: str, start: float, growth: float, days: int = 80):
    result = []
    for i in range(days):
        close = start * (1 + growth) ** i
        result.append(DailyBar(code, date(2026, 1, 1) + timedelta(days=i), close * .99, close * 1.01, close * .98, close, 1000 + i * 10, 1_000_000 + i * 1000, sector="technology"))
    return result


def test_pipeline_is_deterministic_and_date_bounded():
    target = date(2026, 3, 21)
    history = {"000001.SZ": bars("000001.SZ", 10, .01)}
    pipeline = QuantPipeline()
    result = pipeline.run(history, target, MarketContext(target, .55))
    assert result
    assert all(item.trade_date == target for item in result)
    assert all(item.trading_state in {"WATCH", "READY", "TRIGGERED", "HOLD", "NO_CHASE", "INVALID"} for item in result)


def test_forward_return_horizons():
    result = evaluate_forward_returns([[100, 101, 102, 103, 104, 105]])
    assert result["1"]["mean"] == .01
    assert result["5"]["mean"] == .05
    assert result["20"]["count"] == 0


def test_ic_and_rank_ic_are_positive_for_monotonic_data():
    factor = [1, 2, 3, 4, 5]
    returns = [0.01, 0.02, 0.03, 0.04, 0.05]
    assert factor_ic(factor, returns) == 1.0
    assert rank_ic(factor, returns) == pytest.approx(1.0)


def test_snapshot_serializes_as_json():
    target = date(2026, 3, 21)
    result = QuantPipeline().run({"000001.SZ": bars("000001.SZ", 10, .01)}, target, MarketContext(target, .55))[0]
    payload = dumps(result)
    assert '"ts_code": "000001.SZ"' in payload
    assert '"trade_date": "2026-03-21"' in payload


def test_walk_forward_has_no_future_signal_requirement():
    history = {"000001.SZ": bars("000001.SZ", 10, .01)}
    dates = [item.trade_date for item in history["000001.SZ"]]
    result = walk_forward(history, dates[-5:], horizons=(1, 3))
    assert result["sample_count"] > 0
    assert result["horizons"]["1"]["count"] > 0

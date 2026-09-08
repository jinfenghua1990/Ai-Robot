from datetime import date, timedelta

from quant_vnext.alpha158_engine import Alpha158ResearchEngine
from quant_vnext.contracts import DailyBar


def test_alpha158_engine_returns_research_values_only():
    bars = []
    for index in range(40):
        close = 10.0 + index * 0.2
        bars.append(DailyBar("000001.SZ", date(2026, 1, 1) + timedelta(days=index), close, close + 0.2, close - 0.2, close, 1000 + index * 10))
    values = Alpha158ResearchEngine().calculate({"000001.SZ": bars}, bars[-1].trade_date)
    assert len(values) == 13
    assert all(item.name.startswith("qlib_") and item.valid for item in values)


def test_alpha158_engine_date_bounds_history():
    bars = [DailyBar("000001.SZ", date(2026, 1, 1) + timedelta(days=index), 10, 11, 9, 10, 1000) for index in range(25)]
    values = Alpha158ResearchEngine().calculate({"000001.SZ": bars}, bars[-2].trade_date)
    assert values
    assert all(item.trade_date == bars[-2].trade_date for item in values)

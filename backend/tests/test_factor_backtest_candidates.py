import asyncio

from api import factor_backtest
from us_quant.data_provider import _range_to_days


def test_us_factor_backtest_uses_market_universe_members(monkeypatch):
    monkeypatch.setattr("us_quant.universe.get_universe_members", lambda code: {
        "CORE_A_300": ["AAPL"], "CORE_B_500": ["MSFT"],
    }.get(code, []))
    assert asyncio.run(factor_backtest._us_symbols(40)) == ["AAPL", "MSFT"]


def test_data_provider_supports_long_us_history_ranges():
    assert _range_to_days("1y") == 252
    assert _range_to_days("2y") == 504

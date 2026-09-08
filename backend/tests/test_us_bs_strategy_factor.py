import asyncio

from api.us_quant import api_factors
from us_quant.bs_strategy import STRATEGY_META, strong_bs_factor
from us_quant.factors import FACTOR_REGISTRY


def test_bs_strategy_is_registered_as_standalone_factor():
    meta = FACTOR_REGISTRY[STRATEGY_META["key"]]
    assert meta["kind"] == "strategy"
    assert meta["route"] == "/us-bs-strategy"
    assert meta["category"] == "独立策略因子"


def test_factor_library_separates_strategy_from_regular_factors():
    payload = asyncio.run(api_factors())
    assert any(item["key"] == STRATEGY_META["key"] for item in payload["strategies"])
    assert all(item["key"] != STRATEGY_META["key"] for item in payload["factors"])


def test_bs_factor_returns_neutral_when_history_is_insufficient():
    values = [10.0] * 30
    assert strong_bs_factor(values, values, values, values, [1_000_000.0] * 30) is None

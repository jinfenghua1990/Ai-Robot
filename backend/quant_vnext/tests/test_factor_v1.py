from datetime import date, timedelta

from quant_vnext.contracts import DailyBar, DimensionScore, MarketContext
from quant_vnext.market_regime import MarketRegimeEngine
from quant_vnext.pipeline import QuantPipeline
from quant_vnext.registry import default_registry
from quant_vnext.scoring import CrossSectionScorer


def _bars(code: str, growth: float, sector: str = "科技"):
    result = []
    for index in range(80):
        close = 10 * (1 + growth) ** index
        result.append(DailyBar(
            code,
            date(2026, 1, 1) + timedelta(days=index),
            close * 0.99,
            close * 1.01,
            close * 0.98,
            close,
            1000 + index * 10,
            100000 + index * 100,
            sector=sector,
        ))
    return result


def test_registry_contains_seven_factor_groups():
    categories = {item.category for item in default_registry().production()}
    assert categories == {"market", "sector", "momentum", "trend", "volume_price", "position", "risk"}
    assert len(default_registry().production()) >= 30


def test_market_regime_changes_weights_and_new_position_permission():
    engine = MarketRegimeEngine()
    strong = engine.assess(MarketContext(date(2026, 3, 21), 0.80, 30, 5, market_return_20d=0.08))
    weak = engine.assess(MarketContext(date(2026, 3, 21), 0.20, 3, 30, market_return_20d=-0.08))
    assert strong.state == "STRONG"
    assert strong.allow_new_positions is True
    assert strong.weights["trend"] > strong.weights["position"]
    assert weak.state == "WEAK"
    assert weak.allow_new_positions is False
    assert weak.weights["risk_penalty"] > strong.weights["risk_penalty"]


def test_pipeline_exposes_all_factor_groups_and_market_state():
    target = date(2026, 3, 21)
    result = QuantPipeline().run(
        {"000001.SZ": _bars("000001.SZ", 0.01)},
        target,
        MarketContext(target, 0.55),
    )[0]
    assert set(result.dimensions) == {"market", "sector", "strength", "trend", "volume_price", "position", "risk"}
    assert result.market_state == "RANGE"
    assert set(result.factor_weights) == {"market", "sector", "strength", "trend", "volume_price", "position", "risk_penalty"}


def test_score_formula_uses_risk_as_penalty():
    dimensions = {
        name: DimensionScore(name, 80.0, True, [])
        for name in ("market", "sector", "strength", "trend", "volume_price", "position", "risk")
    }
    assert CrossSectionScorer.factor_score(dimensions) == 75.0

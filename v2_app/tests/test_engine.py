from datetime import date, timedelta

from v2_app.data import is_st
from v2_app.domain import Bar, DimensionScore, MarketContext
from v2_app.engine import V2Engine
from v2_app.factors import BASE_FACTOR_NAMES, FACTOR_CATALOG, calculate_raw


def _dimensions(score: float = 80.0, risk: float = 80.0):
    engine = V2Engine()
    result = {
        key: DimensionScore(key, key, score, True, [f"{key}_factor"])
        for key in engine.all_dimensions
    }
    result["risk"] = DimensionScore("risk", "风险质量", risk, True, ["risk_factor"])
    return result


def test_resonance_counts_only_six_opportunity_dimensions():
    engine = V2Engine()
    dimensions = _dimensions()
    resonance = engine._resonance(dimensions)

    assert resonance["count"] == 6
    assert "risk" not in resonance["dimensions"]
    assert resonance["eligible"] is True


def test_risk_is_a_gate_and_never_adds_opportunity_resonance():
    engine = V2Engine()
    dimensions = _dimensions(risk=20)
    resonance = engine._resonance(dimensions)

    assert resonance["count"] == 6
    assert resonance["eligible"] is False
    assert "risk" in resonance["failed"]


def test_weak_market_blocks_new_entry_even_when_stock_evidence_is_ready():
    engine = V2Engine()
    market = MarketContext(
        date(2026, 7, 28), 0.3, 20, 30, -0.1, "偏弱", "WEAK", "test"
    )
    dimensions = _dimensions()
    resonance = {"eligible": True}

    assert engine._trading_state(
        dimensions, resonance, [{"key": "baihu"}], {"high_position_risk": 0, "return_20d": 0.1}, market
    ) == "NO_CHASE"


def test_missing_dimension_is_not_filled_with_default_fifty():
    engine = V2Engine()
    dimensions = _dimensions()
    dimensions["sector"] = DimensionScore("sector", "板块主线", None, False, [])
    dimensions["risk"] = DimensionScore("risk", "风险质量", None, False, [])

    assert engine._factor_score(dimensions) == 80.0


def test_st_names_are_filtered_case_insensitively():
    assert is_st("ST测试")
    assert is_st("*st 测试")
    assert not is_st("平安银行")


def test_alpha158_catalog_is_candidate_and_not_in_operational_base_set():
    assert len(FACTOR_CATALOG) == 189
    assert len(BASE_FACTOR_NAMES) == 31
    candidates = [item for item in FACTOR_CATALOG if item.status == "candidate"]
    assert len(candidates) == 158
    assert all(item.production is False for item in candidates)


def test_candidate_formulas_are_lazy_for_operational_calculation():
    bars = [
        Bar(
            code="000001.SZ",
            trade_date=date(2026, 4, 1) + timedelta(days=index),
            open=10 + index * 0.01,
            high=10.2 + index * 0.01,
            low=9.8 + index * 0.01,
            close=10.1 + index * 0.01,
            volume=100000 + index * 100,
            amount=(100000 + index * 100) * (10.1 + index * 0.01),
            pct_chg=0.001,
            name="测试股票",
            sector="测试行业",
        )
        for index in range(80)
    ]
    history = {"000001.SZ": bars}
    market = MarketContext(date(2026, 6, 19), 0.5, 10, 10, 0.05, "震荡", "RANGE", "test")
    base = calculate_raw(history, market, {}, include_candidate=False)["000001.SZ"]
    full = calculate_raw(history, market, {}, include_candidate=True)["000001.SZ"]

    assert not any(name.startswith("qlib_alpha158_") for name in base)
    assert len([name for name in full if name.startswith("qlib_alpha158_")]) == 158

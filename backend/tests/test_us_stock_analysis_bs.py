from api.us_stock_analysis import _bs_signals


def _series(length=60, target=False):
    opens = [100.0] * length
    closes = [100.0] * length
    if target:
        closes[24] = 108.0
    volumes = [1_000_000.0] * length
    ma5 = [9.0] * 20 + [11.0] * (length - 20)
    ma20 = [10.0] * length
    ma60 = [9.0] * length
    k = [40.0] * 20 + [60.0] * (length - 20)
    d = [50.0] * length
    macd = {"hist": [0.1] * length, "dif": [0.1] * length}
    rsi = [60.0] * length
    return opens, closes, volumes, ma5, ma20, ma60, macd, {"k": k, "d": d}, rsi


def test_bs_v2_requires_positive_macd_confirmation():
    args = list(_series())
    args[6] = {"hist": [-0.1] * len(args[0]), "dif": [0.1] * len(args[0])}
    assert _bs_signals(*args) == []


def test_bs_v2_rejects_low_liquidity_or_weak_long_term_trend():
    low_liquidity = list(_series())
    low_liquidity[2] = [1_000.0] * len(low_liquidity[0])
    assert _bs_signals(*low_liquidity) == []

    below_ma60 = list(_series())
    below_ma60[5] = [101.0] * len(below_ma60[0])
    assert _bs_signals(*below_ma60) == []


def test_bs_v2_takes_profit_at_eight_percent():
    signals = _bs_signals(*_series(target=True))
    assert [(signal["i"], signal["side"]) for signal in signals] == [(20, "B"), (24, "S")]
    assert "+8%" in signals[-1]["reason"]


def test_bs_v2_exits_after_thirty_sessions():
    signals = _bs_signals(*_series())
    assert [(signal["i"], signal["side"]) for signal in signals] == [(20, "B"), (50, "S")]
    assert "30" in signals[-1]["reason"]

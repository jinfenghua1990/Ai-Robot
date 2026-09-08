from market_quant import providers
from market_quant.history import _history_is_current
from datetime import date


def test_provider_clean_rows_drops_invalid_and_deduplicates():
    rows = providers._clean_rows([
        {"date": "2026-07-30", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10},
        {"date": "2026-07-30", "open": 1, "high": 2, "low": 1, "close": 1.6, "volume": 11},
        {"date": "not-a-date", "close": 2},
        {"date": "2026-07-31", "close": -1},
    ])
    assert len(rows) == 1
    assert rows[0]["close"] == 1.6
    assert rows[0]["amount"] == 1.6 * 11


def test_us_production_provider_never_calls_synthetic(monkeypatch):
    import us_quant.collector as collector

    monkeypatch.setattr(collector, "_get_source_klines_sina", lambda symbol, days: None)
    monkeypatch.setattr(collector, "_get_source_klines_gstock", lambda symbol, days: None)
    monkeypatch.setattr(collector, "_get_source_akshare", lambda symbol, days: None)
    monkeypatch.setattr(collector, "_get_source_nasdaq", lambda symbol, days: None)
    monkeypatch.setattr(collector, "_get_source_yahoo", lambda symbol, days: None)
    monkeypatch.setattr(providers, "_fetch_yfinance", lambda market, symbol, days: None)
    assert not hasattr(collector, "_get_source_synthetic")

    assert providers.fetch_daily("US", "AAPL", 120) is None


def test_us_production_provider_prefers_direct_sina(monkeypatch):
    import us_quant.collector as collector

    rows = [
        {"date": "2026-08-06", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        {"date": "2026-08-07", "open": 11, "high": 12, "low": 10, "close": 11.5, "volume": 120},
    ]
    monkeypatch.setattr(collector, "_get_source_klines_sina", lambda symbol, days: rows)
    monkeypatch.setattr(
        collector,
        "_get_source_klines_gstock",
        lambda symbol, days: (_ for _ in ()).throw(AssertionError("slower fallback used")),
    )

    source, result = providers.fetch_daily("US", "AAPL", 1260)
    assert source == "sina"
    assert [row["trade_date"] for row in result] == [date(2026, 8, 6), date(2026, 8, 7)]


def test_yfinance_rows_are_real_provider_shape(monkeypatch):
    import sys
    import types
    import pandas as pd

    frame = pd.DataFrame({
        "Open": [10.0, 11.0],
        "High": [12.0, 13.0],
        "Low": [9.0, 10.0],
        "Close": [11.0, 12.0],
        "Adj Close": [11.0, 12.0],
        "Volume": [100, 120],
    }, index=pd.to_datetime(["2026-07-30", "2026-07-31"]))
    calls = {}

    def download(symbol, **kwargs):
        calls["symbol"] = symbol
        calls.update(kwargs)
        return frame

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=download))
    rows = providers._fetch_yfinance("HK", "00700", 120)
    assert calls["symbol"] == "0700.HK"
    assert rows[0]["date"] == "2026-07-30"
    assert rows[-1]["close"] == 12.0


def test_full_history_is_not_treated_as_cache_when_latest_bar_is_stale():
    target = date(2026, 8, 7)

    assert not _history_is_current(1260, date(2026, 8, 6), target, False)
    assert _history_is_current(120, target, target, False)
    assert not _history_is_current(1260, target, target, True)

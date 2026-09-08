import pandas as pd

from research.market_sources.yahoo_adapter import normalize_yahoo_frame, yahoo_symbol


def test_yahoo_symbol_normalization():
    assert yahoo_symbol("700", "hk") == "0700.HK"
    assert yahoo_symbol("AAPL", "us") == "AAPL"


def test_normalize_yahoo_multiindex_frame():
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAPL"]])
    frame = pd.DataFrame([[1, 2, 0.5, 1.5, 100]], index=pd.to_datetime(["2026-01-02"]), columns=columns)
    result = normalize_yahoo_frame(frame, "AAPL")
    assert list(result.columns) == ["symbol", "trade_date", "open", "high", "low", "close", "volume"]
    assert result.iloc[0]["close"] == 1.5

from datetime import date

from market_quant.calendar import is_session
from market_quant.identity import InstrumentIdentity, normalize_symbol, provider_symbol
from market_quant.universe import universe_code


def test_hk_symbols_are_canonical_and_provider_compatible():
    assert normalize_symbol("HK", "700.HK") == "00700"
    assert normalize_symbol("HK", "00700") == "00700"
    assert provider_symbol("HK", "00700") == "0700.HK"
    assert InstrumentIdentity.from_value("HK", "700").exchange == "XHKG"


def test_us_symbols_preserve_share_class_and_market_pools_are_separate():
    assert normalize_symbol("US", "BRK.B") == "BRK.B"
    assert InstrumentIdentity.from_value("US", "BF-B").provider_symbol == "BF-B"
    assert universe_code("US", "CORE") == "US_CORE_A_300"
    assert universe_code("HK", "RESEARCH") == "HK_RESEARCH_500"


def test_weekends_are_not_sessions():
    assert is_session("US", date(2026, 8, 1)) is False
    assert is_session("HK", date(2026, 8, 2)) is False


def test_market_timezone_helpers_return_exchange_aware_time():
    from market_quant.calendar import now_in_market_timezone

    assert now_in_market_timezone("US").tzinfo is not None
    assert now_in_market_timezone("HK").tzinfo is not None


def test_nasdaq_discovery_keeps_common_stock_candidates(monkeypatch):
    import json
    import urllib.request
    from market_quant import universe

    payload = {"data": {"table": {"rows": [
        {"symbol": "AAPL", "name": "Apple Inc. Common Stock", "lastsale": "$200", "marketCap": "1,000"},
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "lastsale": "$500", "marketCap": "2,000"},
        {"symbol": "BAD/W", "name": "Warrant", "lastsale": "$2", "marketCap": "3,000"},
    ]}}}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: Response())
    rows = universe._us_rows_from_nasdaq()
    assert [row["symbol"] for row in rows] == ["AAPL"]


def test_hkex_discovery_keeps_equities_and_excludes_funds(monkeypatch):
    import urllib.request
    import pandas as pd
    from market_quant import universe

    frame = pd.DataFrame([
        {"Stock Code": "700", "Name of Securities": "TENCENT", "Category": "Equity", "Sub-Category": "Equity Securities (Main Board)", "Trading Currency": "HKD"},
        {"Stock Code": "2800", "Name of Securities": "TRACKER FUND", "Category": "Unit Trusts", "Sub-Category": "Exchange Traded Funds", "Trading Currency": "HKD"},
    ])

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"xlsx"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: Response())
    monkeypatch.setattr(pd, "read_excel", lambda *args, **kwargs: frame)
    rows = universe._hk_rows_from_hkex()
    assert [row["symbol"] for row in rows] == ["00700"]


def test_hk_seed_names_override_remote_english_names():
    from market_quant.universe import HK_NAME_OVERRIDES

    assert HK_NAME_OVERRIDES["00700"] == "腾讯控股"
    assert "00005" in HK_NAME_OVERRIDES

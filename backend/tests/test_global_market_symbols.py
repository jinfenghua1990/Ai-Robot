from api.global_market import _to_yahoo_symbol


def test_hong_kong_symbol_keeps_four_digit_exchange_code():
    assert _to_yahoo_symbol("HK", "00700") == "0700.HK"
    assert _to_yahoo_symbol("HK", "700.HK") == "0700.HK"


def test_us_symbol_is_unchanged():
    assert _to_yahoo_symbol("US", "AAPL") == "AAPL"

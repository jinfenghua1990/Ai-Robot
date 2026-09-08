from analyzers.strategy_engine import _normalize_a_share_ts_code


def test_normalize_a_share_ts_code_deduplicates_exchange_suffix():
    assert _normalize_a_share_ts_code('002245.SZ.SZ') == '002245.SZ'
    assert _normalize_a_share_ts_code('600000.SH') == '600000.SH'
    assert _normalize_a_share_ts_code('430047.BJ') == '430047.BJ'


def test_normalize_a_share_ts_code_handles_raw_and_empty_values():
    assert _normalize_a_share_ts_code(' 300750 ') == '300750.SZ'
    assert _normalize_a_share_ts_code('') == ''

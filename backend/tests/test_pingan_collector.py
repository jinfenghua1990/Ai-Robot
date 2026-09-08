from collectors import pingan_collector


def test_quote_collection_stops_after_rate_limit(monkeypatch):
    calls = []

    def rate_limited(*_args, **_kwargs):
        calls.append(1)
        raise RuntimeError("接口调用频率超限。")

    monkeypatch.setattr(pingan_collector, "MARKET_AVAILABLE", True)
    monkeypatch.setattr(pingan_collector, "_market_call_api", rate_limited)

    count = pingan_collector.pingan_collect_quotes(
        ["SH600000", "SH600001", "SH600002", "SH600003"],
        batch_size=2,
    )

    assert count == 0
    assert len(calls) == 1


def test_optional_float_accepts_percent_strings():
    assert pingan_collector._optional_float('-9.66%') == -9.66
    assert pingan_collector._optional_float('null') is None


def test_etf_code_uses_shanghai_mapping_and_standard_ts_code():
    assert pingan_collector._watchlist_code_to_pingan_code('588080') == 'SH588080'
    assert pingan_collector._watchlist_code_to_pingan_code('159915') == 'SZ159915'
    assert pingan_collector._pingan_code_to_ts_code('SH588080') == '588080.SH'


def test_quote_collection_accepts_percent_change_fields(monkeypatch):
    records = []

    class FakeSession:
        def add(self, record):
            records.append(record)

        def commit(self):
            pass

    from contextlib import contextmanager

    @contextmanager
    def fake_session():
        yield FakeSession()

    monkeypatch.setattr(pingan_collector, 'MARKET_AVAILABLE', True)
    monkeypatch.setattr(pingan_collector, 'get_db_session', fake_session)
    monkeypatch.setattr(pingan_collector, '_market_call_api', lambda *_args, **_kwargs: {
        'items': [{'code': 'SH600000', 'name': '浦发银行', 'price': '10.20', 'change': '-0.22',
                   'change_pct': '-2.11%', 'turnover_pct': '1.20%'}]
    })

    assert pingan_collector.pingan_collect_quotes(['SH600000']) == 1
    assert float(records[0].change_pct) == -2.11
    assert float(records[0].turnover_pct) == 1.2

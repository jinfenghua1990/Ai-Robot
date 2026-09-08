from datetime import datetime
from contextlib import contextmanager
from types import SimpleNamespace
from sqlalchemy.dialects import postgresql

from collectors import scheduler_jobs
from collectors import tdx_collector
from collectors import guosen_collector
from collectors import astock_collector
from collectors import money_flow_middleman
from collectors import realtime_sector_collector
from collectors import akshare_collector
from scripts import sync_concept_sectors
from us_quant import collector as us_collector


def test_concept_cleanup_requires_a_substantial_remote_snapshot():
    assert not sync_concept_sectors._can_prune_stale(188, 0)
    assert not sync_concept_sectors._can_prune_stale(188, 50)
    assert sync_concept_sectors._can_prune_stale(188, 173)


def test_concept_remote_fetch_is_merged_before_any_database_write(monkeypatch):
    monkeypatch.setattr(sync_concept_sectors, 'FALLBACK_CONCEPTS', {'东财补充': ['300750.SZ']})
    monkeypatch.setattr(sync_concept_sectors, 'fetch_from_sina', lambda: {'新浪主题': ['000001.SZ']})
    monkeypatch.setattr(sync_concept_sectors, 'fetch_from_akshare', lambda: {'同源主题': ['600000.SH']})
    monkeypatch.setattr(sync_concept_sectors, 'fetch_from_tushare_ths', lambda: {'同源主题': ['600000.SH', '000001.SZ']})
    monkeypatch.setattr(sync_concept_sectors, 'fetch_from_eastmoney', lambda: ['东财补充', '无成分股主题'])

    merged, sina, akshare, tushare = sync_concept_sectors._fetch_merged_concepts()

    assert sina == {'新浪主题': ['000001.SZ']}
    assert akshare == {'同源主题': ['600000.SH']}
    assert tushare == {'同源主题': ['600000.SH', '000001.SZ']}
    assert merged['东财补充'] == ['300750.SZ']
    assert '无成分股主题' not in merged


def test_latest_a_share_trade_date_skips_weekend(monkeypatch):
    monkeypatch.setattr(
        scheduler_jobs,
        "_is_trading_day",
        lambda value: value == "2026-08-07",
    )

    result = scheduler_jobs._latest_a_share_trade_date(datetime(2026, 8, 10, 9, 30))

    assert result == "20260807"


def test_concept_flow_dedupes_trimmed_sector_names():
    rows = tdx_collector._dedupe_concept_flows([
        {"sector": " 半导体 ", "net_flow": 1},
        {"sector": "半导体", "net_flow": 2},
        {"sector": "", "net_flow": 3},
        {"sector": "人工智能", "net_flow": 4},
    ])

    assert rows == [
        {"sector": "半导体", "net_flow": 1},
        {"sector": "人工智能", "net_flow": 4},
    ]


def test_stock_sector_aggregate_uses_database_rows_without_imputing_gaps():
    stock_rows = [
        SimpleNamespace(ts_code="601318.SH", name="中国平安", sector="保险", net_inflow=120.0),
        SimpleNamespace(ts_code="601336.SH", name="新华保险", sector="保险", net_inflow=-20.0),
        SimpleNamespace(ts_code="688001.SH", name="缺行情", sector="半导体", net_inflow=50.0),
    ]

    rows, skipped = tdx_collector._build_stock_sector_aggregates(
        stock_rows,
        {"601318.SH": 2.0, "601336.SH": -1.0},
    )

    assert skipped == ["半导体"]
    assert rows == [{
        "sector": "保险",
        "money_inflow": 120.0,
        "money_outflow": 20.0,
        "net_flow": 100.0,
        "rise_ratio": 50.0,
        "avg_chg": 0.5,
        "limit_up_count": 0,
        "leader_stock": "中国平安",
        "leader_strength": 2.0,
        "member_count": 2,
    }]


def test_guosen_fund_flow_accepts_result_list_payload():
    payload = guosen_collector._extract_fund_flow_payload({
        "result": [{"mainNetInflow": "1250000", "netInflow": "321.5"}],
    })

    assert payload == {"mainNetInflow": "1250000", "netInflow": "321.5"}


def test_guosen_fund_flow_rejects_failed_response():
    assert guosen_collector._extract_fund_flow_payload({
        "result": {"code": 500, "message": "upstream failed"},
    }) is None


def test_guosen_fund_flow_detects_daily_quota_response():
    assert guosen_collector._fund_flow_quota_exhausted({
        "result": [{"code": 197006, "msg": "超过日限额"}],
    })


def test_guosen_fund_flow_stops_calling_after_daily_quota(monkeypatch):
    calls = []
    monkeypatch.setattr(guosen_collector, 'GUOSEN_AVAILABLE', True)
    monkeypatch.setattr(guosen_collector, '_GUOSEN_FUND_FLOW_QUOTA_EXHAUSTED_DATE', None)

    def quota_response(*_args, **_kwargs):
        calls.append(1)
        return {"result": [{"code": 197006, "msg": "超过日限额"}]}

    monkeypatch.setattr(guosen_collector, 'query_fund_flow', quota_response)

    assert guosen_collector.guosen_single_fund_flow('601318.SH') is None
    assert guosen_collector.guosen_single_fund_flow('000001.SZ') is None
    assert calls == [1]


def test_sina_fund_flow_failure_uses_short_circuit_breaker(monkeypatch):
    calls = []
    monkeypatch.setattr(astock_collector, '_SINA_FUND_FLOW_FAILURE_UNTIL', 0.0)
    monkeypatch.setattr(astock_collector, '_SINA_FUND_FLOW_FAILURE_LOGGED_AT', 0.0)

    def fail_request(*_args, **_kwargs):
        calls.append(1)
        raise astock_collector.requests.ConnectionError('blocked')

    monkeypatch.setattr(astock_collector.requests, 'get', fail_request)

    assert astock_collector.sina_stock_fund_flow('601318') is None
    assert astock_collector.sina_stock_fund_flow('601318') is None
    assert calls == [1]


def test_akshare_quote_failure_uses_circuit_breaker(monkeypatch):
    calls = []
    monkeypatch.setattr(akshare_collector, 'AKSHARE_AVAILABLE', True)
    monkeypatch.setattr(akshare_collector, '_spot_cache_time', 0.0)
    monkeypatch.setattr(akshare_collector, '_SPOT_FAILURE_UNTIL', 0.0)
    monkeypatch.setattr(akshare_collector.time, 'time', lambda: 100.0)

    class BrokenAkshare:
        @staticmethod
        def stock_zh_a_spot():
            calls.append(1)
            raise ValueError('HTML response')

    monkeypatch.setattr(akshare_collector, 'ak', BrokenAkshare())

    assert akshare_collector.akshare_batch_prices(['601318.SH']) == {}
    assert akshare_collector.akshare_batch_prices(['601318.SH']) == {}
    assert calls == [1]


def test_money_flow_middleman_does_not_forward_fill_missing_values(monkeypatch):
    saved = []
    monkeypatch.setitem(money_flow_middleman.DATA_CACHE, 'industry', {
        '缺失行业': {'09:30': 1.25},
    })
    monkeypatch.setattr(money_flow_middleman, 'fetch_raw_data', lambda _dimension: [
        {'block_name': '有效行业', 'net_amount': 0},
    ])
    monkeypatch.setattr(money_flow_middleman, '_bulk_upsert_snapshots', saved.extend)

    assert money_flow_middleman.collect_realtime_money_flow_snapshot('industry', force=True) == 1
    assert [(row.block_name, float(row.net_inflow_yi), row.source) for row in saved] == [
        ('有效行业', 0.0, 'api'),
    ]


def test_money_flow_response_keeps_missing_minutes_as_gaps(monkeypatch):
    monkeypatch.setitem(money_flow_middleman.DATA_CACHE, 'concept', {
        '真实板块': {'09:30': 1.25},
    })

    response = money_flow_middleman.get_money_flow_response('concept', top_n=1, bottom_n=0)

    assert response['source'] == 'database'
    assert response['series'][0]['data'][:2] == [1.25, None]


def test_realtime_sector_snapshot_upserts_same_minute_sector(monkeypatch):
    statements = []

    class FakeSession:
        def execute(self, statement):
            statements.append(statement)

        def commit(self):
            pass

        def rollback(self):
            pass

    @contextmanager
    def fake_session():
        yield FakeSession()

    monkeypatch.setattr(realtime_sector_collector, 'get_db_session', fake_session)
    monkeypatch.setattr(realtime_sector_collector, '_now_truncated', lambda: datetime(2026, 8, 24, 10, 30))
    monkeypatch.setattr(realtime_sector_collector, 'get_sector_money_flow', lambda _trade_date: [
        {'sector': '半导体', 'net_flow': 1},
        {'sector': '半导体', 'net_flow': 2},
    ])

    assert realtime_sector_collector.collect_realtime_sector_flow('2026-08-24') == 1
    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert 'ON CONFLICT ON CONSTRAINT uq_realtime_sector_time DO UPDATE' in sql


def test_us_collector_always_includes_regime_references():
    assert us_collector.REGIME_REFERENCE_SYMBOLS == {"SPY", "QQQ", "IWM", "RSP", "^VIX"}

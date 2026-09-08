import asyncio
from datetime import date

from api import price_levels, us_quant, us_stock_analysis
from collectors import scheduler_jobs
from us_quant import collector, data_provider, universe


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def all(self):
        return self.rows

    def scalar(self):
        return self.rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def query(self, *args, **kwargs):
        return _FakeQuery(self.rows)


class _SequencedSession:
    def __init__(self, values):
        self.values = iter(values)

    def query(self, *args, **kwargs):
        return _FakeQuery(next(self.values))


class _FakeContext:
    def __init__(self, rows):
        self.session = rows if hasattr(rows, "query") else _FakeSession(rows)

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        return False


def _bar(index):
    day = (index % 28) + 1
    return {
        "date": f"2026-07-{day:02d}",
        "open": 100.0 + index,
        "high": 101.0 + index,
        "low": 99.0 + index,
        "close": 100.5 + index,
        "volume": 1_000_000,
        "source": "sina",
    }


def test_get_db_klines_missing_data_never_triggers_collection(monkeypatch):
    monkeypatch.setattr(collector, "get_db_session", lambda: _FakeContext([]))
    monkeypatch.setattr(
        collector,
        "collect_symbol",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("read path must not collect")),
    )

    assert collector.get_db_klines("missing") == []


def test_data_provider_reads_database_only(monkeypatch):
    rows = [_bar(i) for i in range(40)]
    monkeypatch.setattr(collector, "get_db_klines", lambda symbol: rows)
    fail = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("external source called"))
    monkeypatch.setattr(data_provider, "_nasdaq_historical", fail)
    monkeypatch.setattr(data_provider, "_fetch_yahoo_live", fail)
    monkeypatch.setattr(data_provider, "_cboe_vix_klines", fail)

    result = data_provider.get_klines("SNDK", "1mo")

    assert result == rows[-22:]


def test_vix_collection_uses_dedicated_cboe_source(monkeypatch):
    rows = [_bar(0), _bar(1)]
    monkeypatch.setattr(collector, "_get_source_cboe", lambda symbol, days: rows)
    monkeypatch.setattr(
        collector,
        "_get_source_klines_sina",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("VIX should use CBOE first")),
    )

    source, result = collector._fetch_klines_with_source("^VIX", 30)

    assert source == "cboe"
    assert result == rows


def test_cboe_vix_reader_keeps_latest_rows_when_csv_is_ascending(monkeypatch):
    monkeypatch.setattr(data_provider, "_get_text", lambda _url: """DATE,OPEN,HIGH,LOW,CLOSE
01/02/2026,10,11,9,10.5
01/03/2026,11,12,10,11.5
01/04/2026,12,13,11,12.5
""")

    rows = data_provider._cboe_vix_klines(2)

    assert [row["date"] for row in rows] == ["2026-01-03", "2026-01-04"]


def test_price_levels_uses_same_database_cutoff_and_minimum(monkeypatch):
    requested = {}

    def read_db(symbol, start_date=None, end_date=None):
        requested.update(symbol=symbol, end_date=end_date)
        return [_bar(i) for i in range(30)]

    monkeypatch.setattr(collector, "get_db_klines", read_db)
    rows = asyncio.run(price_levels._get_klines("us", "sndk", as_of="2026-08-19"))

    assert len(rows) == price_levels.MIN_ANALYSIS_BARS
    assert requested == {"symbol": "SNDK", "end_date": "2026-08-19"}


def test_price_levels_reports_database_status(monkeypatch):
    async def read_db(*_args, **_kwargs):
        return [_bar(i) for i in range(30)]

    monkeypatch.setattr(price_levels, "_get_klines", read_db)
    result = asyncio.run(price_levels.get_price_levels(market="us", symbol="SNDK"))

    assert result["source"] == "database"
    assert result["status"] == "READY"
    assert result["data"]["status"] == "READY"


def test_stock_overview_does_not_call_external_display_sources(monkeypatch):
    rows = [{
        "d": f"2026-07-{(index % 28) + 1:02d}",
        "o": 100.0 + index,
        "h": 101.0 + index,
        "l": 99.0 + index,
        "c": 100.5 + index,
        "v": 1_000_000.0,
    } for index in range(30)]
    fail = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("external display source called"))
    monkeypatch.setattr(us_stock_analysis, "_tx_quote", fail)
    monkeypatch.setattr(us_stock_analysis, "_tx_news", fail)
    monkeypatch.setattr(us_stock_analysis, "_tx_intraday", fail)
    monkeypatch.setattr(us_stock_analysis, "_db_kline", lambda symbol: rows)
    monkeypatch.setattr(
        us_stock_analysis,
        "_db_quote",
        lambda symbol, values: {"symbol": symbol, "price": values[-1]["c"], "source": "database"},
    )
    us_stock_analysis._cache.clear()

    result = us_stock_analysis.overview(symbol="TEST", news_limit=1)

    assert result["ok"] is True
    assert result["quote"]["source"] == "database"
    assert result["history"]["source"] == "database"
    assert result["intraday"] == []
    assert result["news"] == []


def test_automatic_collector_pool_includes_watchlist_positions_and_references(monkeypatch):
    monkeypatch.setattr(universe, "get_all_pool_symbols", lambda: ["CORE"])
    monkeypatch.setattr(universe, "get_universe_members", lambda code: ["WATCH"] if code == "US_WATCHLIST" else [])
    monkeypatch.setattr(collector, "get_db_session", lambda: _FakeContext([("POSITION",)]))

    result = collector._get_collector_pool()

    assert {"CORE", "WATCH", "POSITION", "SPY", "^VIX"}.issubset(result)


def test_us_catchup_runs_when_database_is_behind(monkeypatch):
    from market_quant import calendar

    monkeypatch.setattr(calendar, "latest_completed_session", lambda market: date(2026, 8, 20))
    monkeypatch.setattr(collector, "_get_collector_pool", lambda: ["AAPL", "SNDK"])
    monkeypatch.setattr(
        scheduler_jobs,
        "get_db_session",
        lambda: _FakeContext(_SequencedSession([date(2026, 8, 19), 0])),
    )
    monkeypatch.setattr(
        scheduler_jobs,
        "scheduled_us_quant_collect",
        lambda force_window=False: {"status": "completed", "force_window": force_window},
    )

    result = scheduler_jobs.scheduled_us_quant_catchup()

    assert result == {"status": "completed", "force_window": True}


def test_scheduled_collection_persists_remaining_coverage_gap(monkeypatch):
    from market_quant import calendar

    alerts = []
    monkeypatch.setattr(calendar, "latest_completed_session", lambda market: date(2026, 8, 20))
    monkeypatch.setattr(collector, "_get_collector_pool", lambda: ["AAPL", "SNDK"])
    monkeypatch.setattr(
        collector,
        "collect_all",
        lambda target_date: {"inserted": 1, "skipped": 0, "total": 2, "factors": {}, "results": []},
    )
    monkeypatch.setattr(scheduler_jobs, "get_db_session", lambda: _FakeContext([("AAPL",)]))
    monkeypatch.setattr(scheduler_jobs, "record_alert", lambda **kwargs: alerts.append(kwargs))

    result = scheduler_jobs.scheduled_us_quant_collect(force_window=True)

    assert result["status"] == "completed"
    assert result["coverage"]["missing"] == ["SNDK"]
    assert alerts[0]["category"] == "collection_gap"


def test_factor_values_missing_snapshot_never_collects_or_writes(monkeypatch):
    from us_quant import factor_storage

    monkeypatch.setattr(factor_storage, "get_latest_factor_values", lambda symbol: None)
    monkeypatch.setattr(
        factor_storage,
        "store_latest_factors_from_db",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("read path must not write factors")),
    )
    monkeypatch.setattr(
        collector,
        "collect_symbol",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("read path must not collect")),
    )

    result = asyncio.run(us_quant.api_factor_values(symbol="MISSING"))

    assert result["ok"] is False
    assert result["status"] == "MISSING"
    assert result["source"] == "database"


def test_position_indicator_compute_does_not_collect_missing_klines(monkeypatch):
    monkeypatch.setattr(data_provider, "get_klines", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        collector,
        "collect_symbol",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compute API must not collect")),
    )

    result = us_quant.compute_position_indicators(["MISSING"])

    assert result["failed"] == 1
    assert result["details"][0]["source"] == "database"

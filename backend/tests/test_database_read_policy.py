import asyncio
import importlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from analyzers import holding_state, market_state, stock_scores, strategy_engine
from api import alerts, bs_signals, fund_weather, leader_system, market_stage, mx_trading, panorama, shared, stock_dashboard, trading, us_quant
from api.watchlist import _shared as watchlist_shared
from api.watchlist import core as watchlist_core
from collectors import scheduler_jobs
from collectors import tdx_collector
from services import auto_trade_engine
from utils import should_defer_current_daily_analysis, should_use_intraday_snapshot

super_panel_router = importlib.import_module('api.super_panel.router')


def test_trading_positions_query_never_calls_miaoxiang(monkeypatch):
    expected = {"positions": [{"secCode": "601318"}], "source": "database"}
    monkeypatch.setattr(trading, "read_positions_from_db", lambda: expected)
    monkeypatch.setattr(
        mx_trading,
        "fetch_positions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("GET must not call Miaoxiang")),
    )

    assert asyncio.run(trading.get_positions(force=True)) == expected


def test_shared_portfolio_force_query_does_not_refresh(monkeypatch):
    expected = {"positions": [], "source": "database", "status": "READY"}
    monkeypatch.setattr(shared, "get_portfolio", lambda: expected)

    async def fail_refresh(*args, **kwargs):
        raise AssertionError("GET must not refresh external data")

    monkeypatch.setattr(shared, "_refresh_portfolio", fail_refresh)

    assert asyncio.run(shared.shared_portfolio(force=1)) == expected


def test_mx_positions_route_reads_database_adapter(monkeypatch):
    expected = {"positions": [{"secCode": "601318"}], "source": "database"}

    async def database_positions(force=False):
        return expected

    monkeypatch.setattr(trading, "get_positions", database_positions)
    monkeypatch.setattr(
        mx_trading,
        "fetch_positions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("GET must not call Miaoxiang")),
    )

    assert asyncio.run(mx_trading.get_positions(force=1)) == expected


def test_trading_collector_persists_remote_snapshot(monkeypatch):
    positions = {"positions": [{"secCode": "601318", "count": 400}]}
    balance = {"totalAssets": 1000000}
    orders = {"orders": [{"id": "order-1"}]}
    captured = {}

    async def fetch_positions(*args, **kwargs):
        return positions

    async def fetch_balance(*args, **kwargs):
        return balance

    async def fetch_orders(*args, **kwargs):
        return orders

    monkeypatch.setattr(mx_trading, "fetch_positions", fetch_positions)
    monkeypatch.setattr(mx_trading, "fetch_balance", fetch_balance)
    monkeypatch.setattr(mx_trading, "fetch_orders", fetch_orders)
    monkeypatch.setattr(
        trading,
        "persist_trading_snapshot",
        lambda b, p, o: captured.update(balance=b, positions=p, orders=o) or {"positions": 1},
    )

    result = asyncio.run(trading.collect_trading_snapshot(force=True))

    assert captured == {"balance": balance, "positions": positions, "orders": orders}
    assert result["persisted"] == {"positions": 1}


def test_auto_trade_collects_then_rereads_account_from_database(monkeypatch):
    events = []

    async def collect_snapshot(force=False):
        events.append(("collect", force))
        return {
            "balance": {"totalAssets": 999},
            "positions": {"positions": [{"secCode": "REMOTE"}]},
        }

    monkeypatch.setattr(trading, "collect_trading_snapshot", collect_snapshot)
    monkeypatch.setattr(
        trading,
        "read_balance_from_db",
        lambda: events.append(("read", "balance")) or {"totalAssets": 100},
    )
    monkeypatch.setattr(
        trading,
        "read_positions_from_db",
        lambda: events.append(("read", "positions")) or {"positions": [{"secCode": "DATABASE"}]},
    )

    result = asyncio.run(auto_trade_engine.get_account_overview(object()))

    assert events[0] == ("collect", True)
    assert result == {"balance": {"totalAssets": 100}, "positions": [{"secCode": "DATABASE"}]}


def test_strategy_quote_uses_database_adapter(monkeypatch):
    expected = {"code": "601318", "price": 53.42, "source": "database"}

    async def database_quote(code):
        assert code == "601318"
        return expected

    monkeypatch.setattr(watchlist_shared, "get_quote", database_quote)

    assert asyncio.run(strategy_engine._get_quote("601318")) == expected


def test_batch_kline_reader_uses_one_database_fetch_and_populates_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(watchlist_shared, "_kline_cache", {})

    def read_batch(codes, datalen):
        calls.append((codes, datalen))
        return {
            "601318": [{"date": "2026-08-21", "close": 53.35}],
            "000001": [{"date": "2026-08-21", "close": 11.41}],
        }

    monkeypatch.setattr(watchlist_shared, "_read_klines_batch_from_db", read_batch)

    first = asyncio.run(watchlist_shared.batch_fetch_kline_cached(["601318", "000001"], 60))
    second = asyncio.run(watchlist_shared.batch_fetch_kline_cached(["601318", "000001"], 60))

    assert calls == [(["000001", "601318"], 60)]
    assert first["601318"][0]["close"] == 53.35
    assert second == first


@pytest.mark.parametrize(
    ('raw', 'bare', 'ts_code'),
    [
        ('002851.SZ', '002851', '002851.SZ'),
        ('688019.SH', '688019', '688019.SH'),
        ('588080', '588080', '588080.SH'),
        ('920438.BJ', '920438', '920438.BJ'),
        ('920438', '920438', '920438.BJ'),
    ],
)
def test_watchlist_code_normalization_preserves_exchange(raw, bare, ts_code):
    assert watchlist_shared.normalize_stock_code(raw) == bare
    assert watchlist_shared.normalize_ts_code(raw) == ts_code


def test_current_day_incomplete_analysis_defers_to_last_completed_daily_result():
    during_session = datetime(2026, 8, 26, 10, 30)
    after_close = datetime(2026, 8, 26, 15, 30)

    assert should_defer_current_daily_analysis(date(2026, 8, 26), True, during_session) is True
    assert should_defer_current_daily_analysis(date(2026, 8, 26), False, after_close) is True
    assert should_defer_current_daily_analysis(date(2026, 8, 26), True, after_close) is False
    assert should_defer_current_daily_analysis(date(2026, 8, 25), False, during_session) is False


def test_bs_signals_respects_completed_daily_cutoff(monkeypatch):
    start = date(2026, 6, 27)
    rows = [
        {
            'date': (start + timedelta(days=index)).isoformat(),
            'open': 10 + index * 0.01,
            'high': 10.2 + index * 0.01,
            'low': 9.8 + index * 0.01,
            'close': 10.1 + index * 0.01,
            'volume': 1000 + index,
        }
        for index in range(61)
    ]

    async def fake_klines(*_args):
        return rows

    async def fake_records(*_args):
        return []

    monkeypatch.setattr(bs_signals, '_fetch_kline', fake_klines)
    monkeypatch.setattr(bs_signals, '_fetch_trade_records', fake_records)

    result = asyncio.run(bs_signals.get_bs_signals('300164', datalen=60, as_of='2026-08-25'))

    assert result['dataAsOf'] == '2026-08-25'
    assert result['klines'][-1]['date'] == '2026-08-25'


def test_market_state_kline_shortfall_does_not_fetch_external_data(monkeypatch):
    calls = []
    row = SimpleNamespace(
        trade_date=date(2026, 8, 20), open=52, close=53.42,
        high=54, low=51.8, volume=1_000_000,
    )

    class Query:
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, *_args): return self
        def all(self): return [row]

    class Session:
        def query(self, *_args): return Query()

    @contextmanager
    def session():
        yield Session()

    monkeypatch.setattr(market_state, "get_db_session", session)
    monkeypatch.setattr(
        tdx_collector,
        "call_tushare_mcp",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = asyncio.run(market_state._fetch_kline("601318", datalen=120))

    assert len(result) == 1
    assert result[0]["day"] == "2026-08-20"
    assert calls == []


def test_market_state_normalizes_suffixed_and_beijing_codes():
    assert market_state._stock_code_to_tushare('688019.SH') == '688019.SH'
    assert market_state._stock_code_to_tushare('002851.SZ') == '002851.SZ'
    assert market_state._stock_code_to_tushare('920438') == '920438.BJ'


def test_market_state_missing_money_flow_remains_missing(monkeypatch):
    class Query:
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, *_args): return self
        def all(self): return []

    class Session:
        def query(self, *_args): return Query()

    @contextmanager
    def session():
        yield Session()

    monkeypatch.setattr(market_state, 'get_db_session', session)

    result = market_state._fetch_money_flow('601318')

    assert result['status'] == 'MISSING'
    assert result['source'] == 'database'
    assert result['main_net_inflow_1d'] is None
    assert result['main_net_inflow_3d'] is None
    assert result['main_net_inflow_5d'] is None
    assert result['flow_continuity'] is None


def test_market_state_partial_money_flow_does_not_invent_multiday_totals(monkeypatch):
    kline_rows = [
        (date(2026, 8, 21),),
        (date(2026, 8, 20),),
    ]
    detail_rows = [
        SimpleNamespace(trade_date=date(2026, 8, 21), main_net=120),
    ]

    class Query:
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, *_args): return self
        def all(self): return self.rows

        def __init__(self, rows):
            self.rows = rows

    class Session:
        def __init__(self):
            self.query_count = 0

        def query(self, *_args):
            self.query_count += 1
            return Query(kline_rows if self.query_count == 1 else detail_rows)

    @contextmanager
    def session():
        yield Session()

    monkeypatch.setattr(market_state, 'get_db_session', session)

    result = market_state._fetch_money_flow('601318')

    assert result['status'] == 'PARTIAL'
    assert result['main_net_inflow_1d'] == 120
    assert result['main_net_inflow_3d'] is None
    assert result['main_net_inflow_5d'] is None
    assert result['flow_continuity'] is None


def test_market_state_money_flow_uses_kline_dates_and_yuan_detail_rows(monkeypatch):
    kline_rows = [
        (date(2026, 8, 21),),
        (date(2026, 8, 20),),
        (date(2026, 8, 19),),
        (date(2026, 8, 18),),
        (date(2026, 8, 17),),
    ]
    detail_rows = [
        SimpleNamespace(trade_date=day[0], main_net=value)
        for day, value in zip(kline_rows, (1_200_000, 800_000, -200_000, 300_000, 400_000))
    ]

    class Query:
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, *_args): return self
        def all(self): return self.rows

        def __init__(self, rows):
            self.rows = rows

    class Session:
        def __init__(self):
            self.query_count = 0

        def query(self, *_args):
            self.query_count += 1
            return Query(kline_rows if self.query_count == 1 else detail_rows)

    @contextmanager
    def session():
        yield Session()

    monkeypatch.setattr(market_state, 'get_db_session', session)

    result = market_state._fetch_money_flow('601318')

    assert result['status'] == 'READY'
    assert result['table'] == 'stock_money_flow_detail'
    assert result['main_net_inflow_1d'] == 1_200_000
    assert result['main_net_inflow_3d'] == 1_800_000
    assert result['main_net_inflow_5d'] == 2_500_000


def test_super_panel_realtime_uses_yuan_and_hides_derived_tick_placeholders(monkeypatch):
    now = datetime.now()
    tick = SimpleNamespace(
        snapshot_time=now,
        price=9.27,
        volume=0,
        amount=0,
        bid_price_1=0,
        bid_vol_1=0,
        ask_price_1=0,
        ask_vol_1=0,
        turnover_rate=0,
        main_force_inflow=-65_385_400,
        source='realtime_stock_flow',
    )
    flow = SimpleNamespace(
        snapshot_time=now,
        price=9.27,
        price_chg=-5.89,
        main_force_inflow=-6538.54,
        source='eastmoney',
    )

    class Query:
        def __init__(self, row): self.row = row
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def first(self): return self.row

    class Session:
        def __init__(self): self.query_count = 0
        def query(self, *_args):
            self.query_count += 1
            return Query(tick if self.query_count == 1 else flow)

    @contextmanager
    def session():
        yield Session()

    monkeypatch.setattr(super_panel_router, 'get_db_session', session)
    monkeypatch.setattr(super_panel_router, '_is_trading_hours', lambda: True)

    result = super_panel_router._realtime_section('300164.SZ')

    assert result['status'] == 'ready'
    assert result['main_force_inflow'] == -65_385_400
    assert result['volume'] is None
    assert result['turnover_rate'] is None
    assert result['upstream_source'] == 'eastmoney'


def test_super_panel_marks_fallback_quote_as_price_only(monkeypatch):
    now = datetime.now()
    tick = SimpleNamespace(
        snapshot_time=now,
        price=9.27,
        volume=0,
        amount=0,
        bid_price_1=0,
        bid_vol_1=0,
        ask_price_1=0,
        ask_vol_1=0,
        turnover_rate=0,
        main_force_inflow=0,
        source='realtime_stock_flow',
    )
    flow = SimpleNamespace(
        snapshot_time=now,
        price=9.27,
        price_chg=None,
        main_force_inflow=0,
        source='fallback',
    )

    class Query:
        def __init__(self, row): self.row = row
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def first(self): return self.row

    class Session:
        def __init__(self): self.query_count = 0
        def query(self, *_args):
            self.query_count += 1
            return Query(tick if self.query_count == 1 else flow)

    @contextmanager
    def session():
        yield Session()

    monkeypatch.setattr(super_panel_router, 'get_db_session', session)
    monkeypatch.setattr(super_panel_router, '_is_trading_hours', lambda: True)

    result = super_panel_router._realtime_section('300164.SZ')

    assert result['status'] == 'price_only'
    assert result['main_force_inflow'] is None
    assert result['volume'] is None


def test_sector_rotation_does_not_compress_missing_trading_days():
    kline_rows = [
        (date(2026, 8, 25),),
        (date(2026, 8, 24),),
        (date(2026, 8, 21),),
    ]
    sector_rows = [
        SimpleNamespace(trade_date=date(2026, 8, 25)),
        SimpleNamespace(trade_date=date(2026, 8, 21)),
    ]

    class Query:
        def __init__(self, rows): self.rows = rows
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, *_args): return self
        def all(self): return self.rows

    class Session:
        def __init__(self): self.query_count = 0
        def query(self, *_args):
            self.query_count += 1
            return Query(kline_rows if self.query_count == 1 else sector_rows)

    result = stock_dashboard._compute_sector_rotation(
        '石油开采', Session(), date(2026, 8, 25), ts_code='300164.SZ', lookback_days=3,
    )

    assert result['status'] == 'PARTIAL'
    assert result['rotation_signal'] == '板块资金数据不足'
    assert result['missing_dates'] == ['2026-08-24']


def test_sector_rotation_labels_single_day_reflow_as_unconfirmed():
    kline_rows = [
        (date(2026, 8, 25),),
        (date(2026, 8, 24),),
        (date(2026, 8, 21),),
    ]
    sector_rows = [
        SimpleNamespace(trade_date=day[0], net_flow=net, heat_score=None, leader_stock=None, leader_strength=None, avg_chg=None)
        for day, net in zip(kline_rows, (100, -1000, -1000))
    ]

    class Query:
        def __init__(self, rows): self.rows = rows
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, *_args): return self
        def all(self): return self.rows

    class Session:
        def __init__(self): self.query_count = 0
        def query(self, *_args):
            self.query_count += 1
            return Query(kline_rows if self.query_count == 1 else sector_rows)

    result = stock_dashboard._compute_sector_rotation(
        '石油开采', Session(), date(2026, 8, 25), ts_code='300164.SZ', lookback_days=3,
    )

    assert result['rotation_signal'] == '单日回流·仍待确认'
    assert result['rotation_detail'] == '1天流入 · 近3日累计-1900万'


def test_missing_money_flow_is_not_scored_as_neutral_or_outflow():
    klines = [
        {
            'day': f'2026-06-{index + 1:02d}',
            'open': 10.0,
            'close': 10.0,
            'high': 10.2,
            'low': 9.8,
            'volume': 1000,
        }
        for index in range(60)
    ]
    features = market_state.compute_features(
        klines,
        sector_strength=None,
        money_flow={
            'main_net_inflow_1d': None,
            'main_net_inflow_3d': None,
            'main_net_inflow_5d': None,
            'flow_continuity': None,
        },
    )

    _, reasons = market_state.classify_market_state(features)

    assert features['main_net_inflow_3d'] is None
    assert features['flow_continuity'] is None
    assert all('主力' not in reason for reason in reasons)
    assert stock_scores.calc_main_force(
        {'changePct': 1.0}, features, None,
    ) is None


def test_missing_score_inputs_never_become_neutral_scores():
    assert stock_scores.calc_sentiment(
        {"changePct": 1.0}, {"available": False}, {"volume_ratio": 1.2},
    ) is None
    assert stock_scores.calc_momentum(
        {"available": False}, {"main_net_inflow_3d": 100, "flow_continuity": 1},
    ) is None
    assert stock_scores.calc_risk(
        {"noise_ratio": 1.0, "atr_14": 0.2, "close": 10.0}, None, None,
    ) is None
    assert stock_scores.calc_technical({"trend_consistency_score": 0.8}) is None
    assert stock_scores.calc_sector_resonance(
        {"available": True, "latest_heat": 60}, {},
    ) is None


def test_holding_decision_pauses_when_database_dimensions_are_missing():
    result = holding_state.evaluate_holding_state(
        code="601318",
        name="中国平安",
        position={"count": 400, "profitPct": -1.0},
        quote={"price": 53.35},
        market_state={"features": {"close_vs_ma20": 0.01, "noise_ratio": 1.0}},
        score_dimensions={
            "trend_strength": 65,
            "relative_strength": 70,
            "capital_momentum": 60,
            "sector_resonance": None,
            "volume_health": 80,
            "volatility_health": 75,
            "drawdown_status": 70,
        },
        overall_score=None,
        technical={"stage": "偏多", "score": 65},
        bs_signal="B",
    )

    assert result["status"] == "READY"
    assert result["action"] == "数据不足，暂停持仓决策"
    assert result["factorScore"] is None
    assert result["dataStatus"] == "PARTIAL"
    assert result["missingDimensions"] == ["sector_resonance", "overall_score"]


def test_panorama_normalizes_beijing_exchange_code():
    assert panorama._normalize_ts_code('920438') == '920438.BJ'
    assert panorama._normalize_ts_code('920438.BJ') == '920438.BJ'


def test_dashboard_kline_fallback_uses_latest_window_and_exact_flows():
    kline_rows = [
        SimpleNamespace(
            trade_date=date(2026, 8, 21) - timedelta(days=offset),
            open=130 - offset - 0.2,
            close=130 - offset,
            high=130 - offset + 1,
            low=130 - offset - 1,
            volume=1000 + offset,
        )
        for offset in range(30)
    ]
    flow_rows = [
        SimpleNamespace(
            trade_date=date(2026, 8, 21) - timedelta(days=offset),
            main_force_inflow=100 + offset,
        )
        for offset in range(5)
    ]

    class Query:
        def __init__(self, rows): self.rows = rows
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, *_args): return self
        def all(self): return self.rows

    class Session:
        def query(self, model):
            if model is stock_dashboard.StockDailyKline:
                return Query(kline_rows)
            if model is stock_dashboard.StockFlow:
                return Query(flow_rows)
            raise AssertionError(f'unexpected model: {model}')

    result = stock_dashboard._features_from_kline_fallback(
        '601318.SH', date(2026, 8, 21), Session(),
    )

    assert result['_close'] == 130
    assert result['higher_high_flag'] == 1
    assert result['main_net_inflow_1d'] == 100
    assert result['main_net_inflow_3d'] == 303
    assert result['main_net_inflow_5d'] == 510


def test_dashboard_kline_fallback_rejects_stale_flow_dates():
    kline_rows = [
        SimpleNamespace(
            trade_date=date(2026, 8, 21) - timedelta(days=offset),
            open=130 - offset - 0.2,
            close=130 - offset,
            high=130 - offset + 1,
            low=130 - offset - 1,
            volume=1000 + offset,
        )
        for offset in range(30)
    ]
    # 资金表晚了一天；不能作为 8/21 的当日、3日、5日资金输入。
    flow_rows = [
        SimpleNamespace(
            trade_date=date(2026, 8, 20) - timedelta(days=offset),
            main_force_inflow=100 + offset,
        )
        for offset in range(5)
    ]

    class Query:
        def __init__(self, rows): self.rows = rows
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, *_args): return self
        def all(self): return self.rows

    class Session:
        def query(self, model):
            if model is stock_dashboard.StockDailyKline:
                return Query(kline_rows)
            if model is stock_dashboard.StockFlow:
                return Query(flow_rows)
            raise AssertionError(f'unexpected model: {model}')

    result = stock_dashboard._features_from_kline_fallback(
        '601318.SH', date(2026, 8, 21), Session(),
    )

    assert result['main_net_inflow_1d'] is None
    assert result['main_net_inflow_3d'] is None
    assert result['main_net_inflow_5d'] is None
    assert result['flow_continuity'] is None


def test_intraday_snapshot_yields_to_same_day_daily_close_after_close():
    snapshot = date(2026, 8, 25)
    assert should_use_intraday_snapshot(snapshot, snapshot, datetime(2026, 8, 25, 10, 0))
    assert not should_use_intraday_snapshot(snapshot, snapshot, datetime(2026, 8, 25, 15, 1))
    assert should_use_intraday_snapshot(snapshot, date(2026, 8, 24), datetime(2026, 8, 25, 15, 1))


def test_technical_ma20_slope_uses_normalized_fraction_unit():
    base = {
        'higher_high_flag': 1,
        'higher_low_flag': 1,
        'trend_consistency_score': 0.5,
        'close_vs_ma20': 0.0,
    }
    down = stock_scores.calc_technical({**base, 'ma20_slope': -0.02})
    up = stock_scores.calc_technical({**base, 'ma20_slope': 0.02})

    assert up['score'] - down['score'] >= 14


def test_market_stage_rejects_all_zero_price_changes(monkeypatch):
    class Query:
        def __init__(self, kind):
            self.kind = kind

        def scalar(self):
            return date(2026, 8, 21)

        def filter(self, *_args):
            return self

        def all(self):
            assert self.kind == 'price_chg'
            return [(0,), (0,), (0,)]

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def query(self, field):
            kind = 'latest' if getattr(field, 'name', None) == 'max' else 'price_chg'
            return Query(kind)

    monkeypatch.setattr(market_stage, 'get_db_session', Session)

    result = market_stage._compute_market_stage()

    assert result['status'] == 'INSUFFICIENT'
    assert result['source'] == 'database'
    assert result['stage'] is None
    assert result['score'] is None
    assert result['metrics']['flat'] == 3


def test_market_stage_broken_board_requires_touch_without_close_limit():
    assert market_stage._is_broken_board('600000.SH', 10, 11.0, 10.5)
    assert not market_stage._is_broken_board('600000.SH', 10, 11.0, 10.98)
    assert market_stage._is_broken_board('300001.SZ', 10, 12.0, 11.0)


def test_fund_weather_marks_incomplete_inputs_instead_of_cloudy():
    assert fund_weather._missing_classification_inputs(None, None, {}) == [
        'technical', 'change_5d', 'quote',
    ]
    assert fund_weather._missing_classification_inputs(
        {'stage': '偏多'},
        3.2,
        {'status': 'READY', 'price': 10},
    ) == []


def test_watchlist_data_status_distinguishes_missing_database_inputs():
    assert watchlist_core._classify_watchlist_data_status('005247', '', None, 0) == (
        'UNSUPPORTED', '本地证券主数据、行情和日K均不存在',
    )
    assert watchlist_core._classify_watchlist_data_status('588080', '科创50ETF', None, 0) == (
        'ETF_KLINE_MISSING', '本地 ETF 日K尚未入库，暂停技术与资金流评分',
    )
    assert watchlist_core._classify_watchlist_data_status('688825', '长鑫科技', {'status': 'READY'}, 20) == (
        'INSUFFICIENT_HISTORY', '本地日K仅 20 根，少于 60 根策略窗口',
    )


class _FakeResponse:
    def json(self):
        return {"code": 0, "data": {"totalAssets": 1}}


class _LoopLocalClient:
    created = 0

    def __init__(self, *args, **kwargs):
        type(self).created += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return _FakeResponse()


def test_miaoxiang_http_client_is_created_per_event_loop(monkeypatch):
    _LoopLocalClient.created = 0
    monkeypatch.setattr(mx_trading.httpx, "AsyncClient", _LoopLocalClient)

    assert asyncio.run(mx_trading._proxy("/one", {}, api_key="key")) == {"totalAssets": 1}
    assert asyncio.run(mx_trading._proxy("/two", {}, api_key="key")) == {"totalAssets": 1}
    assert _LoopLocalClient.created == 2


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def delete(self):
        return 0


class _FakeSession:
    def __init__(self):
        self.added = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def query(self, *args, **kwargs):
        return _FakeQuery()

    def add(self, row):
        self.added.append(row)

    def commit(self):
        return None


def test_us_sector_snapshot_uses_database_builder_for_completed_session(monkeypatch):
    from db import connection
    from market_quant import calendar

    session = _FakeSession()
    called = []
    monkeypatch.setattr(connection, "SessionLocal", lambda: session)
    monkeypatch.setattr(calendar, "latest_completed_session", lambda market: date(2026, 8, 20))
    monkeypatch.setattr(
        us_quant,
        "build_sector_snapshot_from_db",
        lambda target: called.append(target) or {
            "status": "READY",
            "sectors": [{"etf_symbol": "XLK", "rank": 1}],
        },
    )

    assert scheduler_jobs._run_us_sector_snapshot_core() is True
    assert called == [date(2026, 8, 20)]
    assert len(session.added) == 1


def test_us_regime_collector_refuses_to_copy_stale_snapshot(monkeypatch):
    from db import connection
    from market_quant import calendar

    monkeypatch.setattr(calendar, "latest_completed_session", lambda market: date(2026, 8, 20))
    monkeypatch.setattr(
        us_quant,
        "build_regime_snapshot_from_db",
        lambda target: {"status": "STALE", "stale_symbols": ["^VIX"]},
    )
    monkeypatch.setattr(
        connection,
        "SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("stale snapshot must not be written")),
    )

    assert scheduler_jobs._run_us_regime_snapshot_core() is False


def test_watchlist_cold_start_build_is_singleflight(monkeypatch):
    calls = []

    async def fake_threadpool(func):
        calls.append(func)
        await asyncio.sleep(0.01)
        return {"signals": []}

    monkeypatch.setattr(watchlist_core, "run_in_threadpool", fake_threadpool)
    watchlist_core._watchlist_build_task = None

    async def run_concurrent():
        return await asyncio.gather(
            watchlist_core._build_watchlist_singleflight(),
            watchlist_core._build_watchlist_singleflight(),
            watchlist_core._build_watchlist_singleflight(),
        )

    assert asyncio.run(run_concurrent()) == [{"signals": []}] * 3
    assert calls == [watchlist_core._sync_build_watchlist]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"type": "sell", "stock_code": "601318", "quantity": 0, "use_market_price": True},
        {"type": "sell", "stock_code": "60A318", "quantity": 100, "use_market_price": True},
        {"type": "sell", "stock_code": "601318", "quantity": 150, "use_market_price": True},
        {"type": "sell", "stock_code": "601318", "quantity": 100, "use_market_price": False, "price": 0},
    ],
)
def test_trade_validation_rejects_invalid_order_before_plugin(monkeypatch, kwargs):
    async def fail_proxy(*args, **options):
        raise AssertionError("invalid order must not reach Miaoxiang")

    monkeypatch.setattr(mx_trading, "_proxy", fail_proxy)
    with pytest.raises(Exception) as exc_info:
        asyncio.run(mx_trading.place_trade(**kwargs))
    assert getattr(exc_info.value, "status_code", None) == 400


def test_us_backtest_write_is_post_only():
    route = next(route for route in us_quant.router.routes if route.path == "/api/us-quant/backtest")

    assert route.methods == {"POST"}


def test_gap_check_write_is_post_only():
    route = next(route for route in alerts.router.routes if route.path == "/api/alerts/check-gap")

    assert route.methods == {"POST"}


def test_leader_get_disables_persistence(monkeypatch):
    captured = {}
    empty_result = {
        "leader": None,
        "candidates": [],
        "all_stocks": [],
        "successor_candidates": [],
        "all_count": 0,
        "sector_filter": {},
        "sector_rotation": {},
        "decay_warning": False,
        "current_leader_track": None,
        "date": "2026-08-21",
        "message": "无强主龙",
    }

    async def inline_threadpool(func, *args):
        if func is leader_system.run_leader_engine:
            captured["args"] = args
            return empty_result
        return func(*args)

    @contextmanager
    def empty_session():
        yield object()

    monkeypatch.setattr(leader_system, "run_in_threadpool", inline_threadpool)
    monkeypatch.setattr(leader_system, "get_db_session", empty_session)
    leader_system._leader_cache.update(data=None, ts=0, date=None)

    result = asyncio.run(leader_system.leader_system(target_date=None))

    assert captured["args"] == (None, False)
    assert result["date"] == "2026-08-21"


def test_realtime_latest_snapshot_queries_have_code_time_indexes():
    from db.models import RealtimeStockFlow, StockRealtimeTick

    def columns_for(model, index_name):
        index = next(item for item in model.__table__.indexes if item.name == index_name)
        return [column.name for column in index.columns]

    assert columns_for(RealtimeStockFlow, "ix_realtime_stock_code_time") == ["ts_code", "snapshot_time"]
    assert columns_for(StockRealtimeTick, "ix_realtime_tick_code_time") == ["ts_code", "snapshot_time"]

from datetime import date
from types import SimpleNamespace

from api import us_sector_rotation
from sqlalchemy.dialects import postgresql


def test_us_event_summary_counts_distinct_dates_and_compounded_evidence():
    rows = [
        {"symbol": "AAA", "trade_date": date(2026, 1, 2), "market_seq": 1, "max_seq": 5,
         "change_pct": 9.5, "two_day_pct": 17.0, "single_hit": True, "two_day_hit": True},
        {"symbol": "AAA", "trade_date": date(2026, 1, 5), "market_seq": 2, "max_seq": 5,
         "change_pct": 10.0, "two_day_pct": 20.0, "single_hit": True, "two_day_hit": True},
    ]

    evidence = us_sector_rotation._summarize_events(rows)["AAA"]

    assert evidence["event_count"] == 2
    assert evidence["single_day_count"] == 2
    assert evidence["two_day_count"] == 2
    assert evidence["days_since_trigger"] == 3
    assert evidence["trigger_type"] == "both"


def test_us_core_gate_requires_recent_repeat_events_and_ma60():
    stock = {
        "qualification": {"days_since_trigger": 5, "event_count": 2},
        "metrics": {"above_ma60": True},
    }
    assert us_sector_rotation._is_core_stock(stock) is True
    assert stock["core_gate"] == {"valid": True, "reasons": []}

    stock["qualification"]["event_count"] = 1
    assert us_sector_rotation._is_core_stock(stock) is False
    assert stock["core_gate"]["reasons"] == ["insufficient_repeat_events"]


def test_us_latest_completed_date_skips_partial_daily_batch():
    class Query:
        def __init__(self, scalar_value=None, rows=None):
            self.scalar_value = scalar_value
            self.rows = rows

        def filter(self, *_args): return self
        def join(self, *_args): return self
        def group_by(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, *_args): return self
        def scalar(self): return self.scalar_value
        def all(self): return self.rows

    class DB:
        calls = 0

        def query(self, *_args):
            self.calls += 1
            if self.calls == 1:
                return Query(scalar_value=100)
            return Query(rows=[(date(2026, 8, 12), 40), (date(2026, 8, 11), 95)])

    assert us_sector_rotation._latest_completed_trade_date(DB()) == date(2026, 8, 11)


def test_us_metrics_exposes_full_indicator_set():
    rows = []
    for index in range(220):
        close = 100 + index * 0.2
        rows.append(SimpleNamespace(
            trade_date=date.fromordinal(date(2025, 1, 1).toordinal() + index),
            open=close - 0.1, high=close + 1, low=close - 1, close=close,
            volume=1_000_000 + index, amount=None, turnover=None, change_pct=0.2,
        ))

    metrics = us_sector_rotation._metrics(rows)

    for key in ("ema10", "ema20", "ma5", "ma20", "ma50", "ma60", "ma200", "rsi", "dif", "dea", "macd",
                "kdj_k", "kdj_d", "kdj_j", "support", "resistance", "atr",
                "volume_ratio", "ret_5d", "ret_20d", "ret_60d", "volatility", "drawdown",
                "high_52w", "low_52w", "pct_from_high", "pct_from_low", "amplitude"):
        assert key in metrics
        assert metrics[key] is not None


def test_us_metrics_matches_watchlist_volume_support_and_resistance_windows():
    rows = []
    for index in range(80):
        close = 100 + index * .3
        rows.append(SimpleNamespace(
            trade_date=date.fromordinal(date(2026, 1, 1).toordinal() + index),
            open=close - .1, high=close + 1 + index % 4 * .1,
            low=close - 1 - index % 3 * .1, close=close,
            volume=1_000_000 + index * 10_000, amount=None, turnover=None, change_pct=.3,
        ))

    metrics = us_sector_rotation._metrics(rows)

    expected_volume = rows[-1].volume / (sum(row.volume for row in rows[-6:-1]) / 5)
    assert metrics["volume_ratio"] == expected_volume
    assert metrics["support"] == min(float(row.low) for row in rows[-20:])
    assert metrics["resistance"] == max(float(row.high) for row in rows[-20:])


def test_us_metrics_atr_uses_the_labeled_fourteen_day_period():
    from services.indicators import calc_atr

    rows = []
    for index in range(80):
        close = 100 + index * 0.25 + (index % 5) * 0.4
        rows.append(SimpleNamespace(
            trade_date=date.fromordinal(date(2026, 1, 1).toordinal() + index),
            open=close - 0.2, high=close + 1 + index % 3 * 0.15,
            low=close - 0.8 - index % 4 * 0.1, close=close,
            volume=1_000_000, amount=None, turnover=None, change_pct=0.2,
        ))

    metrics = us_sector_rotation._metrics(rows)
    expected = calc_atr(
        [float(row.high) for row in rows],
        [float(row.low) for row in rows],
        [float(row.close) for row in rows],
        period=14,
    )[-1]

    assert metrics["atr"] == expected


def test_us_snapshot_json_roundtrip_keeps_trade_date():
    payload = us_sector_rotation._serialize_snapshot({"trade_date": date(2026, 8, 11), "sectors": []})
    assert '"trade_date":"2026-08-11"' in payload


def test_us_sector_snapshot_query_does_not_build_or_persist(monkeypatch):
    monkeypatch.setattr(us_sector_rotation, "_load_persisted_snapshot", lambda _db, _target: None)
    monkeypatch.setattr(
        us_sector_rotation,
        "_build_snapshot",
        lambda _db, _target: (_ for _ in ()).throw(AssertionError("GET must not build a snapshot")),
    )

    assert us_sector_rotation._snapshot_for_date(object(), date(2026, 8, 20)) is None


def test_us_metrics_adjusts_historical_prices_across_stock_split_jump():
    rows = []
    for index in range(220):
        if index < 200:
            close = 500 + index
        else:
            close = (700 + index - 200) / 5
        open_price = close * (1.002 if index != 200 else 1.0)
        rows.append(SimpleNamespace(
            trade_date=date.fromordinal(date(2025, 1, 1).toordinal() + index),
            open=open_price, high=max(open_price, close) * 1.01,
            low=min(open_price, close) * .99, close=close,
            volume=1_000_000, amount=None, turnover=None, change_pct=0.2,
        ))

    metrics = us_sector_rotation._metrics(rows)

    assert metrics["corporate_action_adjustments"] == 1
    assert 115 < metrics["ma200"] < 145
    assert metrics["drawdown"] > -5


def test_us_metrics_keeps_large_earnings_gap_as_real_price_move():
    rows = []
    for index in range(220):
        close = 100 + index * .2
        if index >= 200:
            close += 36
        open_price = close * (1.002 if index != 200 else .995)
        rows.append(SimpleNamespace(
            trade_date=date.fromordinal(date(2025, 1, 1).toordinal() + index),
            open=open_price, high=max(open_price, close) * 1.01,
            low=min(open_price, close) * .99, close=close,
            volume=1_000_000, amount=None, turnover=None, change_pct=0.2,
        ))

    metrics = us_sector_rotation._metrics(rows)

    assert metrics["corporate_action_adjustments"] == 0


def test_us_event_query_excludes_split_day_and_following_two_day_window():
    class DB:
        def execute(self, statement, params):
            sql = str(statement.compile(dialect=postgresql.dialect()))
            assert "corporate_action_jump IS FALSE" in sql
            assert "COALESCE(prev_corporate_action_jump, FALSE) IS FALSE" in sql
            assert params["single_threshold"] == 9.0
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))

    assert us_sector_rotation._event_rows(DB(), date(2026, 8, 11)) == []


def test_us_sector_context_opens_gate_only_for_rising_sector(monkeypatch):
    snapshot = {
        "trade_date": "2026-08-11",
        "sectors": [
            {"sector": "半导体", "rank": 1, "stock_count": 4,
             "qualified_stock_count": 10, "universe_stock_count": 23,
             "leader_strength": 81,
             "metrics": {"status": "OPEN", "rise_score": 80, "ret_5d": 3, "ret_20d": 12, "ret_60d": 20, "breadth": 70},
             "etf": {"symbol": "SMH"}},
            {"sector": "制药", "rank": 2, "stock_count": 2,
             "qualified_stock_count": 5, "universe_stock_count": 12,
             "leader_strength": 75,
             "metrics": {"status": "CLOSED", "rise_score": 45, "ret_5d": -2, "ret_20d": -1, "ret_60d": 8, "breadth": 60},
             "etf": {"symbol": "XLV"}},
        ],
    }

    class Session:
        def __enter__(self): return self
        def __exit__(self, *_args): return None

    monkeypatch.setattr(us_sector_rotation, "get_db_session", lambda: Session())
    monkeypatch.setattr(us_sector_rotation, "_latest_completed_trade_date", lambda _db: date(2026, 8, 11))
    monkeypatch.setattr(us_sector_rotation, "_snapshot_for_date", lambda _db, _target: snapshot)
    monkeypatch.setitem(us_sector_rotation._CACHE, "trade_date", None)
    monkeypatch.setitem(us_sector_rotation._CACHE, "snapshot", None)

    result = us_sector_rotation.get_sector_context_by_name(["半导体", "制药", "银行"])

    assert result["sectors"]["半导体"]["opportunity_gate"] == "OPEN"
    assert result["sectors"]["制药"]["opportunity_gate"] == "CLOSED"
    assert "银行" not in result["sectors"]


def test_us_sector_rise_uses_full_universe_and_etf_can_veto():
    stocks = [
        {"metrics": {"ret_5d": 3, "ret_20d": 10, "ret_60d": 15, "above_ma20": True, "above_ma60": True}},
        {"metrics": {"ret_5d": 2, "ret_20d": 8, "ret_60d": 12, "above_ma20": True, "above_ma60": True}},
        {"metrics": {"ret_5d": 1, "ret_20d": 6, "ret_60d": 10, "above_ma20": True, "above_ma60": True}},
        {"metrics": {"ret_5d": -1, "ret_20d": -2, "ret_60d": 4, "above_ma20": False, "above_ma60": False}},
    ]
    confirmed_etf = {
        "is_current": True, "score": 75, "ret_20d": 8,
        "rel_strength_20d": 3, "ma_trend": 10,
    }

    metrics = us_sector_rotation._sector_universe_metrics(stocks, 4, confirmed_etf)

    assert metrics["status"] == "OPEN"
    assert metrics["breadth"] == 75
    assert metrics["valid_stock_count"] == 4

    weak_etf = {**confirmed_etf, "score": 30, "ret_20d": -6, "rel_strength_20d": -6, "ma_trend": 2}
    vetoed = us_sector_rotation._sector_universe_metrics(stocks, 4, weak_etf)
    assert vetoed["status"] == "CLOSED"
    assert "etf_weak_veto" in vetoed["gate_reasons"]


def test_market_opportunity_response_flattens_only_open_sector_top10():
    snapshot = {
        "trade_date": "2026-08-12",
        "sectors": [
            {
                "sector": "半导体", "rank": 1,
                "metrics": {"status": "OPEN", "rise_score": 88, "ret_20d": 12, "breadth": 75, "etf_status": "CONFIRM"},
                "etf": {"symbol": "SMH", "rel_strength_20d": 4.5},
            },
            {
                "sector": "制药", "rank": 2,
                "metrics": {"status": "CLOSED", "rise_score": 55},
                "etf": {"symbol": "XLV"},
            },
        ],
        "candidate_stocks_by_sector": {
            "半导体": [{"symbol": f"OPEN{index}", "rank": index} for index in range(1, 13)],
            "制药": [{"symbol": "CLOSED1", "rank": 1}],
        },
        "pool_rule": {"single_day_pct_gte": 9},
        "data_mode": "completed_daily_cached",
    }

    payload = us_sector_rotation._market_opportunity_response(snapshot)

    assert payload["sector_count"] == 1
    assert payload["candidate_count"] == 10
    assert [row["symbol"] for row in payload["candidates"]] == [f"OPEN{index}" for index in range(1, 11)]
    assert payload["candidates"][0]["sector_context"]["etf"]["symbol"] == "SMH"

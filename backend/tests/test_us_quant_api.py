import asyncio
from datetime import date
from types import SimpleNamespace

from starlette.responses import JSONResponse

from api import us_quant


def test_watchlist_symbols_are_deduplicated_without_reordering():
    assert us_quant._unique_symbols(["AAPL", "NVDA", "AAPL", "MSFT", "NVDA"]) == ["AAPL", "NVDA", "MSFT"]


def test_watchlist_opportunity_requires_sector_gate_and_uses_position_semantics():
    assert us_quant._watchlist_opportunity({"action": "buy"}, {"is_rising": False})["status"] == "SECTOR_CLOSED"
    assert us_quant._watchlist_opportunity({"action": "buy"}, {"is_rising": True})["status"] == "READY"
    assert us_quant._watchlist_opportunity({"action": "watch"}, {"is_rising": True})["status"] == "STOCK_WAIT"
    assert us_quant._watchlist_opportunity({"action": "stop", "action_label": "止损"}, {"is_rising": False}, has_position=True) == {
        "status": "RISK", "label": "止损", "sector_gate": False,
    }
    assert us_quant._watchlist_opportunity({"action": "stop", "action_label": "止损"}, {"is_rising": False}) == {
        "status": "SECTOR_CLOSED", "label": "板块未通过", "sector_gate": False,
    }
    assert us_quant._watchlist_opportunity({"action": "stop", "action_label": "止损"}, {"is_rising": True}) == {
        "status": "AVOID", "label": "回避·等待修复", "sector_gate": True,
    }


def test_watchlist_opportunity_blocks_stale_or_missing_data():
    assert us_quant._watchlist_opportunity(
        {"action": "buy", "data_status": "STALE"}, {"status": "OPEN"},
    )["status"] == "DATA_STALE"
    assert us_quant._watchlist_opportunity(
        {"action": "buy", "data_status": "MISSING"}, {"status": "OPEN"},
    )["status"] == "DATA_INSUFFICIENT"
    assert us_quant._watchlist_opportunity(
        {"action": "buy", "data_status": "CURRENT"}, {"status": "ETF_MISSING"},
    ) == {"status": "DATA_INSUFFICIENT", "label": "ETF数据缺失", "sector_gate": False}


def test_watchlist_opportunity_downgrades_overheated_entry_to_wait_for_pullback():
    opportunity = us_quant._watchlist_opportunity(
        {"action": "buy", "price": 110, "ma20": 100, "rsi": 72, "kdj": {"j": 101}},
        {"status": "OPEN"},
    )

    assert opportunity["status"] == "STOCK_WAIT"
    assert opportunity["label"] == "板块通过·等待回踩"
    assert len(opportunity["entry_risks"]) == 2


def test_watchlist_effective_action_never_exposes_buy_when_sector_is_closed():
    raw = {
        "action": "buy", "action_label": "买入", "action_color": "#ef4444",
        "action_strength": 80, "action_reasons": ["均线多头排列"], "raw_action": "buy",
    }

    blocked = us_quant._watchlist_effective_action(
        raw,
        {"status": "SECTOR_CLOSED", "label": "板块未通过", "sector_gate": False},
    )
    waiting = us_quant._watchlist_effective_action(
        raw,
        {"status": "STOCK_WAIT", "label": "板块通过·等待回踩", "sector_gate": True,
         "entry_risks": ["KDJ-J 101.0 超买，等待回踩"]},
    )

    assert blocked["action"] == "blocked"
    assert blocked["action_label"] == "板块未通过"
    assert blocked["raw_action"] == "buy"
    assert waiting["action"] == "watch"
    assert waiting["action_label"] == "等待回踩"
    assert waiting["action_reasons"][0] == "KDJ-J 101.0 超买，等待回踩"
    assert raw["action"] == "buy"


def test_sina_us_quote_uses_percent_field_not_change_amount():
    line = 'var hq_str_gb_mu="美光科技,948.9850,4.14,2026-08-12 16:00:00,37.6950,0,0,0,0";'

    symbol, quote = us_quant._parse_sina_watchlist_line(line, "US")

    assert symbol == "MU"
    assert quote == {"price": 948.985, "change_pct": 4.14, "quote_time": "2026-08-12 16:00:00"}


def test_watchlist_split_adjustment_keeps_technical_series_continuous():
    rows = []
    for index in range(30):
        close = 500 + index if index < 20 else (520 + index - 20) / 5
        rows.append({
            "date": f"2026-07-{index + 1:02d}",
            "open": close, "high": close * 1.01, "low": close * .99,
            "close": close, "volume": 1_000_000,
        })

    adjusted, count = us_quant._continuous_watchlist_klines(rows)

    assert count == 1
    assert abs(adjusted[19]["close"] - adjusted[20]["close"]) < 2


def test_watchlist_indicators_use_shared_ohlc_calculation():
    from services.indicators import calc_kdj, calc_macd, calc_rsi

    closes = [100 + index * 0.35 + (index % 7 - 3) * 0.4 for index in range(90)]
    highs = [value + 1.2 + index % 3 * 0.1 for index, value in enumerate(closes)]
    lows = [value - 1.1 - index % 2 * 0.1 for index, value in enumerate(closes)]
    rsi_values = calc_rsi(closes, 14)
    dif_values, dea_values, macd_values = calc_macd(closes)
    k_values, d_values, j_values = calc_kdj(highs, lows, closes)

    result_macd = us_quant._latest_macd(closes)
    result_kdj = us_quant._latest_kdj(highs, lows, closes)

    assert us_quant._latest_rsi(closes, 14) == rsi_values[-1]
    assert result_macd["dif"] == round(dif_values[-1], 4)
    assert result_macd["dea"] == round(dea_values[-1], 4)
    assert result_macd["hist"] == round(macd_values[-1], 4)
    assert result_kdj["k"] == round(k_values[-1], 2)
    assert result_kdj["d"] == round(d_values[-1], 2)
    assert result_kdj["j"] == round(j_values[-1], 2)


def test_cached_live_availability_never_probes_network(monkeypatch):
    from us_quant import data_provider

    monkeypatch.setattr(data_provider, "_LIVE_CACHE", {"ok": True, "ts": 100.0})
    monkeypatch.setattr(data_provider.time, "time", lambda: 101.0)
    assert data_provider.cached_live_availability() is True

    monkeypatch.setattr(data_provider.time, "time", lambda: 100.0 + data_provider._LIVE_TTL)
    assert data_provider.cached_live_availability() is None


def test_overview_uses_cached_live_state_without_forcing_probe(monkeypatch):
    from market_quant import service as market_service
    from us_quant import data_provider

    async def regime():
        return {"allow_new_positions": True}

    async def sectors():
        return {"sectors": []}

    monkeypatch.setattr(us_quant, "get_regime", regime)
    monkeypatch.setattr(us_quant, "get_sectors", sectors)
    monkeypatch.setattr(us_quant, "_decision_payload", lambda *_args: {})
    monkeypatch.setattr(market_service, "get_latest_snapshot", lambda *_args: {
        "status": "SUCCESS", "signals": [], "data_quality": {"status": "VALID"},
    })
    monkeypatch.setattr(data_provider, "cached_live_availability", lambda: None)
    monkeypatch.setattr(
        data_provider,
        "is_live_available",
        lambda: (_ for _ in ()).throw(AssertionError("overview must not probe live source")),
    )
    monkeypatch.setattr(data_provider, "_get_proxies", lambda: None)

    payload = asyncio.run(us_quant.get_overview())

    assert payload["system"]["live"] is False
    assert payload["system"]["live_probe"] == "not_checked"


def test_backtest_response_sanitizes_infinite_profit_factor(monkeypatch):
    metric = SimpleNamespace(
        symbol="AAPL",
        strategy="ALL",
        total_trades=1,
        winning_trades=1,
        losing_trades=0,
        win_rate=100.0,
        total_pnl=10.0,
        total_pnl_pct=1.0,
        profit_factor=float("inf"),
        max_drawdown_pct=0.0,
        sharpe_ratio=0.0,
        avg_bars_held=1.0,
    )
    monkeypatch.setattr(us_quant, "run_backtest_batch", lambda **_kwargs: [metric])

    payload = asyncio.run(us_quant.api_backtest(symbols="AAPL"))

    assert payload["results"][0]["profit_factor"] is None
    JSONResponse(payload)


def test_factor_values_reads_persisted_snapshot_without_live_fetch(monkeypatch):
    from us_quant import factor_storage

    monkeypatch.setattr(factor_storage, "get_latest_factor_values", lambda symbol: {
        "symbol": symbol,
        "trade_date": "2026-08-07",
        "data_trade_date": "2026-08-07",
        "is_current": True,
        "values": {"trend": 1.25},
    })
    monkeypatch.setattr(
        factor_storage,
        "store_latest_factors_from_db",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected recompute")),
    )

    payload = asyncio.run(us_quant.api_factor_values(symbol="AAPL"))

    assert payload == {
        "ok": True,
        "status": "READY",
        "symbol": "AAPL",
        "trade_date": "2026-08-07",
        "data_trade_date": "2026-08-07",
        "source": "database",
        "count": 1,
        "values": {"trend": 1.25},
    }


def test_decision_payload_only_promotes_triggered_and_qualified_watch_rows():
    snapshot = {
        "status": "SUCCESS",
        "trade_date": "2026-08-10",
        "pool_total": 3,
        "valid_count": 3,
        "data_quality": {"status": "VALID"},
        "signals": [
            {
                "symbol": "BUY", "trading_state": "TRIGGERED", "factor_score": 70,
                "resonance": {"eligible": True, "count": 6}, "dimensions": {"trend": {"score": 80}},
            },
            {
                "symbol": "WATCH", "trading_state": "READY", "factor_score": 60,
                "resonance": {"eligible": True, "count": 5}, "dimensions": {"trend": {"score": 70}},
            },
            {
                "symbol": "VETOED_TRIGGER", "trading_state": "TRIGGERED", "factor_score": 95,
                "risk_veto": True, "resonance": {"eligible": True, "count": 6},
            },
            {
                "symbol": "BLOCKED", "trading_state": "INVALID", "factor_score": 90,
                "risk_veto": True, "resonance": {"eligible": False, "count": 5},
            },
        ],
    }

    payload = us_quant._decision_payload(snapshot, {"allow_new_positions": True, "label": "中性震荡"})

    assert [item["symbol"] for item in payload["buyable"]] == ["BUY"]
    assert [item["symbol"] for item in payload["watch"]] == ["WATCH"]
    assert payload["counts"] == {"buyable": 1, "watch": 1, "qualified": 2, "risk_blocked": 2}
    assert payload["market_gate"]["allow_new_positions"] is True


def test_selection_history_counts_only_contiguous_persisted_candidates():
    def run(day, symbols):
        return SimpleNamespace(
            trade_date=day,
            payload={
                "signals": [
                    {
                        "symbol": symbol,
                        "risk_veto": False,
                        "resonance": {"eligible": True},
                    }
                    for symbol in symbols
                ],
            },
        )

    runs = [
        run(date(2026, 8, 10), ["BUY", "WATCH"]),
        run(date(2026, 8, 7), ["BUY", "WATCH"]),
        run(date(2026, 8, 6), ["BUY"]),
        run(date(2026, 8, 5), ["BUY"]),
    ]

    history = us_quant._selection_history_from_runs(runs, ["BUY", "WATCH", "MISSING"])

    assert history["BUY"] == {
        "consecutive_days": 4,
        "selected_in_recent_scans": 4,
        "recent_scan_days": 4,
        "streak_start_date": "2026-08-05",
    }
    assert history["WATCH"] == {
        "consecutive_days": 2,
        "selected_in_recent_scans": 2,
        "recent_scan_days": 4,
        "streak_start_date": "2026-08-07",
    }
    assert "MISSING" not in history


def test_candidate_changes_compares_only_saved_postmarket_snapshots():
    def run(day, signals):
        return SimpleNamespace(trade_date=day, payload={"signals": signals})

    current = [
        {"symbol": "BUY", "trading_state": "TRIGGERED", "factor_score": 71, "resonance": {"eligible": True, "count": 6}},
        {"symbol": "NEW", "trading_state": "READY", "factor_score": 62, "resonance": {"eligible": True, "count": 5}},
    ]
    prior = [
        {"symbol": "BUY", "trading_state": "READY", "factor_score": 69, "resonance": {"eligible": True, "count": 5}},
        {"symbol": "DROPPED", "trading_state": "READY", "resonance": {"eligible": True, "count": 5}},
    ]

    changes, summary = us_quant._candidate_changes_from_runs(
        [run(date(2026, 8, 10), current), run(date(2026, 8, 7), prior)], current,
    )

    assert changes["BUY"]["kind"] == "upgraded"
    assert changes["NEW"]["kind"] == "new"
    assert summary["baseline_trade_date"] == "2026-08-07"
    assert summary["new_count"] == 1
    assert summary["upgraded_count"] == 1
    assert summary["dropped"] == [{"symbol": "DROPPED", "name": None, "previous_state": "READY"}]


def test_correlation_groups_only_marks_highly_correlated_return_series():
    dates = [date(2026, 7, 1 + offset) for offset in range(18)]
    shared = {day: (index - 9) / 1000 for index, day in enumerate(dates)}
    inverse = {day: -value for day, value in shared.items()}

    pairs, groups = us_quant._correlation_groups({"AAA": shared, "BBB": dict(shared), "CCC": inverse})

    assert pairs == [{"left": "AAA", "right": "BBB", "correlation": 1.0}]
    assert groups == [{"symbols": ["AAA", "BBB"], "average_correlation": 1.0}]

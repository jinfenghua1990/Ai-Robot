from datetime import date, datetime

from industry_stage.compute import (
    STATE_ACTIVE,
    STATE_CANDIDATE,
    STATE_COOLING,
    STATE_INACTIVE,
    _is_selectable,
    adaptive_candidate_cap,
    transition_state,
)
from industry_stage.market_clock import (
    PHASE_BREAK,
    PHASE_CLOSED,
    PHASE_PREOPEN,
    PHASE_TRADING,
    market_phase,
)
from industry_stage.models import INDUSTRY_STAGE_TABLES
from industry_stage.realtime import _quote_values, parse_tencent_payload


def test_adaptive_candidate_cap_boundaries():
    assert adaptive_candidate_cap(1) == 8
    assert adaptive_candidate_cap(50) == 8
    assert adaptive_candidate_cap(51) == 15
    assert adaptive_candidate_cap(150) == 15
    assert adaptive_candidate_cap(151) == 20
    assert adaptive_candidate_cap(300) == 20
    assert adaptive_candidate_cap(301) == 30


def test_state_requires_three_consecutive_strong_sessions():
    state, streak, weak = transition_state(None, 0, 0, strong_now=True, weak_now=False)
    assert (state, streak, weak) == (STATE_CANDIDATE, 1, 0)
    state, streak, weak = transition_state(state, streak, weak, strong_now=True, weak_now=False)
    assert (state, streak, weak) == (STATE_CANDIDATE, 2, 0)
    state, streak, weak = transition_state(state, streak, weak, strong_now=True, weak_now=False)
    assert (state, streak, weak) == (STATE_ACTIVE, 3, 0)


def test_active_sector_cools_then_exits_after_three_weak_sessions():
    state, streak, weak = transition_state(
        STATE_ACTIVE, 6, 0, strong_now=False, weak_now=True,
    )
    assert (state, weak) == (STATE_COOLING, 1)
    state, streak, weak = transition_state(
        state, streak, weak, strong_now=False, weak_now=True,
    )
    assert (state, weak) == (STATE_COOLING, 2)
    state, streak, weak = transition_state(
        state, streak, weak, strong_now=False, weak_now=True,
    )
    assert (state, weak) == (STATE_INACTIVE, 3)


def test_new_tables_do_not_reuse_legacy_sector_rotation_tables():
    names = {table.name for table in INDUSTRY_STAGE_TABLES}
    assert len(names) == 8
    assert all(name.startswith("industry_stage_") for name in names)
    assert "sector_rotation_snapshot" not in names


def test_market_phase_covers_live_break_and_closed_windows():
    assert market_phase(datetime(2026, 9, 1, 9, 24)) == PHASE_PREOPEN
    assert market_phase(datetime(2026, 9, 1, 9, 25)) == PHASE_TRADING
    assert market_phase(datetime(2026, 9, 1, 12, 0)) == PHASE_BREAK
    assert market_phase(datetime(2026, 9, 1, 13, 0)) == PHASE_TRADING
    assert market_phase(datetime(2026, 9, 1, 15, 1)) == PHASE_CLOSED
    assert market_phase(datetime(2026, 9, 1, 10, 0), is_market_day=False) == PHASE_CLOSED


def test_tencent_parser_preserves_beijing_exchange_and_intraday_fields():
    values = [""] * 50
    values[1] = "秋乐种业"
    values[3] = "20.95"
    values[4] = "17.93"
    values[30] = "20260901103307"
    values[32] = "16.84"
    values[37] = "32145.5"
    values[38] = "18.76"
    values[49] = "2.31"
    payload = f'v_bj920087="{"~".join(values)}";'

    quotes = parse_tencent_payload(payload, {"bj920087": "920087.BJ"})

    assert set(quotes) == {"920087.BJ"}
    quote = quotes["920087.BJ"]
    assert quote["price"] == 20.95
    assert quote["amount_wan"] == 32145.5
    assert quote["turnover_rate"] == 18.76
    assert quote["volume_ratio"] == 2.31
    assert quote["quote_time"] == datetime(2026, 9, 1, 10, 33, 7)


def test_realtime_rows_only_accept_same_day_stage_pool_quotes():
    quotes = {
        "600127.SH": {
            "name": "金健米业",
            "price": 13.24,
            "previous_close": 12.04,
            "day_change_pct": 9.97,
            "amount_wan": 167125,
            "turnover_rate": 20.47,
            "volume_ratio": 1.92,
            "quote_time": datetime(2026, 9, 1, 10, 32, 0),
        },
        "600722.SH": {
            "name": "金牛化工",
            "price": 17.57,
            "previous_close": 16.8,
            "day_change_pct": 4.58,
            "amount_wan": 179770,
            "turnover_rate": 15.24,
            "volume_ratio": 2.86,
            "quote_time": datetime(2026, 8, 31, 15, 0, 0),
        },
    }

    rows = _quote_values(
        quotes,
        {"600127.SH": "金健米业", "600722.SH": "金牛化工"},
        date(2026, 8, 31),
        date(2026, 9, 1),
    )

    assert len(rows) == 1
    assert rows[0]["ts_code"] == "600127.SH"
    assert rows[0]["pool_trade_date"] == date(2026, 8, 31)


def test_sixty_day_return_requires_sixty_one_closes():
    stock = {
        "history_count": 60,
        "ret_20d": 12,
        "ret_60d": None,
        "above_ma20": True,
        "above_ma60": True,
        "drawdown_60d": -5,
        "score": 80,
        "stock_name": "测试股份",
    }
    assert _is_selectable(stock) is False

from datetime import date, datetime

import pytest

from api import sector_rotation
from api.sector_rotation import (
    SINGLE_DAY_THRESHOLD,
    TWO_DAY_THRESHOLD,
    _summarize_events,
    _etf_match,
    _latest_completed_trade_date,
    _serialize_snapshot,
    _theme_names_for_concept,
    _two_day_return,
)
from collectors.pingan_collector import _optional_float


def test_two_day_return_is_compounded_not_added():
    result = _two_day_return(8.0, 8.0)
    assert round(result, 4) == 16.64
    assert result >= TWO_DAY_THRESHOLD


def test_event_summary_keeps_auditable_latest_trigger():
    rows = [
        {
            "ts_code": "000001.SZ",
            "trade_date": date(2026, 1, 5),
            "market_seq": 10,
            "max_seq": 100,
            "pct_chg": SINGLE_DAY_THRESHOLD,
            "two_day_pct": 10.0,
            "single_hit": True,
            "two_day_hit": False,
        },
        {
            "ts_code": "000001.SZ",
            "trade_date": date(2026, 4, 8),
            "market_seq": 70,
            "max_seq": 100,
            "pct_chg": 8.0,
            "two_day_pct": TWO_DAY_THRESHOLD,
            "single_hit": False,
            "two_day_hit": True,
        },
    ]

    evidence = _summarize_events(rows)["000001.SZ"]

    assert evidence["trigger_type"] == "both"
    assert evidence["single_day_count"] == 1
    assert evidence["two_day_count"] == 1
    assert evidence["event_count"] == 2
    assert evidence["latest_trigger_date"] == date(2026, 4, 8)
    assert evidence["latest_trigger_types"] == ["two_day"]
    assert evidence["days_since_trigger"] == 30


def test_same_date_single_and_two_day_hit_counts_as_one_distinct_event():
    rows = [{
        "ts_code": "000001.SZ",
        "trade_date": date(2026, 4, 8),
        "market_seq": 70,
        "max_seq": 100,
        "pct_chg": 10.0,
        "two_day_pct": 18.0,
        "single_hit": True,
        "two_day_hit": True,
    }]

    evidence = _summarize_events(rows)["000001.SZ"]

    assert evidence["single_day_count"] == 1
    assert evidence["two_day_count"] == 1
    assert evidence["event_count"] == 1
    assert evidence["latest_trigger_types"] == ["single_day", "two_day"]


def test_etf_match_prefers_direct_sector_name_over_alias_and_liquidity():
    class Etf:
        def __init__(self, name, index, amount):
            self.etf_name = name
            self.tracking_index = index
            self.etf_type = "行业主题"
            self.amount_20d = amount

    etfs = [
        Etf("科技ETF", "信息技术", 10_000),
        Etf("软件ETF", "中证软件", 100),
        Etf("云计算ETF", "云计算", 20_000),
    ]

    matched, keywords = _etf_match("软件服务", etfs)

    assert keywords[0] == "软件服务"
    assert matched.etf_name == "软件ETF"


def test_etf_decimal_return_is_stored_as_percentage_points():
    assert _optional_float("0.1246", 100) == pytest.approx(12.46)
    assert _optional_float(None, 100) is None


def test_intraday_latest_bar_falls_back_to_previous_completed_day():
    class ScalarQuery:
        def __init__(self, values):
            self.values = values

        def filter(self, *args):
            return self

        def scalar(self):
            return self.values.pop(0)

    class Db:
        def __init__(self):
            self.values = [date(2026, 8, 13), date(2026, 8, 12)]

        def query(self, *args):
            return ScalarQuery(self.values)

    result = _latest_completed_trade_date(Db(), datetime(2026, 8, 13, 10, 0))

    assert result == date(2026, 8, 12)


def test_snapshot_serialization_preserves_dates_for_persistent_cache():
    payload = _serialize_snapshot({
        "trade_date": date(2026, 8, 13),
        "data_as_of": {"daily_kline": date(2026, 8, 13)},
    })

    assert '"trade_date":"2026-08-13"' in payload
    assert '"daily_kline":"2026-08-13"' in payload


def test_concepts_map_to_trade_themes_without_replacing_industry():
    assert "算力" in _theme_names_for_concept("云计算")
    assert "算力" in _theme_names_for_concept("英伟达概念")
    assert {"算力", "半导体"}.issubset(_theme_names_for_concept("AI芯片"))


def test_sector_snapshot_query_does_not_build_or_persist(monkeypatch):
    monkeypatch.setattr(sector_rotation, "_load_persisted_snapshot", lambda _db, _target: None)
    monkeypatch.setattr(
        sector_rotation,
        "_build_snapshot",
        lambda _db, _target: (_ for _ in ()).throw(AssertionError("GET must not build a snapshot")),
    )

    assert sector_rotation._snapshot_for_date(object(), date(2026, 8, 20)) is None

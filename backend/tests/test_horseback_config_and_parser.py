import stat
from datetime import date

import pytest

from horseback.config_store import TokenStore, normalize_token
from horseback import ifind_client
from horseback.ifind_client import (
    MCPClientError,
    IfindMCPClient,
    collect_daily_limit_up_candidates,
    parse_candidates,
    parse_realtime_quotes,
)


def test_markdown_escaped_jwe_is_normalized_without_changing_payload():
    escaped = r"aaa\_bbb.ccc\-ddd.eee.fff.ggg"
    assert normalize_token(escaped) == "aaa_bbb.ccc-ddd.eee.fff.ggg"


def test_token_store_uses_owner_only_permissions(tmp_path):
    store = TokenStore(tmp_path / "ifind.json", env={})
    token = "aaa.bbb.ccc.ddd.eee"

    store.save(token)

    assert store.load() == token
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store.status() == {"configured": True, "source": "file"}


@pytest.mark.parametrize("value", ["", "only.one", "a.b.c.d.e!", "a..c.d.e"])
def test_invalid_token_is_rejected(value):
    with pytest.raises(ValueError):
        normalize_token(value)


def test_candidate_parser_handles_structured_ifind_rows_and_deduplicates():
    payload = {
        "data": [
            {"股票代码": "600000", "股票简称": "浦发银行", "区间涨停次数": "2"},
            {"股票代码": "600000.SH", "股票简称": "浦发银行", "区间涨停次数": 2},
            {"股票代码": "300750.SZ", "股票简称": "宁德时代", "区间涨停次数": 1},
        ]
    }

    rows = parse_candidates(payload)

    assert rows == [{
        "ts_code": "600000.SH",
        "name": "浦发银行",
        "limit_up_count": 2,
        "source_rank": 1,
        "raw": {"股票代码": "600000", "股票简称": "浦发银行", "区间涨停次数": "2"},
    }]


def test_candidate_parser_handles_markdown_table():
    payload = """
| 股票代码 | 股票简称 | 涨停次数 |
| --- | --- | --- |
| 000001.SZ | 平安银行 | 1 |
| 688981.SH | 中芯国际 | 1 |
"""

    rows = parse_candidates(payload)

    assert [(row["ts_code"], row["name"], row["limit_up_count"]) for row in rows] == [
        ("000001.SZ", "平安银行", 1),
    ]


def test_realtime_quote_parser_handles_nested_ifind_table_payload():
    payload = {
        "content": [{
            "type": "text",
            "text": '{"data":"{\\"tables\\":[[[\\"证券代码\\",\\"最新价\\",\\"涨跌幅\\",\\"开盘价\\",\\"最高价\\",\\"最低价\\",\\"成交量\\",\\"时间\\"],[\\"600000.SH\\",\\"12.34\\",\\"3.56\\",\\"12.01\\",\\"12.50\\",\\"11.88\\",\\"12345\\",\\"2026-08-28 10:30:00\\"]]]}"}'
        }]
    }

    quotes = parse_realtime_quotes(payload)

    assert quotes["600000.SH"] == {
        "price": 12.34,
        "change_pct": 3.56,
        "open": 12.01,
        "high": 12.5,
        "low": 11.88,
        "volume": 12345.0,
        "at": "2026-08-28 10:30:00",
    }


def test_daily_candidate_collection_rejects_an_incomplete_trading_window(monkeypatch):
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def initialize(self):
            return None

        def call_tool(self, _name, arguments):
            if "20日" in arguments["query"]:
                return {"data": [{"股票代码": "600000.SH", "股票简称": "浦发银行"}]}
            return {"data": []}

    monkeypatch.setattr(ifind_client, "IfindMCPClient", FakeClient)
    monkeypatch.setattr(ifind_client.time, "sleep", lambda _seconds: None)

    with pytest.raises(MCPClientError, match="涨停池不完整.*2026-08-21"):
        collect_daily_limit_up_candidates(
            "test.token.value",
            [date(2026, 8, 20), date(2026, 8, 21)],
            attempts_per_day=1,
        )


def test_csv_download_client_never_inherits_mcp_authorization_header():
    client = IfindMCPClient("aaa.bbb.ccc.ddd.eee")
    try:
        assert client._client.headers.get("authorization", "").startswith("Bearer ")
        assert client._client.headers.get("mcp-protocol-version") == "2025-06-18"
        assert "authorization" not in client._download_client.headers
    finally:
        client.close()

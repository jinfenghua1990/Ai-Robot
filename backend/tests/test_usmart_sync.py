import json

import services.usmart_positions_sync as positions_sync
from services.usmart_positions_sync import _has_auth_error, _parse_positions
from services.usmart_watchlist_sync import _FILL_LOGIN_JS


def test_parse_new_usmart_asset_endpoint_uses_parent_us_exchange():
    payload = {
        "code": 0,
        "data": {
            "assetSingleInfoRespVOS": [{
                "appCardType": 11,
                "moneyType": "USD",
                "holdInfos": [{
                    "code": "aapl",
                    "curHoldNum": "2",
                    "costPrice": "100",
                    "lastPrice": "120",
                    "marketValue": "240",
                    "holdProfit": "40",
                    "holdProfitPercent": "0.2",
                    "todayProfit": "1",
                }],
            }],
        },
    }
    rows = _parse_positions([{
        "url": "https://jy.yxzq.com/asset-center-server/api/query-accountAssetInfoForAE",
        "body": json.dumps(payload),
    }])

    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["exchange_type"] == 5
    assert rows[0]["quantity"] == 2
    assert rows[0]["hold_profit_pct"] == 20


def test_parse_new_usmart_fractional_asset_endpoint():
    payload = {
        "data": {
            "assetSingleInfoRespVOS": [{
                "appCardType": 13,
                "holdInfos": [{"stockCode": "MSFT", "exchangeType": "52", "currentAmount": 0.5}],
            }],
        },
    }
    rows = _parse_positions([{
        "url": "query-accountAssetInfoForAE",
        "body": json.dumps(payload),
    }])

    assert rows[0]["symbol"] == "MSFT"
    assert rows[0]["exchange_type"] == 52
    assert rows[0]["quantity"] == 0.5


def test_asset_endpoint_auth_error_is_not_treated_as_empty_position():
    response = {
        "url": "query-accountAssetInfoForAE",
        "body": json.dumps({"code": 450003, "data": None, "error": "userid 不能为空", "msg": "userid 不能为空"}),
    }
    assert _has_auth_error([response]) is True
    assert _parse_positions([response]) == []


def test_login_script_uses_safe_json_placeholders():
    assert "var phone = __PHONE__;" in _FILL_LOGIN_JS
    assert "var pwd = __PWD__;" in _FILL_LOGIN_JS


def test_auth_error_does_not_close_existing_positions(monkeypatch):
    response = {
        "url": "query-accountAssetInfoForAE",
        "body": json.dumps({"code": 450003, "error": "userid 不能为空"}),
    }
    writes = []
    monkeypatch.setattr(positions_sync, "_discover_page_ws", lambda: "ws://test")
    monkeypatch.setattr(positions_sync, "_check_login_state", lambda _: "logged_in")
    monkeypatch.setattr(positions_sync, "_auto_login", lambda _: {"ok": True})
    monkeypatch.setattr(positions_sync, "_collect_asset_responses", lambda _: [response])
    monkeypatch.setattr(positions_sync, "sync_us_positions", lambda rows: writes.append(rows))
    monkeypatch.setattr(positions_sync, "_save_status", lambda _: None)

    result = positions_sync._run_sync_locked()

    assert result["ok"] is False
    assert result["login"] == "relogin_ok"
    assert writes == []

from api.us_quant import _unified_snapshot_to_legacy


def test_legacy_adapter_exposes_new_factor_fields_without_strategy_hit_count():
    result = _unified_snapshot_to_legacy({
        "status": "SUCCESS",
        "trade_date": "2026-07-31",
        "universe": "US_CORE_A_300",
        "pool_total": 300,
        "valid_count": 120,
        "candidate_count": 3,
        "triggered_count": 1,
        "signals": [{
            "symbol": "AAPL",
            "name": "Apple",
            "factor_score": 82.5,
            "dimension_scores": {"trend": {"score": 80, "valid": True}},
            "resonance_count": 5,
            "resonance_dimensions": ["market", "strength", "trend", "position", "risk"],
            "failed_dimensions": [],
            "trading_state": "TRIGGERED",
            "lifecycle": "主升",
            "data_quality": "VALID",
            "risk_veto": False,
            "rank": 1,
        }],
    })
    item = result["candidates"][0]
    assert item["factor_score"] == 82.5
    assert item["breakout_score"] == 80
    assert item["resonance_count"] == 5
    assert item["primary_strategy"] == "统一七维因子"


def test_miaoxiang_adapter_honors_request_timeout(monkeypatch):
    import asyncio
    from api import mx_skills

    calls = {}

    class Response:
        def json(self):
            return {"ok": True}

    class Client:
        async def post(self, *args, **kwargs):
            calls.update(kwargs)
            return Response()

    monkeypatch.setattr(mx_skills, "_ensure_apikey", lambda: None)
    monkeypatch.setattr(mx_skills, "_get_http_client", lambda: Client())

    result = asyncio.run(mx_skills._mx_post("/api/test", {}, timeout=7))
    assert result == {"ok": True}
    assert calls["timeout"] == 7

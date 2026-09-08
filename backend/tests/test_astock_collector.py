from collectors import astock_collector


def test_eastmoney_failure_uses_cooldown_before_retrying(monkeypatch):
    now = [100.0]
    calls = []

    def fail_get(*_args, **_kwargs):
        calls.append(True)
        raise ConnectionError("upstream disconnected")

    monkeypatch.setattr(astock_collector.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(astock_collector.requests, "get", fail_get)
    monkeypatch.setattr(astock_collector, "_EM_LAST_CALL", 0.0)
    monkeypatch.setattr(astock_collector, "_EM_FAILURE_UNTIL", 0.0)
    monkeypatch.setattr(astock_collector, "_EM_FAILURE_LOGGED_AT", 0.0)
    monkeypatch.setattr(astock_collector, "_EM_MIN_INTERVAL_SECONDS", 0.0)

    assert astock_collector.eastmoney_fund_flow_daily("600519") is None
    assert astock_collector.eastmoney_fund_flow_daily("000001") is None
    assert len(calls) == 1

    now[0] += astock_collector._EM_FAILURE_COOLDOWN_SECONDS
    assert astock_collector.eastmoney_fund_flow_daily("000001") is None
    assert len(calls) == 2

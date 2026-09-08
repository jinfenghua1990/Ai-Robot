from collectors import tdx_collector


def test_tushare_permission_error_disables_only_that_endpoint(monkeypatch):
    tdx_collector._TUSHARE_DISABLED_ENDPOINTS.clear()
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 40203, "msg": "抱歉，您没有接口(limit_list_d)访问权限"}

    def fake_post(*_args, **_kwargs):
        calls.append(True)
        return Response()

    monkeypatch.setattr(tdx_collector.requests, "post", fake_post)
    monkeypatch.setattr(tdx_collector, "_tushare_rate_acquire", lambda: None)

    assert tdx_collector.call_tushare_mcp("limit_list_d") is None
    assert tdx_collector.call_tushare_mcp("limit_list_d") is None
    assert calls == [True]
    assert "limit_list_d" in tdx_collector._TUSHARE_DISABLED_ENDPOINTS

    tdx_collector._TUSHARE_DISABLED_ENDPOINTS.clear()

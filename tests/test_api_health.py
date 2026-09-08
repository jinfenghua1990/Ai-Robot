"""API 健康检查测试（使用 httpx 直连后端）"""
import httpx


def _get_local(path: str) -> httpx.Response:
    with httpx.Client(base_url="http://127.0.0.1:9000", timeout=5, trust_env=False) as client:
        return client.get(path)


def test_health_endpoint():
    """GET /api/health 返回 ok"""
    resp = _get_local("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "AIROBOT"


def test_latest_date_endpoint():
    """GET /api/latest-date 返回日期格式或 null"""
    resp = _get_local("/api/latest-date")
    assert resp.status_code == 200
    data = resp.json()
    if data["date"] is not None:
        assert len(data["date"]) == 10
        assert data["date"][4] == "-"
        assert data["date"][7] == "-"

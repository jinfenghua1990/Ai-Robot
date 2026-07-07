"""API 健康检查测试（使用 httpx 直连后端）"""
import httpx


def test_health_endpoint():
    """GET /api/health 返回 ok"""
    resp = httpx.get("http://localhost:9000/api/health", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "AIROBOT"


def test_latest_date_endpoint():
    """GET /api/latest-date 返回日期格式或 null"""
    resp = httpx.get("http://localhost:9000/api/latest-date", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    if data["date"] is not None:
        assert len(data["date"]) == 10
        assert data["date"][4] == "-"
        assert data["date"][7] == "-"

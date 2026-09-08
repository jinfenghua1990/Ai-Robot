from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import horseback as horseback_api
from api.auth import verify_api_key


def _client():
    app = FastAPI()
    app.include_router(horseback_api.router)
    app.dependency_overrides[verify_api_key] = lambda: True
    return TestClient(app)


def test_config_write_never_returns_secret(monkeypatch):
    saved = []

    class Store:
        def status(self):
            return {"configured": bool(saved), "source": "file" if saved else "none"}

        def save(self, value):
            saved.append(value)

    monkeypatch.setattr(horseback_api, "TokenStore", Store)
    monkeypatch.setattr(horseback_api, "is_local_host", lambda _host: True)
    token = "aaaa.bbbb.cccc.dddd.eeee"

    response = _client().put("/api/horseback/config", json={"token": token})

    assert response.status_code == 200
    assert saved == [token]
    assert token not in response.text
    assert response.json()["secret_returned"] is False


def test_run_request_rejects_inverted_limit_count_without_starting(monkeypatch):
    monkeypatch.setattr(
        horseback_api,
        "start_run",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("invalid input must not start a run")),
    )

    response = _client().post("/api/horseback/runs", json={"min_limit_count": 4, "max_limit_count": 2})

    assert response.status_code == 422


def test_run_request_rejects_inverted_consolidation_range_without_starting(monkeypatch):
    monkeypatch.setattr(
        horseback_api,
        "start_run",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("invalid input must not start a run")),
    )

    response = _client().post("/api/horseback/runs", json={"min_consolidation_days": 12, "max_consolidation_days": 3})

    assert response.status_code == 422


def test_run_request_maps_options_to_background_service(monkeypatch):
    captured = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return {"id": "run-1", "status": "QUEUED"}

    monkeypatch.setattr(horseback_api, "start_run", fake_start)

    response = _client().post("/api/horseback/runs", json={
        "end_date": "2026-08-20",
        "min_consolidation_days": 4,
        "max_consolidation_days": 10,
        "min_limit_count": 1,
        "max_limit_count": 3,
        "min_score": 80,
        "max_candidates": 0,
    })

    assert response.status_code == 202
    assert response.json() == {"id": "run-1", "status": "QUEUED"}
    assert captured["requested_end_date"].isoformat() == "2026-08-20"
    assert captured["min_consolidation_days"] == 4
    assert captured["max_consolidation_days"] == 10
    assert captured["min_score"] == 80
    assert captured["max_candidates"] == 0

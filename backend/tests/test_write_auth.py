from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import config
from api.auth import (
    WriteAuthMiddleware,
    is_loopback_client,
    is_write_auth_client,
    mark_write_operations_protected,
    verify_api_key,
)


def _make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(WriteAuthMiddleware)

    @app.get("/api/value")
    def read_value():
        return {"ok": True}

    @app.post("/api/value")
    def write_value():
        return {"ok": True}

    @app.post("/internal/task")
    def internal_task():
        return {"ok": True}

    return TestClient(app)


def test_write_auth_protects_api_mutations(monkeypatch):
    monkeypatch.setattr(config, "API_READ_KEY", "expected-key")
    client = _make_client()

    assert client.get("/api/value").status_code == 200
    assert client.post("/internal/task").status_code == 200
    assert client.post("/api/value").status_code == 401
    assert client.post("/api/value", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/api/value", headers={"X-API-Key": "expected-key"}).status_code == 200
    client.cookies.set("airobot_write_token", "expected-key")
    assert client.post("/api/value").status_code == 200


def test_write_auth_fails_closed_without_configuration(monkeypatch):
    monkeypatch.setattr(config, "API_READ_KEY", "")
    assert _make_client().post("/api/value").status_code == 503


def test_dependency_accepts_same_origin_write_cookie(monkeypatch):
    monkeypatch.setattr(config, "API_READ_KEY", "expected-key")
    app = FastAPI()
    app.add_middleware(WriteAuthMiddleware)

    @app.post("/api/protected", dependencies=[Depends(verify_api_key)])
    def protected_write():
        return {"ok": True}

    client = TestClient(app)
    client.cookies.set("airobot_write_token", "expected-key")

    assert client.post("/api/protected").status_code == 200


def test_loopback_detection_does_not_trust_hostnames():
    assert is_loopback_client("127.0.0.1")
    assert is_loopback_client("::1")
    assert not is_loopback_client("192.168.1.10")
    assert not is_loopback_client("localhost")


def test_write_auth_trusts_only_explicit_configured_hosts(monkeypatch):
    monkeypatch.setattr(config, "WRITE_AUTH_TRUSTED_HOSTS", frozenset({"192.168.3.48"}))

    assert is_write_auth_client("192.168.3.48")
    assert not is_write_auth_client("192.168.3.49")


def test_openapi_marks_all_api_write_operations():
    schema = {
        "paths": {
            "/api/value": {"get": {}, "post": {}, "delete": {}},
            "/internal/task": {"post": {}},
        }
    }

    marked = mark_write_operations_protected(schema)

    assert marked["paths"]["/api/value"]["get"].get("security") is None
    assert marked["paths"]["/api/value"]["post"]["security"] == [{"WriteAPIKey": []}]
    assert marked["paths"]["/api/value"]["delete"]["security"] == [{"WriteAPIKey": []}]
    assert marked["paths"]["/internal/task"]["post"].get("security") is None

"""Every trading and control endpoint needs the API key; only /health is public."""

import logging

import pytest
from fastapi.routing import APIRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app

KEY = "correct-horse-battery-staple"
PUBLIC = {"/health", "/openapi.json", "/api/docs", "/api/redoc", "/api/docs/oauth2-redirect"}


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)  # no `with`: the lifespan (databases, brokers) is not started


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(settings, "CONTROL_API_KEY", KEY)
    monkeypatch.setattr(settings, "API_AUTH_DISABLED", False)


def api_calls():
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path not in PUBLIC:
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, route.path


def fill(path):
    import re

    return re.sub(r"\{[^}]+\}", "x", path)


def test_health_stays_public(client, keyed):
    assert client.get("/health").status_code == 200


def test_missing_key_is_401(client, keyed):
    assert client.get("/api/agents/pods").status_code == 401


def test_wrong_key_is_401(client, keyed):
    assert client.get("/api/agents/pods", headers={"X-API-Key": "nope"}).status_code == 401


def test_empty_and_differently_cased_keys_are_401(client, keyed):
    assert client.get("/api/agents/pods", headers={"X-API-Key": ""}).status_code == 401
    assert client.get("/api/agents/pods", headers={"X-API-Key": KEY.upper()}).status_code == 401


def test_key_in_query_string_is_rejected(client, keyed):
    assert client.get(f"/api/agents/pods?x-api-key={KEY}&api_key={KEY}").status_code == 401


def test_correct_key_passes(client, keyed):
    assert client.get("/api/agents/pods", headers={"X-API-Key": KEY}).status_code == 200


def test_unset_server_key_is_503_not_open(client, monkeypatch):
    monkeypatch.setattr(settings, "CONTROL_API_KEY", None)
    monkeypatch.setattr(settings, "API_AUTH_DISABLED", False)
    assert client.get("/api/agents/pods").status_code == 503
    assert client.get("/api/agents/pods", headers={"X-API-Key": ""}).status_code == 503


def test_disabled_flag_allows_and_warns(client, monkeypatch, caplog):
    import app.security as security

    monkeypatch.setattr(security, "_warned_disabled", False)
    monkeypatch.setattr(settings, "CONTROL_API_KEY", None)
    monkeypatch.setattr(settings, "API_AUTH_DISABLED", True)
    with caplog.at_level(logging.WARNING):
        assert client.get("/api/agents/pods").status_code == 200
    assert "authentication is DISABLED" in caplog.text


def test_every_router_requires_the_key(client, keyed):
    seen = 0
    for method, path in api_calls():
        response = client.request(method, fill(path))
        assert response.status_code == 401, f"{method} {path} answered {response.status_code} without a key"
        seen += 1
    assert seen > 20  # the whole API was walked, not an empty list


def test_ws_without_token_is_refused(client, keyed):
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws"):
            pass
    assert refused.value.code == 1008


def test_ws_with_wrong_token_is_refused(client, keyed):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=nope"):
            pass


def test_ws_with_the_token_connects(client, keyed):
    with client.websocket_connect(f"/ws?token={KEY}") as socket:
        socket.send_text("hi")
        assert socket.receive_json()["data"] == "hi"

import pytest
from starlette.testclient import TestClient

from app.agents.router import set_pods
from app.config import settings
from app.control.killswitch import KillSwitch
from app.data.database import get_db_session
from app.main import app

KEY = "k" * 16
HEADERS = {"X-API-Key": KEY}


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setattr(settings, "CONTROL_API_KEY", KEY)
    monkeypatch.setattr(settings, "API_AUTH_DISABLED", False)
    app.dependency_overrides[get_db_session] = lambda: session
    set_pods({})
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    set_pods({})


def test_halt_requires_the_key(client):
    assert client.post("/api/control/halt", json={"scope": "all", "reason": "x"}).status_code == 401


def test_halt_then_status_shows_the_reason(client):
    assert client.post("/api/control/halt", headers=HEADERS, json={"scope": "all", "reason": "crash"}).status_code == 200
    body = client.get("/api/control/status", headers=HEADERS).json()
    assert body["kill_switch"]["global"]["reason"] == "crash"


def test_resume_clears_the_halt(client):
    client.post("/api/control/halt", headers=HEADERS, json={"scope": "paper_test", "reason": "x"})
    client.post("/api/control/resume", headers=HEADERS, json={"scope": "paper_test"})
    assert client.get("/api/control/status", headers=HEADERS).json()["kill_switch"]["accounts"] == {}


def test_halt_needs_a_reason(client):
    assert client.post("/api/control/halt", headers=HEADERS, json={"scope": "all", "reason": ""}).status_code == 422


def test_manual_order_returns_423_when_halted(client, session):
    KillSwitch(lambda: session).halt("paper_test", "stop everything", "pytest")
    response = client.post(
        "/api/execution/order?account_name=paper_test",
        headers=HEADERS,
        json={"tradingsymbol": "NIFTY", "transaction_type": "BUY", "quantity": 1},
    )
    assert response.status_code == 423


def test_flatten_unknown_account_is_404(client):
    assert client.post("/api/control/flatten/nope", headers=HEADERS).status_code == 404


def test_flatten_calls_the_pod(client):
    class Pod:
        async def flatten(self, reason):
            self.reason = reason
            return 2

    pod = Pod()
    set_pods({"paper_test": pod})
    response = client.post("/api/control/flatten/paper_test", headers=HEADERS)
    assert response.status_code == 200 and response.json()["closed"] == 2 and "flatten" in pod.reason

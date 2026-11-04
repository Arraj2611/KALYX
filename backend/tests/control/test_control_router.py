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


class FakeAlerts:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    async def send_critical(self, account, message):
        self.calls.append(("critical", account, message))
        if self.fail:
            raise RuntimeError("telegram down")

    async def send_info(self, account, message):
        self.calls.append(("info", account, message))


@pytest.fixture
def alerts():
    from app.control.router import set_alert_service

    fake = FakeAlerts()
    set_alert_service(fake)
    yield fake
    set_alert_service(None)


def test_halt_sends_a_critical_alert(client, alerts):
    client.post("/api/control/halt", headers=HEADERS, json={"scope": "paper_test", "reason": "odd fills"})
    kind, scope, message = alerts.calls[0]
    assert kind == "critical" and scope == "paper_test" and "odd fills" in message


def test_resume_sends_an_info_alert(client, alerts):
    client.post("/api/control/resume", headers=HEADERS, json={"scope": "all"})
    assert alerts.calls[0][0] == "info"


def test_a_failing_alert_does_not_fail_the_halt(client):
    from app.control.router import set_alert_service

    set_alert_service(FakeAlerts(fail=True))
    try:
        response = client.post("/api/control/halt", headers=HEADERS, json={"scope": "all", "reason": "x"})
    finally:
        set_alert_service(None)
    assert response.status_code == 200
    assert client.get("/api/control/status", headers=HEADERS).json()["kill_switch"]["global"]["reason"] == "x"

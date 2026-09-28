# CMN-C2-226 — Entry-adapter authentication tests
#
# Verifies the _ctx() auth core in src/api/server.py:
#   - unauthenticated caller (no verified trust, no token) -> 401 (fail-closed)
#   - INVOKE_AUTH_TOKEN Bearer promotes ANONYMOUS -> VERIFIED_EXTERNAL -> 200
#   - wrong token -> 401
#   - /health needs no auth
#
# The old server defaulted an unauthenticated caller to ANONYMOUS and passed it
# straight into InvocationContext (S-1 fail-open). These tests pin the fix.


import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", "test-entry-token")
    # Import after env is set so the module-level app picks up a clean state.
    from src.api import server

    return TestClient(server.app)


def _payload():
    return {"input": "smoke", "session_id": "auth-test"}


def test_health_requires_no_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_unauthenticated_invoke_is_rejected(client):
    # No Authorization header, no verified middleware trust -> 401 (fail-closed).
    resp = client.post("/invoke", json=_payload())
    assert resp.status_code == 401


def test_wrong_token_is_rejected(client):
    resp = client.post(
        "/invoke", json=_payload(), headers={"Authorization": "Bearer wrong-token"}
    )
    assert resp.status_code == 401


def test_valid_token_is_accepted(client):
    resp = client.post(
        "/invoke",
        json=_payload(),
        headers={"Authorization": "Bearer test-entry-token"},
    )
    # Auth passed -> agent.invoke() runs (200). Business outcome may vary, but the
    # entry gate must not 401/403 a correctly-authenticated caller.
    assert resp.status_code == 200

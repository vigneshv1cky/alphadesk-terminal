"""The shared access token (2026-10-03): one secret in front of a one-person
server that is reachable beyond its own machine."""
import pytest

from alphadesk.app import auth

TOKEN = "t" * 24


@pytest.fixture
def gated(client, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "off")
    monkeypatch.setenv("ALPHADESK_ACCESS_TOKEN", TOKEN)
    auth._attempts.clear()
    # The local account is remembered per process; each test has a fresh database.
    from alphadesk.app import dashboard
    dashboard._local_uid_value = None
    auth._session_states.clear()
    return client


def test_without_a_token_an_open_instance_stays_open(client, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "off")
    monkeypatch.delenv("ALPHADESK_ACCESS_TOKEN", raising=False)
    assert client.get("/api/auth/me").json()["auth_required"] is False
    assert client.get("/api/keys").status_code == 200


def test_data_routes_refuse_until_the_token_is_given(gated):
    me = gated.get("/api/auth/me").json()
    assert me["auth_required"] is True and me["token_login"] is True and me["user"] is None
    assert gated.get("/api/keys").status_code == 401
    assert gated.post("/api/auth/token-login", json={"token": "wrong-" + TOKEN}).status_code == 401
    assert gated.get("/api/keys").status_code == 401
    ok = gated.post("/api/auth/token-login", json={"token": TOKEN})
    assert ok.status_code == 200
    assert gated.get("/api/keys").status_code == 200
    assert gated.get("/api/auth/me").json()["user"] is not None


def test_a_wrong_token_locks_after_five_misses(gated):
    for _ in range(5):
        assert gated.post("/api/auth/token-login", json={"token": "nope"}).status_code == 401
    assert gated.post("/api/auth/token-login", json={"token": TOKEN}).status_code == 429


def test_the_agent_door_keeps_its_own_tokens(gated):
    # Not the access token and not a session: the agent door answers to its own credential.
    assert gated.post("/api/agent/tools/mcp", headers={"Authorization": f"Bearer {TOKEN}"}, json={}).status_code in (401, 403)


def test_the_token_is_ignored_where_accounts_gate(client, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    monkeypatch.setenv("ALPHADESK_ACCESS_TOKEN", TOKEN)
    assert client.post("/api/auth/token-login", json={"token": TOKEN}).status_code == 400


def test_a_short_token_is_refused(monkeypatch):
    monkeypatch.setenv("ALPHADESK_ACCESS_TOKEN", "short")
    assert "at least" in auth.access_token_problem()
    monkeypatch.setenv("ALPHADESK_ACCESS_TOKEN", TOKEN)
    assert auth.access_token_problem() is None

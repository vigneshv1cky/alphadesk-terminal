"""A server with sign-in off must not be reachable through a visited web page (2026-10-03)."""
import pytest

from alphadesk.app import auth


@pytest.fixture
def open_server(client, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "off")
    for k in ("ALPHADESK_ACCESS_TOKEN", "ALPHADESK_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    return client


def test_a_foreign_host_is_refused_on_an_open_server(open_server, monkeypatch):
    monkeypatch.delenv("ALPHADESK_ALLOWED_HOSTS", raising=False)
    assert open_server.get("/api/keys", headers={"host": "evil.example"}).status_code == 400
    assert open_server.get("/api/keys", headers={"host": "localhost:8000"}).status_code == 200
    assert open_server.get("/api/keys", headers={"host": "127.0.0.1:8000"}).status_code == 200
    assert open_server.get("/healthz", headers={"host": "anything"}).status_code in (200, 503)


def test_another_name_can_be_allowed(open_server, monkeypatch):
    monkeypatch.setenv("ALPHADESK_ALLOWED_HOSTS", "desk.lan")
    assert open_server.get("/api/keys", headers={"host": "desk.lan:8000"}).status_code == 200


def test_a_gated_server_does_not_check_the_host(client, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    assert client.get("/api/keys", headers={"host": "evil.example"}).status_code == 401   # the gate, not the host guard


def test_cross_site_writes_are_refused_everywhere(open_server):
    assert open_server.put("/api/board", json={"symbols": [], "active": ""},
                           headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert open_server.put("/api/board", json={"symbols": [], "active": ""},
                           headers={"origin": "https://evil.example"}).status_code == 403
    assert open_server.put("/api/board", json={"symbols": [], "active": ""},
                           headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"}).status_code == 200
    assert open_server.put("/api/board", json={"symbols": [], "active": ""}).status_code == 200   # a program: no browser headers
    assert open_server.get("/api/board", headers={"sec-fetch-site": "cross-site"}).status_code == 200  # reads are not writes


def test_a_nul_in_a_static_path_is_a_404_not_a_500(open_server):
    assert open_server.get("/assets/%00x.js").status_code == 404


def test_the_owner_cannot_be_locked_out_from_another_address(client, store, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    monkeypatch.delenv("ALPHADESK_LOGIN_EMAIL", raising=False)
    auth._attempts.clear()
    store.create_user("u", "me@example.com", auth.hash_password("a-long-password"))
    for _ in range(6):                                           # an attacker, one address
        client.post("/api/auth/login", json={"email": "me@example.com", "password": "wrong"},
                    headers={"x-forwarded-for": "6.6.6.6"})
    assert client.post("/api/auth/login", json={"email": "me@example.com", "password": "wrong"},
                       headers={"x-forwarded-for": "6.6.6.6"}).status_code == 429
    ok = client.post("/api/auth/login", json={"email": "me@example.com", "password": "a-long-password"},
                     headers={"x-forwarded-for": "1.2.3.4"})
    assert ok.status_code == 200


def test_a_new_password_ends_the_old_sessions(client, store, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    monkeypatch.setenv("ALPHADESK_LOGIN_EMAIL", "me@example.com")
    monkeypatch.setenv("ALPHADESK_LOGIN_PASSWORD", "first-long-password")
    monkeypatch.delenv("ALPHADESK_LOGIN_PASSWORD_HASH", raising=False)
    auth._attempts.clear()
    auth._session_states.clear()
    auth.apply_login_from_settings()
    assert client.post("/api/auth/login", json={"email": "me@example.com", "password": "first-long-password"}).status_code == 200
    assert client.get("/api/keys").status_code == 200
    monkeypatch.setenv("ALPHADESK_LOGIN_PASSWORD", "second-long-password")
    assert auth.apply_login_from_settings() == "password set"
    auth._session_states.clear()
    assert client.get("/api/keys").status_code == 401

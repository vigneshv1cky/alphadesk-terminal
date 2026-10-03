"""One user (2026-10-03): where accounts gate, only the login set in the settings may sign in, keep a
session or own an agent token."""
import pytest

from alphadesk.app import auth


@pytest.fixture
def accounts(client, store, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    monkeypatch.delenv("ALPHADESK_LOGIN_EMAIL", raising=False)
    store.create_user("u1", "me@example.com", auth.hash_password("a-long-password"))
    store.create_user("u2", "other@example.com", auth.hash_password("a-long-password"))
    auth._attempts.clear()
    return client


def _login(client, email):
    return client.post("/api/auth/login", json={"email": email, "password": "a-long-password"})


def test_with_no_login_set_every_account_works(accounts):
    assert _login(accounts, "me@example.com").status_code == 200
    assert accounts.get("/api/keys").status_code == 200


def test_only_the_login_signs_in(accounts, monkeypatch):
    monkeypatch.setenv("ALPHADESK_LOGIN_EMAIL", " Me@Example.com ")
    assert _login(accounts, "me@example.com").status_code == 200
    accounts.post("/api/auth/logout")
    r = _login(accounts, "other@example.com")
    assert r.status_code == 403 and accounts.get("/api/keys").status_code == 401


def test_an_open_session_ends_when_it_is_not_the_login(accounts, monkeypatch):
    assert _login(accounts, "other@example.com").status_code == 200
    assert accounts.get("/api/keys").status_code == 200
    monkeypatch.setenv("ALPHADESK_LOGIN_EMAIL", "me@example.com")
    assert accounts.get("/api/keys").status_code == 401


def test_agent_tokens_of_other_accounts_are_refused(store, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    store.create_user("u9", "gone@example.com", "x")
    monkeypatch.setenv("ALPHADESK_LOGIN_EMAIL", "me@example.com")
    assert auth.uid_allowed("u9") is False
    monkeypatch.setenv("ALPHADESK_LOGIN_EMAIL", "gone@example.com")
    assert auth.uid_allowed("u9") is True
    monkeypatch.delenv("ALPHADESK_LOGIN_EMAIL")
    assert auth.uid_allowed("u9") is True


def test_the_login_is_not_enforced_where_sign_in_is_off(monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "off")
    monkeypatch.setenv("ALPHADESK_LOGIN_EMAIL", "me@example.com")
    assert auth.email_allowed("local@alphadesk.invalid") is True

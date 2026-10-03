"""ALPHADESK_ALLOWED_EMAILS (2026-10-03): the people an operator names, and no one else."""
import pytest

from alphadesk.app import auth


@pytest.fixture
def accounts(client, store, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    monkeypatch.delenv("ALPHADESK_ALLOWED_EMAILS", raising=False)
    store.create_user("u1", "me@example.com", auth.hash_password("a-long-password"))
    store.create_user("u2", "other@example.com", auth.hash_password("a-long-password"))
    return client


def _login(client, email):
    return client.post("/api/auth/login", json={"email": email, "password": "a-long-password"})


def test_unset_changes_nothing(accounts):
    assert _login(accounts, "me@example.com").status_code == 200
    assert accounts.get("/api/keys").status_code == 200


def test_a_listed_address_signs_in_and_another_is_refused(accounts, monkeypatch):
    monkeypatch.setenv("ALPHADESK_ALLOWED_EMAILS", " Me@Example.com , friend@example.com ")
    assert _login(accounts, "me@example.com").status_code == 200
    accounts.post("/api/auth/logout")
    r = _login(accounts, "other@example.com")
    assert r.status_code == 403 and accounts.get("/api/keys").status_code == 401


def test_an_open_session_ends_when_the_address_leaves_the_list(accounts, monkeypatch):
    assert _login(accounts, "other@example.com").status_code == 200
    assert accounts.get("/api/keys").status_code == 200
    monkeypatch.setenv("ALPHADESK_ALLOWED_EMAILS", "me@example.com")
    assert accounts.get("/api/keys").status_code == 401


def test_the_list_guards_agent_tokens_too(store, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    store.create_user("u9", "gone@example.com", "sso-only")
    monkeypatch.setenv("ALPHADESK_ALLOWED_EMAILS", "me@example.com")
    assert auth.uid_allowed("u9") is False
    monkeypatch.setenv("ALPHADESK_ALLOWED_EMAILS", "gone@example.com")
    assert auth.uid_allowed("u9") is True
    monkeypatch.delenv("ALPHADESK_ALLOWED_EMAILS")
    assert auth.uid_allowed("u9") is True


def test_the_list_is_ignored_where_sign_in_is_off(monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "off")
    monkeypatch.setenv("ALPHADESK_ALLOWED_EMAILS", "me@example.com")
    assert auth.email_allowed("local@alphadesk.invalid") is True

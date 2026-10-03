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


class TestSharedWorkspace:
    """ALPHADESK_SHARED_ACCOUNT: the allowed people sign in as themselves and act as one account."""

    def _signed_in(self, client, store, monkeypatch, email):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        r = client.post("/api/auth/login", json={"email": email, "password": "a-long-password"})
        assert r.status_code == 200, r.text

    def test_two_people_see_the_same_keys(self, client, store, monkeypatch):
        store.create_user("shared", "team@example.com", "sso-only")
        store.create_user("a", "a@example.com", auth.hash_password("a-long-password"))
        store.create_user("b", "b@example.com", auth.hash_password("a-long-password"))
        store.set_user_key("shared", "news", "alpaca", "sealed", "…abcd")
        monkeypatch.setenv("ALPHADESK_SHARED_ACCOUNT", "team@example.com")
        monkeypatch.setenv("ALPHADESK_ALLOWED_EMAILS", "a@example.com b@example.com")
        for who in ("a@example.com", "b@example.com"):
            self._signed_in(client, store, monkeypatch, who)
            assert [k["provider"] for k in client.get("/api/keys").json()["keys"]] == ["alpaca"]
            assert client.get("/api/auth/me").json()["user"]["email"] == who
            client.post("/api/auth/logout")

    def test_someone_off_the_list_is_refused(self, client, store, monkeypatch):
        store.create_user("shared", "team@example.com", "sso-only")
        store.create_user("c", "c@example.com", auth.hash_password("a-long-password"))
        monkeypatch.setenv("ALPHADESK_SHARED_ACCOUNT", "team@example.com")
        monkeypatch.setenv("ALPHADESK_ALLOWED_EMAILS", "a@example.com")
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        assert client.post("/api/auth/login", json={"email": "c@example.com",
                                                    "password": "a-long-password"}).status_code == 403

    def test_without_a_list_nobody_gets_in(self, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        monkeypatch.setenv("ALPHADESK_SHARED_ACCOUNT", "team@example.com")
        monkeypatch.delenv("ALPHADESK_ALLOWED_EMAILS", raising=False)
        assert auth.email_allowed("a@example.com") is False

    def test_only_the_shared_accounts_agent_tokens_work(self, store, monkeypatch):
        store.create_user("shared", "team@example.com", "sso-only")
        store.create_user("old", "old@example.com", "sso-only")
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        monkeypatch.setenv("ALPHADESK_SHARED_ACCOUNT", "team@example.com")
        monkeypatch.setenv("ALPHADESK_ALLOWED_EMAILS", "a@example.com")
        assert auth.uid_allowed("shared") is True
        assert auth.uid_allowed("old") is False

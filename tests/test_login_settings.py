"""A login set in the settings (2026-10-03): the operator chooses the email and password."""
import pytest

from alphadesk.app import auth

EMAIL, PASSWORD = "me@example.com", "a-long-password-1"


@pytest.fixture
def configured(client, monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    monkeypatch.setenv("ALPHADESK_LOGIN_EMAIL", EMAIL)
    monkeypatch.setenv("ALPHADESK_LOGIN_PASSWORD", PASSWORD)
    monkeypatch.delenv("ALPHADESK_LOGIN_PASSWORD_HASH", raising=False)
    auth._attempts.clear()
    return client


def test_the_account_is_made_and_signs_in_with_the_password(configured, store):
    assert auth.apply_login_from_settings() == "created"
    assert auth.apply_login_from_settings() == "unchanged"               # a restart changes nothing
    r = configured.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200 and configured.get("/api/keys").status_code == 200
    configured.post("/api/auth/logout")
    assert configured.post("/api/auth/login", json={"email": EMAIL, "password": "wrong"}).status_code == 401


def test_an_existing_account_keeps_its_data_and_gains_the_password(configured, store):
    store.create_user("old", EMAIL, "sso-only")                           # made by a Google or GitHub sign-in
    store.set_user_key("old", "news", "alpaca", "sealed", "…abcd")
    assert auth.apply_login_from_settings() == "password set"
    assert configured.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    assert [k["provider"] for k in configured.get("/api/keys").json()["keys"]] == ["alpaca"]


def test_a_hash_works_and_a_changed_password_is_applied(configured, store, monkeypatch):
    monkeypatch.delenv("ALPHADESK_LOGIN_PASSWORD")
    monkeypatch.setenv("ALPHADESK_LOGIN_PASSWORD_HASH", auth.hash_password("another-long-pass-2"))
    assert auth.apply_login_from_settings() == "created"
    assert configured.post("/api/auth/login", json={"email": EMAIL, "password": "another-long-pass-2"}).status_code == 200
    configured.post("/api/auth/logout")
    monkeypatch.setenv("ALPHADESK_LOGIN_PASSWORD_HASH", auth.hash_password("third-long-pass-3"))
    assert auth.apply_login_from_settings() == "password set"
    assert configured.post("/api/auth/login", json={"email": EMAIL, "password": "another-long-pass-2"}).status_code == 401


def test_only_the_configured_login_can_be_used(configured, store):
    """One user: another account, even with a correct password, is refused."""
    store.create_user("other", "other@example.com", auth.hash_password("some-other-password"))
    assert configured.post("/api/auth/login", json={"email": "other@example.com",
                                                    "password": "some-other-password"}).status_code == 403
    assert auth.uid_allowed("other") is False


def test_sign_in_on_with_no_login_set_is_a_start_up_problem(monkeypatch):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    monkeypatch.delenv("ALPHADESK_LOGIN_EMAIL", raising=False)
    assert "no login is set" in auth.login_problem()
    monkeypatch.setenv("ALPHADESK_AUTH", "off")
    assert auth.login_problem() is None


@pytest.mark.parametrize("env,expect", [
    ({"ALPHADESK_LOGIN_EMAIL": "not-an-email", "ALPHADESK_LOGIN_PASSWORD": PASSWORD}, "email address"),
    ({"ALPHADESK_LOGIN_EMAIL": EMAIL}, "needs ALPHADESK_LOGIN_PASSWORD_HASH"),
    ({"ALPHADESK_LOGIN_EMAIL": EMAIL, "ALPHADESK_LOGIN_PASSWORD": "short"}, "at least"),
    ({"ALPHADESK_LOGIN_EMAIL": EMAIL, "ALPHADESK_LOGIN_PASSWORD_HASH": "plain"}, "not a hash"),
])
def test_a_login_that_cannot_work_is_named(monkeypatch, env, expect):
    for k in ("ALPHADESK_LOGIN_EMAIL", "ALPHADESK_LOGIN_PASSWORD", "ALPHADESK_LOGIN_PASSWORD_HASH"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert expect in auth.login_problem()

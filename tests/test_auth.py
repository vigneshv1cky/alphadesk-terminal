"""Hosted-mode auth: COMPULSORY by default (opting out takes an explicit
off). With a Google client configured, Google is the ONLY door and it is
sign-up too — a verified account provisions itself on first sign-in, and
password logins are refused. Without one (self-host, dev), the operator's
password allowlist is the gate. Honest failures, lockout on brute force."""

import pytest

from alphadesk.app import auth


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHADESK_AUTH", "off")
    for env in ("GOOGLE", "GITHUB", "MICROSOFT"):
        monkeypatch.delenv(f"{env}_CLIENT_ID", raising=False)
        monkeypatch.delenv(f"{env}_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("ALPHADESK_SECRET", "test-secret-not-for-production")
    auth.reset_for_tests()
    yield
    auth.reset_for_tests()


def _add_user(store, email="reader@example.com", password="a-long-password"):
    import uuid
    store.create_user(uuid.uuid4().hex, email, auth.hash_password(password))
    return email, password


class TestPasswords:
    def test_hash_verifies_and_rejects(self):
        h = auth.hash_password("correct horse battery")
        assert auth.verify_password("correct horse battery", h)
        assert not auth.verify_password("wrong", h)
        assert h.startswith("scrypt$")
        assert "correct" not in h

    def test_two_hashes_differ(self):
        assert auth.hash_password("x" * 12) != auth.hash_password("x" * 12)

    def test_garbage_stored_value_never_verifies(self):
        assert not auth.verify_password("anything", "not-a-hash")
        assert not auth.verify_password("anything", "")


class TestSessions:
    def test_round_trip(self):
        token = auth.issue_session("u1", "a@b.c")
        claims = auth.read_session(token)
        assert claims["uid"] == "u1" and claims["email"] == "a@b.c"

    def test_tampering_invalidates(self):
        token = auth.issue_session("u1", "a@b.c")
        payload, mac = token.split(".")
        # Flip a byte INSIDE the payload — appending after base64 padding
        # decodes to the same bytes and rightly still verifies.
        flipped = payload[0] + ("A" if payload[1] != "A" else "B") + payload[2:]
        assert auth.read_session(flipped + "." + mac) is None
        assert auth.read_session(payload + "." + mac[:-2]) is None
        assert auth.read_session("") is None
        assert auth.read_session(None) is None

    def test_expiry(self, monkeypatch):
        token = auth.issue_session("u1", "a@b.c")
        import time
        monkeypatch.setattr(time, "time", lambda: time.mktime((2999, 1, 1, 0, 0, 0, 0, 1, -1)))
        assert auth.read_session(token) is None


class TestGate:
    def test_compulsory_by_default(self, monkeypatch):
        """No setting at all means GATED — opting out takes an explicit off."""
        monkeypatch.delenv("ALPHADESK_AUTH", raising=False)
        assert auth.auth_required()
        monkeypatch.setenv("ALPHADESK_AUTH", "off")
        assert not auth.auth_required()

    def test_opted_out_instance_is_open(self, client):
        assert client.get("/api/system").status_code == 200
        assert client.get("/api/auth/me").json() == {
            "auth_required": False, "token_login": False, "user": None}

    def test_login_on_an_open_instance_is_a_400(self, client):
        r = client.post("/api/auth/login", json={"email": "a@b.c", "password": "x"})
        assert r.status_code == 400

    def test_gated_data_routes_401_without_a_session(self, client, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        assert client.get("/api/system").status_code == 401
        assert client.get("/api/news").status_code == 401
        # The shell and the auth surface stay reachable.
        assert client.get("/api/auth/me").status_code == 200
        assert client.get("/healthz").status_code in (200, 503)

    def test_login_flow_end_to_end(self, client, store, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        email, password = _add_user(store)
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200
        assert client.get("/api/system").status_code == 200          # cookie carried
        me = client.get("/api/auth/me").json()
        assert me["user"]["email"] == email
        client.post("/api/auth/logout")
        assert client.get("/api/system").status_code == 401

    def test_wrong_password_and_unknown_email_read_the_same(self, client, store, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        email, _ = _add_user(store)
        wrong = client.post("/api/auth/login", json={"email": email, "password": "nope-nope"})
        unknown = client.post("/api/auth/login", json={"email": "ghost@x.y", "password": "nope-nope"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    def test_lockout_after_five_failures(self, client, store, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        email, password = _add_user(store)
        for _ in range(5):
            assert client.post("/api/auth/login",
                               json={"email": email, "password": "bad"}).status_code == 401
        # The right password is now refused too, with the throttle status.
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 429

    def test_disabled_flag_blocks_login(self, client, store, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        email, password = _add_user(store)
        with store._connect() as conn:
            conn.execute("UPDATE users SET disabled=1 WHERE email=?", (email,))
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 401


class TestSessionLifecycle:
    @staticmethod
    def _configure(monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")

    def test_logout_all_kills_the_other_devices_cookie(self, client, store, monkeypatch):
        """The session-version stamp: bump the row and every cookie issued
        before it — another device's included — stops verifying."""
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        email, password = _add_user(store)
        client.post("/api/auth/login", json={"email": email, "password": password})
        other_device = client.cookies.get(auth.SESSION_COOKIE)   # a second browser's copy
        assert client.get("/api/system").status_code == 200
        client.post("/api/auth/logout-all")
        client.cookies.set(auth.SESSION_COOKIE, other_device)
        assert client.get("/api/system").status_code == 401
        # Signing back in works and gets the NEW version.
        client.cookies.delete(auth.SESSION_COOKIE)
        client.post("/api/auth/login", json={"email": email, "password": password})
        assert client.get("/api/system").status_code == 200

    def test_disabling_an_account_kills_its_live_sessions(self, client, store, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        email, password = _add_user(store)
        client.post("/api/auth/login", json={"email": email, "password": password})
        assert client.get("/api/system").status_code == 200
        with store._connect() as conn:
            conn.execute("UPDATE users SET disabled=1 WHERE email=?", (email,))
        auth._session_states.clear()          # the ~30s cache TTL, elapsed
        assert client.get("/api/system").status_code == 401

    def test_a_pre_stamp_cookie_stays_valid_until_a_bump(self, client, store, monkeypatch):
        """Legacy cookies carry an implicit version 1 and rows start at 1,
        so the stamp's arrival signs nobody out — only a bump does."""
        import json as _json
        import time as _time
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        email, password = _add_user(store)
        user = store.get_user_by_email(email)
        legacy = auth._sign(_json.dumps({"uid": user["user_id"], "email": email,
                                         "exp": int(_time.time()) + 3600}).encode())
        client.cookies.set(auth.SESSION_COOKIE, legacy)
        assert client.get("/api/system").status_code == 200
        auth.invalidate_sessions(user["user_id"])
        assert client.get("/api/system").status_code == 401

    def test_sso_only_account_cannot_use_the_password_form(self, client, store, monkeypatch):
        # Google unconfigured here, so the password form IS the door — and
        # the sso-only sentinel still never verifies through it.
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        store.create_user("u1", "reader@example.com", "sso-only")
        r = client.post("/api/auth/login",
                        json={"email": "reader@example.com", "password": "sso-only"})
        assert r.status_code == 401

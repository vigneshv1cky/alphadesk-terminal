"""Exporting a reader's vendor keys as a passphrase-sealed file (2026-10-02).

The vault's rule is that a key is never shown after entry. An export is the
one deliberate exception, so what it hands out must be useless without the
passphrase, must say nothing about the keys when it fails, and must not be
reachable by anything but the reader's own freshly signed-in browser session.
"""

import base64
import json

import pytest

from alphadesk.ledger import keyexport

PASSPHRASE = "correct horse battery"
PAYLOAD = {"keys": [{"seam": "prices", "provider": "alpaca",
                     "api_key": "AK-super-secret-1111", "api_secret": "AS-super-secret-2222"}]}


class TestFile:
    def test_round_trip_and_the_file_holds_no_plaintext(self):
        text = keyexport.seal(PAYLOAD, PASSPHRASE)
        assert "super-secret" not in text and "alpaca" not in text
        assert keyexport.open_file(text, PASSPHRASE) == PAYLOAD

    def test_two_seals_of_the_same_keys_differ(self):
        assert keyexport.seal(PAYLOAD, PASSPHRASE) != keyexport.seal(PAYLOAD, PASSPHRASE)

    def test_a_short_passphrase_is_refused_before_anything_is_sealed(self):
        with pytest.raises(keyexport.KeyFileError, match="at least 12"):
            keyexport.seal(PAYLOAD, "short")

    def test_a_wrong_passphrase_fails_without_leaking_anything(self):
        text = keyexport.seal(PAYLOAD, PASSPHRASE)
        with pytest.raises(keyexport.KeyFileError) as err:
            keyexport.open_file(text, "another passphrase")
        assert "super-secret" not in str(err.value)

    def test_a_flipped_byte_in_the_contents_fails_like_a_wrong_passphrase(self):
        doc = json.loads(keyexport.seal(PAYLOAD, PASSPHRASE))
        raw = bytearray(base64.b64decode(doc["ciphertext"]))
        raw[0] ^= 0x01
        doc["ciphertext"] = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(keyexport.KeyFileError):
            keyexport.open_file(json.dumps(doc), PASSPHRASE)

    def test_the_header_is_covered_so_it_cannot_be_weakened(self):
        """An attacker who could lower the work factor in the header would make
        guessing the passphrase cheap. The header is authenticated, so editing
        it breaks the file instead."""
        doc = json.loads(keyexport.seal(PAYLOAD, PASSPHRASE))
        doc["kdf"]["n"] = 1024
        with pytest.raises(keyexport.KeyFileError):
            keyexport.open_file(json.dumps(doc), PASSPHRASE)

    def test_a_file_cannot_demand_unbounded_memory(self):
        """Opening reads the work factor from the file. A hostile file asking
        for an enormous one must be refused, not obeyed."""
        doc = json.loads(keyexport.seal(PAYLOAD, PASSPHRASE))
        doc["kdf"]["n"] = 2 ** 30
        with pytest.raises(keyexport.KeyFileError, match="work factor"):
            keyexport.open_file(json.dumps(doc), PASSPHRASE)

    def test_anything_that_is_not_our_file_is_refused(self):
        for junk in ("", "not json", "[]", json.dumps({"format": "something-else"})):
            with pytest.raises(keyexport.KeyFileError):
                keyexport.open_file(junk, PASSPHRASE)


# ── the endpoint ───────────────────────────────────────────────────────────

import logging
import time
import uuid

MASTER = base64.b64encode(b"\x07" * 32).decode()


@pytest.fixture(autouse=True)
def _vault_env(monkeypatch):
    monkeypatch.setenv("ALPHADESK_VAULT_KEY", MASTER)
    yield


@pytest.fixture
def _fresh_limiter():
    from alphadesk.app import dashboard
    dashboard.export_limiter._hits.clear()
    yield
    dashboard.export_limiter._hits.clear()


def _sign_in(client, store, monkeypatch) -> str:
    """A gated instance with one password account, signed in. Returns its id."""
    from alphadesk.app import auth
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    email, password = "reader@example.com", "a-long-password"
    uid = uuid.uuid4().hex
    store.create_user(uid, email, auth.hash_password(password))
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200
    return uid


def _store_key(client, key="AK-super-secret-1111", secret="AS-super-secret-2222"):
    r = client.put("/api/keys/prices", json={"provider": "alpaca", "api_key": key, "api_secret": secret})
    assert r.status_code == 200, r.text


def _export(client, passphrase=PASSPHRASE, **headers):
    return client.post("/api/keys/export", json={"passphrase": passphrase}, headers=headers)


@pytest.mark.usefixtures("_fresh_limiter")
class TestExportEndpoint:
    def test_anonymous_is_refused(self, client, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        assert _export(client).status_code == 401

    def test_a_fresh_session_gets_a_file_that_opens_with_the_passphrase(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        _store_key(client)
        r = _export(client)
        assert r.status_code == 200
        assert "super-secret" not in r.text                  # sealed on the wire too
        assert "attachment" in r.headers["content-disposition"]
        assert "alphadesk-keys" in r.headers["content-disposition"]
        assert "no-store" in r.headers["cache-control"]
        keys = keyexport.open_file(r.text, PASSPHRASE)["keys"]
        assert keys == [{"seam": "prices", "provider": "alpaca", "api_key": "AK-super-secret-1111",
                         "api_secret": "AS-super-secret-2222", "base_url": "", "model": "", "plan": "free"}]

    def test_a_short_passphrase_is_refused(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        _store_key(client)
        assert _export(client, "short").status_code == 422

    def test_an_old_session_must_sign_in_again(self, client, store, monkeypatch):
        """A stolen cookie is the threat. The download wants a session made in
        the last few minutes, so a cookie that has been around cannot do it."""
        from alphadesk.app import auth
        _sign_in(client, store, monkeypatch)
        _store_key(client)
        claims = auth.read_session(client.cookies.get(auth.SESSION_COOKIE))
        claims["exp"] = int(time.time()) + auth.SESSION_TTL_S - 3600     # issued an hour ago
        client.cookies.set(auth.SESSION_COOKIE, auth._sign(json.dumps(claims).encode()))
        r = _export(client)
        assert r.status_code == 403
        assert r.json()["reauth"] is True and "sign in again" in r.json()["detail"]
        assert "super-secret" not in r.text

    def test_another_site_cannot_post_for_the_reader(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        _store_key(client)
        assert _export(client, Origin="https://evil.example").status_code == 403

    def test_an_agent_token_can_never_export(self, client, store, monkeypatch):
        """Tokens are for data. If one could export, the API built for a bot
        would also be the way to walk off with every vendor key."""
        from alphadesk.app import agent_access
        uid = _sign_in(client, store, monkeypatch)
        _store_key(client)
        _, token = agent_access.issue(uid, "bot")
        client.cookies.clear()
        r = _export(client, Authorization=f"Bearer {token}")
        assert r.status_code == 401

    def test_nothing_stored_is_a_404_not_an_empty_file(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        assert _export(client).status_code == 404

    def test_vault_off_is_an_honest_503(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        _store_key(client)
        monkeypatch.delenv("ALPHADESK_VAULT_KEY")
        assert _export(client).status_code == 503

    def test_exports_are_rate_limited(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        _store_key(client)
        assert [_export(client).status_code for _ in range(5)] == [200] * 5
        r = _export(client)
        assert r.status_code == 429 and "retry-after" in r.headers

    def test_an_export_is_logged_without_its_contents(self, client, store, monkeypatch, caplog):
        _sign_in(client, store, monkeypatch)
        _store_key(client)
        with caplog.at_level(logging.INFO):
            assert _export(client).status_code == 200
        text = " ".join(rec.getMessage() for rec in caplog.records)
        assert "keys exported" in text and "1 key" in text
        assert "super-secret" not in text and PASSPHRASE not in text

    def test_an_open_local_instance_exports_on_the_passphrase_alone(self, client, store, monkeypatch):
        """With sign-in off there is no one to re-confirm; the passphrase is
        the only protection, and the file is still sealed."""
        monkeypatch.setenv("ALPHADESK_AUTH", "off")
        uid = store.ensure_local_user()
        from alphadesk.ledger import vault
        store.set_user_key(uid, "prices", "alpaca",
                           vault.encrypt({"api_key": "AK-super-secret-1111", "api_secret": ""}), "1111")
        r = _export(client)
        assert r.status_code == 200 and "super-secret" not in r.text


# ── using the file elsewhere ───────────────────────────────────────────────

class TestRestore:
    """The other end of an export: a file opened with its passphrase goes back
    into an account, sealed under THAT instance's own vault key."""

    def _payload(self, *entries):
        return {"exported_at": "2026-10-02T00:00:00+00:00", "keys": list(entries)}

    def _entry(self, **over):
        base = {"seam": "prices", "provider": "alpaca", "api_key": "AK-super-secret-1111",
                "api_secret": "AS-super-secret-2222", "base_url": "", "model": "", "plan": "free"}
        return {**base, **over}

    def test_keys_go_back_in_sealed_with_their_plan_and_hint(self, store):
        from alphadesk.ledger import vault
        store.create_user("u2", "other@example.com", "sso-only")
        restored, skipped = keyexport.restore("u2", self._payload(
            self._entry(), self._entry(seam="news", provider="polygon", api_key="PK-9999-aaaa", api_secret="", plan="paid")))
        assert sorted(restored) == ["news:polygon", "prices:alpaca"] and skipped == []
        listing = {(k["seam"], k["provider"]): k for k in store.list_user_keys("u2")}
        assert listing[("prices", "alpaca")]["key_hint"] == "1111"
        assert listing[("news", "polygon")]["vendor_plan"] == "paid"
        sealed = store.get_user_keys("u2", "prices")[0]["config"]
        assert "super-secret" not in sealed
        assert vault.decrypt(sealed)["api_secret"] == "AS-super-secret-2222"

    def test_a_vendor_this_instance_does_not_know_is_skipped_by_name(self, store):
        store.create_user("u2", "other@example.com", "sso-only")
        restored, skipped = keyexport.restore("u2", self._payload(self._entry(provider="no-such-vendor")))
        assert restored == [] and skipped == ["prices:no-such-vendor"]
        assert store.list_user_keys("u2") == []

    def test_entries_that_would_be_refused_on_entry_are_refused_here(self, store):
        store.create_user("u2", "other@example.com", "sso-only")
        restored, skipped = keyexport.restore("u2", self._payload(
            self._entry(api_key="x"), self._entry(seam="wat"), {"seam": "prices"}))
        assert restored == [] and len(skipped) == 3
        assert store.list_user_keys("u2") == []

    def test_a_round_trip_through_the_file_loses_nothing(self, client, store, monkeypatch):
        """Export from one account, open the file, restore into another."""
        _sign_in(client, store, monkeypatch)
        _store_key(client)
        text = _export(client).text
        store.create_user("u3", "third@example.com", "sso-only")
        restored, _ = keyexport.restore("u3", keyexport.open_file(text, PASSPHRASE))
        assert restored == ["prices:alpaca"]


class TestCommandLine:
    """`python -m alphadesk.main keys decrypt FILE` and `keys import-file FILE`.
    The passphrase is only ever asked for at the prompt — never taken from an
    argument or the environment, where it would sit in shell history."""

    def _file(self, tmp_path):
        path = tmp_path / "alphadesk-keys.json"
        path.write_text(keyexport.seal(PAYLOAD, PASSPHRASE))
        return str(path)

    def test_decrypt_prints_the_keys_and_warns_on_stderr(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("getpass.getpass", lambda prompt="": PASSPHRASE)
        assert keyexport.run_cli("decrypt", self._file(tmp_path)) == 0
        out, err = capsys.readouterr()
        assert json.loads(out)["keys"] == PAYLOAD["keys"]
        assert "plain text" in err                       # said where it will not be piped

    def test_a_wrong_passphrase_exits_nonzero_and_leaks_nothing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("getpass.getpass", lambda prompt="": "not the passphrase")
        assert keyexport.run_cli("decrypt", self._file(tmp_path)) == 1
        out, err = capsys.readouterr()
        assert out == "" and "super-secret" not in err and "wrong passphrase" in err

    def test_a_missing_file_is_a_plain_message(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("getpass.getpass", lambda prompt="": PASSPHRASE)
        assert keyexport.run_cli("decrypt", str(tmp_path / "nope.json")) == 1
        assert "cannot read" in capsys.readouterr().err

    def test_import_file_seals_the_keys_into_the_local_account(self, tmp_path, store, monkeypatch, capsys):
        monkeypatch.setattr("getpass.getpass", lambda prompt="": PASSPHRASE)
        assert keyexport.run_cli("import-file", self._file(tmp_path)) == 0
        rows = store.list_user_keys(store.ensure_local_user())
        assert [(r["seam"], r["provider"], r["key_hint"]) for r in rows] == [("prices", "alpaca", "1111")]
        out = capsys.readouterr().out
        assert "prices:alpaca" in out and "super-secret" not in out

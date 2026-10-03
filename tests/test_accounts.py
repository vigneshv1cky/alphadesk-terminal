"""Deleting an account removes everything it holds (store.delete_account)."""
import re
import uuid
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("ALPHADESK_SECRET", "test-secret-not-for-production")


def _sign_in(client, store, monkeypatch, email="reader@example.com"):
    from alphadesk.app import auth
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    uid = uuid.uuid4().hex
    store.create_user(uid, email, auth.hash_password("a-long-password"))
    assert client.post("/api/auth/login", json={"email": email, "password": "a-long-password"}).status_code == 200
    return uid


def _fill(store, uid):
    """One row in every per-account table."""
    with store._lock, store._connect() as conn:
        conn.execute("INSERT INTO user_sign_ins (user_id, method) VALUES (?, 'github')", (uid,))
        conn.execute("INSERT INTO user_views (user_id, view_id, name, layout, position) VALUES (?, 'v1', 'n', '', 0)", (uid,))
        conn.execute("INSERT INTO news_articles (owner, article_id, title) VALUES (?, 'a1', 't')", (uid,))
        conn.execute("INSERT INTO earnings_forecasts (owner, vendor, symbol, captured_on, report_date) VALUES (?, 'fmp', 'A', '2026-09-01', '2026-09-02')", (uid,))
        conn.execute("INSERT INTO reader_dollar_pools (owner, vendor, symbols, built_at) VALUES (?, 'alpaca', '[]', 1)", (uid,))
    store.set_user_key(uid, "news", "polygon", "sealed", "…abcd")
    store.set_chart_state(uid, "prefs", "{}")


def _count(store, uid):
    total = 0
    with store._connect() as conn:
        for t in store._ACCOUNT_TABLES_BY_USER + ("users",):
            total += conn.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE user_id=?", (uid,)).fetchone()["n"]
        for t in store._ACCOUNT_TABLES_BY_OWNER:
            total += conn.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE owner=?", (uid,)).fetchone()["n"]
    return total


def test_every_per_account_table_is_on_the_deletion_list(store):
    """A new table keyed by account must be added to the deletion lists."""
    schema = Path(store.__file__).read_text()
    keyed = set()
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", schema, re.S):
        cols = {line.strip().split()[0] for line in body.splitlines() if line.strip()}
        if name != "users" and ("user_id" in cols or "owner" in cols):
            keyed.add(name)
    assert keyed == set(store._ACCOUNT_TABLES_BY_USER) | set(store._ACCOUNT_TABLES_BY_OWNER)


def test_delete_account_removes_everything_and_nobody_else(store):
    store.create_user("u1", "a@b.c", "sso-only")
    store.create_user("u2", "d@e.f", "sso-only")
    _fill(store, "u1")
    _fill(store, "u2")
    before_other = _count(store, "u2")
    assert _count(store, "u1") > 0
    assert store.delete_account("u1")["users"] == 1
    assert _count(store, "u1") == 0
    assert _count(store, "u2") == before_other
    assert store.delete_account("u1") is None

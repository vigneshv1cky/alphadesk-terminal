"""ALPHADESK_PURGE_OTHER_ACCOUNTS: every account but the login, whole, and only when asked."""
import pytest

from alphadesk.ledger import purge


@pytest.fixture
def accounts(store, monkeypatch):
    store.create_user("keep", "me@example.com", "x")
    for i in range(3):
        uid = f"other{i}"
        store.create_user(uid, f"o{i}@example.com", "x")
        store.set_user_key(uid, "news", "alpaca", "sealed", "…abcd")
        with store._lock, store._connect() as conn:
            conn.execute("INSERT INTO news_articles (owner, article_id, title, feeds) VALUES (?, 'a', 't', 'alpaca')", (uid,))
    store.set_user_key("keep", "news", "alpaca", "sealed", "…keep")
    monkeypatch.delenv("ALPHADESK_PURGE_OTHER_ACCOUNTS", raising=False)
    return store


def _emails(store):
    return sorted(u["email"] for u in store.list_users())


def test_nothing_happens_unless_asked(accounts):
    purge.run_at_start("me@example.com")
    assert len(_emails(accounts)) == 4


def test_count_only_reports(accounts, monkeypatch, caplog):
    monkeypatch.setenv("ALPHADESK_PURGE_OTHER_ACCOUNTS", "count")
    with caplog.at_level("INFO", logger="alphadesk.purge"):
        purge.run_at_start("me@example.com")
    assert "3 accounts besides the login" in caplog.text and len(_emails(accounts)) == 4


def test_delete_removes_the_others_whole_and_keeps_the_login(accounts, monkeypatch):
    monkeypatch.setenv("ALPHADESK_PURGE_OTHER_ACCOUNTS", "delete")
    purge.run_at_start("me@example.com")
    assert _emails(accounts) == ["me@example.com"]
    assert [k["provider"] for k in accounts.get_user_keys("keep", "news")] == ["alpaca"]
    with accounts._connect() as conn:
        assert [r["owner"] for r in conn.execute("SELECT owner FROM news_articles")] == []
    assert accounts.get_user_keys("other0", "news") == []


def test_a_missing_login_account_deletes_nothing(accounts, monkeypatch):
    monkeypatch.setenv("ALPHADESK_PURGE_OTHER_ACCOUNTS", "delete")
    purge.run_at_start("nobody@example.com")
    assert len(_emails(accounts)) == 4


def test_an_unknown_value_deletes_nothing(accounts, monkeypatch):
    monkeypatch.setenv("ALPHADESK_PURGE_OTHER_ACCOUNTS", "yes")
    purge.run_at_start("me@example.com")
    assert len(_emails(accounts)) == 4

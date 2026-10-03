"""The Postgres leg of the store, run only where a server is offered.

Set ALPHADESK_TEST_DATABASE_URL to a postgres:// URL and this exercises the
same store module against it — the adapter routes per call, so no reload
dance is needed. Skipped otherwise: the default suite stays zero-
infrastructure, which is the SQLite contract.

The full round-trip (every store surface, double-init idempotence, the
earnings COALESCE behavior) lives in the deployment verification; this
keeps a representative slice in the suite so a dialect regression fails a
gated CI leg rather than a deploy.
"""

import os

import pytest

URL = os.environ.get("ALPHADESK_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not URL, reason="no ALPHADESK_TEST_DATABASE_URL — Postgres leg not offered")


@pytest.fixture()
def pg_store(monkeypatch):
    monkeypatch.setenv("ALPHADESK_DATABASE_URL", URL)
    from alphadesk.ledger import db, store
    assert db.backend() == "postgres"
    store.init()
    yield store
    # Leave the database empty for the next run.
    with store._connect() as conn:
        for t in ("earnings", "news_articles", "news_tickers", "vendor_cache",
                  "filings", "filing_text_cache",
                  "users"):
            conn.execute(f"DELETE FROM {t}")


def test_init_twice_is_idempotent(pg_store):
    pg_store.init()


def test_article_upsert_and_read(pg_store):
    pg_store.save_articles([{"id": "a1", "title": "T1", "tickers": ["NVDA"],
                             "published_at": "2026-09-01T10:00:00+00:00"}])
    pg_store.save_articles([{"id": "a1", "title": "CHANGED", "tickers": ["NVDA"],
                             "published_at": "2026-09-01T10:00:00+00:00"}])
    arts = pg_store.recent_articles("2026-09-01T00:00:00+00:00")
    assert len(arts) == 1 and arts[0]["title"] == "T1"



def test_users_round_trip(pg_store):
    pg_store.create_user("u1", "a@b.c", "scrypt$x$y")
    assert pg_store.get_user_by_email("A@B.C")["user_id"] == "u1"


def test_the_symbol_side_table_the_kept_answers_and_the_search_indexes(pg_store):
    """The 2026-10-03 additions, on the engine the live server runs."""
    import json
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    pg_store.save_articles([
        {"id": f"p{i}", "title": f"robinhood rates {i}", "url": f"https://x/{i}",
         "published_at": (now - timedelta(minutes=i)).isoformat(),
         "tickers": ["HOOD"] if i % 2 == 0 else ["AAPL"], "body": "text" if i == 0 else None, "feeds": ["alpaca"]}
        for i in range(6)], owner="u")
    got = pg_store.articles_for_symbol("u", "hood", limit=10, body=False)
    assert [a["article_id"] for a in got] == ["p0", "p2", "p4"]
    assert got[0]["has_body"] is True and got[1]["has_body"] is False and "body" not in got[0]
    assert [a["article_id"] for a in pg_store.articles_before("u", (now + timedelta(days=1)).isoformat(), 10, "robinhood", body=False)][:2] == ["p0", "p1"]
    pg_store.vendor_cache_put("u", "alpaca", "fundamentals", "k", json.dumps({"a": 1}))
    pg_store.vendor_cache_put("u", "alpaca", "fundamentals", "k", json.dumps({"a": 2}))     # an upsert, not a clash
    assert json.loads(pg_store.vendor_cache_get("u", "alpaca", "fundamentals", "k")[0]) == {"a": 2}
    assert pg_store.ensure_search_indexes() == len(pg_store._POSTGRES_SEARCH_DDL)
    assert pg_store.ensure_search_indexes() == len(pg_store._POSTGRES_SEARCH_DDL)            # idempotent

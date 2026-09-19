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
        for t in ("earnings", "news_articles",
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


def test_earnings_upsert_preserves_armed_columns(pg_store):
    pg_store.upsert_earnings([{"symbol": "nvda", "report_date": "2026-09-03",
                               "session": "AMC", "eps_estimate": 1.0,
                               "market_cap": 5e12, "company_name": "NVIDIA"}])
    pg_store.update_earnings_arm("NVDA", "2026-09-03", pre_close=100.0, implied=5.0)
    pg_store.upsert_earnings([{"symbol": "nvda", "report_date": "2026-09-03",
                               "session": "AMC", "eps_estimate": 1.1,
                               "market_cap": 5e12}])
    up = pg_store.upcoming_earnings(7)
    assert up and up[0]["pre_report_close"] == 100.0
    assert pg_store.earnings_between("2026-09-01", "2026-09-10")[0]["company_name"] == "NVIDIA"


def test_users_round_trip(pg_store):
    pg_store.create_user("u1", "a@b.c", "scrypt$x$y")
    assert pg_store.get_user_by_email("A@B.C")["user_id"] == "u1"

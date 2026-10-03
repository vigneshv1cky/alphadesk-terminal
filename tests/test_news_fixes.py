"""Fixes from the 2026-10-03 review: backfill depth, refusal wording, older pages after a prune,
the poll cursor's inputs, the retention clamp and what counts as being seen."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from alphadesk.ingest import news
from alphadesk.providers.base import Article


def _art(i, when):
    return Article(id=f"a{i}", title=f"t{i}", url=f"https://x/{i}", published_at=when.isoformat(), symbols=["AAPL"])


def test_a_busy_day_is_walked_in_pages_not_capped_at_one(store, monkeypatch):
    uid = uuid.uuid4().hex
    store.set_user_key(uid, "news", "alpaca", "sealed", "…abcd")
    now = datetime.now(timezone.utc)
    pool = [_art(i, now - timedelta(minutes=i)) for i in range(900)]     # 900 stories inside one day, newest first

    class Feed:
        asks = 0

        def fetch(self, since, limit=200, until=None, symbols=None):
            Feed.asks += 1
            rows = [a for a in pool if datetime.fromisoformat(a.published_at) < until
                    and datetime.fromisoformat(a.published_at) >= since]
            return rows[:limit]

    monkeypatch.setattr(news, "_user_news_provider", lambda *a, **k: Feed())
    assert news.backfill_user(uid, "alpaca", days=1) == 900
    assert Feed.asks >= 3                                                  # more than one page of 400


@pytest.mark.parametrize("text,refused", [
    ("alpaca news fetch failed: <html><title>401 Authorization Required</title>", True),
    ('{"code":40110000,"message":"request is not authorized"}', True),
    ("Unknown API Key", True),
    ("403 Forbidden", True),
    ("timed out", False),
    ("returned 14012 rows", False),
    ("", False),
])
def test_refusal_wording(text, refused):
    assert news._refused(text) is refused


def test_older_pages_can_be_refetched_after_the_store_forgot_them(store, monkeypatch):
    """The older-page path used the poll's seen-id set, so stories pruned from the store were
    never fetched again until a restart."""
    uid = uuid.uuid4().hex
    store.set_user_key(uid, "news", "alpaca", "sealed", "…abcd")
    when = datetime.now(timezone.utc) - timedelta(days=3)

    class Feed:
        def fetch(self, since, limit=200, until=None, symbols=None):
            return [_art(1, when)]

    monkeypatch.setattr(news, "_user_news_provider", lambda *a, **k: Feed())
    before = datetime.now(timezone.utc).isoformat()
    assert len(news.older_articles(uid, before, limit=10)) == 1
    with store._lock, store._connect() as conn:                          # pruned
        conn.execute("DELETE FROM news_articles WHERE owner=?", (uid,))
    assert len(news.older_articles(uid, before, limit=10)) == 1          # fetched again, not hidden


def test_an_eastern_clock_reading_is_converted_to_utc_for_polygon():
    from zoneinfo import ZoneInfo

    from alphadesk.providers.news import _utc
    eastern = datetime(2026, 10, 3, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _utc(eastern).strftime("%H") == "13"
    assert _utc(datetime(2026, 10, 3, 9, 0)).strftime("%H") == "09"      # naive: taken as UTC


def test_a_failed_feed_is_reported_so_the_poll_cursor_holds(monkeypatch):
    news._feed_errors.clear()
    assert news.has_feed_problem("u1") is False
    news._feed_errors[("u1", "alpaca")] = "401"
    assert news.has_feed_problem("u1") is True and news.has_feed_problem("u2") is False
    news._feed_errors.clear()


@pytest.mark.parametrize("value,expect", [("1e12", 36500.0), ("inf", 36500.0), ("nan", None), ("-5", None), ("0", None)])
def test_keep_data_cannot_overflow_the_prune(monkeypatch, value, expect):
    import importlib

    import alphadesk.config as config
    monkeypatch.setenv("ALPHADESK_KEEP_DATA", value)
    try:
        assert importlib.reload(config).KEEP_DATA_DAYS == expect
    finally:
        monkeypatch.delenv("ALPHADESK_KEEP_DATA", raising=False)
        importlib.reload(config)


def test_only_a_person_is_seen_not_a_replay_or_a_probe(client, store, monkeypatch):
    from alphadesk.app import dashboard
    seen = []
    monkeypatch.setattr(dashboard, "_touch_seen", seen.append)
    monkeypatch.setenv("ALPHADESK_AUTH", "off")
    client.get("/api/keys")
    assert len(seen) == 1
    client.get("/api/keys", headers={"x-alphadesk-prewarm": "1"})
    client.get("/healthz")
    assert len(seen) == 1

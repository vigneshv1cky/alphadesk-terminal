"""THE CATALYST TAPE (2026-09-22): four feeds in one time-ordered list.

Most of these are about TIME and about CONCURRENCY, which is where the two
real bugs were."""

import threading
import time

from alphadesk.ingest import catalysts


def test_a_halt_time_is_given_the_offset_the_exchange_left_off():
    """The exchange writes "2026-09-22T14:54:49" and means New York. Merged
    bare it would be read as UTC, and every halt would sort four hours late
    — ahead of filings that actually preceded it."""
    at = catalysts._et_instant("2026-09-22T14:54:49")
    assert at is not None and ("-04:00" in at or "-05:00" in at)
    assert at.startswith("2026-09-22T14:54:49")
    assert catalysts._et_instant(None) is None
    assert catalysts._et_instant("not a time") is None


def test_a_day_stamped_row_never_outranks_a_real_moment_on_its_own_day(monkeypatch):
    """A date is not a time. The Federal Register publishes once a day, so
    its row sorts to the START of its day and falls below that day's timed
    rows — the most that can honestly be said about their order."""
    monkeypatch.setattr(catalysts, "_filings",
                        lambda limit: [catalysts._row("filings", "8-K", "Morning filing",
                                                      "2026-09-22T09:31:00-04:00", "second")])
    monkeypatch.setattr(catalysts, "_government",
                        lambda limit: [catalysts._row("government", "Rule", "A rule",
                                                      "2026-09-22", "day")])
    out = catalysts.tape(feeds=["filings", "government"])
    assert [r["title"] for r in out["rows"]] == ["Morning filing", "A rule"]
    assert [r["precision"] for r in out["rows"]] == ["second", "day"]


def test_a_feed_that_is_switched_off_says_so_rather_than_looking_quiet(monkeypatch):
    """Halts and social run on scraped sources the reader may not have. An
    empty tape must never be mistaken for a market where nothing happened."""
    monkeypatch.setattr(catalysts, "_filings", lambda limit: [])
    monkeypatch.setattr(catalysts, "_government", lambda limit: [])
    out = catalysts.tape()
    assert "not switched on" in out["unavailable"]["halts"]
    assert "not switched on" in out["unavailable"]["social"]
    assert "nasdaq" in out["unavailable"]["halts"]


def test_a_feed_past_the_deadline_is_named_and_left_running(monkeypatch):
    """The endpoint answers rather than holding a request worker — the fault
    that took this service down twice. The slow read keeps going, because it
    is filling its own cache for the next poll."""
    started = threading.Event()
    monkeypatch.setattr(catalysts, "DEADLINE_S", 0.2)
    monkeypatch.setattr(catalysts, "_government", lambda limit: [])
    def slow(limit):
        started.set()
        time.sleep(1.0)
        return [catalysts._row("filings", "8-K", "late", "2026-09-22T10:00:00-04:00", "second")]
    monkeypatch.setattr(catalysts, "_filings", slow)
    t0 = time.time()
    out = catalysts.tape(feeds=["filings", "government"])
    assert time.time() - t0 < 0.9, "the deadline must not be waited past"
    assert "arriving" in out["unavailable"]["filings"]
    assert started.is_set()


def test_one_read_is_shared_rather_than_started_twice(monkeypatch):
    """MEASURED: EDGAR takes seconds and the tile polls, so a second call
    lands while the first read is still out. The feeds cache only when a
    read FINISHES, so without this each caller starts another — the rail's
    multiplier, in a new place."""
    catalysts._inflight.clear()
    calls = []
    monkeypatch.setattr(catalysts, "DEADLINE_S", 0.05)
    monkeypatch.setattr(catalysts, "_government", lambda limit: [])
    def slow(limit):
        calls.append(1)
        time.sleep(0.6)
        return []
    monkeypatch.setattr(catalysts, "_filings", slow)
    for _ in range(4):
        catalysts.tape(feeds=["filings", "government"])
    time.sleep(0.8)
    assert len(calls) == 1, f"one read, not {len(calls)}"


def test_a_social_row_carries_its_warning_and_no_symbol(monkeypatch):
    """A ticker inside a post is the author's claim. The tape never attaches
    one, and the row says it is unverified."""
    class Router:
        connected = ["social"]
        def ask(self, method, surface=None, **kw):
            if method != "social_posts":
                return None
            return [{"at": "2026-09-22T11:14:40+00:00",
                     "text": "BREAKING: (NASDAQ: FAKE) announces a merger",
                     "url": "https://example.test/1", "via": "a mirror",
                     "trust": "unverified: anyone may write a social post"}]
    rows = catalysts._social(Router(), 10)
    assert rows[0]["symbols"] == []
    assert "unverified" in rows[0]["trust"]
    assert "NASDAQ: FAKE" in rows[0]["title"]


def test_a_source_switched_on_but_unreachable_is_not_a_quiet_day(monkeypatch):
    """THE READER'S REPORT (2026-09-23): the halts and social tabs "was
    empty" with the source switched on.

    Nobody sells halts or social posts, so when the scraped source could not
    be read there was no second vendor to try — and a failed read returned
    None, which the router reads as "this source does not carry that". The
    panel then showed an empty list whether the world was quiet or the feed
    was down. The failure is named now."""
    from alphadesk.providers.base import NeedsKey

    class Unreachable:
        connected = ["nasdaq", "social"]
        def ask(self, method, surface=None, **kw):
            raise NeedsKey(surface or method, [], signed_in=True)
        def get(self, *a, **k):
            return None

    monkeypatch.setattr(catalysts, "_filings", lambda limit: [])
    monkeypatch.setattr(catalysts, "_government", lambda limit: [])
    import alphadesk.providers as providers
    monkeypatch.setattr(providers, "get_prices", lambda: Unreachable())
    catalysts._inflight.clear()
    out = catalysts.tape()
    assert "could not be read" in out["unavailable"]["halts"]
    assert "could not be read" in out["unavailable"]["social"]
    # And it is NOT confused with being switched off, which says something else.
    assert "not switched on" not in out["unavailable"]["halts"]


def test_a_quiet_source_is_still_quiet(monkeypatch):
    """The other half: a source that answers with nothing is not a failure."""
    class Quiet:
        connected = ["nasdaq", "social"]
        def ask(self, method, surface=None, **kw):
            return []
        def get(self, *a, **k):
            return []

    monkeypatch.setattr(catalysts, "_filings", lambda limit: [])
    monkeypatch.setattr(catalysts, "_government", lambda limit: [])
    import alphadesk.providers as providers
    monkeypatch.setattr(providers, "get_prices", lambda: Quiet())
    catalysts._inflight.clear()
    out = catalysts.tape()
    assert out["unavailable"] == {}
    assert out["rows"] == []

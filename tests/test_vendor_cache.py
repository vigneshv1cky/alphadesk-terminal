"""Kept vendor answers (2026-10-03): a restart is warm, a quiet panel spares the rate limit, a dead vendor is
answered from the last copy, and live answers are never kept."""
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from alphadesk.providers import registry
from alphadesk.providers.base import EntitlementError, ProviderError


class Vendor:
    name = "alpaca"

    def __init__(self):
        self.calls = []
        self.fail = False

    def _answer(self, what, *a, **k):
        self.calls.append(what)
        if self.fail:
            raise ProviderError("vendor down")
        return {"what": what, "args": list(a), "n": len(self.calls)}

    def fundamentals(self, symbol): return self._answer("fundamentals", symbol)
    def quote(self, symbol): return self._answer("quote", symbol)
    def daily_history(self, symbols, sessions=21): return self._answer("daily_history", list(symbols), sessions)
    def chart_series(self, symbol, days=2, range_key=None, interval=None, before=None, need=None):
        return self._answer("chart_series", symbol, range_key, interval)
    def company_profile(self, symbol): return {"tuple": (1, 2)}                    # not JSON-faithful: never kept
    def peers(self, symbol):
        time.sleep(0.05)
        return self._answer("peers", symbol)


def wrap(vendor, owner="u1"):
    return registry._CachedPrices(vendor, owner=owner, vendor=vendor.name)


def test_a_restart_is_warm_for_slow_changing_answers(store):
    v = Vendor()
    assert wrap(v).fundamentals("AAPL")["n"] == 1
    again = wrap(v)                                           # a new process: an empty memory
    assert again.fundamentals("AAPL")["n"] == 1               # read back from the store
    assert v.calls == ["fundamentals"]


def test_live_answers_are_never_kept(store):
    v = Vendor()
    wrap(v).quote("AAPL")
    assert wrap(v).quote("AAPL")["n"] == 2                    # a fresh process asks the vendor again
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM vendor_cache WHERE method='quote'").fetchone()["n"] == 0


def test_a_chart_is_kept_only_when_it_is_history(store):
    v = Vendor()
    wrap(v).chart_series("AAPL", range_key="1D", interval="1m")     # the live tail
    wrap(v).chart_series("AAPL", range_key="1Y", interval="1d")     # history
    with store._connect() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM vendor_cache WHERE method='chart_series'").fetchone()["n"]
    assert n == 1


def test_a_dead_vendor_is_answered_from_the_last_copy_however_old(store):
    v = Vendor()
    first = wrap(v).fundamentals("AAPL")
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with store._lock, store._connect() as conn:                     # three days old: far past fresh, inside the stale limit
        conn.execute("UPDATE vendor_cache SET fetched_at = ?", (three_days_ago,))
    v.fail = True
    other = wrap(v)
    assert other.fundamentals("AAPL") == first                      # served from the store, not an error
    with pytest.raises(ProviderError):
        other.fundamentals("MSFT")                                  # nothing kept for this one: the failure shows


def test_a_copy_older_than_the_stale_limit_is_not_served(store):
    v = Vendor()
    wrap(v).fundamentals("AAPL")
    with store._lock, store._connect() as conn:
        conn.execute("UPDATE vendor_cache SET fetched_at = ?", ("2020-01-01T00:00:00+00:00",))
    v.fail = True
    with pytest.raises(ProviderError):
        wrap(v).fundamentals("AAPL")


def test_a_value_that_would_change_in_storage_is_not_kept(store):
    v = Vendor()
    wrap(v).company_profile("AAPL")
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM vendor_cache").fetchone()["n"] == 0


def test_kept_answers_are_per_reader(store):
    v = Vendor()
    wrap(v, "u1").fundamentals("AAPL")
    assert wrap(v, "u2").fundamentals("AAPL")["n"] == 2             # another reader's copy is not shared


def test_simultaneous_identical_requests_make_one_vendor_call(store):
    v = Vendor()
    w = wrap(v)
    out = []
    ts = [threading.Thread(target=lambda: out.append(w.peers("AAPL"))) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert v.calls.count("peers") == 1 and len({o["n"] for o in out}) == 1


def test_a_plan_refusal_is_not_replaced_by_an_old_copy(store):
    class Refusing(Vendor):
        def fundamentals(self, symbol):
            raise EntitlementError("not on your plan")

    v = Refusing()
    with pytest.raises(EntitlementError):
        wrap(v).fundamentals("AAPL")


def test_an_account_delete_takes_the_kept_answers_with_it(store):
    store.create_user("gone", "g@example.com", "x")
    wrap(Vendor(), "gone").fundamentals("AAPL")
    assert store.delete_account("gone")["vendor_cache"] == 1


def test_daily_bars_with_datetime_stamps_are_kept_and_come_back_as_datetimes(store):
    """Real bars carry their stamp as a datetime, which plain JSON refused, so
    daily history was listed as kept and never saved (2026-10-06 audit)."""
    stamp = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)

    class Bars(Vendor):
        def daily_history(self, symbols, sessions=21):
            self.calls.append("daily_history")
            return {s: [{"ts": stamp, "close": 12.57, "volume": 88.0}] for s in symbols}

    v = Bars()
    wrap(v).daily_history(["CTVA"], 21)
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM vendor_cache WHERE method='daily_history'").fetchone()["n"] == 1
    again = wrap(v).daily_history(["CTVA"], 21)                     # a new process: read back from the store
    assert v.calls == ["daily_history"]
    bar = again["CTVA"][0]
    assert bar["ts"] == stamp and isinstance(bar["ts"], datetime) and bar["ts"].date().isoformat() == "2026-10-01"


def test_the_kept_counts_page_says_what_is_saved_and_nothing_else(store):
    v = Vendor()
    wrap(v).fundamentals("AAPL")
    got = store.kept_counts("u1")
    assert got["vendor_answers"]["fundamentals (alpaca)"]["rows"] == 1
    assert "payload" not in str(got) and set(got["tables"]) >= {"session_days", "movers_days", "options_flow_sessions",
                                                                 "filings", "filing_text_cache"}

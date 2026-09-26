"""The two measures on the window (2026-09-26, #83), and mostly the rule
that decides when NOT to show one.

The first version of this rescaled a stale SEC share count by the split
ratio, which is what the earnings estimates already do and which is wrong
here. It produced a turnover of 2,851x for CTNT — 515,748,469 shares traded
against a count of 180,889 — because the company had diluted enormously
between the filing and the split, which is why it trades at three cents.
These tests exist so that does not come back.
"""

from datetime import date, timedelta

from alphadesk.desk import screener


def _splits(**by_symbol):
    return {sym: {"date": d, "from": 9.0, "to": 1.0, "reverse": True} for sym, d in by_symbol.items()}


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def test_a_fresh_count_with_no_split_is_usable():
    assert screener._stale_count("AAPL", _days_ago(30), {}) is None


def test_a_count_filed_before_the_split_cannot_describe_today():
    why = screener._stale_count("WHLR", _days_ago(40), _splits(WHLR=_days_ago(10)))
    assert why and "predates" in why


def test_a_count_filed_after_the_split_is_fine():
    assert screener._stale_count("WHLR", _days_ago(10), _splits(WHLR=_days_ago(40))) is None


def test_an_old_count_is_refused_even_with_no_split_at_all():
    # INLF's was nine months old; the split was not the only thing wrong.
    why = screener._stale_count("INLF", _days_ago(270), {})
    assert why and "270 days old" in why


def test_the_age_limit_is_a_boundary_not_a_vibe():
    assert screener._stale_count("X", _days_ago(screener.SHARES_MAX_AGE_DAYS - 1), {}) is None
    assert screener._stale_count("X", _days_ago(screener.SHARES_MAX_AGE_DAYS + 1), {})


def test_an_undated_count_is_refused():
    # Without a date there is no way to know what it describes, and this is
    # the one measure a reader would act on.
    assert screener._stale_count("X", None, {})
    assert screener._stale_count("X", "not-a-date", {})


def test_another_symbols_split_does_not_touch_this_one():
    assert screener._stale_count("AAPL", _days_ago(30), _splits(WHLR=_days_ago(10))) is None


def test_the_plain_window_asks_for_nothing_extra(monkeypatch):
    """No fill means no vendor call and no SEC read — the window polls."""
    called = []
    monkeypatch.setattr(screener, "_attach", lambda *a, **k: called.append(a))
    monkeypatch.setattr(screener.store, "recent_articles_by_ticker", lambda *a, **k: {})
    from alphadesk.ingest import earnings_calendar
    monkeypatch.setattr(earnings_calendar, "upcoming", lambda days=0: [])
    assert screener.inventory() == []
    assert called == []


def test_a_count_dated_in_the_future_is_refused():
    # Not hypothetical: American Airlines' cover date reads 2027-07-17 on a
    # filing made 2026-07-23, and the SEC's own frame label repeats the
    # mistake. A future date sails past every "is it recent" test.
    ahead = (date.today() + timedelta(days=200)).isoformat()
    why = screener._stale_count("AAL", ahead, {})
    assert why and "future" in why

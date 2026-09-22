"""A SCRAPED SOURCE (2026-09-22): a vendor with no key, switched on from the
Account page, asked only after every vendor the reader keyed, and marked as
scraped wherever its answers surface."""

import pytest

from alphadesk.providers import catalogue
from alphadesk.providers.registry import DataRouter
from alphadesk.providers.scraped import SCRAPED_SOURCES, YahooPrices, is_scraped


def test_a_scraped_source_needs_no_credential():
    """Every other provider is built from a sealed key; this one takes the
    same call and ignores it, which is what lets the Account page offer a
    button where the others need a field."""
    assert YahooPrices().name == "yahoo"
    assert YahooPrices(api_key=None, api_secret=None).official is False
    assert is_scraped("yahoo") and not is_scraped("alpaca") and not is_scraped(None)


def test_the_catalogue_calls_it_unofficial_and_lists_it_against_no_surface():
    """The ordering is not a special case in the router: a surface names the
    vendors that serve it, and a connected vendor named by none is asked
    after all of them. Listing a scraped source on a surface would put it
    ahead of a keyed vendor for some reader, which is the one thing it must
    never do."""
    assert catalogue.VENDORS["yahoo"].official is False
    assert catalogue.VENDORS["yahoo"].signup == ""          # nothing to sign up for
    for surface in catalogue.SURFACES.values():
        assert "yahoo" not in [n for n, _ in surface.vendors], surface.id
    # Every keyed vendor stays official.
    assert all(v.official for v in catalogue.VENDORS.values() if v.name not in SCRAPED_SOURCES)


class _Keyed:
    name = "keyed"
    def quote(self, symbol):
        return {"symbol": symbol, "price": 1.0, "vendor": "keyed"}


class _Scraped:
    name = "yahoo"
    official = False
    def quote(self, symbol):
        return {"symbol": symbol, "price": 2.0, "vendor": "yahoo"}


def test_a_keyed_vendor_is_asked_before_a_scraped_one():
    both = DataRouter("u1", {"yahoo": _Scraped(), "keyed": _Keyed()})
    # The quote surface lists real vendors; neither of these is on it, so the
    # walk falls to the unlisted ones — alphabetically "keyed" then "yahoo".
    assert both.ask("quote", "NVDA", surface="quote")["vendor"] == "keyed"
    alone = DataRouter("u1", {"yahoo": _Scraped()})
    assert alone.ask("quote", "NVDA", surface="quote")["vendor"] == "yahoo"


def test_a_null_bar_is_dropped_rather_than_read_as_zero():
    """The endpoint writes null into every parallel array for a minute that
    did not trade. A null close taken as zero would draw the price falling to
    nothing, so the bar is dropped instead."""
    result = {
        "timestamp": [1_790_000_000, 1_790_000_060, 1_790_000_120],
        "indicators": {"quote": [{"open": [10.0, None, 10.4], "high": [10.2, None, 10.5],
                                  "low": [9.9, None, 10.3], "close": [10.1, None, 10.45],
                                  "volume": [1000, None, 1200]}]},
    }
    bars = YahooPrices._bars(result)
    assert [b["close"] for b in bars] == [10.1, 10.45]
    assert [b["volume"] for b in bars] == [1000.0, 1200.0]
    assert bars[0]["ts"] < bars[1]["ts"]


def test_a_missing_volume_reads_as_zero_not_as_none():
    result = {"timestamp": [1_790_000_000],
              "indicators": {"quote": [{"open": [1.0], "high": [1.0], "low": [1.0],
                                        "close": [1.0], "volume": [None]}]}}
    assert YahooPrices._bars(result)[0]["volume"] == 0.0


def test_it_cannot_page_backwards_and_says_so():
    """The endpoint answers a range ending now, so a reader panning left past
    the oldest bar cannot be served. None is the contract's way of saying the
    history ends here — better than a second copy of the same window."""
    assert YahooPrices().chart_series("NVDA", range_key="1M", before=object()) is None


@pytest.mark.parametrize("range_key,interval,served", [
    ("1D", "1m", "1m"),
    ("5D", "1m", "1m"),      # one-minute bars reach 7 days, so five of them fit
    ("1M", "1m", "5m"),      # a month does not: the next size up reaches 60 days
    ("1Y", "1m", "1h"),      # coarsened step by step until one reaches a year
    ("MAX", "1m", "1d"),     # only daily bars run to the start of the listing
    ("1M", "4h", "1h"),      # an interval it does not serve, at the nearest coarser
])
def test_a_range_deeper_than_the_bar_reaches_is_coarsened(range_key, interval, served, monkeypatch):
    """A short series over a long range would read as a thin feed rather than
    a limit, so the coarser bar is served and the payload reports which."""
    seen = {}
    def fake(self, symbol, rng, itv):
        seen["interval"] = itv
        return None
    monkeypatch.setattr(YahooPrices, "_chart", fake)
    YahooPrices().chart_series("NVDA", range_key=range_key, interval=interval)
    assert seen["interval"] == served


def test_the_agent_can_resolve_a_vendor_name_it_was_given():
    """Every tool names the vendor that answered it. This is what turns that
    name into a judgement: whether the figures were licensed or read off a
    page. Called, not merely registered — the first version of this tool
    raised on its first line because a name was out of scope.

    It answers without a reader too — the standalone server has no identity,
    and the catalogue is the same for everyone; only `connected` is theirs."""
    from alphadesk import mcp_server
    out = mcp_server.data_sources()
    assert out["connected"] == []
    assert "yahoo" in out["scraped"]
    by_name = {r["name"]: r for r in out["sources"]}
    assert by_name["yahoo"]["official"] is False
    assert by_name["alpaca"]["official"] is True
    # A scraped source names no panel, because it is asked wherever nothing
    # keyed answered rather than for a listed surface.
    assert by_name["yahoo"]["serves"] == ["whatever no keyed vendor carried"]
    assert by_name["alpaca"]["serves"]


# ── Nasdaq's calendars ────────────────────────────────────────────────────

from alphadesk.providers.scraped import NasdaqCalendars  # noqa: E402


def test_a_window_wider_than_the_source_can_serve_is_refused():
    """Each calendar is a day at a time, so a wide window is a long queue of
    requests. Refusing it lets the router move on and the panel say what it
    could not fill — truer than a calendar quietly missing its later half."""
    n = NasdaqCalendars()
    assert n._days("2026-01-01", "2026-09-30") is None
    assert n.earnings_calendar("2026-01-01", "2026-09-30") is None
    assert n.dividend_calendar("2026-01-01", "2026-09-30") is None
    assert n.split_calendar("2026-01-01", "2026-09-30") is None
    # Backwards, and unparseable, are refused the same way.
    assert n._days("2026-09-30", "2026-09-01") is None
    assert n._days("not-a-date", "2026-09-30") is None


def test_only_weekdays_are_asked_for():
    """No corporate calendar lists a Saturday, so asking for one is a request
    spent to be told nothing."""
    days = NasdaqCalendars()._days("2026-09-18", "2026-09-22")   # Friday to Tuesday
    assert days == ["2026-09-18", "2026-09-21", "2026-09-22"]


def test_the_splits_route_is_asked_once_because_it_ignores_the_date():
    """MEASURED 2026-09-22: this route answers the same upcoming list
    whatever date it is given. Asking per day put every split in the calendar
    once per day of the window — thirteen splits returned as sixty-five rows
    — and carried in dates weeks past the window's end. One request,
    filtered here."""
    calls = []
    same_list_every_time = [
        {"symbol": "ZCSH", "ratio": "3 : 1", "executionDate": "9/30/2026"},
        {"symbol": "DXJ", "ratio": "2 : 1", "executionDate": "10/9/2026"},   # past the window
        {"symbol": "ZCSH", "ratio": "3 : 1", "executionDate": "9/30/2026"},  # and repeated
    ]
    n = NasdaqCalendars()
    n._rows = lambda path, holder="rows": (calls.append(path), same_list_every_time)[1]
    rows = n.split_calendar("2026-09-23", "2026-09-30")
    assert len(calls) == 1, "one request, not one per day"
    assert rows == [{"symbol": "ZCSH", "date": "2026-09-30", "to": 3.0, "from": 1.0,
                     "kind": None, "source": "nasdaq"}]


def test_a_stated_session_is_carried_and_a_missing_one_stays_silent():
    """The session is the one fact no free key states, and the reason this
    source is worth having. A company that states none must not be given
    one — the calendar predicts it from filing history instead."""
    n = NasdaqCalendars()
    n._rows = lambda path, holder="rows": [
        {"symbol": "CTAS", "time": "time-pre-market", "epsForecast": "$1.35", "marketCap": "$78,656,864,000"},
        {"symbol": "XXXX", "time": "time-after-hours", "epsForecast": "N/A", "marketCap": "N/A"},
        {"symbol": "YYYY", "time": "time-not-supplied", "epsForecast": "$0.10", "marketCap": "$1,000"},
    ]
    rows = {r["symbol"]: r for r in n.earnings_calendar("2026-09-23", "2026-09-23")}
    assert rows["CTAS"]["session"] == "BMO" and rows["CTAS"]["confirmed"] is True
    assert rows["CTAS"]["eps_estimate"] == 1.35 and rows["CTAS"]["market_cap"] == 78_656_864_000.0
    assert rows["XXXX"]["session"] == "AMC" and rows["XXXX"]["eps_estimate"] is None
    assert rows["YYYY"]["session"] is None and rows["YYYY"]["confirmed"] is False


def test_a_figure_written_for_a_page_is_read_as_a_number_or_not_at_all():
    money = NasdaqCalendars._money
    assert money("$78,656,864,000") == 78_656_864_000.0
    assert money("15.00") == 15.0
    assert money("N/A") is None and money("--") is None and money("") is None and money(None) is None
    us = NasdaqCalendars._us_date
    assert us("9/23/2026") == "2026-09-23" and us("2026-09-23") == "2026-09-23"
    assert us("N/A") is None and us("") is None and us(None) is None

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


def test_a_halt_is_a_record_with_its_own_clock():
    """A halt is a catalyst nothing else here carries: the exchange stopped
    the stock at a stated time for a stated reason. The record is handed over
    whole — code included — and the times are the exchange's, in New York."""
    feed = """<rss><channel>
      <item><ndaq:IssueSymbol>JAGX</ndaq:IssueSymbol><ndaq:IssueName>Jaguar Health, Inc. Cmn</ndaq:IssueName>
        <ndaq:Market>NASDAQ</ndaq:Market><ndaq:ReasonCode>LUDP</ndaq:ReasonCode>
        <ndaq:HaltDate>09/22/2026</ndaq:HaltDate><ndaq:HaltTime>14:54:49.693</ndaq:HaltTime>
        <ndaq:ResumptionDate>09/22/2026</ndaq:ResumptionDate>
        <ndaq:ResumptionQuoteTime>14:54:49</ndaq:ResumptionQuoteTime>
        <ndaq:ResumptionTradeTime>14:59:49</ndaq:ResumptionTradeTime>
        <ndaq:PauseThresholdPrice /></item>
      <item><ndaq:IssueSymbol>STOP</ndaq:IssueSymbol><ndaq:IssueName>Still Halted Co</ndaq:IssueName>
        <ndaq:Market>NYSE</ndaq:Market><ndaq:ReasonCode>T1</ndaq:ReasonCode>
        <ndaq:HaltDate>09/22/2026</ndaq:HaltDate><ndaq:HaltTime>15:30:00.000</ndaq:HaltTime>
        <ndaq:ResumptionDate /><ndaq:ResumptionQuoteTime /><ndaq:ResumptionTradeTime /></item>
      <item><ndaq:IssueSymbol>ZZZZ</ndaq:IssueSymbol><ndaq:ReasonCode>WAT</ndaq:ReasonCode>
        <ndaq:HaltDate>09/22/2026</ndaq:HaltDate><ndaq:HaltTime>09:31:00.000</ndaq:HaltTime></item>
    </channel></rss>"""
    import alphadesk.providers.scraped as sc
    n = NasdaqCalendars()
    original, sc._get_text = sc._get_text, lambda url, timeout=20.0: feed
    try:
        rows = n.trading_halts()
    finally:
        sc._get_text = original

    by = {r["symbol"]: r for r in rows}
    # Newest first, and the times are the exchange's own, stated as New York.
    assert [r["symbol"] for r in rows] == ["STOP", "JAGX", "ZZZZ"]
    assert by["JAGX"]["halted_at"] == "2026-09-22T14:54:49"
    assert by["JAGX"]["timezone"] == "America/New_York"
    assert by["JAGX"]["resumption_trade_at"] == "2026-09-22T14:59:49"
    assert by["JAGX"]["resumed"] is True
    assert by["JAGX"]["reason"] == "Volatility pause (limit up–limit down)"
    # Still stopped: no resumption named. This is the state that matters.
    assert by["STOP"]["resumed"] is False
    assert by["STOP"]["resumption_trade_at"] is None
    assert by["STOP"]["reason"] == "News pending"
    # A code nobody publishes stays a code rather than being given a meaning.
    assert by["ZZZZ"]["reason_code"] == "WAT" and by["ZZZZ"]["reason"] is None


def test_the_same_stock_halted_twice_is_two_events():
    """Each pause is its own catalyst; collapsing them would hide the second."""
    feed = "<rss><channel>" + "".join(
        f"""<item><ndaq:IssueSymbol>RAIN</ndaq:IssueSymbol><ndaq:ReasonCode>LUDP</ndaq:ReasonCode>
            <ndaq:HaltDate>09/22/2026</ndaq:HaltDate><ndaq:HaltTime>{t}</ndaq:HaltTime></item>"""
        for t in ("14:28:18.900", "14:22:24.146")) + "</channel></rss>"
    import alphadesk.providers.scraped as sc
    original, sc._get_text = sc._get_text, lambda url, timeout=20.0: feed
    try:
        rows = NasdaqCalendars().trading_halts()
    finally:
        sc._get_text = original
    assert [r["halted_at"] for r in rows] == ["2026-09-22T14:28:18", "2026-09-22T14:22:24"]


# ── social: the one source anyone can write into ──────────────────────────

from alphadesk.providers.scraped import SocialPulse  # noqa: E402


def test_social_is_off_until_a_reader_switches_it_on():
    """Government feeds are on for everyone because an agency is accountable
    for what it publishes. A social post is accountable to nobody, so this
    one is opt-in like every other scraped source."""
    assert catalogue.VENDORS["social"].official is False
    assert "social" in SCRAPED_SOURCES
    for surface in catalogue.SURFACES.values():
        assert "social" not in [n for n, _ in surface.vendors], surface.id


def test_no_ticker_is_read_out_of_a_post(monkeypatch):
    """A ticker inside a post is the AUTHOR'S CLAIM about which company the
    post concerns. Attaching it would route an unverified assertion into
    that symbol's context, so the text is handed over whole and nothing is
    inferred from it."""
    feed = """<rss><channel><item>
      <title>post</title>
      <pubDate>Tue, 22 Sep 2026 11:14:40 +0000</pubDate>
      <link>https://www.trumpstruth.org/statuses/41842</link>
      <description><![CDATA[<p>BREAKING: (NASDAQ: FAKE) announces a merger with (NYSE: ALSOFAKE)</p>]]></description>
    </item></channel></rss>"""
    import alphadesk.providers.scraped as sc
    original, sc._get_text = sc._get_text, lambda url, timeout=20.0: feed
    try:
        rows = SocialPulse().social_posts()
    finally:
        sc._get_text = original
    assert len(rows) == 1
    row = rows[0]
    # The claim survives as TEXT and reaches no symbol field anywhere.
    assert "NASDAQ: FAKE" in row["text"]
    assert "symbol" not in row and "symbols" not in row and "tickers" not in row
    assert row["at"] == "2026-09-22T11:14:40+00:00"
    # Every row carries the warning, not only the tool's description.
    assert "unverified" in row["trust"]
    assert "mirror" in row["via"]


def test_a_source_that_cannot_be_read_raises_rather_than_answering_nothing(monkeypatch):
    """CORRECTED 2026-09-23, and the correction is the point.

    This test used to assert that a failed read returns None. That was the
    bug the reader hit: None means "I do not carry this surface", so the
    router moved on — and since NOBODY sells halts or social posts, there was
    no second vendor and the panel simply showed nothing. A source switched
    ON but unreachable was indistinguishable from a quiet day.

    A failed read is an error now. The router still skips the source, but the
    caller can tell the two apart and say which it was."""
    import alphadesk.providers.scraped as sc
    from alphadesk.providers.base import ProviderError
    def refuse(url, timeout=20.0):
        raise ProviderError("scraped source refused (403)")
    original, sc._get_text = sc._get_text, refuse
    try:
        for call in (SocialPulse().social_posts, NasdaqCalendars().trading_halts):
            with pytest.raises(ProviderError):
                call()
    finally:
        sc._get_text = original


def test_a_source_that_is_read_but_says_nothing_is_still_empty():
    """The other half: an answer with no rows is not a failure. Only the
    calendars can be legitimately empty on a quiet day — they are the ones
    with a real second vendor behind them."""
    import alphadesk.providers.scraped as sc
    original, sc._get_text = sc._get_text, lambda url, timeout=20.0: "<rss><channel></channel></rss>"
    try:
        assert SocialPulse().social_posts() is None      # nothing in the feed
        assert NasdaqCalendars().trading_halts() is None
    finally:
        sc._get_text = original


def test_a_scraped_source_is_asked_last_whatever_it_is_called():
    """THE RULE (2026-09-23, the owner): never scrape what a keyed vendor
    carries — scrape only where none does.

    It held before only because no scraped source is listed on a surface AND
    their names sorted after the vendors they compete with. That is luck: a
    vendor or plugin named after "nasdaq" would have taken a calendar from a
    paid vendor. The walk now cannot reach a scraped source until every keyed
    one has declined, whatever either is called."""
    from alphadesk.providers import catalogue as cat

    class Any_:
        def __init__(self, name): self.name = name
        def dividend_calendar(self, start, end): return [{"from": self.name}]

    # A keyed vendor whose name sorts AFTER every scraped source, which is
    # the case the alphabet used to get wrong.
    keyed = cat.Vendor("zzz-paid", "Paid, late in the alphabet", "")
    scraped = cat.Vendor("aaa-scraped", "Scraped, early in the alphabet", "", official=False)
    added = {}
    for v in (keyed, scraped):
        if v.name not in cat.VENDORS:
            cat.VENDORS[v.name] = v
            added[v.name] = v
    try:
        router = DataRouter("u1", {"aaa-scraped": Any_("aaa-scraped"), "zzz-paid": Any_("zzz-paid")})
        got = router.ask("dividend_calendar", "2026-09-01", "2026-09-07")
        assert got == [{"from": "zzz-paid"}], "the paid vendor must be asked first"
        # With nothing keyed, the scraped source is what is left — the second
        # half of the rule: scrape WHERE NO PAID SOURCE IS AVAILABLE.
        alone = DataRouter("u1", {"aaa-scraped": Any_("aaa-scraped")})
        assert alone.ask("dividend_calendar", "2026-09-01", "2026-09-07") == [{"from": "aaa-scraped"}]
    finally:
        for name in added:
            cat.VENDORS.pop(name, None)


def test_every_scraped_source_stays_off_every_catalogue_surface():
    """The ordering above is belt; this is braces. Listing a scraped source
    on a surface would put it in the catalogue's own order, ahead of a keyed
    vendor further down that list."""
    for surface in catalogue.SURFACES.values():
        for name, _tier in surface.vendors:
            assert name not in SCRAPED_SOURCES, f"{name} is listed on {surface.id}"


def test_a_switch_says_whether_it_would_ever_be_asked(client, store, monkeypatch):
    """A keyed vendor is always asked first, so a scraped source whose every
    surface the reader already pays for can never answer — and a button
    reading "Switch on" implied otherwise (2026-09-23, the owner: the button
    decides whether scraping happens, keyed takes precedence)."""
    import uuid

    from alphadesk.app import auth
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    uid = uuid.uuid4().hex
    store.create_user(uid, "cover@example.com", auth.hash_password("a-long-password"))
    assert client.post("/api/auth/login", json={"email": "cover@example.com",
                                                "password": "a-long-password"}).status_code == 200

    def coverage():
        rows = {v["name"]: v for v in client.get("/api/data/vendors").json()["vendors"]}
        return {n: rows[n].get("coverage") for n in ("yahoo", "nasdaq", "social")}

    # With NOTHING keyed, every scraped source is reachable.
    bare = coverage()
    assert "Price chart" in bare["yahoo"]["only_source_for"]
    assert bare["yahoo"]["already_covered"] == []
    assert "Trading halts and resumptions" in bare["nasdaq"]["only_source_for"]

    # With a price vendor keyed, Yahoo can never be asked — it says so, and
    # names who took its place.
    store.set_user_key(uid, "prices", "alpaca", "sealed", "…abcd")
    keyed = coverage()
    assert keyed["yahoo"]["only_source_for"] == []
    assert any(t["surface"] == "Price chart" and "Alpaca" in t["vendors"]
               for t in keyed["yahoo"]["already_covered"])
    # Alpaca does not carry the calendars, so Nasdaq is still the only source
    # for them AND for the halts.
    assert "Trading halts and resumptions" in keyed["nasdaq"]["only_source_for"]
    assert "Earnings calendar" in keyed["nasdaq"]["only_source_for"]

    # Key the vendor that DOES sell the calendars and they drop away, leaving
    # the one thing nobody sells. This is the rule in one assertion.
    store.set_user_key(uid, "prices", "fmp", "sealed", "…efgh")
    full = coverage()
    assert full["nasdaq"]["only_source_for"] == ["Trading halts and resumptions"]
    assert any(t["surface"] == "Earnings calendar" and "Financial Modeling Prep" in t["vendors"]
               for t in full["nasdaq"]["already_covered"])
    # And social is reachable whatever is keyed — no vendor carries either.
    assert full["social"]["only_source_for"] == ["Social posts"]
    assert full["social"]["already_covered"] == []


def test_a_standing_suspension_is_not_a_live_pause():
    """MEASURED 2026-09-23: of 14 unresumed halts, TWO were from today and
    the rest were suspensions going back to 2019 — mostly T12, additional
    information requested. The feed keeps an open halt listed until it
    clears, so "still halted" counted as stocks stopped right now was wrong
    by an order of magnitude. Each row says which it is."""
    from datetime import datetime

    from alphadesk.config import ET
    today = datetime.now(ET).strftime("%m/%d/%Y")
    feed = f"""<rss><channel>
      <item><ndaq:IssueSymbol>NOWW</ndaq:IssueSymbol><ndaq:ReasonCode>LUDP</ndaq:ReasonCode>
        <ndaq:HaltDate>{today}</ndaq:HaltDate><ndaq:HaltTime>14:54:49.693</ndaq:HaltTime>
        <ndaq:ResumptionDate /><ndaq:ResumptionTradeTime /></item>
      <item><ndaq:IssueSymbol>BACK</ndaq:IssueSymbol><ndaq:ReasonCode>LUDP</ndaq:ReasonCode>
        <ndaq:HaltDate>{today}</ndaq:HaltDate><ndaq:HaltTime>13:00:00.000</ndaq:HaltTime>
        <ndaq:ResumptionDate>{today}</ndaq:ResumptionDate>
        <ndaq:ResumptionTradeTime>13:05:00</ndaq:ResumptionTradeTime></item>
      <item><ndaq:IssueSymbol>OLDD</ndaq:IssueSymbol><ndaq:ReasonCode>T12</ndaq:ReasonCode>
        <ndaq:HaltDate>02/22/2019</ndaq:HaltDate><ndaq:HaltTime>10:00:00.000</ndaq:HaltTime>
        <ndaq:ResumptionDate /><ndaq:ResumptionTradeTime /></item>
    </channel></rss>"""
    import alphadesk.providers.scraped as sc
    original, sc._get_text = sc._get_text, lambda url, timeout=20.0: feed
    try:
        rows = {r["symbol"]: r for r in NasdaqCalendars().trading_halts()}
    finally:
        sc._get_text = original

    # Stopped during this session and not resumed: the state that matters.
    assert rows["NOWW"]["today"] and not rows["NOWW"]["resumed"]
    assert rows["NOWW"]["standing"] is False
    # Resumed today: neither.
    assert rows["BACK"]["resumed"] and rows["BACK"]["standing"] is False
    # Stopped in 2019 and never resumed: a suspension, not a pause.
    assert rows["OLDD"]["standing"] is True and rows["OLDD"]["today"] is False
    # The naive count is what was wrong: two rows are unresumed, but only
    # ONE of them is a stock stopped today.
    assert sum(1 for r in rows.values() if not r["resumed"]) == 2
    assert sum(1 for r in rows.values() if r["today"] and not r["resumed"]) == 1

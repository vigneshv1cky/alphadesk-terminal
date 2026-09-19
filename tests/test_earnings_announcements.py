"""Companies' own announcements of when they will report (2026-09-14): read
from press releases, they date and time a report on the company's word, and
name the release that said so."""

from alphadesk.ingest import earnings_announcements as ea
from alphadesk.ingest import earnings_calendar as uc
from alphadesk.ingest import edgar, edgar_releases


class TestParse:
    def test_the_release_date_wins_over_a_next_morning_call(self):
        text = ("MIAMI, Sept. 2, 2026 /PRNewswire/ -- Lennar Corporation will release its third quarter earnings "
                "after the market closes on Tuesday, September 16, 2026. The company will host a conference call "
                "on Wednesday, September 17, 2026 at 11:00 a.m. Eastern time.")
        got = ea.parse_announcement("Lennar Sets Date for Third Quarter Earnings", text, "2026-09-02T12:00:00+00:00")
        assert got["report_date"] == "2026-09-16" and got["session"] == "AMC" and got["basis"] == "stated"
        assert got["kind"] == "release" and "September 16" in got["sentence"]

    def test_a_wire_dateline_is_not_the_report_date(self):
        text = ("TEL AVIV, Israel, Sept. 3, 2026 /PRNewswire/ -- Coda Markets Ltd. plans to report its second "
                "quarter 2026 financial results on September 17, 2026, before the opening of trading on Nasdaq.")
        got = ea.parse_announcement("Coda to Announce Results", text, "2026-09-03T11:00:00Z")
        assert got["report_date"] == "2026-09-17" and got["session"] == "BMO"

    def test_financial_markets_close_and_a_company_suffix_do_not_hide_the_session(self):
        text = ("CALGARY, AB, Aug. 25, 2026 /PRNewswire/ -- High Tide Inc. (\"High Tide\" or the \"Company\") (Nasdaq: HITI) "
                "(TSXV: HITI), a retail-forward enterprise built to deliver real-world value across every component of "
                "its industry and the communities it serves, announced today that it will release its financial and "
                "operational results for the quarter ended July 31, 2026, after financial markets close on Monday, "
                "September 14, 2026. Results will be available on its website.")
        got = ea.parse_announcement("High Tide to Announce Third Fiscal Quarter 2026 Financial Results", text,
                                    "2026-08-25T10:00:00+00:00")
        assert got["report_date"] == "2026-09-14" and got["session"] == "AMC" and got["basis"] == "stated"
        assert got["sentence"].startswith("…") and "September 14" in got["sentence"] and len(got["sentence"]) <= 245

    def test_a_title_names_the_date_and_an_evening_call_implies_after_the_close(self):
        got = ea.parse_announcement(
            "Trip.com Group to Report Second Quarter 2026 Financial Results on September 16",
            "Management will hold an earnings conference call at 8:00 PM US Eastern Time on the same day.",
            "2026-09-01T09:00:00Z")
        assert got["report_date"] == "2026-09-16" and got["session"] == "AMC" and got["basis"] == "call time"

    def test_a_morning_call_implies_before_the_open(self):
        got = ea.parse_announcement(
            "Acme to report results", "Acme will report its fiscal fourth quarter results on October 2, 2026. "
            "A conference call will follow at 8:30 a.m. ET.", "2026-09-10T13:00:00Z")
        assert got["session"] == "BMO" and got["basis"] == "call time"

    def test_results_already_reported_are_not_an_announcement(self):
        text = "Acme today reported its results for the second quarter ended August 31, 2026."
        assert ea.parse_announcement("Acme Reports Second Quarter Results", text, "2026-09-10T20:05:00Z") is None

    def test_a_call_without_a_stated_session_is_not_trusted_as_the_report_date(self):
        text = "Acme will host a conference call to discuss its quarterly results on September 25, 2026."
        assert ea.parse_announcement("Acme conference call", text, "2026-09-10T13:00:00Z") is None
        text2 = ("Acme will host a conference call to discuss its quarterly results on September 25, 2026, "
                 "after the market close.")
        got = ea.parse_announcement("Acme conference call", text2, "2026-09-10T13:00:00Z")
        assert got["report_date"] == "2026-09-25" and got["kind"] == "call" and got["session"] == "AMC"

    def test_a_yearless_date_past_the_turn_of_the_year_rolls_forward(self):
        got = ea.parse_announcement("Acme to Report Fourth Quarter Results on January 28", "",
                                    "2026-12-20T13:00:00Z")
        assert got["report_date"] == "2027-01-28" and got["session"] is None

    def test_a_date_months_away_is_not_this_announcement(self):
        text = "Acme will report its fiscal year results on March 3, 2027."
        assert ea.parse_announcement("Acme", text, "2026-09-10T13:00:00Z") is None


def _ann(sym, day, published, session=None, url=None):
    return {"symbol": sym, "report_date": day, "session": session, "basis": "stated" if session else None,
            "published_at": published, "url": url or f"https://x/{sym}/{published}", "source": "wire",
            # Real announcements name the period; the apply step now drops a
            # stored row whose sentence does not (Rezolute's trial release).
            "sentence": f"{sym} will report third quarter financial results on {day}."}


def _row(sym, day, **kw):
    return {"symbol": sym, "report_date": day, "session": "DAY", "confirmed": False, "eps_estimate": None,
            "eps_actual": None, **kw}


class TestApply:
    def test_the_company_date_and_session_replace_the_vendors_and_keep_them(self):
        rows = [_row("LEN", "2026-09-15", session="BMO")]
        ea.apply_announcements(rows, [_ann("LEN", "2026-09-16", "2026-09-02T12:00:00+00:00", "AMC")])
        r = rows[0]
        assert r["report_date"] == "2026-09-16" and r["vendor_date"] == "2026-09-15"
        assert r["session"] == "AMC" and r["vendor_session"] == "BMO" and r["confirmed"] is True
        assert r["announcement"]["url"].startswith("https://x/LEN")

    def test_the_newest_announcement_wins_and_a_session_less_one_keeps_the_vendor_session(self):
        rows = [_row("A", "2026-09-20", session="AMC")]
        ea.apply_announcements(rows, [_ann("A", "2026-09-22", "2026-09-01T00:00:00+00:00", "BMO"),
                                      _ann("A", "2026-09-23", "2026-09-10T00:00:00+00:00")])
        assert rows[0]["report_date"] == "2026-09-23" and rows[0]["session"] == "AMC"

    def test_a_released_row_and_another_quarter_are_left_alone(self):
        rows = [_row("A", "2026-09-10", eps_actual=1.0), _row("B", "2026-12-10")]
        ea.apply_announcements(rows, [_ann("A", "2026-09-12", "2026-09-01T00:00:00+00:00", "AMC"),
                                      _ann("B", "2026-09-12", "2026-09-01T00:00:00+00:00", "AMC")])
        assert "announcement" not in rows[0] and "announcement" not in rows[1]
        assert rows[1]["report_date"] == "2026-12-10"

    def test_one_announcement_settles_one_row_and_an_older_one_for_the_same_report_is_superseded(self):
        rows = [_row("COE", "2026-09-01"), _row("COE", "2026-09-15", session="BMO", confirmed=True)]
        ea.apply_announcements(rows, [_ann("COE", "2026-09-15", "2026-09-10T10:00:00+00:00", "BMO"),
                                      _ann("COE", "2026-09-08", "2026-08-20T10:00:00+00:00", "AMC")])
        assert [r["report_date"] for r in rows] == ["2026-09-01", "2026-09-15"]
        assert "announcement" not in rows[0] and rows[1]["announcement"]["published_at"].startswith("2026-09-10")

    def test_a_report_out_without_a_clock_takes_the_announced_session_for_that_day_only(self):
        rows = [_row("CSHR", "2026-09-14", eps_actual=0.1), _row("ADBE", "2026-09-10", eps_actual=5.3,
                                                                  released_at="2026-09-10T16:06:00-04:00")]
        ea.apply_announcements(rows, [_ann("CSHR", "2026-09-14", "2026-09-08T20:00:00+00:00", "BMO"),
                                      _ann("ADBE", "2026-09-10", "2026-08-20T00:00:00+00:00", "BMO")])
        assert rows[0]["session"] == "BMO" and rows[0]["announcement"]
        assert rows[1]["session"] == "DAY" and "announcement" not in rows[1]           # EDGAR's clock stands

    def test_announced_rows_add_listed_companies_no_vendor_carries_once_each(self):
        listed = {"TCOM": "1", "LEN": "2", "LEN-B": "2", "ADBE": "3"}
        rows = [_row("LEN", "2026-09-16")]
        anns = [_ann("TCOM", "2026-09-16", "2026-09-01T00:00:00+00:00", "AMC"),
                _ann("TCOM", "2026-09-16", "2026-08-30T00:00:00+00:00", "AMC", url="https://x/old"),
                _ann("LEN-B", "2026-09-16", "2026-09-02T00:00:00+00:00"),       # a second class of a listed row
                _ann("NOTSEC", "2026-09-16", "2026-09-02T00:00:00+00:00"),
                _ann("ADBE", "2026-10-30", "2026-09-02T00:00:00+00:00")]         # outside the window
        got = ea.announced_rows(rows, anns, "2026-09-13", "2026-09-19", listed)
        assert [r["symbol"] for r in got] == ["TCOM"]
        assert got[0]["session"] == "AMC" and got[0]["sources"] == "announcement"
        assert got[0]["announcement"]["url"] == "https://x/TCOM/2026-09-01T00:00:00+00:00"


def test_articles_are_read_once_per_ticker_and_stored_under_the_reader(store):
    articles = [
        {"title": "Acme to Report Third Quarter Results on October 1", "summary": "Before the market opens.",
         "url": "https://www.businesswire.com/news/home/1/en/acme", "published_at": "2026-09-14T12:00:00+00:00",
         "tickers": ["ACME", "ACMEW"], "source": "Business Wire"},
        # A reporter's article names a date too, but it is not the company's word.
        {"title": "Prediction: Micron will report blowout results on Sept. 30", "summary": "After the close.",
         "url": "https://www.fool.com/investing/2026/09/14/micron", "published_at": "2026-09-14T12:00:00+00:00",
         "tickers": ["MU", "SNDK"]},
        {"title": "Acme ships a product", "summary": "", "url": "https://x/p",
         "published_at": "2026-09-14T12:00:00+00:00", "tickers": ["ACME"]},
    ]
    assert ea.record_from_articles("reader-1", articles) == 2
    got = store.announcements_between("reader-1", "2026-09-20", "2026-10-05")
    assert sorted(a["symbol"] for a in got) == ["ACME", "ACMEW"]
    assert got[0]["session"] == "BMO" and got[0]["source"] == "Business Wire"
    assert store.announcements_between("reader-2", "2026-09-20", "2026-10-05") == []


class _Fmp:
    name = "fmp"

    def __init__(self):
        self.asked = []

    def earnings_calendar(self, start, end, symbol=None):
        return [_row("LEN", "2026-09-15", eps_estimate=2.0), _row("KR", "2026-09-18", session="BMO", confirmed=True)]

    def press_releases(self, symbol, limit=40):
        self.asked.append(symbol)
        if symbol != "LEN":
            return []
        # A wire release names its company in the ticker line, which is how
        # the reader tells it from the other companies this vendor returns
        # under the symbol asked for (2026-09-15).
        return [{"symbol": "LEN", "title": "Lennar sets date",
                 "text": "Lennar Corporation (NYSE: LEN) will release its earnings after the market "
                         "closes on September 16, 2026.",
                 "published_at": "2026-09-02T12:00:00+00:00", "url": "https://x/len", "source": "PRNewswire"},
                {"symbol": "LEN", "title": "Playboy to Host Second Quarter Call",
                 "text": "PLBY Group, Inc. will release financial results for the second quarter on "
                         "September 18, 2026, after the market closes.",
                 "published_at": "2026-09-02T13:00:00+00:00", "url": "https://x/plby", "source": "GlobeNewswire"}]


def test_the_calendar_asks_untimed_companies_and_stores_what_it_finds(vendors, monkeypatch):
    fmp = _Fmp()
    vendors(fmp=fmp)
    monkeypatch.setattr(uc, "_today_et", lambda: "2026-09-14")
    monkeypatch.setattr(uc, "_release_habit", lambda sym, dates: (None, None))
    monkeypatch.setattr(edgar, "_ticker_cik_map", lambda: {"LEN": "1", "KR": "2", "TCOM": "3"})
    monkeypatch.setattr(edgar, "company_title", lambda s: s.title())
    monkeypatch.setattr(edgar_releases, "releases_by_symbol", lambda a, b: {})
    from alphadesk.ledger import store
    store.save_announcements("u-test", [_ann("TCOM", "2026-09-16", "2026-09-01T00:00:00+00:00", "AMC")])
    rows = {r["symbol"]: r for r in uc.rows_between("2026-09-13", "2026-09-19", stats=False)}
    assert fmp.asked == ["LEN"]                                  # KR is already timed
    assert rows["LEN"]["report_date"] == "2026-09-16" and rows["LEN"]["session"] == "AMC"
    # The other company's release, returned under LEN by the vendor, is not
    # Lennar's announcement and does not move the row to the 18th.
    assert rows["LEN"]["announcement"]["url"] == "https://x/len"
    assert rows["TCOM"]["sources"] == "announcement" and rows["TCOM"]["company_name"] == "Tcom"
    assert any(a["symbol"] == "LEN" for a in store.announcements_between("u-test", "2026-09-16", "2026-09-16"))


def test_press_releases_read_recently_are_not_fetched_again_and_a_failed_fetch_is_retried(store):
    from alphadesk.providers import registry
    from alphadesk.providers.base import ProviderError
    calls = []

    class _Pr:
        name = "fmp"
        def press_releases(self, symbol, limit=40):
            calls.append(symbol)
            if symbol == "DOWN":
                raise ProviderError("HTTP 500")
            return []
    router = registry.DataRouter("reader-1", {"fmp": _Pr()})
    ea.for_symbols(router, ["LEN", "DOWN"], "reader-1")
    assert sorted(calls) == ["DOWN", "LEN"]
    calls.clear()
    ea.for_symbols(registry.DataRouter("reader-1", {"fmp": _Pr()}), ["LEN", "DOWN"], "reader-1")
    assert calls == []                                   # LEN was read; DOWN failed and waits before a retry
    from alphadesk.ingest import background_fill
    background_fill._failed.clear()
    ea.for_symbols(registry.DataRouter("reader-1", {"fmp": _Pr()}), ["LEN", "DOWN"], "reader-1")
    assert calls == ["DOWN"]


def test_many_companies_to_read_go_to_the_background_and_are_counted(store, monkeypatch):
    from alphadesk.ingest import background_fill
    from alphadesk.providers import registry
    ran = []
    monkeypatch.setattr(background_fill, "submit", lambda kind, owner, syms, job: ran.append((kind, list(syms))) or len(ran))

    class _Pr:
        name = "fmp"
        def press_releases(self, symbol, limit=40):
            return []
    pending = {}
    got = ea.for_symbols(registry.DataRouter("reader-1", {"fmp": _Pr()}), [f"S{i}" for i in range(5)], "reader-1",
                         pending=pending, block_limit=3)
    assert got == [] and pending == {"announcements": 5} and ran == [("announcements", [f"S{i}" for i in range(5)])]
    assert ea.for_symbols(registry.DataRouter("reader-1", {}), ["X"], "reader-1") == []    # no press-release vendor: nothing to read


# ── what is NOT an earnings announcement ─────────────────────────────────

RZLT = (
    "REDWOOD CITY, Calif., Sept. 09, 2026 (GLOBE NEWSWIRE) -- Rezolute, Inc. (Nasdaq: RZLT), a "
    "late-stage clinical company, today provided an update on the FDA review of its Phase 3 sunRIZE "
    "study. The Company also completed enrollment in its upLIFT study in tumor HI and the Company "
    "remains on track to report topline results before the end of 2026."
)


def test_a_clinical_update_is_not_an_earnings_date():
    """Rezolute's trial release read as an earnings announcement and moved
    its report seven days earlier, onto the release's own day, emptying the
    date its vendor listed (2026-09-15)."""
    assert ea.parse_announcement(
        "Rezolute Provides Update on FDA Review of its Phase 3 sunRIZE Study",
        RZLT, "2026-09-09T11:00:00Z") is None


def test_a_wire_dateline_is_never_the_report_date():
    """The dateline carries the publication day; sentence splitting can
    leave it trailing a forward-looking sentence."""
    text = (
        "The Company will report results. MIAMI, Sept. 09, 2026 (GLOBE NEWSWIRE) -- Acme Corp "
        "said it continues to expect growth."
    )
    assert ea.parse_announcement("Acme update", text, "2026-09-09T11:00:00Z") is None


def test_a_real_results_announcement_still_parses():
    text = (
        "OAK BROOK, Ill., Sept. 02, 2026 (GLOBE NEWSWIRE) -- Acme Corp announced today that it "
        "will report third quarter 2026 financial results on Wednesday, October 15, 2026, before "
        "the market opens."
    )
    got = ea.parse_announcement("Acme Sets Date for Third Quarter Earnings", text, "2026-09-02T12:00:00Z")
    assert got and got["report_date"] == "2026-10-15" and got["session"] == "BMO"


def test_a_stored_announcement_that_is_not_about_results_is_ignored():
    """The parser was tightened after these rows were written, and a stored
    row outlives the fix."""
    rows = [{"symbol": "RZLT", "report_date": "2026-09-16", "session": None, "confirmed": True}]
    ea.apply_announcements(rows, [{
        "symbol": "RZLT", "report_date": "2026-09-09", "session": "AMC", "basis": None,
        "published_at": "2026-09-09T11:00:00Z", "url": "https://example.com/trial",
        "source": "globenewswire.com",
        "sentence": "the Company remains on track to report topline results before the end of 2026",
    }])
    assert rows[0]["report_date"] == "2026-09-16" and "announcement" not in rows[0]


# ── a release must be about the company it is filed under ────────────────
#
# Asked for Eastern Company's press releases, FMP answered with Playboy's,
# DexCom's, Parker's and eight more, every row tagged EML (2026-09-15).

def test_a_release_naming_another_company_is_not_this_company_s():
    assert not ea.names_company(
        "Playboy to Host Second Quarter Call. PLBY Group, Inc. will release results.",
        "EML", "EASTERN CO")
    assert not ea.names_company(
        "Dave & Buster's Entertainment, Inc. (NASDAQ: PLAY) to Report Second Quarter Results",
        "DAVE", "Dave Inc./DE")


def test_the_ticker_line_is_the_evidence():
    assert ea.names_company("The Eastern Company (NASDAQ: EML) will release results", "EML", "EASTERN CO")
    assert ea.names_company("Lennar Corporation (NYSE: LEN) will release its earnings", "LEN", "Lennar Corp")


def test_a_two_word_company_name_also_counts():
    """A release that never prints the ticker still names the company."""
    assert ea.names_company("Eastern Bankshares, Inc. announces its results", "EBC", "Eastern Bankshares Inc")
    assert not ea.names_company("Eastern Bankshares, Inc. announces its results", "EML", "EASTERN CO")

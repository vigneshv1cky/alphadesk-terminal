"""2026-10-27: the evidence ladder — every gainer and loser comes back with the
public records that bear on its move, each marked with the check that found
it, or with every check that ran empty and every one that could not be read.
Never a reason, a score or a verdict (invariant 1)."""
from datetime import date

from alphadesk.desk import focus
from alphadesk.ingest import edgar_feed

DAY = date(2026, 10, 27)
WINDOW = {"from": "2026-10-26T16:00-04:00", "to": "2026-10-27T15:30-04:00"}


def _empty(**over):
    """Every check ran and found nothing, unless overridden."""
    kw = dict(stories={"releases": [], "analyst_notes": [], "own": [], "read_for_passages": []},
              passages_found=[], filings=[], earnings=[], actions=[], listing_filings=[],
              prior_sessions=20, halts=[], group={})
    kw.update(over)
    return kw


def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


# ── a mover explained by a filing ──

def test_a_filing_names_its_items_in_the_secs_own_words_and_a_results_item_is_a_report():
    items = edgar_feed.items_from_codes("2.02,9.01")
    assert items == [{"number": "2.02", "label": "Results of Operations and Financial Condition"},
                     {"number": "9.01", "label": "Financial Statements and Exhibits"}]
    filing = {"form": "8-K", "filed_at": "2026-10-27T06:31:02-04:00", "accession": "0001364479-26-000050",
              "items": items, "url": "u"}
    lad = focus.ladder("HRI", "Herc Holdings Inc.", 22.8, WINDOW, **_empty(filings=[filing]))
    word = lad["rungs"]["company_word"]
    assert word["status"] == "records" and word["records"][0]["check"] == "sec_filing"
    assert word["records"][0]["items"][0]["label"] == "Results of Operations and Financial Condition"
    sched = lad["rungs"]["scheduled_report"]
    assert sched["status"] == "records" and sched["records"][0]["check"] == "results_filing"
    assert lad["checks_with_records"] == ["company_word", "scheduled_report"]
    assert lad["nothing_found"] is False


def test_the_company_list_carries_item_codes_and_a_past_window_closes_at_that_days_close(monkeypatch):
    from alphadesk.ingest import edgar
    monkeypatch.setattr(edgar, "cik_for", lambda s: "0001364479")
    monkeypatch.setattr(edgar, "get_json", lambda url, *a, **k: {})
    monkeypatch.setattr(edgar, "filings_for_cik", lambda cik, sym, forms, limit=20: [
        {"accession": "a1", "form": "8-K", "accepted_at": "2026-10-27T06:31:02-04:00", "url": "u", "items": "2.02,9.01"},
        {"accession": "a2", "form": "8-K", "accepted_at": "2026-10-27T17:05:00-04:00", "url": "u", "items": "8.01"},
    ])
    got, _ = edgar_feed.filings_since(["HRI"], "2026-10-26T16:00:00-04:00", [], until="2026-10-27T16:00:00-04:00")
    assert [f["accession"] for f in got["HRI"]] == ["a1"]       # after the close bears on the next session
    assert got["HRI"][0]["items"][0]["number"] == "2.02"


def test_a_wire_release_counts_only_when_its_headline_names_the_company():
    stories = focus.sort_stories("SOFI", "SoFi", [
        {"article_id": "1", "title": "SoFi Reports Third Quarter 2026 Results", "kind": "release", "tickers": ["SOFI"]},
        {"article_id": "2", "title": "KBRA Assigns Preliminary Ratings to FTAI MRE 2026-2", "kind": "release",
         "tickers": ["SOFI"]},
    ])
    assert [a["article_id"] for a in stories["releases"]] == ["1"]
    assert [a["article_id"] for a in stories["read_for_passages"]] == ["2"]


# ── a mover explained only by a round-up passage ──

BOEING_WRAP = (
    "<p>U.S. stocks traded mixed midway through trading on Tuesday.</p>"
    "<p>Shares of Boeing Co (NYSE:BA) fell sharply after the company pushed its 737 production target into "
    "2027 and guided 2027 free cash flow below expectations.</p>"
    "<p>Valero Energy Corp (NYSE:VLO) and Marathon Petroleum Corp (NYSE:MPC) declined as diesel and gasoline "
    "futures fell about 2% and 1.5%.</p>")


def test_a_round_up_sentence_is_quoted_verbatim_with_its_story():
    text = focus.plain_text(BOEING_WRAP)
    got = focus.passages(text, "BA", focus.company_short_name("Boeing Company"))
    assert got == ["Shares of Boeing Co (NYSE:BA) fell sharply after the company pushed its 737 production "
                   "target into 2027 and guided 2027 free cash flow below expectations"]
    assert got[0] in text                                  # verbatim: a substring of the story itself
    wrap = {"article_id": "w1", "title": "Mid-Day Market Update", "kind": "movers",
            "tickers": ["BA", "VLO", "MPC", "KO", "SPY", "QQQ", "DIA", "IWM"]}
    stories = focus.sort_stories("BA", "Boeing", [wrap])
    assert stories["own"] == [] and stories["read_for_passages"] == [wrap]
    found = [{"check": "tagged_story_passage", **focus._story_ref(wrap), "passage": got[0]}]
    lad = focus.ladder("BA", "Boeing Company", -10.9, WINDOW, **_empty(stories=stories, passages_found=found))
    assert lad["checks_with_records"] == ["roundup_passages"]
    assert lad["rungs"]["roundup_passages"]["records"][0]["article_id"] == "w1"
    assert lad["rungs"]["third_party"]["status"] == "empty"


def test_a_company_abbreviation_does_not_end_the_sentence_and_a_table_row_is_not_prose():
    text = ("Valero Energy Corp. (NYSE:VLO) dropped 7% with the refiners, as Phillips 66 (NYSE:PSX) and "
            "Marathon Petroleum Corp. (NYSE:MPC) also fell. Oil was flat.")
    assert focus.passages(text, "VLO", "Valero") == [
        "Valero Energy Corp. (NYSE:VLO) dropped 7% with the refiners, as Phillips 66 (NYSE:PSX) and "
        "Marathon Petroleum Corp. (NYSE:MPC) also fell"]
    grid = " ".join(f"{t} CALL SWEEP BULLISH 10/30/26 $55.00 $87.9K 184 482" for t in
                    ("RTX", "WCN", "INOD", "AAPL", "MSFT", "NVDA", "AMD", "TSLA"))
    assert focus.passages(grid, "INOD", "Innodata") == []


def test_a_short_ticker_is_matched_only_in_a_tickers_dress():
    assert focus.names_company("(NYSE: DK) slid", "DK", None)
    assert not focus.names_company("DK Metcalf caught two passes", "DK", None)
    assert focus.names_company("Delek US shares slid", "DK", focus.company_short_name("Delek US Holdings, Inc."))
    assert focus.company_short_name("National Vision Holdings, Inc. Common Stock") == "National Vision"
    assert focus.company_short_name("Par Pacific Holdings, Inc. Common Stock") == "Par Pacific"


# ── a mover explained by a group move ──

def test_refiners_share_an_sec_industry_and_one_members_passage_reaches_every_member():
    refiners = {"DK": -9.8, "PARR": -9.81, "VLO": -8.78, "DINO": -8.35, "PBF": -8.21, "MPC": -7.0, "CVI": -7.5}
    rows = [{"symbol": s, "change_pct": c} for s, c in refiners.items()] + [{"symbol": "BA", "change_pct": -10.9}]
    industry = {s: {"sic": "2911", "industry": "PETROLEUM REFINING"} for s in refiners}
    industry["BA"] = {"sic": "3721", "industry": "AIRCRAFT"}
    passage = {"check": "tagged_story_passage", "article_id": "w1", "title": "Mid-Day Market Update",
               "passage": "Valero Energy Corp (NYSE:VLO) and Marathon Petroleum Corp (NYSE:MPC) declined as diesel "
                          "and gasoline futures fell about 2% and 1.5%"}
    groups = focus.group_records(rows, industry, {}, {}, {"VLO": [passage]},
                                 {"DK": {"vendor_sector": "Energy", "fund": "XLE", "fund_change_pct": -1.9}})
    dk = groups["DK"]
    assert dk["sec_industry"]["moved_together"] is True
    assert len(dk["sec_industry"]["others_in_this_list"]) == 6
    assert dk["member_passages"][0]["via"] == "VLO"
    assert groups["BA"]["sec_industry"]["moved_together"] is False
    lad = focus.ladder("DK", "Delek US Holdings, Inc.", -9.8, WINDOW, **_empty(group=dk))
    grp = lad["rungs"]["group_move"]
    assert lad["checks_with_records"] == ["group_move"]
    assert [r["check"] for r in grp["records"]] == ["sec_industry", "group_member_passage"]
    assert grp["sector_fund"]["fund"] == "XLE"                 # context, never a record


def test_the_vendors_industry_catches_a_refiner_the_sec_files_elsewhere_and_own_news_stays_put():
    rows = [{"symbol": "DK", "change_pct": -9.8}, {"symbol": "PARR", "change_pct": -9.81},
            {"symbol": "DINO", "change_pct": -8.4},
            {"symbol": "MBRX", "change_pct": -31.9}, {"symbol": "KNSA", "change_pct": -23.4}]
    industry = {"DK": {"sic": "2911"}, "PARR": {"sic": "1311"},          # the SEC files Par Pacific as crude production
                "DINO": {"sic": "4610"}, "MBRX": {"sic": "2834"}, "KNSA": {"sic": "2834"}}
    vendor = {"DK": "Oil & Gas Refining & Marketing", "PARR": "Oil & Gas Refining & Marketing",
              "DINO": "Oil & Gas Refining & Marketing", "MBRX": "Biotechnology", "KNSA": "Medical - Pharmaceuticals"}
    group_sentence = {"check": "tagged_story_passage", "passage": "Delek US (NYSE:DK) and Valero (NYSE:VLO) slid"}
    own_news = {"check": "tagged_story_passage", "passage": "Kiniksa (NASDAQ:KNSA) fell after its trial update"}
    groups = focus.group_records(rows, industry, {}, {}, {"DK": [group_sentence], "KNSA": [own_news]}, {}, vendor)
    assert groups["PARR"]["sec_industry"]["moved_together"] is False
    assert groups["PARR"]["vendor_industry"]["moved_together"] is True
    assert groups["PARR"]["member_passages"][0]["via"] == "DK"
    # Two companies sharing a code is not a group move, and a sentence about
    # one's own news is not passed to the other.
    assert groups["MBRX"]["sec_industry"]["moved_together"] is False
    assert "member_passages" not in groups["MBRX"]
    assert focus.tickers_named("Valero Energy Corp (NYSE:VLO) and Marathon (MPC) fell") == {"VLO", "MPC"}


def test_a_basket_holds_a_record_only_when_two_other_members_moved_the_same_way():
    basket = {"id": "oil", "label": "Oil & gas", "symbols": ["XOM", "CVX", "COP", "OXY"]}
    of = {m: basket for m in basket["symbols"]}
    rows = [{"symbol": "OXY", "change_pct": -6.0}]
    together = focus.group_records(rows, {}, of, {"XOM": -2.1, "CVX": -1.4, "COP": 0.3}, {}, {})
    assert together["OXY"]["basket"]["same_direction"] == 2 and together["OXY"]["basket"]["moved_together"]
    apart = focus.group_records(rows, {}, of, {"XOM": -2.1, "CVX": 1.4, "COP": None}, {}, {})
    assert apart["OXY"]["basket"]["moved_together"] is False and apart["OXY"]["basket"]["members_measured"] == 2


# ── a mover explained by a corporate action ──

def test_a_listing_with_no_prior_close_is_marked_and_its_spin_off_is_a_record():
    spin = {"type": "spin_offs", "dates": ["2026-10-24"], "symbols": ["MSGS", "MSGR"], "detail": {"new_symbol": "MSGR"}}
    assert focus.action_counts(spin, ("2026-10-13", "2026-10-27"))
    dividend = {"type": "cash_dividends", "dates": ["2026-10-27"], "symbols": ["MSGR"], "detail": {"rate": 0.2}}
    assert not focus.action_counts(dividend, ("2026-10-13", "2026-10-27"))
    assert focus.action_counts({**dividend, "detail": {"special": True}}, ("2026-10-13", "2026-10-27"))
    listing = [{"form": "10-12B", "filed_at": "2026-10-01", "accession": "x", "url": "u"}]
    lad = focus.ladder("MSGR", "MSG Rangers Corp.", 1271.3, WINDOW,
                       **_empty(actions=[focus.action_ref(spin)], listing_filings=listing, prior_sessions=0))
    corp = lad["rungs"]["corporate_action"]
    assert [r["check"] for r in corp["records"]] == ["corporate_actions_feed", "listing_filing", "daily_bars"]
    assert corp["change_base"] == {"prior_sessions_in_daily_bars": 0, "change_has_a_prior_close": False}
    assert lad["checks_with_records"] == ["corporate_action"]


def test_a_report_after_yesterdays_close_or_before_todays_counts_and_tomorrows_does_not():
    row = lambda **k: {"symbol": "AEYE", **k}  # noqa: E731
    assert focus.report_in_window(row(report_date="2026-10-26", session="AMC"), "AEYE", DAY)
    assert focus.report_in_window(row(report_date="2026-10-27", session="BMO"), "AEYE", DAY)
    assert not focus.report_in_window(row(report_date="2026-10-27", session="AMC"), "AEYE", DAY)
    assert not focus.report_in_window(row(report_date="2026-10-26", session="BMO"), "AEYE", DAY)
    assert focus.report_in_window(row(report_date="2026-10-26", released_at="2026-10-26T16:09:45-04:00"), "AEYE", DAY)
    assert not focus.report_in_window(row(report_date="2026-10-27", session="BMO"), "OTHER", DAY)


# ── a mover with nothing found ──

def test_nothing_found_names_every_check_that_ran_and_every_one_that_could_not_be_read():
    lad = focus.ladder("CLRO", "ClearOne, Inc. Common Stock", 15.2, WINDOW, **_empty())
    assert lad["nothing_found"] is True
    assert lad["checks_empty"] == list(focus.RUNGS) and lad["checks_unread"] == {}
    # An unreadable source is never an empty one.
    lad = focus.ladder("CLRO", "ClearOne, Inc. Common Stock", 15.2, WINDOW,
                       **_empty(filings=None, halts=None),
                       unread={"company_word": "EDGAR rate limit: paused",
                               "market_structure": "the halts list holds the current session only"})
    assert lad["rungs"]["company_word"]["status"] == "unread"
    assert lad["checks_unread"]["company_word"] == "EDGAR rate limit: paused"
    assert "company_word" not in lad["checks_empty"] and lad["nothing_found"] is True
    assert focus.coverage([lad])["nothing_found"] == ["CLRO"]


def test_no_news_feed_leaves_the_story_checks_unread():
    lad = focus.ladder("X", "X Corp", 9.0, WINDOW, **_empty(stories=None, passages_found=None),
                       unread={"third_party": "no news feed is connected", "roundup_passages": "no news feed is connected"})
    assert set(lad["checks_unread"]) == {"company_word", "third_party", "roundup_passages"}



# ── when the move began, and which records came before it ──

def _bars(*pairs):
    """1-minute bars from (New York HH:MM on the 27th, close) pairs, stamped in
    UTC as the vendor stamps them."""
    from datetime import datetime, timezone
    from alphadesk.desk import sessions as cal
    out = []
    for hhmm, close in pairs:
        day = 26 if hhmm >= "16:00" and hhmm.startswith(("16", "17", "18", "19")) else 27
        h, m = map(int, hhmm.split(":"))
        at = datetime(2026, 10, day, h, m, tzinfo=cal.NY).astimezone(timezone.utc)
        out.append({"t": at.isoformat(), "c": close})
    return out


def _since():
    from datetime import datetime
    from alphadesk.desk import sessions as cal
    return datetime(2026, 10, 26, 16, 0, tzinfo=cal.NY)


def test_the_move_began_in_the_bar_that_first_covered_a_quarter_of_it():
    bars = _bars(("09:30", 10.0), ("09:31", 10.1), ("09:32", 10.2), ("09:33", 10.3), ("09:34", 10.4),
                 ("09:35", 10.6), ("09:36", 10.4), ("09:40", 11.2))
    got = focus.move_start(bars, 10.0, 20.0, _since())
    assert got["found"] and got["began_after"] == "2026-10-27T09:35-04:00"
    assert got["began_by"] == "2026-10-27T09:36-04:00" and got["interval_minutes"] == 1
    assert got["price_at_that_share"] == 10.5 and got["half_of_move_by"] == "2026-10-27T09:41-04:00"
    # A loser is read the other way.
    down = _bars(("09:30", 10.0), ("09:31", 9.7), ("09:32", 9.4))
    assert focus.move_start(down, 10.0, -20.0, _since())["began_by"] == "2026-10-27T09:33-04:00"


def test_sparse_trading_gives_a_wide_interval_never_a_guessed_instant():
    bars = _bars(("16:30", 10.0), ("16:31", 10.0), ("08:00", 10.8))
    got = focus.move_start(bars, 10.0, 20.0, _since())
    assert got["began_after"] == "2026-10-26T16:32-04:00" and got["began_by"] == "2026-10-27T08:01-04:00"
    assert got["interval_minutes"] == 929


def test_no_bar_or_no_crossing_is_said_and_orders_nothing():
    assert focus.move_start([], 10.0, 20.0, _since())["not_found_note"].startswith("the reader's intraday bars")
    flat = focus.move_start(_bars(("09:30", 10.0), ("09:31", 10.1)), 10.0, 20.0, _since())
    assert flat["found"] is False and "25%" in flat["not_found_note"]
    assert focus.move_start(_bars(("09:30", 10.0)), None, 20.0, _since())["found"] is False
    lad = focus.ladder("X", "X Corp", 20.0, WINDOW, move=flat,
                       **_empty(filings=[{"form": "8-K", "filed_at": "2026-10-27T07:00:00-04:00"}]))
    assert lad["time_order"] is None and lad["move_began"] is flat
    assert "time_order" not in lad["rungs"]["company_word"]["records"][0]


def test_each_timed_record_is_placed_before_inside_or_after_the_start():
    start = focus.move_start(_bars(("09:34", 10.0), ("09:35", 10.6)), 10.0, 20.0, _since())
    order = lambda rec: focus.time_order(rec, start)  # noqa: E731
    assert order({"filed_at": "2026-10-27T07:00:00-04:00"}) == {"order": "before_move", "minutes_from_move_start": -155}
    assert order({"published_at": "2026-10-27T13:35:30Z"})["order"] == "as_move_began"
    assert order({"published_at": "2026-10-27T14:06:00Z"}) == {"order": "after_move_began", "minutes_from_move_start": 30}
    assert order({"halted_at": "2026-10-27T09:40:00-04:00"})["order"] == "after_move_began"
    assert order({"filed_at": "2026-10-27"}) == {"order": "dated_by_day_only"}
    assert order({"type": "spin_offs", "dates": ["2026-10-24"]}) == {"order": "dated_by_day_only"}
    assert order({"report_date": "2026-10-27", "session": "bmo"}) == {"order": "dated_by_day_only"}
    assert order({"check": "sec_industry", "sic": "2911"}) is None


def test_the_ladder_counts_records_by_order_and_names_the_earliest_before_the_move():
    start = focus.move_start(_bars(("09:34", 10.0), ("09:35", 10.6)), 10.0, 20.0, _since())
    story = {"article_id": "s1", "title": "X Corp shares trade higher", "published_at": "2026-10-27T14:10:00Z"}
    lad = focus.ladder("X", "X Corp", 20.0, WINDOW, move=start, **_empty(
        filings=[{"form": "8-K", "filed_at": "2026-10-27T07:00:00-04:00", "items": []},
                 {"form": "8-K", "filed_at": "2026-10-26T17:05:00-04:00", "items": []}],
        stories={"releases": [], "analyst_notes": [], "own": [story], "read_for_passages": []},
        halts=[{"halted_at": "2026-10-27T09:40:00-04:00"}]))
    assert lad["time_order"] == {"before_move": 2, "as_move_began": 0, "after_move_began": 2,
                                 "dated_by_day_only": 0,
                                 "earliest_before_move": {"rung": "company_word", "check": "sec_filing",
                                                          "at": "2026-10-26T17:05:00-04:00"}}
    assert lad["rungs"]["third_party"]["records"][0]["time_order"]["order"] == "after_move_began"
    after_only = focus.ladder("Y", "Y Inc", 20.0, WINDOW, move=start, **_empty(
        stories={"releases": [], "analyst_notes": [], "own": [{**story, "title": "Y Inc shares trade higher"}],
                 "read_for_passages": []}))
    cov = focus.coverage([lad, after_only])
    assert cov["move_start_found"] == 2
    assert cov["with_a_record_before_the_move"] == ["X"]
    assert cov["records_only_after_the_move_began"] == ["Y"]


# ── what may never appear ──

def test_no_field_names_a_verdict_and_the_description_names_every_check():
    from alphadesk import mcp_server
    lad = focus.ladder("BA", "Boeing Company", -10.9, WINDOW,
                       **_empty(filings=[{"form": "8-K", "items": edgar_feed.items_from_codes("7.01")}],
                                passages_found=[{"check": "tagged_story_passage", "passage": "Boeing fell"}]))
    banned = ("verdict", "score", "rating", "signal", "recommend", "reason", "cause", "likel", "confidence", "explain")
    assert not [k for k in _keys(lad) if any(b in k.lower() for b in banned)]
    doc = mcp_server.movers_in_context.__doc__ or ""
    for rung in focus.RUNGS:
        assert f"`{rung}`" in doc, rung
    for word in ("unread", "nothing_found", "not_covered", "VERBATIM"):
        assert word in doc


# ── the whole tool, every source stood in for ──

class _Router:
    owner = "u1"

    def ask(self, method, *args, **kw):
        if method == "trading_halts":
            return [{"symbol": "CLRO", "halted_at": "2026-10-27T10:02:00-04:00", "reason": "LUDP"}]
        if method == "corporate_action_events":
            return [{"type": "spin_offs", "dates": ["2026-10-24"], "symbols": ["MSGS", "MSGR"], "detail": {}}]
        if method == "daily_history":
            old = [{"ts": f"2026-10-{d:02d}T04:00:00Z", "close": 10.0} for d in (20, 21, 22, 23, 26)]
            return {s: ([] if s == "MSGR" else old) for s in args[0]}
        raise AssertionError(method)

    # Flat from the open, then every name jumps at 09:45 New York.
    BARS = [{"t": f"2026-10-27T13:{m:02d}:00Z", "c": 10.0 if m < 45 else 10.5} for m in range(30, 50)]

    def chart_series(self, symbol, days=2, range_key=None, before=None, need=None):
        return {"bars": self.BARS}

    def get(self, method, *args, **kw):
        return {"company_profile": {"sector": "Energy"}, "short_interest": {"shares_short": 1000, "as_of": "2026-10-15"}}.get(method)


def test_the_tool_returns_a_ladder_per_row_and_counts_coverage(monkeypatch):
    from alphadesk import config, identity, mcp_server, providers
    from alphadesk.desk import sessions as cal
    from alphadesk.ingest import earnings_calendar, edgar, movers as mv, sectors as sec
    from alphadesk.ledger import store
    import alphadesk.config as cfg
    from datetime import datetime

    movers = [{"symbol": "MSGR", "name": "MSG Rangers Corp.", "change_pct": 1271.3},
              {"symbol": "DK", "name": "Delek US Holdings, Inc.", "change_pct": 9.8},
              {"symbol": "VLO", "name": "Valero Energy Corporation", "change_pct": 8.8},
              {"symbol": "CLRO", "name": "ClearOne, Inc. Common Stock", "change_pct": 15.2},
              {"symbol": "AEHR", "name": "Aehr Test Systems Common Stock", "change_pct": 13.4}]
    monkeypatch.setattr(cfg, "now_et", lambda: datetime(2026, 10, 27, 15, 30, tzinfo=cal.NY))
    monkeypatch.setattr(mv, "category_movers", lambda cat, top=10: {"tabs": [{"id": "gainers", "rows": movers}]})
    monkeypatch.setattr(providers, "get_prices", lambda: _Router())
    monkeypatch.setattr(identity, "request_user", lambda: "u1")
    monkeypatch.setattr(mcp_server, "_data_freshness", lambda: {})
    monkeypatch.setattr(edgar_feed, "recent", lambda **k: {"filings": []})
    monkeypatch.setattr(edgar_feed, "filings_since", lambda syms, since, feed, until=None: (
        {s: ([{"form": "8-K", "filed_at": "2026-10-27T07:00:00-04:00", "accession": "a",
               "items": edgar_feed.items_from_codes("2.02")}] if s == "AEHR" else []) for s in syms}, {}))
    sic = {"DK": "2911", "VLO": "2911", "MSGR": "7941", "CLRO": "3661", "AEHR": "3825"}
    monkeypatch.setattr(edgar, "cik_for", lambda s: s)
    monkeypatch.setattr(edgar, "get_json", lambda url, *a, **k: {"sic": next(v for s, v in sic.items() if s in url)})
    monkeypatch.setattr(edgar, "_SUBMISSIONS_URL", "sub/{cik10}")
    monkeypatch.setattr(edgar, "filings_for_cik", lambda cik, sym, forms, limit=10: [])
    monkeypatch.setattr(earnings_calendar, "shared_rows_between", lambda a, b, stats=False: [])
    monkeypatch.setattr(sec, "sectors", lambda: {"sectors": [{"symbol": "XLE", "change_pct": 1.1}]})
    monkeypatch.setattr(config, "THEMES", [])
    monkeypatch.setattr(store, "get_user_keys", lambda uid, kind: [{"provider": "alpaca"}])
    wrap = {"article_id": "w1", "title": "Mid-Day Market Update", "url": "https://www.benzinga.com/trading-ideas/movers/26/10/1/x",
            "source": "benzinga", "published_at": "2026-10-27T12:00:00-04:00",
            "tickers": ["VLO", "A", "B", "C", "D", "E", "F", "G"]}
    monkeypatch.setattr(store, "articles_for_symbol", lambda owner, sym, before, limit, body=False:
                        [wrap] if sym == "VLO" else [])
    monkeypatch.setattr(store, "recent_articles", lambda since, limit=600, owner="", body=False: [wrap])
    monkeypatch.setattr(store, "article", lambda owner, aid: {
        **wrap, "body": "<p>Valero Energy Corp (NYSE:VLO) and Marathon Petroleum (NYSE:MPC) fell as diesel futures slid about 2%.</p>"})

    got = mcp_server.movers_in_context("gainers", top=5, with_shape=False)
    ev = {r["symbol"]: r["evidence"] for r in got["rows"]}
    assert ev["VLO"]["rungs"]["roundup_passages"]["records"][0]["passage"].startswith("Valero Energy Corp (NYSE:VLO)")
    assert ev["DK"]["rungs"]["group_move"]["records"][-1]["via"] == "VLO"
    assert ev["MSGR"]["rungs"]["corporate_action"]["change_base"]["change_has_a_prior_close"] is False
    assert ev["CLRO"]["checks_with_records"] == ["market_structure"]
    assert ev["AEHR"]["checks_with_records"] == ["company_word", "scheduled_report"]
    assert got["coverage"]["rows"] == 5 and got["coverage"]["nothing_found"] == []
    assert got["rows"][0]["context"]["short_interest"]["shares_short"] == 1000
    assert any("FDA" in n for n in got["not_covered"])
    assert got["unavailable"] == {}
    # The 8-K at 07:00 came before the 09:45 move; the halt at 10:02 after it.
    assert ev["AEHR"]["move_began"]["began_by"] == "2026-10-27T09:46-04:00"
    assert ev["AEHR"]["rungs"]["company_word"]["records"][0]["time_order"]["order"] == "before_move"
    assert ev["CLRO"]["rungs"]["market_structure"]["records"][0]["time_order"]["order"] == "after_move_began"
    assert ev["VLO"]["rungs"]["roundup_passages"]["records"][0]["time_order"]["order"] == "after_move_began"
    # MSGR has no prior session and no price, so no start can be measured.
    assert ev["MSGR"]["move_began"]["found"] is False and ev["MSGR"]["time_order"] is None
    assert got["coverage"]["with_a_record_before_the_move"] == ["AEHR"]

    # After the bell the list measures a late print from the session just
    # closed, so the start is searched from today's close, not yesterday's —
    # where this name, high last evening and flat all day, would have read
    # as moving from the first minute (live, 2026-10-27).
    monkeypatch.setattr(cfg, "now_et", lambda: datetime(2026, 10, 27, 17, 0, tzinfo=cal.NY))
    monkeypatch.setattr(mv, "category_movers", lambda cat, top=10: {"tabs": [{"id": "gainers", "rows": [
        {"symbol": "UCTT", "name": "Ultra Clean Holdings", "price": 11.5, "change_pct": 15.0, "extended": True}]}]})
    monkeypatch.setattr(_Router, "BARS", [{"t": "2026-10-26T20:01:00Z", "c": 10.5}, {"t": "2026-10-26T20:02:00Z", "c": 10.5},
                                          {"t": "2026-10-27T19:58:00Z", "c": 10.0}, {"t": "2026-10-27T19:59:00Z", "c": 10.0},
                                          {"t": "2026-10-27T20:10:00Z", "c": 11.5}])
    late = mcp_server.movers_in_context("gainers", top=1, with_shape=False)["rows"][0]["evidence"]["move_began"]
    assert late["measured_from"] == "2026-10-27T16:00-04:00" and late["previous_close"] == 10.0
    assert late["began_by"] == "2026-10-27T16:11-04:00"

    # A past session: the story window's end reaches the store in UTC, the
    # stored stamps' own zone, because they are compared as text.
    seen = []
    monkeypatch.setattr(mv, "session_movers", lambda cat, day, top=10: {"tabs": [{"id": "gainers", "rows": movers}]})
    monkeypatch.setattr(store, "articles_for_symbol", lambda owner, sym, before, limit, body=False: seen.append(before) or [])
    monkeypatch.setattr(store, "articles_before", lambda owner, before, limit=600, body=False: seen.append(before) or [])
    got = mcp_server.movers_in_context("gainers", top=5, session="2026-10-23")
    assert set(seen) == {"2026-10-23T20:00:00+00:00"}
    assert got["window"]["from"].startswith("2026-10-22T16:00")
    assert got["rows"][0]["evidence"]["checks_unread"]["market_structure"].startswith("the halts list holds")
    # A window the store holds no story for at all is a gap in what was
    # stored, so the story checks are unread, never empty.
    unread = got["rows"][0]["evidence"]["checks_unread"]
    assert unread["third_party"].startswith("the stored news holds no story at all")
    assert "roundup_passages" in unread and got["news_window"]["stories_read"] == 0

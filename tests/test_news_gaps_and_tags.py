"""The days a reader was away are filled on their return, and a story keeps
only US-listed tags (2026-11-23)."""

from datetime import datetime, timedelta, timezone

import pytest

from alphadesk.ingest import news

NOW = datetime(2026, 11, 19, 14, 34, tzinfo=timezone.utc)


@pytest.fixture
def universe(monkeypatch):
    """A loaded list: SEC tickers, a fund the SEC file lacks, and a coin pair."""
    import alphadesk.config as config
    listed = {"MFG", "NVS", "AVY", "ROP", "QQQ", "BTC-USD", "BRK-B"}
    monkeypatch.setattr(config, "in_universe", lambda s: s.upper().replace(".", "-") in listed)
    monkeypatch.setattr(news, "_listing_loaded", lambda uid: True)
    return listed


def _story(i, tickers):
    return {"id": f"s{i}", "title": f"story {i}", "tickers": tickers, "published_at": NOW.isoformat()}


def test_a_story_with_no_us_ticker_is_left_out_and_foreign_tags_are_dropped(universe):
    rows = [_story(1, ["1155"]),                         # Maybank, Bursa Malaysia
            _story(2, ["SIE"]),                          # Siemens, Xetra
            _story(3, ["MFG"]),                          # Mizuho's US listing
            _story(4, ["AVY", "DHL", "ROP"]),            # a mix
            _story(5, ["QQQ"]),                          # a fund the SEC file lacks
            _story(6, ["BTC-USD", "9984"]),              # a coin and SoftBank
            _story(7, ["BRK.B"])]                        # a share class as a vendor writes it
    kept = {r["id"]: r["tickers"] for r in news.us_listed_only(rows, "u")}
    assert kept == {"s3": ["MFG"], "s4": ["AVY", "ROP"], "s5": ["QQQ"], "s6": ["BTC-USD"], "s7": ["BRK.B"]}


def test_nothing_is_dropped_until_the_broker_listing_is_in(monkeypatch):
    """Without the funds the SEC file leaves out, SPY would be cut off a story;
    keeping a foreign code is the lesser fault."""
    monkeypatch.setattr(news, "_listing_loaded", lambda uid: False)
    rows = [_story(1, ["1155"]), _story(2, ["SPY"])]
    assert news.us_listed_only(rows, "u") == rows


def test_every_save_goes_through_the_filter(universe, monkeypatch):
    saved = []
    monkeypatch.setattr(news.store, "save_articles", lambda rows, owner="": saved.append((owner, rows)))
    out = news._save([_story(1, ["9984"]), _story(2, ["NVS"])], "reader-1")
    assert [r["id"] for r in out] == ["s2"]
    assert saved == [("reader-1", out)]
    saved.clear()
    assert news._save([_story(3, ["1155"])], "reader-1") == [] and saved == []   # nothing to store


def test_a_cursor_days_back_is_a_gap_and_a_cycle_is_not(monkeypatch):
    import alphadesk.config as config
    monkeypatch.setattr(config, "NEWS_BACKFILL_DAYS", 30.0)
    assert news.gap_days(NOW - timedelta(minutes=5), NOW) == 0                   # an ordinary cycle
    assert news.gap_days(NOW - timedelta(minutes=29), NOW) == 0
    four = news.gap_days(NOW - timedelta(days=4, hours=1), NOW)                  # away 15-19 November
    assert 4.04 < four < 4.11
    assert news.gap_days(NOW - timedelta(days=90), NOW) == 30.0                  # capped at the window


def test_the_gap_is_walked_on_every_news_feed(monkeypatch):
    import alphadesk.config as config
    monkeypatch.setattr(config, "NEWS_BACKFILL_DAYS", 30.0)
    monkeypatch.setattr(news.store, "get_user_keys", lambda uid, seam: [{"provider": "alpaca"}, {"provider": "fmp"}])
    walked = []
    monkeypatch.setattr(news, "backfill_user", lambda uid, provider, days: walked.append((provider, round(days, 2))) or 7)
    assert news.fill_gap("u", NOW - timedelta(days=4), NOW) == 14
    assert walked == [("alpaca", 4.04), ("fmp", 4.04)]
    walked.clear()
    assert news.fill_gap("u", NOW - timedelta(minutes=5), NOW) == 0 and walked == []


def test_after_a_restart_the_cursor_is_read_from_the_store(monkeypatch):
    monkeypatch.setattr(news.store, "get_user_keys", lambda uid, seam: [
        {"provider": "alpaca", "last_used_at": "2026-11-15T13:20:00+00:00"},
        {"provider": "fmp", "last_used_at": None}])
    assert news.resume_point("u", NOW) == datetime(2026, 11, 15, 13, 20, tzinfo=timezone.utc)
    monkeypatch.setattr(news.store, "get_user_keys", lambda uid, seam: [{"provider": "alpaca", "last_used_at": None}])
    assert news.resume_point("u", NOW) is None


def test_a_fiscal_ai_tag_on_another_company_is_dropped(universe, monkeypatch):
    """Centrica's own news, tagged CNA (CNA Financial in New York), and a
    story naming Mizuho: only the second keeps its tag (2026-11-26)."""
    import alphadesk.config as config
    universe.add("CNA")
    names = {"CNA": "CNA FINANCIAL CORP", "MFG": "MIZUHO FINANCIAL GROUP INC"}
    monkeypatch.setattr(config, "company_name", lambda s: names.get(s))
    rows = [{**_story(1, ["CNA"]), "title": "Centrica plc Director/PDMR Share Transaction", "source": "fiscal.ai"},
            {**_story(2, ["MFG"]), "title": "Mizuho Raises Its Outlook", "source": "fiscal.ai"}]
    kept = {r["id"]: r["tickers"] for r in news.us_listed_only(rows, "u")}
    assert kept == {"s2": ["MFG"]}


def test_other_publishers_tags_are_not_checked(universe, monkeypatch):
    """Polygon and FMP tag companies an article names only in its body; the
    check would cut a third of their correct tags, so it does not run."""
    import alphadesk.config as config
    universe.add("CNA")
    monkeypatch.setattr(config, "company_name", lambda s: "CNA FINANCIAL CORP")
    rows = [{**_story(1, ["CNA"]), "title": "Insurers Brace for a Costly Storm Season", "source": "The Motley Fool"}]
    assert news.us_listed_only(rows, "u")[0]["tickers"] == ["CNA"]


def test_a_known_past_gap_is_walked_once_it_is_found_short(monkeypatch):
    """15-19 November 2026 was never stored (2026-11-26). The fill walks it
    only while the window is short, so a filled window is never asked again."""
    calls = []
    monkeypatch.setattr(news.store, "count_articles_between", lambda o, a, b: 12)
    monkeypatch.setattr(news, "fill_window", lambda uid, a, b: calls.append((a, b)) or 900)
    assert news.fill_past_gaps("u") == 900
    assert [(a.isoformat()[:13], b.isoformat()[:13]) for a, b in calls] == [("2026-11-15T12", "2026-11-20T00")]

    calls.clear()
    monkeypatch.setattr(news.store, "count_articles_between", lambda o, a, b: news.PAST_GAP_FULL)
    assert news.fill_past_gaps("u") == 0 and calls == []


def test_the_window_is_walked_backwards_to_its_start(monkeypatch):
    """Each ask ends where the last one's oldest story began, and stops at the
    window's start."""
    from types import SimpleNamespace
    start = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
    end = datetime(2026, 11, 20, tzinfo=timezone.utc)
    asked = []

    class Feed:
        def fetch(self, since, limit=0, until=None):
            asked.append(until)
            oldest = until - timedelta(days=2)
            return [SimpleNamespace(published_at=(oldest if i == 0 else until - timedelta(minutes=i)).isoformat())
                    for i in range(limit)]

    monkeypatch.setattr(news.store, "get_user_keys", lambda uid, kind: [{"provider": "alpaca", "created_at": "", "config": None}])
    monkeypatch.setattr(news, "_user_news_provider", lambda *a: Feed())
    monkeypatch.setattr(news, "_article_dicts", lambda got, name: [{"id": str(i)} for i in range(len(got))])
    monkeypatch.setattr(news, "_save", lambda rows, uid, owner: rows)
    news.fill_window("u", start, end)
    assert asked == [end, end - timedelta(days=2), end - timedelta(days=4)]

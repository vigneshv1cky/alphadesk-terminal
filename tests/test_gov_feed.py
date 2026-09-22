"""WHAT THE GOVERNMENT JUST DID (2026-09-22). Keyless public data from three
services that do not agree about time, which is the thing these tests are
mostly about."""

import pytest

from alphadesk.ingest import gov_feed


def test_the_three_sources_do_not_agree_about_time_and_every_row_says_so():
    """A catalyst is a claim about WHEN. The Federal Register publishes once
    a day, so its stamp is a date and the decision often preceded it; the
    Fed's carries a real moment. A caller that reads the first as the second
    concludes a stock moved before the news, which is only the lag."""
    day = gov_feed._event("agencies", "Rule", "A rule", "2026-09-22", "day")
    moment = gov_feed._event("fed", "Press release", "FOMC", "2026-09-16T18:00:00+00:00", "second")
    assert day["at_precision"] == "day" and moment["at_precision"] == "second"
    assert set(day) >= {"source", "kind", "title", "at", "at_precision", "url"}


def test_an_rfc822_date_becomes_an_instant():
    assert gov_feed._rfc822("Fri, 18 Sep 2026 15:00:00 GMT") == "2026-09-18T15:00:00+00:00"
    assert gov_feed._rfc822("not a date") is None
    assert gov_feed._rfc822("") is None


def test_the_faa_is_left_out_of_the_default_shortlist():
    """Measured: 47 of 92 rules in a fortnight, nearly all airworthiness
    directives naming one aircraft model. It would have been more than half
    of every answer, so it is asked for by name or not at all."""
    assert "federal-aviation-administration" not in gov_feed.MARKET_AGENCIES
    assert "surface-transportation-board" in gov_feed.MARKET_AGENCIES
    assert "securities-and-exchange-commission" in gov_feed.MARKET_AGENCIES


def test_an_agency_slug_that_is_not_one_is_dropped_before_the_request(monkeypatch):
    """The slug goes into a URL, so anything that is not one never gets
    there — and a caller naming only nonsense falls back to the shortlist
    rather than asking for every agency at once."""
    seen = {}
    def fake(url, timeout=25.0):
        seen["url"] = url
        return '{"results": []}'
    monkeypatch.setattr(gov_feed, "_fetch", fake)
    gov_feed.federal_register(agencies=["surface-transportation-board", "../etc/passwd", "NOT A SLUG"])
    assert "surface-transportation-board" in seen["url"]
    assert "passwd" not in seen["url"] and "NOT%20A%20SLUG" not in seen["url"]


def test_a_source_that_could_not_be_read_is_named_not_emptied(monkeypatch):
    """A quiet day and an unreachable service must never look alike."""
    gov_feed.reset_cache()
    monkeypatch.setattr(gov_feed, "_READERS", {
        "fed": lambda **kw: [gov_feed._event("fed", "Press release", "FOMC", "2026-09-16T18:00:00+00:00", "second")],
        "treasury": lambda **kw: (_ for _ in ()).throw(gov_feed.GovUnavailable("refused (503)")),
    })
    monkeypatch.setattr(gov_feed, "SOURCES", {"fed": "Fed", "treasury": "Treasury"})
    out = gov_feed.recent()
    assert [e["title"] for e in out["events"]] == ["FOMC"]
    assert "503" in out["unavailable"]["treasury"]
    assert out["read_at"]["treasury"] is None and out["read_at"]["fed"]


def test_events_are_newest_first_across_sources(monkeypatch):
    gov_feed.reset_cache()
    monkeypatch.setattr(gov_feed, "_READERS", {
        "a": lambda **kw: [gov_feed._event("a", "Rule", "older", "2026-09-18", "day"),
                           gov_feed._event("a", "Rule", "newest", "2026-09-22", "day")],
        "b": lambda **kw: [gov_feed._event("b", "Auction", "middle", "2026-09-20", "day")],
    })
    monkeypatch.setattr(gov_feed, "SOURCES", {"a": "A", "b": "B"})
    out = gov_feed.recent()
    assert [e["title"] for e in out["events"]] == ["newest", "middle", "older"]


@pytest.mark.parametrize("value,expected", [("4.113000", 4.113), ("", None), (None, None), ("N/A", None)])
def test_a_rate_the_service_did_not_give_is_absent_not_zero(value, expected):
    """An unsettled auction has no rate. Zero would read as one."""
    assert gov_feed._num(value) == expected

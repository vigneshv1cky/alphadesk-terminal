"""The economic calendar: Finnhub's documented shape into the contract's
rows, the source order (selected provider, then the operator's key), the
unkeyed note, and a plan refusal reported as such (2026-09-13, built
against the documented payload without a premium key on hand)."""

import pytest

from alphadesk.ingest import economic
from alphadesk.providers import prices as pp


@pytest.fixture(autouse=True)
def _fresh():
    economic.reset_cache()


PAYLOAD = {"economicCalendar": [
    {"actual": None, "country": "US", "estimate": 0.3, "event": "CPI m/m", "impact": "high", "prev": 0.2, "time": "2026-09-15 12:30:00", "unit": "%"},
    {"actual": 4.25, "country": "US", "estimate": 4.25, "event": "Fed Interest Rate Decision", "impact": "high", "prev": 4.5, "time": "2026-09-16 18:00:00", "unit": "%"},
    {"actual": None, "country": "DE", "estimate": None, "event": "", "impact": "low", "prev": None, "time": "2026-09-14 06:00:00", "unit": ""},
    {"actual": 52.1, "country": "us", "estimate": 51.8, "event": "S&P Global Manufacturing PMI", "impact": "MEDIUM", "prev": 51.5, "time": "2026-09-14 13:45:00", "unit": ""},
]}


def test_finnhub_rows_normalize_and_sort():
    rows = pp.finnhub_economic_rows(PAYLOAD)
    assert [r["event"] for r in rows] == ["S&P Global Manufacturing PMI", "CPI m/m", "Fed Interest Rate Decision"]  # nameless row dropped, by time
    assert rows[1] == {"time": "2026-09-15T12:30:00Z", "country": "US", "event": "CPI m/m", "impact": "high",
                       "actual": None, "estimate": 0.3, "previous": 0.2, "unit": "%"}
    assert rows[0]["country"] == "US" and rows[0]["impact"] == "medium" and rows[0]["unit"] is None
    assert pp.finnhub_economic_rows(None) == [] and pp.finnhub_economic_rows({"economicCalendar": None}) == []


def test_finnhub_provider_asks_the_calendar_endpoint(monkeypatch):
    seen = {}
    def get_json(url, headers, timeout=20.0):
        seen["url"] = url; seen["headers"] = headers
        return PAYLOAD
    monkeypatch.setattr(pp, "_get_json", get_json)
    rows = pp.FinnhubPrices(api_key="k").economic_calendar("2026-09-14", "2026-09-20")
    assert seen["url"].endswith("/calendar/economic?from=2026-09-14&to=2026-09-20")
    assert seen["headers"] == {"X-Finnhub-Token": "k"}
    assert len(rows) == 3
    assert pp.PolygonPrices(api_key="k").economic_calendar("2026-09-14", "2026-09-20") is None


def test_no_vendor_is_a_key_prompt_naming_a_plan_refusal(vendors):
    from alphadesk.providers.base import NeedsKey

    class _Free:
        name = "finnhub"
        def economic_calendar(self, s, e):
            raise pp.EntitlementError("HTTP 403: You don't have access to this resource.")
    vendors(finnhub=_Free())
    with pytest.raises(NeedsKey) as exc:
        economic.calendar("2026-09-14", "2026-09-20")
    assert exc.value.prompt()["refused"] == ["Finnhub"]


def test_a_vendor_with_the_calendar_answers(vendors, monkeypatch):
    monkeypatch.setattr(pp, "_get_json", lambda url, headers, timeout=20.0: PAYLOAD)
    vendors(finnhub=pp.FinnhubPrices(api_key="k"))
    out = economic.calendar("2026-09-14", "2026-09-20")
    assert out["source"] == "finnhub" and len(out["rows"]) == 3
    assert out["start"] == "2026-09-14" and out["end"] == "2026-09-20"


def test_the_window_defaults_and_is_bounded():
    s, e = economic._window(None, None)
    assert (economic.date.fromisoformat(e) - economic.date.fromisoformat(s)).days == 7
    s, e = economic._window("2026-09-01", "2026-12-31")
    assert e == "2026-10-02"                      # capped at a month
    s, e = economic._window("2026-09-20", "2026-09-14")
    assert (s, e) == ("2026-09-14", "2026-09-20")  # reversed bounds swap

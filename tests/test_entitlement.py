"""A key's plan is a wall the platform only meets on contact: when it does,
the reader is told in words, the refused bar is remembered, and a coarser bar
the plan serves is tried before giving up."""
import json
from urllib.error import HTTPError

from alphadesk.providers import prices as prices_mod
from alphadesk.providers.base import EntitlementError, ProviderError


class _Body:
    def __init__(self, b): self.b = b
    def read(self): return self.b


def test_a_403_becomes_an_entitlement_error_with_the_vendor_sentence(monkeypatch):
    def fake_open(req, timeout=20.0):
        raise HTTPError(req.full_url, 403, "Forbidden", {}, _Body(json.dumps({"status": "NOT_AUTHORIZED", "message": "Your plan doesn't include this data timeframe"}).encode()))
    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    try:
        prices_mod._get_json("https://api.polygon.io/x", {})
        assert False, "should raise"
    except EntitlementError as exc:
        assert "doesn't include this data timeframe" in str(exc)
    assert issubclass(EntitlementError, ProviderError)


class _PlanProvider:
    """Serves minutes, refuses seconds — a free-tier shape."""
    name = "polygon"
    def __init__(self): self.calls = []
    def chart_intervals(self): return prices_mod.PolygonPrices._INTERVALS
    def chart_series(self, symbol, days=2, range_key=None, interval=None):
        self.calls.append(interval)
        if interval and interval.endswith("s"):
            raise EntitlementError("HTTP 403: Your plan doesn't include this data timeframe")
        return {"symbol": symbol, "bars": [{"t": "2026-09-10T14:00:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}] * 2,
                "interval": interval or "1m", "interval_label": interval or "1m", "intervals": [],
                "rsi_9": [None, None], "macd": [None, None], "macd_signal": [None, None], "macd_hist": [None, None],
                "thresholds": {"rsi_oversold": 30, "rsi_overbought": 70}, "bar_count": 2, "sessions": 1,
                "coverage": 1.0, "median_gap_min": None, "indicators_reliable": True}


def test_endpoint_tries_a_coarser_bar_and_says_why(monkeypatch):
    from fastapi.testclient import TestClient
    from alphadesk.app import dashboard
    from alphadesk.providers import registry
    import alphadesk.providers as pkg
    prov = _PlanProvider()
    monkeypatch.setattr(registry, "get_prices", lambda: registry.DataRouter("u", {prov.name: prov}))
    monkeypatch.setattr(pkg, "get_prices", lambda: registry.DataRouter("u", {prov.name: prov}))
    dashboard._refusals.clear()
    client = TestClient(dashboard.app)
    r = client.get("/api/chart/NVDA?range=1D&interval=1s")
    assert r.status_code == 200
    body = r.json()
    assert body["interval"] == "1m" and body["interval_requested"] == "1s"
    assert "plan does not include 1 sec bars" in body["plan_note"] and "showing 1 min" in body["plan_note"]
    # 1s refused, then 5s, 10s, 15s, 30s refused in turn, then 1m served.
    assert prov.calls == ["1s", "5s", "10s", "15s", "30s", "1m"][:len(prov.calls)]
    # The refusals are remembered and reported.
    caps = client.get("/api/chart/capabilities").json()
    assert "1s" in caps["refused"] and "5s" in caps["refused"]
    # A second ask for 1s skips the remembered walls straight to a served bar.
    prov.calls.clear()
    r2 = client.get("/api/chart/NVDA?range=1D&interval=1s")
    assert r2.status_code == 200 and "1s" not in prov.calls[1:]


def test_endpoint_402_when_nothing_coarser_serves(monkeypatch):
    from fastapi.testclient import TestClient
    from alphadesk.app import dashboard
    from alphadesk.providers import registry
    import alphadesk.providers as pkg
    class Wall(_PlanProvider):
        def chart_series(self, symbol, days=2, range_key=None, interval=None):
            raise EntitlementError("HTTP 403: candles are premium")
    prov = Wall()
    monkeypatch.setattr(registry, "get_prices", lambda: registry.DataRouter("u", {prov.name: prov}))
    monkeypatch.setattr(pkg, "get_prices", lambda: registry.DataRouter("u", {prov.name: prov}))
    dashboard._refusals.clear()
    client = TestClient(dashboard.app)
    r = client.get("/api/chart/NVDA?range=1D&interval=1m")
    assert r.status_code == 402
    assert "plan does not include 1 min bars" in r.json()["detail"]


def test_chart_state_never_saves_drawings():
    """Drawings live for one visit to /chart (2026-09-18): no key saves them."""
    from alphadesk.app.dashboard import _CHART_KEY
    for key in ("drawings:NVDA", "drawings:^GSPC", "drawings:BRK-B"):
        assert not _CHART_KEY.match(key), key
    assert _CHART_KEY.match("prefs")


def test_a_remembered_refusal_is_not_retried_upstream(monkeypatch):
    """After the plan refuses a bar, the next poll goes straight to the
    coarser bar instead of paying the refused call again."""
    from fastapi.testclient import TestClient
    from alphadesk.app import dashboard
    from alphadesk.providers.base import EntitlementError

    calls = []

    class Wall:
        name = "polygon"
        def chart_intervals(self):
            from alphadesk.ingest.prices import CHART_INTERVALS
            return CHART_INTERVALS
        def chart_series(self, symbol, days=2, range_key=None, interval=None, **kw):
            calls.append(interval)
            if interval == "1m":
                raise EntitlementError("HTTP 403: minute bars are premium")
            from alphadesk.ingest.prices import build_series_payload
            from datetime import datetime, timezone, timedelta
            t0 = datetime(2026, 9, 10, 13, 30, tzinfo=timezone.utc)
            bars = [{"ts": t0 + timedelta(minutes=5 * i), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for i in range(40)]
            return build_series_payload(symbol, bars, interval or "5m", range_key=range_key, interval=interval, stats=None)

    from alphadesk.providers import registry as _reg
    _wall = Wall()
    monkeypatch.setattr("alphadesk.providers.get_prices", lambda: _reg.DataRouter("u", {getattr(_wall, "name", "wall"): _wall}))
    dashboard._refusals.clear()
    client = TestClient(dashboard.app)
    r1 = client.get("/api/chart/NVDA?range=1D&interval=1m")
    assert r1.status_code == 200 and calls[0] == "1m"
    n = len(calls)
    r2 = client.get("/api/chart/NVDA?range=1D&interval=1m")
    assert r2.status_code == 200
    assert "1m" not in calls[n:]              # the refused bar was not asked for again
    assert "refused" in (r2.json().get("plan_note") or "")

"""The HTTP surface. No endpoint had a test before this."""




class TestSurface:
    def test_consumption_endpoints_serve(self, client):
        for url in ("/healthz", "/api/screener", "/api/system", "/api/tokens"):
            assert client.get(url).status_code == 200, url
        # Market data is the user's own: with no vendor connected the
        # calendar answers the key prompt, not an empty page.
        r = client.get("/api/earnings")
        assert r.status_code == 428 and r.json()["detail"]["needs_key"]["surface"] == "earnings_calendar"

    def test_trading_endpoints_are_gone(self, client):
        # AlphaDesk is a consumption product; these were removed with the
        # execution layer and must not come back by accident.
        for url in ("/api/live", "/api/performance", "/api/stats",
                    "/api/sessions", "/api/timelines", "/api/quant/stats"):
            r = client.get(url)
            assert "application/json" not in r.headers.get("content-type", ""), url
        assert client.post("/api/picks/manual", json={}).status_code in (404, 405)

    def test_system_reports_the_provider_roster(self, client):
        p = client.get("/api/system").json()["providers"]
        assert "polygon" in p["available"]["news"]
        assert set(p) == {"available"}


class TestScreener:
    def test_window_is_unranked_and_alphabetical(self, client, store, monkeypatch):
        store.save_articles([
            {"id": "a1", "title": "Zeta up", "summary": "", "source": "s", "url": "u",
             "published_at": "2099-01-02T00:00:00Z", "tickers": ["ZETA"]},
            {"id": "a2", "title": "Acme up", "summary": "", "source": "s", "url": "u",
             "published_at": "2099-01-02T00:00:00Z", "tickers": ["ACME"]},
        ])
        import alphadesk.desk.screener as sc
        # monkeypatch, NOT a bare assignment: an unreverted patch here once
        # emptied every later test's window (the 2099 cutoff outlived this test).
        monkeypatch.setattr(sc, "_since_iso", lambda: "2099-01-01T00:00:00Z")
        rows = client.get("/api/screener").json()["symbols"]
        syms = [r["symbol"] for r in rows]
        assert syms == sorted(syms), "the window must not be ranked"
        assert all("score" not in r for r in rows)

    def test_the_window_has_no_ask_endpoint_any_more(self, client):
        """The in-app model went on 2026-09-17; asking happens in the
        reader's own agent over MCP."""
        assert client.post("/api/screener/ask", json={"question": "what?"}).status_code in (404, 405)
        assert client.get("/api/screener").status_code == 200

class TestChart:
    def test_bad_symbol_is_rejected(self, client):
        assert client.get("/api/chart/%20").status_code in (400, 404)



class TestMarketData:
    """The quote and movers surfaces added for the AlphaSpace-style board."""

    def test_movers_filters_out_untradeable_instruments(self):
        from alphadesk.ingest.prices import _is_tradeable_symbol
        # warrants / rights / units print huge percentage moves and cannot be
        # traded in any normal sense — they must never reach the board
        for junk in ("XOSWW", "NTWOW", "AACBR", "BGLWW", "RNWWW"):
            assert not _is_tradeable_symbol(junk), junk
        for real in ("NVDA", "INTC", "AAPL", "SPCX", "F"):
            assert _is_tradeable_symbol(real), real

    def test_bad_symbol_rejected(self, client):
        assert client.get("/api/quote/%20").status_code in (400, 404)

    def test_movers_top_is_clamped(self, client, monkeypatch):
        """A caller asking for 10000 must not turn into a 10000-row upstream
        request; the endpoint clamps before the provider sees it."""
        seen = {}

        class FakePrices:
            name = "fake"

            def movers(self, top=20):
                seen["top"] = top
                return {"most_active": [], "gainers": [], "losers": []}

        from alphadesk.providers import registry
        import alphadesk.providers as pkg
        router = registry.DataRouter("u", {"alpaca": FakePrices()})
        monkeypatch.setattr(pkg, "get_prices", lambda: router)

        assert client.get("/api/movers?top=10000").status_code == 200
        assert seen["top"] == 50
        assert client.get("/api/movers?top=-5").status_code == 200
        assert seen["top"] == 1

    def test_crypto_top_is_clamped_and_indices_are_wrapped(self, client, monkeypatch):
        """Same clamp as movers, plus the indices envelope. /api/indices returns
        {"indices": [...]} rather than a bare list — a top-level JSON array is
        the one shape that cannot gain a sibling field later without breaking
        every caller."""
        seen = {}

        class FakePrices:
            name = "fake2"

            def crypto_movers(self, top=20):
                seen["top"] = top
                return {"all": [], "most_active": [], "gainers": [], "losers": []}

            def index_board(self):
                return [{"symbol": "^GSPC", "label": "S&P 500",
                         "price": 1.0, "change_pct": 0.5}]

        from alphadesk.providers import registry
        import alphadesk.providers as pkg
        router = registry.DataRouter("u", {"alpaca": FakePrices()})
        monkeypatch.setattr(pkg, "get_prices", lambda: router)

        assert client.get("/api/crypto?top=10000").status_code == 200
        assert seen["top"] == 50
        assert client.get("/api/crypto?top=-5").status_code == 200
        assert seen["top"] == 1

        body = client.get("/api/indices").json()
        assert list(body) == ["indices"]
        assert body["indices"][0]["label"] == "S&P 500"

    def test_no_connected_vendor_is_a_428_naming_the_keys(self, client, monkeypatch):
        from alphadesk.providers import registry
        import alphadesk.providers as pkg
        monkeypatch.setattr(pkg, "get_prices", lambda: registry.DataRouter("u", {}))
        r = client.get("/api/movers")
        assert r.status_code == 428
        prompt = r.json()["detail"]["needs_key"]
        assert prompt["surface"] == "stock_movers" and prompt["vendors"][0]["name"] == "alpaca"
        assert prompt["vendors"][0]["tier"] == "free" and prompt["signed_in"] is True

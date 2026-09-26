"""The two outside sources the Profile page fetches from — the SEC's
structured facts, CoinGecko's coin record — parsed from the shapes those
APIs return, without a socket."""
from alphadesk.ingest import coingecko, secfacts


def test_sec_facts_take_the_newest_full_year_across_concepts():
    gaap = {
        "Revenues": {"units": {"USD": [
            {"form": "10-K", "fp": "FY", "end": "2026-01-25", "val": 215_938_000_000, "fy": 2026, "accn": "a26"},
            {"form": "10-Q", "fp": "Q2", "end": "2026-07-26", "val": 70_000_000_000, "fy": 2027, "accn": "q"},
        ]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            {"form": "10-K", "fp": "FY", "end": "2022-01-30", "val": 26_914_000_000, "fy": 2022, "accn": "a22"},
        ]}},
    }
    best = secfacts.latest_annual(gaap, secfacts.CONCEPTS["revenue"])
    assert best["val"] == 215_938_000_000 and best["end"] == "2026-01-25" and best["accn"] == "a26"
    assert secfacts.latest_annual(gaap, ["NetIncomeLoss"]) is None


def test_sec_facts_payload_shape(monkeypatch):
    payload = {"facts": {
        "us-gaap": {"NetIncomeLoss": {"units": {"USD": [{"form": "10-K", "fp": "FY", "end": "2026-01-25", "val": 120_067_000_000, "fy": 2026, "accn": "a26"}]}}},
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [{"end": "2026-08-21", "val": 24_100_000_000, "accn": "q"}]}}},
    }}
    import json
    monkeypatch.setattr(secfacts.edgar, "_get", lambda url, timeout=15.0: json.dumps(payload).encode())
    secfacts._cache.clear()
    f = secfacts.facts("0001045810")
    assert f["as_of"] == "2026-01-25"
    assert f["items"]["net_income"]["val"] == 120_067_000_000
    assert f["shares_outstanding"] == {"val": 24_100_000_000, "end": "2026-08-21", "accn": "q"}
    assert f["source_url"].endswith("CIK0001045810.json")


def test_coingecko_resolves_by_rank_and_parses(monkeypatch):
    def fake_get(path, api_key, timeout=15.0):
        if path.startswith("/search"):
            return {"coins": [{"id": "btc-clone", "symbol": "btc", "market_cap_rank": None},
                              {"id": "bitcoin", "symbol": "btc", "market_cap_rank": 1}]}
        assert path.startswith("/coins/bitcoin")
        return {"name": "Bitcoin", "symbol": "btc", "description": {"en": "<p>Bitcoin is the <b>first</b> cryptocurrency.</p>"},
                "categories": ["Layer 1 (L1)", None], "links": {"homepage": ["https://bitcoin.org"], "whitepaper": "https://bitcoin.org/bitcoin.pdf", "blockchain_site": ["https://mempool.space", ""]},
                "genesis_date": "2009-01-03", "hashing_algorithm": "SHA-256", "market_cap_rank": 1,
                "market_data": {"circulating_supply": 20_082_346.0, "total_supply": 21_000_000.0, "max_supply": 21_000_000.0}}
    monkeypatch.setattr(coingecko, "_get", fake_get)
    coingecko._cache.clear()
    c = coingecko.coin("BTC-USD")
    assert c["id"] == "bitcoin" and c["description"] == "Bitcoin is the first cryptocurrency."
    assert c["categories"] == ["Layer 1 (L1)"] and c["explorers"] == ["https://mempool.space"]
    assert c["max_supply"] == 21_000_000.0 and c["url"].endswith("/coins/bitcoin")


def test_coingecko_key_rides_the_header(monkeypatch):
    seen = {}
    class R:
        def __init__(self, b): self.b = b
        def read(self): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake_open(req, timeout=15.0):
        seen["key"] = req.headers.get("X-cg-demo-api-key")
        return R(b"{}")
    monkeypatch.setattr(coingecko.urllib.request, "urlopen", fake_open)
    coingecko._get("/ping", "abc123")
    assert seen["key"] == "abc123"


def test_keys_api_accepts_the_crypto_seam(monkeypatch):
    from fastapi.testclient import TestClient
    from alphadesk.app import dashboard
    from alphadesk.ledger import store, vault
    monkeypatch.setattr(dashboard, "_key_user", lambda request: "u1")
    monkeypatch.setattr(vault, "enabled", lambda: True)
    monkeypatch.setattr(vault, "encrypt", lambda cfg: "sealed")
    saved = {}
    monkeypatch.setattr(store, "set_user_key", lambda uid, seam, provider, sealed, hint, vendor_plan=None: saved.update(seam=seam, provider=provider))
    client = TestClient(dashboard.app)
    r = client.put("/api/keys/crypto", json={"provider": "coingecko", "api_key": "CG-abcdefgh"})
    # The crypto seam folded into market data (2026-09-13): the same route
    # still accepts it, and stores the key as a market-data vendor.
    assert r.status_code == 200 and saved == {"seam": "prices", "provider": "coingecko"}
    assert client.put("/api/keys/crypto", json={"provider": "nonsense", "api_key": "CG-abcdefgh"}).status_code == 422

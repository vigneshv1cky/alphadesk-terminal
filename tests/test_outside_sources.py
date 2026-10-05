"""The two outside sources the Profile page fetches from — the SEC's
structured facts — parsed from the shapes those
APIs return, without a socket."""
from alphadesk.ingest import secfacts


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
    r = client.put("/api/keys/crypto", json={"provider": "fmp", "api_key": "CG-abcdefgh"})
    # The crypto seam folded into market data (2026-09-13): the same route
    # still accepts it, and stores the key as a market-data vendor.
    assert r.status_code == 200 and saved == {"seam": "prices", "provider": "fmp"}
    assert client.put("/api/keys/crypto", json={"provider": "nonsense", "api_key": "CG-abcdefgh"}).status_code == 422

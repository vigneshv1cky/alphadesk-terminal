"""A reader's own baskets (2026-09-18): saved per reader beside the curated
ones, listed by /api/themes, and read by their agent's baskets tool."""

import uuid

from alphadesk import mcp_server
from alphadesk.app import auth


def _sign_in(client, store, monkeypatch, email="r@example.com"):
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    uid = uuid.uuid4().hex
    store.create_user(uid, email, auth.hash_password("pw-long-enough-1"))
    assert client.post("/api/auth/login", json={"email": email, "password": "pw-long-enough-1"}).status_code == 200
    return uid


def test_a_reader_makes_edits_and_deletes_a_basket(client, store, monkeypatch):
    _sign_in(client, store, monkeypatch)
    r = client.put("/api/baskets/my-shipping", json={
        "label": "Shipping rates", "why": "Container and tanker lines on freight-rate news",
        "symbols": "zim, $mATX  zim DAC"})
    # Typed as one string: split, upper-cased, the $ dropped, each once.
    assert r.status_code == 200 and r.json()["symbols"] == ["ZIM", "MATX", "DAC"]
    themes = client.get("/api/themes").json()["themes"]
    mine = [t for t in themes if t.get("mine")]
    assert mine == [{"id": "my-shipping", "label": "Shipping rates",
                     "why": "Container and tanker lines on freight-rate news",
                     "symbols": ["ZIM", "MATX", "DAC"], "mine": True}]
    assert len(themes) > 1  # the curated baskets are still there
    # Saving again replaces it.
    client.put("/api/baskets/my-shipping", json={"label": "Shipping", "symbols": ["ZIM", "BTC/USD"]})
    mine = [t for t in client.get("/api/themes").json()["themes"] if t.get("mine")]
    assert mine[0]["label"] == "Shipping" and mine[0]["symbols"] == ["ZIM", "BTC/USD"] and mine[0]["why"] is None
    assert client.delete("/api/baskets/my-shipping").status_code == 200
    assert not [t for t in client.get("/api/themes").json()["themes"] if t.get("mine")]
    assert client.delete("/api/baskets/my-shipping").status_code == 404


def test_a_basket_needs_a_name_a_ticker_and_its_own_id(client, store, monkeypatch):
    _sign_in(client, store, monkeypatch)
    assert client.put("/api/baskets/my-x1", json={"label": " ", "symbols": "ZIM"}).status_code == 422
    assert client.put("/api/baskets/my-x1", json={"label": "X", "symbols": "!!! ,"}).status_code == 422
    # A reader's id is prefixed, so it can never shadow a curated basket.
    assert client.put("/api/baskets/energy", json={"label": "X", "symbols": "XOM"}).status_code == 422
    too_many = " ".join(f"A{i}" for i in range(41))
    assert client.put("/api/baskets/my-x1", json={"label": "X", "symbols": too_many}).status_code == 422


def test_baskets_are_the_readers_own(client, store, monkeypatch):
    _sign_in(client, store, monkeypatch, "a@example.com")
    client.put("/api/baskets/my-mine", json={"label": "Mine", "symbols": "ZIM"})
    client.post("/api/auth/logout")
    _sign_in(client, store, monkeypatch, "b@example.com")
    assert not [t for t in client.get("/api/themes").json()["themes"] if t.get("mine")]
    assert client.delete("/api/baskets/my-mine").status_code == 404


def test_the_agent_sees_the_readers_baskets_marked_mine(store, monkeypatch):
    from alphadesk import identity
    uid = uuid.uuid4().hex
    store.create_user(uid, "c@example.com", "sso-only")
    store.upsert_user_basket(uid, "my-ships", "Shipping", "Freight rates", ["ZIM", "MATX"])
    monkeypatch.setattr(identity, "request_user", lambda: uid)
    listed = mcp_server.baskets()["baskets"]
    assert {"id": "my-ships", "label": "Shipping", "why": "Freight rates", "symbols": ["ZIM", "MATX"], "mine": True} in listed
    # Found by a member beside any curated basket that also holds it.
    assert "my-ships" in [b["id"] for b in mcp_server.baskets(symbol="MATX")["baskets"]]
    assert mcp_server.baskets(basket="shipping")["members"][0]["symbol"] == "ZIM"


def test_the_account_page_learns_which_methods_this_account_used(client, store, monkeypatch):
    """2026-09-18: the Security panel showed every method the server offers as
    active; a reader who only used GitHub saw Google active too. A sign-in now
    records its method, and /api/auth/me returns this account's."""
    uid = _sign_in(client, store, monkeypatch, "s@example.com")
    me = client.get("/api/auth/me").json()
    assert [s["method"] for s in me["user"]["sign_ins"]] == ["password"]
    store.record_sign_in(uid, "github")
    methods = {s["method"] for s in client.get("/api/auth/me").json()["user"]["sign_ins"]}
    assert methods == {"password", "github"}
    assert "google" not in methods

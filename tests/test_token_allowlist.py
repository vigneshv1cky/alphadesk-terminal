"""A token that may only be used from the addresses its reader named (2026-10-02)."""
import pytest

from alphadesk.app import agent_access, agent_tools


def test_an_address_is_matched_against_single_addresses_and_ranges():
    allow = agent_access.parse_allowlist("203.0.113.7, 198.51.100.0/24")
    assert agent_access.address_allowed("203.0.113.7", allow)
    assert agent_access.address_allowed("198.51.100.200", allow)
    assert not agent_access.address_allowed("203.0.113.8", allow)
    assert not agent_access.address_allowed("not-an-address", allow)
    assert agent_access.address_allowed("203.0.113.8", [])            # no list: from anywhere


def test_entries_are_stored_in_the_form_the_reader_would_expect_to_read_back():
    assert agent_access.normalise_allowlist(["203.0.113.7", "198.51.100.5/24", " 2001:db8::1 "]) == \
        ["203.0.113.7", "198.51.100.0/24", "2001:db8::1"]


def test_a_malformed_entry_is_refused_when_the_list_is_set():
    with pytest.raises(ValueError, match="not an address"):
        agent_access.parse_allowlist("203.0.113.7, banana")


def test_the_address_is_the_one_the_front_door_added_not_the_one_the_caller_claimed():
    """Cloud Run APPENDS the real client address to X-Forwarded-For; anything
    before it was sent by the caller and proves nothing."""
    scope = {"headers": [(b"x-forwarded-for", b"1.2.3.4, 203.0.113.7")], "client": ("10.0.0.1", 1234)}
    assert agent_tools.client_address(scope) == "203.0.113.7"
    assert agent_tools.client_address({"headers": [], "client": ("127.0.0.1", 1)}) == "127.0.0.1"


@pytest.fixture()
def gated(store, monkeypatch):
    from fastapi.testclient import TestClient

    from alphadesk.app import dashboard
    store.ensure_local_user()
    uid = dashboard._local_uid()
    monkeypatch.setattr(dashboard, "_key_user", lambda request: uid)
    monkeypatch.setattr(agent_access, "limiter", agent_access.RateLimit())
    with TestClient(dashboard.app) as c:
        c.uid = uid
        yield c


def test_a_token_refuses_an_address_outside_its_list_and_accepts_one_inside(gated):
    _, token = agent_access.issue(gated.uid, "bot", allowed_ips=["203.0.113.7"])
    auth = {"Authorization": f"Bearer {token}"}
    outside = gated.get("/api/v1/data_sources", headers={**auth, "X-Forwarded-For": "198.51.100.9"})
    inside = gated.get("/api/v1/data_sources", headers={**auth, "X-Forwarded-For": "203.0.113.7"})
    assert outside.status_code == 403 and "address" in outside.json()["detail"]
    assert inside.status_code == 200


def test_a_forged_earlier_entry_does_not_let_a_stranger_in(gated):
    """The caller can write anything before the address the front door adds."""
    _, token = agent_access.issue(gated.uid, "bot", allowed_ips=["203.0.113.7"])
    r = gated.get("/api/v1/data_sources", headers={"Authorization": f"Bearer {token}",
                                                   "X-Forwarded-For": "203.0.113.7, 198.51.100.9"})
    assert r.status_code == 403


def test_the_list_guards_the_agent_door_too(gated):
    _, token = agent_access.issue(gated.uid, "bot", allowed_ips=["203.0.113.7"])
    r = gated.post("/api/agent/tools/mcp", headers={"Authorization": f"Bearer {token}",
                                                    "X-Forwarded-For": "198.51.100.9"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 403


def test_a_token_with_no_list_works_from_anywhere(gated):
    _, token = agent_access.issue(gated.uid, "bot")
    assert gated.get("/api/v1/data_sources", headers={"Authorization": f"Bearer {token}",
                                                      "X-Forwarded-For": "198.51.100.9"}).status_code == 200


def test_the_list_can_be_set_at_creation_and_is_listed_back(gated):
    r = gated.post("/api/agent/access-tokens", json={"name": "bot", "allowed_ips": ["203.0.113.7", "198.51.100.5/24"]})
    assert r.status_code == 200 and r.json()["allowed_ips"] == ["203.0.113.7", "198.51.100.0/24"]
    listed = gated.get("/api/agent/access-tokens").json()["tokens"]
    assert listed[0]["allowed_ips"] == ["203.0.113.7", "198.51.100.0/24"]
    plain = gated.post("/api/agent/access-tokens", json={"name": "open"}).json()
    assert plain["allowed_ips"] == []
    assert gated.post("/api/agent/access-tokens", json={"name": "x", "allowed_ips": ["banana"]}).status_code == 422

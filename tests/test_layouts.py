"""A reader's boards follow the ACCOUNT, not the browser they were arranged
in (2026-09-21). The symbol strip already had a row; the tile layouts did
not, so a board built on a desktop was absent on a phone."""


def test_a_layout_is_kept_and_read_back(store):
    store.set_user_layout("u1", "markets", "market-chart:12,news-tape:6")
    store.set_user_layout("u1", "earnings", "calendar:12")
    assert store.user_layouts("u1") == {
        "markets": "market-chart:12,news-tape:6", "earnings": "calendar:12"}


def test_another_reader_sees_none_of_it(store):
    store.set_user_layout("u1", "markets", "market-chart:12")
    assert store.user_layouts("u2") == {}
    assert store.user_layouts("") == {}


def test_an_empty_layout_is_forgotten_rather_than_stored(store):
    """Empty means "the page's default". Storing it would pin the board to
    whatever the defaults were that day, so a tile added to the product later
    would never appear on it."""
    store.set_user_layout("u1", "markets", "market-chart:12")
    store.set_user_layout("u1", "markets", "")
    assert store.user_layouts("u1") == {}


def test_arranging_it_again_replaces_the_row(store):
    store.set_user_layout("u1", "markets", "a:6")
    store.set_user_layout("u1", "markets", "b:12")
    assert store.user_layouts("u1")["markets"] == "b:12"


def test_a_views_layout_rides_the_same_table(store):
    """A custom view's page key carries a colon; the route must accept it."""
    store.set_user_layout("u1", "view:abc123", "chart:12")
    assert store.user_layouts("u1")["view:abc123"] == "chart:12"


def test_the_route_keeps_and_returns_a_layout(client):
    assert client.put("/api/layouts/markets", json={"tiles": "chart:12,news:6"}).status_code == 200
    got = client.get("/api/layouts").json()["layouts"]
    assert got["markets"] == "chart:12,news:6"


def test_the_route_refuses_a_page_key_it_does_not_recognise(client):
    # Reaches the route and is rejected by it.
    for bad in ("Markets!", "a" * 70, "-leading", "page with spaces"):
        r = client.put(f"/api/layouts/{bad}", json={"tiles": "chart:12"})
        assert r.status_code == 422, bad
    # Never reaches it at all: a path with a slash is a different route.
    assert client.put("/api/layouts/../etc", json={"tiles": "x"}).status_code in (404, 405)


def test_deleting_an_account_takes_its_layouts(store):
    store.create_user("u1", "a@b.c", "sso-only")
    store.set_user_layout("u1", "markets", "chart:12")
    store.delete_account("u1")
    assert store.user_layouts("u1") == {}

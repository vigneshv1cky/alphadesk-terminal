"""The key vault: sealed storage, the hints-only API, and the per-user LLM
path. The invariant under test everywhere: plaintext key material exists only
between the request body and the vault envelope — never in a response, a
row a listing returns, or an error message."""

import base64
import uuid

import pytest

from alphadesk.ledger import vault

MASTER = base64.b64encode(b"\x07" * 32).decode()


@pytest.fixture(autouse=True)
def _vault_env(monkeypatch):
    monkeypatch.setenv("ALPHADESK_VAULT_KEY", MASTER)
    yield


class TestCrypto:
    def test_round_trip(self):
        cfg = {"api_key": "sk-test-1234", "base_url": "", "model": "m"}
        sealed = vault.encrypt(cfg)
        assert "sk-test-1234" not in sealed
        assert vault.decrypt(sealed) == cfg

    def test_two_seals_differ(self):
        cfg = {"api_key": "sk-test-1234"}
        assert vault.encrypt(cfg) != vault.encrypt(cfg)   # fresh nonce each time

    def test_tamper_and_wrong_key_fail_alike(self, monkeypatch):
        sealed = vault.encrypt({"api_key": "sk-test-1234"})
        raw = bytearray(base64.b64decode(sealed))
        raw[-1] ^= 0x01
        with pytest.raises(vault.VaultError):
            vault.decrypt(base64.b64encode(bytes(raw)).decode())
        monkeypatch.setenv("ALPHADESK_VAULT_KEY", base64.b64encode(b"\x08" * 32).decode())
        with pytest.raises(vault.VaultError):
            vault.decrypt(sealed)

    def test_master_key_is_validated(self, monkeypatch):
        monkeypatch.delenv("ALPHADESK_VAULT_KEY")
        assert not vault.enabled()
        monkeypatch.setenv("ALPHADESK_VAULT_KEY", "not-base64!!")
        assert not vault.enabled()
        monkeypatch.setenv("ALPHADESK_VAULT_KEY", base64.b64encode(b"short").decode())
        assert not vault.enabled()
        monkeypatch.setenv("ALPHADESK_VAULT_KEY", MASTER)
        assert vault.enabled()

    def test_errors_never_carry_plaintext(self):
        sealed = vault.encrypt({"api_key": "sk-super-secret-9999"})
        raw = bytearray(base64.b64decode(sealed))
        raw[20] ^= 0xFF
        try:
            vault.decrypt(base64.b64encode(bytes(raw)).decode())
        except vault.VaultError as exc:
            assert "sk-super-secret" not in str(exc)


class TestStore:
    def test_re_entering_a_vendors_key_replaces_it(self, store):
        store.create_user("u1", "a@b.c", "sso-only")
        store.set_user_key("u1", "prices", "alpaca", vault.encrypt({"api_key": "k1-aaaa"}), "aaaa")
        store.set_user_key("u1", "prices", "alpaca", vault.encrypt({"api_key": "k2-bbbb"}), "bbbb")
        rows = store.list_user_keys("u1")
        assert len(rows) == 1                          # same seam + provider: replaced
        assert rows[0]["provider"] == "alpaca" and rows[0]["key_hint"] == "bbbb"
        assert "config" not in rows[0]                 # listings never carry the envelope

    def test_delete(self, store):
        store.create_user("u1", "a@b.c", "sso-only")
        store.set_user_key("u1", "news", "polygon", vault.encrypt({"api_key": "k-cccc"}), "cccc")
        assert store.delete_user_key("u1", "news")
        assert not store.delete_user_key("u1", "news")
        assert store.list_user_keys("u1") == []


def _sign_in(client, store, monkeypatch):
    """A gated instance with one password account, signed in."""
    from alphadesk.app import auth
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    email, password = "reader@example.com", "a-long-password"
    store.create_user(uuid.uuid4().hex, email, auth.hash_password(password))
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200


class TestKeysApi:
    def test_anonymous_is_refused(self, client, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        assert client.get("/api/keys").status_code == 401
        assert client.put("/api/keys/news", json={"provider": "polygon",
                                                  "api_key": "sk-xxxxxxxx"}).status_code == 401

    def test_set_list_delete_never_echo_the_key(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        r = client.put("/api/keys/news", json={
            "provider": "polygon", "api_key": "sk-live-abcd1234"})
        assert r.status_code == 200
        assert "sk-live-abcd1234" not in r.text and r.json()["key_hint"] == "1234"
        listing = client.get("/api/keys")
        assert listing.json()["vault"] is True
        assert "sk-live-abcd1234" not in listing.text
        assert listing.json()["keys"][0]["seam"] == "news"
        assert client.delete("/api/keys/news").status_code == 200
        assert client.get("/api/keys").json()["keys"] == []

    def test_each_feed_says_how_its_stories_arrive(self, client, store, monkeypatch):
        """The Account page states per feed whether stories arrive over the
        held socket in seconds or on the poll (2026-09-18). The answer comes
        from the stream module, so the page cannot claim a stream that is not
        there — only Alpaca's feed has one."""
        _sign_in(client, store, monkeypatch)
        client.put("/api/keys/news", json={"provider": "polygon", "api_key": "pk-xxxxxxxx1111"})
        client.put("/api/keys/news", json={"provider": "alpaca", "api_key": "ak-xxxxxxxx2222",
                                           "api_secret": "as-xxxxxxxx3333"})
        listing = client.get("/api/keys").json()
        how = {k["provider"]: k["delivery"] for k in listing["keys"] if k["seam"] == "news"}
        assert how == {"alpaca": "stream", "polygon": "poll"}
        from alphadesk.config import NEWS_REFRESH_MINUTES
        assert listing["news_poll_minutes"] == NEWS_REFRESH_MINUTES

    def test_vault_off_is_an_honest_503(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        monkeypatch.delenv("ALPHADESK_VAULT_KEY")
        r = client.put("/api/keys/news", json={"provider": "polygon",
                                              "api_key": "sk-xxxxxxxx"})
        assert r.status_code == 503
        assert client.get("/api/keys").json()["vault"] is False

    def test_garbage_is_rejected(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        assert client.put("/api/keys/wat", json={"provider": "polygon",
                                                 "api_key": "sk-xxxxxxxx"}).status_code == 422
        assert client.put("/api/keys/news", json={"provider": "no-such-provider",
                                                  "api_key": "sk-xxxxxxxx"}).status_code == 422
        assert client.put("/api/keys/news", json={"provider": "polygon",
                                                  "api_key": "x"}).status_code == 422
class TestUserViews:
    """My Views, server-side: per-user named boards. Same session rules as
    keys — anonymous is refused, and one reader never sees another's."""

    def test_anonymous_is_refused(self, client, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        assert client.get("/api/views").status_code == 401

    def test_crud_round_trip(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        r = client.put("/api/views/abcd1234", json={
            "name": "Energy Desk", "layout": "market-chart:8,watchlist:4"})
        assert r.status_code == 200
        views = client.get("/api/views").json()["views"]
        assert views == [{"view_id": "abcd1234", "name": "Energy Desk",
                          "layout": "market-chart:8,watchlist:4", "position": 0}]
        client.put("/api/views/abcd1234", json={"name": "Renamed", "layout": "market-chart:12"})
        assert client.get("/api/views").json()["views"][0]["name"] == "Renamed"
        assert client.delete("/api/views/abcd1234").status_code == 200
        assert client.get("/api/views").json()["views"] == []
        assert client.delete("/api/views/abcd1234").status_code == 404

    def test_garbage_is_rejected(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        assert client.put("/api/views/NO", json={"name": "x"}).status_code == 422
        assert client.put("/api/views/abcd1234", json={"name": "  "}).status_code == 422
        assert client.put("/api/views/abcd1234",
                          json={"name": "x", "layout": "y" * 3000}).status_code == 422

    def test_views_are_private_per_user(self, store):
        store.create_user("u1", "a@b.c", "sso-only")
        store.create_user("u2", "b@c.d", "sso-only")
        store.upsert_user_view("u1", "v1", "Mine", "market-chart", 0)
        assert store.list_user_views("u2") == []
        assert [v["name"] for v in store.list_user_views("u1")] == ["Mine"]


class TestMultiFeedKeys:
    """One key PER PROVIDER on the news seam — a reader's window merges every
    feed they key. The llm seam stays one-active-key by code."""

    def test_news_keys_accumulate(self, store):
        store.create_user("u1", "a@b.c", "sso-only")
        store.set_user_key("u1", "news", "polygon", "sealed-p", "pppp")
        store.set_user_key("u1", "news", "alpaca", "sealed-a", "aaaa")
        news = store.get_user_keys("u1", "news")
        assert [r["provider"] for r in news] == ["alpaca", "polygon"]
        store.set_user_key("u1", "prices", "alpaca", "sealed-1", "1111")
        store.set_user_key("u1", "prices", "polygon", "sealed-2", "2222")
        assert [r["provider"] for r in store.get_user_keys("u1", "prices")] == ["alpaca", "polygon"]

    def test_provider_scoped_delete(self, store):
        store.create_user("u1", "a@b.c", "sso-only")
        store.set_user_key("u1", "news", "polygon", "sealed-p", "pppp")
        store.set_user_key("u1", "news", "alpaca", "sealed-a", "aaaa")
        assert store.delete_user_key("u1", "news", "polygon")
        assert [r["provider"] for r in store.get_user_keys("u1", "news")] == ["alpaca"]
        assert not store.delete_user_key("u1", "news", "polygon")
        # seam-wide delete still takes everything
        assert store.delete_user_key("u1", "news")
        assert store.get_user_keys("u1", "news") == []

    def test_api_lists_both_and_deletes_one(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        assert client.put("/api/keys/news", json={
            "provider": "polygon", "api_key": "pk-aaaaaaaa"}).status_code == 200
        assert client.put("/api/keys/news", json={
            "provider": "alpaca", "api_key": "ak-bbbbbbbb", "api_secret": "sec"}).status_code == 200
        rows = [k for k in client.get("/api/keys").json()["keys"] if k["seam"] == "news"]
        assert sorted(k["provider"] for k in rows) == ["alpaca", "polygon"]
        assert client.delete("/api/keys/news/polygon").status_code == 200
        rows = [k for k in client.get("/api/keys").json()["keys"] if k["seam"] == "news"]
        assert [k["provider"] for k in rows] == ["alpaca"]
        assert client.delete("/api/keys/news/polygon").status_code == 404

    def test_pre_multifeed_table_is_rebuilt_with_rows_intact(self, tmp_path, monkeypatch):
        import importlib
        import sqlite3
        monkeypatch.setenv("ALPHADESK_DATA", str(tmp_path))
        from alphadesk import config
        importlib.reload(config)
        db_path = config.DATA_DIR / "ledger.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT, password_hash TEXT,"
            " created_at TEXT, disabled INTEGER DEFAULT 0, session_version INTEGER DEFAULT 1,"
            " last_seen_at TEXT)")
        conn.execute(
            "CREATE TABLE user_api_keys ("
            " user_id TEXT NOT NULL REFERENCES users(user_id),"
            " seam TEXT NOT NULL CHECK (seam IN ('news', 'llm')),"
            " provider TEXT NOT NULL, config TEXT NOT NULL, key_hint TEXT NOT NULL,"
            " created_at TEXT NOT NULL, last_used_at TEXT,"
            " PRIMARY KEY (user_id, seam))")
        conn.execute("INSERT INTO users (user_id, email) VALUES ('u1', 'a@b.c')")
        conn.execute(
            "INSERT INTO user_api_keys (user_id, seam, provider, config, key_hint, created_at)"
            " VALUES ('u1', 'news', 'polygon', 'sealed', 'pppp', '2026-01-01')")
        conn.commit(); conn.close()

        from alphadesk.ledger import store as store_mod
        importlib.reload(store_mod)
        store_mod.init()
        assert [r["provider"] for r in store_mod.get_user_keys("u1", "news")] == ["polygon"]
        store_mod.set_user_key("u1", "news", "alpaca", "sealed-a", "aaaa")
        assert len(store_mod.get_user_keys("u1", "news")) == 2

    def test_poll_user_merges_every_keyed_feed(self, store, monkeypatch):
        from datetime import datetime, timedelta, timezone

        from alphadesk.ingest import news as ingest_news
        store.create_user("u1", "a@b.c", "sso-only")
        store.set_user_key("u1", "news", "polygon", "sealed-p", "pppp")
        store.set_user_key("u1", "news", "alpaca", "sealed-a", "aaaa")

        class _Feed:
            def __init__(self, name, arts): self.name, self._a = name, arts
            def fetch(self, since, limit=200): return self._a

        class _Art:
            def __init__(self, id, url):
                self.id, self.url, self.title = id, url, f"story {id}"
                self.summary = ""; self.source = "t"; self.published_at = "2026-09-03T00:00:00Z"
                self.symbols = ["NVDA"]; self.image_url = None; self.author = None; self.body = None

        feeds = {"polygon": _Feed("polygon", [_Art("p1", "https://x.com/a"), _Art("p2", "https://x.com/b")]),
                 "alpaca": _Feed("alpaca", [_Art("a1", "https://x.com/a"), _Art("a2", "https://x.com/c")])}
        monkeypatch.setattr(ingest_news, "_user_news_provider",
                            lambda uid, created, name, sealed: feeds[name])
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        n = ingest_news.poll_user("u1", since)
        # a1/a2 from alpaca, p2 from polygon; p1 is the same press release as
        # a1 (same URL) and joins its row.
        assert n == 3
        for row in store.get_user_keys("u1", "news"):
            assert row["last_used_at"] is not None
        feeds = {r["article_id"]: r["feeds"] for r in store.recent_articles("2026-01-01T00:00:00Z", owner="u1")}
        assert feeds == {"a1": ["alpaca", "polygon"], "p2": ["polygon"], "a2": ["alpaca"]}   # feeds poll alphabetically


class TestUserPricesKeys:
    """BYOK on the prices seam: the reader's keyed provider becomes THE price
    source for their requests; anonymous and background stay on the operator's.
    Same hard-error rule as the llm seam — an unopenable key never falls
    through silently."""

    def _fake_provider(self):
        from alphadesk.providers import registry

        class FakePx:
            name = "fake-prices"
            def __init__(self, *, api_key=None, api_secret=None):
                self.api_key = api_key
            def quote(self, symbol):
                return {"symbol": symbol, "price": 1.0, "source": "fake"}
        registry.register("prices", "fake-prices", FakePx)
        return FakePx

    def test_request_user_rides_their_own_key(self, store):
        from alphadesk import identity as ai_llm
        from alphadesk.providers import registry
        self._fake_provider()
        registry.reset_cache()
        store.create_user("u1", "a@b.c", "sso-only")
        store.set_user_key("u1", "prices", "fake-prices",
                           vault.encrypt({"api_key": "pk-user-1"}), "er-1")
        token = ai_llm.set_request_user("u1")
        try:
            router = registry.get_prices()
            assert router.connected == ["fake-prices"]
            # Each vendor arrives behind the per-user TTL memo; plain
            # attributes pass through it untouched.
            vendor = router.vendors["fake-prices"]
            assert isinstance(vendor, registry._CachedPrices) and vendor.api_key == "pk-user-1"
            assert router.ask("quote", "NVDA")["source"] == "fake" and router.answered_by == "fake-prices"
        finally:
            ai_llm.reset_request_user(token)
        # No identity stamped: an empty router, and every surface needs a key.
        from alphadesk.providers.base import NeedsKey
        anon = registry.get_prices()
        assert anon.connected == []
        with pytest.raises(NeedsKey) as exc:
            anon.ask("quote", "NVDA")
        assert exc.value.prompt()["signed_in"] is False
        registry.reset_cache()

    def test_the_router_asks_vendors_in_catalogue_order_and_skips_refusals(self, store):
        from alphadesk import identity as ai_llm
        from alphadesk.providers import registry
        from alphadesk.providers.base import EntitlementError, NeedsKey

        class Refuses:
            name = "finnhub"
            def __init__(self, *, api_key=None, api_secret=None): pass
            def quote(self, symbol): raise EntitlementError("plan")
            def peers(self, symbol): return None

        class Answers:
            name = "alpaca"
            def __init__(self, *, api_key=None, api_secret=None): pass
            def quote(self, symbol): return {"symbol": symbol, "price": 2.0}

        registry.register("prices", "finnhub", Refuses)
        registry.register("prices", "alpaca", Answers)
        try:
            registry.reset_cache()
            store.create_user("u7", "g@h.i", "sso-only")
            for v in ("finnhub", "alpaca"):
                store.set_user_key("u7", "prices", v, vault.encrypt({"api_key": f"k-{v}-xxxx"}), "xxxx")
            token = ai_llm.set_request_user("u7")
            try:
                router = registry.get_prices()
                assert router.connected == ["alpaca", "finnhub"]          # keys accumulate
                assert router.ask("quote", "NVDA")["price"] == 2.0 and router.answered_by == "alpaca"
                with pytest.raises(NeedsKey) as exc:
                    router.ask("peers", "NVDA")                            # finnhub answered None
                prompt = exc.value.prompt()
                assert prompt["surface"] == "peers" and prompt["refused"] == []
                assert [v["name"] for v in prompt["vendors"]] == ["fmp", "finnhub"]
                assert router.get("peers", "NVDA") is None and router.peers("NVDA") is None
            finally:
                ai_llm.reset_request_user(token)
        finally:
            from alphadesk.providers import prices as _pp
            registry.register("prices", "finnhub", _pp.FinnhubPrices)
            registry.register("prices", "alpaca", getattr(_pp, "AlpacaPrices", Answers))
            registry.reset_cache()

    def test_polling_rides_the_memo_not_the_key(self, store):
        from alphadesk import identity as ai_llm
        from alphadesk.providers import registry

        calls = {"n": 0}

        class CountingPx:
            name = "counting-prices"
            def __init__(self, *, api_key=None, api_secret=None): pass
            def quote(self, symbol):
                calls["n"] += 1
                return {"symbol": symbol, "price": calls["n"]}
        registry.register("prices", "counting-prices", CountingPx)
        registry.reset_cache()
        store.create_user("u9", "z@b.c", "sso-only")
        store.set_user_key("u9", "prices", "counting-prices",
                           vault.encrypt({"api_key": "pk-count-1"}), "nt-1")
        token = ai_llm.set_request_user("u9")
        try:
            p = registry.get_prices()
            first = p.quote("NVDA")
            again = p.quote("NVDA")
            other = p.quote("AMD")
        finally:
            ai_llm.reset_request_user(token)
        assert first == again                 # the second poll never left the memo
        assert other["price"] == 2 and calls["n"] == 2
        registry.reset_cache()

    def test_an_unopenable_key_is_a_hard_error(self, store, monkeypatch):
        import base64 as b64

        import pytest as _pytest

        from alphadesk import identity as ai_llm
        from alphadesk.providers import registry
        self._fake_provider()
        registry.reset_cache()
        store.create_user("u2", "b@c.d", "sso-only")
        store.set_user_key("u2", "prices", "fake-prices",
                           vault.encrypt({"api_key": "pk-secret-9"}), "et-9")
        monkeypatch.setenv("ALPHADESK_VAULT_KEY", b64.b64encode(b"\x05" * 32).decode())
        token = ai_llm.set_request_user("u2")
        try:
            with _pytest.raises(Exception) as exc:
                registry.get_prices()
        finally:
            ai_llm.reset_request_user(token)
        assert "pk-secret-9" not in str(exc.value)
        registry.reset_cache()

    def test_api_accepts_prices_and_refuses_the_builtin(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        r = client.put("/api/keys/prices", json={"provider": "polygon",
                                                 "api_key": "pk-xxxxxxxx"})
        assert r.status_code == 200
        rows = [k for k in client.get("/api/keys").json()["keys"] if k["seam"] == "prices"]
        assert [k["provider"] for k in rows] == ["polygon"]
        # The builtin composite reads only env — refused at the door.
        assert client.put("/api/keys/prices", json={"provider": "builtin",
                                                    "api_key": "pk-yyyyyyyy"}).status_code == 422
        assert client.delete("/api/keys/prices/polygon").status_code == 200

    def test_market_data_keys_accumulate(self, store):
        self._fake_provider()
        store.create_user("u3", "c@d.e", "sso-only")
        store.set_user_key("u3", "prices", "polygon",
                           vault.encrypt({"api_key": "pk-1"}), "pk-1")
        store.set_user_key("u3", "prices", "fake-prices",
                           vault.encrypt({"api_key": "pk-2"}), "pk-2")
        rows = [k for k in store.list_user_keys("u3") if k["seam"] == "prices"]
        assert sorted(r["provider"] for r in rows) == ["fake-prices", "polygon"]

    def test_the_crypto_seam_folds_into_market_data(self, store):
        store.create_user("u4", "d@e.f", "sso-only")
        from alphadesk.ledger import store as store_mod
        with store_mod._connect() as conn:
            conn.execute("INSERT INTO user_api_keys (user_id, seam, provider, config, key_hint, created_at)"
                         " VALUES ('u4', 'crypto', 'coingecko', 'sealed', 'cccc', '2026-01-01')")
        store_mod.init()
        assert [(r["seam"], r["provider"]) for r in store_mod.list_user_keys("u4")] == [("prices", "coingecko")]

    def test_pre_prices_check_table_is_rebuilt(self, tmp_path, monkeypatch):
        import importlib
        import sqlite3
        monkeypatch.setenv("ALPHADESK_DATA", str(tmp_path))
        from alphadesk import config
        importlib.reload(config)
        db_path = config.DATA_DIR / "ledger.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE users (user_id TEXT PRIMARY KEY, email TEXT, password_hash TEXT,"
            " created_at TEXT, disabled INTEGER DEFAULT 0, session_version INTEGER DEFAULT 1,"
            " last_seen_at TEXT)")
        conn.execute(
            "CREATE TABLE user_api_keys ("
            " user_id TEXT NOT NULL REFERENCES users(user_id),"
            " seam TEXT NOT NULL CHECK (seam IN ('news', 'llm')),"
            " provider TEXT NOT NULL, config TEXT NOT NULL, key_hint TEXT NOT NULL,"
            " created_at TEXT NOT NULL, last_used_at TEXT,"
            " PRIMARY KEY (user_id, seam, provider))")
        conn.execute("INSERT INTO users (user_id, email) VALUES ('u1', 'a@b.c')")
        conn.execute(
            "INSERT INTO user_api_keys (user_id, seam, provider, config, key_hint, created_at)"
            " VALUES ('u1', 'news', 'polygon', 'sealed', 'pppp', '2026-01-01')")
        conn.commit(); conn.close()

        from alphadesk.ledger import store as store_mod
        importlib.reload(store_mod)
        store_mod.init()
        assert [r["provider"] for r in store_mod.get_user_keys("u1", "news")] == ["polygon"]
        store_mod.set_user_key("u1", "prices", "polygon", "sealed-x", "xxxx")
        assert [r["provider"] for r in store_mod.get_user_keys("u1", "prices")] == ["polygon"]


class TestUserNewsFetchMemo:
    """The per-reader news memo: within the TTL a feed's key is not touched
    again — the previous batch replays idempotently."""

    def _wire(self, store, monkeypatch):
        from alphadesk.ingest import news as ingest_news
        calls = {"n": 0}

        class Feed:
            name = "memo-feed"
            def fetch(self, since, limit=200):
                calls["n"] += 1

                class A:
                    id = f"m{calls['n']}"
                    url = f"https://x.com/{calls['n']}"
                    title = "story"; summary = ""; source = "t"
                    published_at = "2026-09-03T00:00:00Z"; symbols = ["NVDA"]
                    image_url = None; author = None; body = None
                return [A()]
        store.create_user("um", "m@b.c", "sso-only")
        store.set_user_key("um", "news", "polygon",
                           vault.encrypt({"api_key": "pk-memo-1"}), "mo-1")
        monkeypatch.setattr(ingest_news, "_user_news_provider",
                            lambda uid, created, name, sealed: Feed())
        monkeypatch.setattr(ingest_news, "_user_fetch_memo", {})
        return ingest_news, calls

    def test_a_second_poll_inside_the_window_replays(self, store, monkeypatch):
        from datetime import datetime, timedelta, timezone
        ingest_news, calls = self._wire(store, monkeypatch)
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        assert ingest_news.poll_user("um", since) == 1
        assert ingest_news.poll_user("um", since) == 1   # replayed, not refetched
        assert calls["n"] == 1

    def test_past_the_window_the_feed_is_asked_again(self, store, monkeypatch):
        from datetime import datetime, timedelta, timezone
        ingest_news, calls = self._wire(store, monkeypatch)
        monkeypatch.setattr(ingest_news, "NEWS_USER_FETCH_TTL_S", 0.0)
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        ingest_news.poll_user("um", since)
        ingest_news.poll_user("um", since)
        assert calls["n"] == 2


class TestChartState:
    """Chart state follows the account: the reading setup under 'prefs'.
    Drawings are not saved (2026-09-18)."""

    def test_anonymous_is_refused(self, client, monkeypatch):
        monkeypatch.setenv("ALPHADESK_AUTH", "required")
        assert client.get("/api/chart/state/prefs").status_code == 401

    def test_round_trip_and_keys(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        assert client.get("/api/chart/state/prefs").json()["state"] is None
        assert client.put("/api/chart/state/prefs", json={"state": {"type": "candles"}}).status_code == 200
        assert client.get("/api/chart/state/prefs").json()["state"] == {"type": "candles"}
        # Drawings are never saved: the key is refused outright.
        lines = [{"id": "d1", "kind": "hline", "a": {"time": "2026-09-05T14:00:00Z", "price": 224.4}}]
        assert client.put("/api/chart/state/drawings:NVDA", json={"state": lines}).status_code == 422
        assert client.get("/api/chart/state/drawings:NVDA").status_code == 422
        # The workspace's extra cells, the grid, saved layouts and templates
        # are keys; a fifth cell is not.
        for ok in ("prefs:1", "prefs:3", "layout", "layouts", "templates"):
            assert client.put(f"/api/chart/state/{ok}", json={"state": {"k": 1}}).status_code == 200, ok
        assert client.put("/api/chart/state/prefs:4", json={"state": {}}).status_code == 422
        assert client.put("/api/chart/state/prefs:0", json={"state": {}}).status_code == 422
        assert client.put("/api/chart/state/junk", json={"state": {}}).status_code == 422
        big = {"k": ["x" * 100] * 1500}
        assert client.put("/api/chart/state/layouts", json={"state": big}).status_code == 422
        assert client.delete("/api/chart/state/prefs").status_code == 200
        assert client.delete("/api/chart/state/prefs").status_code == 404

    def test_saved_drawings_are_deleted_on_start(self, store):
        store.create_user("dz", "dz@b.c", "sso-only")
        store.set_chart_state("dz", "drawings:NVDA", "[]")
        store.set_chart_state("dz", "prefs", "{}")
        store.init()
        assert store.get_chart_state("dz", "drawings:NVDA") is None
        assert store.get_chart_state("dz", "prefs") == "{}"

    def test_isolation(self, store):
        store.create_user("c1", "c1@b.c", "sso-only")
        store.create_user("c2", "c2@b.c", "sso-only")
        store.set_chart_state("c1", "drawings:NVDA", "[1]")
        assert store.get_chart_state("c2", "drawings:NVDA") is None
        assert store.get_chart_state("c1", "drawings:NVDA") == "[1]"


def test_a_market_data_key_is_stamped_used_when_it_answers(store, monkeypatch):
    """2026-09-14: the Account page said "not used yet" on the Alpaca key
    that had just served every quote — the router never stamped it."""
    from alphadesk.providers import registry
    registry._stamped.clear()
    store.create_user("u1", "a@b.c", "sso-only")
    store.set_user_key("u1", "prices", "alpaca", "sealed", "aaaa")

    class _V:
        name = "alpaca"
        def quote(self, symbol): return {"symbol": symbol, "price": 1.0}
    router = registry.DataRouter("u1", {"alpaca": _V()})
    router.ask("quote", "AAPL")
    [row] = store.get_user_keys("u1", "prices")
    assert row["last_used_at"] is not None
    first = row["last_used_at"]
    router.ask("quote", "AAPL")                                   # within five minutes: no second write
    assert store.get_user_keys("u1", "prices")[0]["last_used_at"] == first
    registry._stamped.clear()


def test_init_drops_the_retired_agent_tables(store):
    """The in-app agent's tables go on start, rows and all (2026-09-17)."""
    dead = ("agent_threads", "user_modes", "user_commands", "user_mcp_servers", "user_documents")
    with store._lock, store._connect() as conn:
        for t in dead:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {t} (x TEXT)")
            conn.execute(f"INSERT INTO {t} (x) VALUES ('secret')")
    store.init()
    from alphadesk.ledger import db
    with store._connect() as conn:
        for t in dead:
            assert not db.table_columns(conn, t), t

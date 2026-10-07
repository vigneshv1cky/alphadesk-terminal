"""Shared fixtures.

Every test runs against a THROWAWAY ledger in a temp directory. That has to be
set before any alphadesk import, because config.py resolves DATA_DIR at import
time — get this wrong and a test run writes into the developer's real
~/.alphadesk.
"""

import os
import tempfile

import pytest

os.environ.setdefault("ALPHADESK_DATA", tempfile.mkdtemp(prefix="alphadesk-test-"))
# Auth is compulsory by default in the product; the suite runs OPEN so the
# hundreds of data-route tests exercise data, not the gate. test_auth flips
# it back on per test and covers the gate — including that the default IS
# required.
os.environ.setdefault("ALPHADESK_AUTH", "off")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A fresh, isolated ledger per test."""
    monkeypatch.setenv("ALPHADESK_DATA", str(tmp_path))
    import importlib

    from alphadesk import config
    importlib.reload(config)
    from alphadesk.ledger import store as store_mod
    importlib.reload(store_mod)
    store_mod.init()
    return store_mod


@pytest.fixture()
def client(store):
    """TestClient over the real app, wired to the throwaway ledger."""
    from fastapi.testclient import TestClient

    from alphadesk.app import dashboard
    return TestClient(dashboard.app)


def _clear_kept_sec():
    """SEC documents and Form 4s are kept in the ledger now (2026-10-07); a
    test that swaps in its own EDGAR answer must not be served the last test's
    kept copy, just as the memory cache is cleared between tests."""
    try:
        from alphadesk.ingest import edgar
        if edgar._sec_writer is not None:              # a write queued by the last test lands first
            edgar._sec_writer.submit(lambda: None).result(timeout=5)
        from alphadesk.ledger import store
        with store._lock, store._connect() as conn:
            conn.execute("DELETE FROM sec_documents")
            conn.execute("DELETE FROM insider_form4")
            conn.execute("DELETE FROM quarter_release_checks")
            conn.execute("DELETE FROM vendor_cache WHERE method LIKE 'list:%'")
    except Exception:
        pass                                          # no ledger yet: nothing kept


@pytest.fixture(autouse=True)
def _no_alpha_vantage_pacing(monkeypatch):
    """The one-a-second pacing (providers/avpace.py) would make every test that
    calls a stand-in Alpha Vantage wait; its own test sets it back."""
    from alphadesk.providers import avpace
    monkeypatch.setattr(avpace, "MIN_INTERVAL_S", 0.0)
    avpace._next_slot.clear()


@pytest.fixture(autouse=True)
def _reset_providers():
    """Provider selection is cached for the process; clear it between tests so
    one test's NEWS_PROVIDER can't leak into the next."""
    from alphadesk.ingest import background_fill
    from alphadesk.providers import registry
    from alphadesk.ingest import edgar
    registry.reset_cache()
    background_fill._failed.clear()
    edgar._json_cache.clear()
    _clear_kept_sec()
    from alphadesk.desk import memo
    memo.clear()
    yield
    memo.clear()
    registry.reset_cache()
    background_fill._failed.clear()
    edgar._json_cache.clear()


@pytest.fixture(autouse=True)
def _test_client_host(monkeypatch):
    """The test client's host name is `testserver`; an open server answers only to
    names it is told about (dashboard._browser_guards)."""
    monkeypatch.setenv("ALPHADESK_ALLOWED_HOSTS", "testserver")


@pytest.fixture(autouse=True)
def _no_vendor_key_check(monkeypatch):
    """Saving a news key tries it once at the vendor (ingest/news.check_news_key);
    no test may reach a real vendor, so the check is off unless a test turns it on."""
    monkeypatch.setenv("ALPHADESK_SKIP_KEY_CHECK", "1")


@pytest.fixture()
def vendors(monkeypatch):
    """Install a signed-in user's connected vendors for one test:
    `vendors(finnhub=obj, alpaca=obj)` makes every `get_prices()` answer a
    DataRouter over exactly those, so no test can reach a real vendor
    (2026-09-13: all market data is the user's own)."""
    import sys

    import alphadesk.providers as pkg
    from alphadesk.providers import registry

    def install(**vs):
        router = registry.DataRouter("u-test", dict(vs))
        factory = lambda: router  # noqa: E731
        monkeypatch.setattr(pkg, "get_prices", factory)
        monkeypatch.setattr(registry, "get_prices", factory)
        for name in ("alphadesk.ingest.corporate_actions",):
            mod = sys.modules.get(name)
            if mod is not None and hasattr(mod, "get_prices"):
                monkeypatch.setattr(mod, "get_prices", factory)
        return router
    return install

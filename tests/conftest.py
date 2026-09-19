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


@pytest.fixture(autouse=True)
def _reset_providers():
    """Provider selection is cached for the process; clear it between tests so
    one test's NEWS_PROVIDER can't leak into the next."""
    from alphadesk.ingest import background_fill
    from alphadesk.providers import registry
    registry.reset_cache()
    background_fill._failed.clear()
    yield
    registry.reset_cache()
    background_fill._failed.clear()


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

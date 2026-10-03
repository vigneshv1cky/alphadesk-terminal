"""Vendor keys from the settings (2026-10-03): sealed at start into the one account, add or update only."""
import base64

import pytest

from alphadesk.ledger import envkeys, vault

_VENDOR_ENV = ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "POLYGON_API_KEY", "FINNHUB_API_KEY",
               "ALPHAVANTAGE_API_KEY", "FMP_API_KEY", "COINGECKO_API_KEY"]


@pytest.fixture
def settings(monkeypatch):
    for name in _VENDOR_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALPHADESK_VAULT_KEY", base64.b64encode(b"\x07" * 32).decode())
    monkeypatch.setenv("ALPHADESK_AUTH", "off")
    monkeypatch.delenv("ALPHADESK_ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("ALPHADESK_LOCAL_USER_EMAIL", raising=False)
    return monkeypatch


def test_keys_in_the_settings_are_sealed_for_prices_and_news(store, settings):
    settings.setenv("ALPACA_API_KEY", "AKEY-1111-xxxx")
    settings.setenv("ALPACA_SECRET_KEY", "SECRET-2222-yyyy")
    settings.setenv("FINNHUB_API_KEY", "FH-key-3333")
    uid = store.ensure_local_user()
    done = envkeys.load(uid)
    assert sorted(done["sealed"]) == ["news:alpaca", "prices:alpaca", "prices:finnhub"]   # finnhub is not a news key
    row = store.get_user_keys(uid, "news")[0]
    assert vault.decrypt(row["config"]) == {"api_key": "AKEY-1111-xxxx", "api_secret": "SECRET-2222-yyyy"}
    assert row["key_hint"] == "xxxx"


def test_a_restart_rewrites_nothing_and_a_changed_key_is_updated(store, settings):
    settings.setenv("POLYGON_API_KEY", "PK-one-1111")
    uid = store.ensure_local_user()
    assert envkeys.load(uid)["sealed"]
    again = envkeys.load(uid)
    assert again["sealed"] == [] and sorted(again["current"]) == ["news:polygon", "prices:polygon"]
    settings.setenv("POLYGON_API_KEY", "PK-two-2222")
    assert sorted(envkeys.load(uid)["sealed"]) == ["news:polygon", "prices:polygon"]


def test_a_key_removed_from_the_settings_is_kept(store, settings):
    settings.setenv("FMP_API_KEY", "FMP-key-1111")
    uid = store.ensure_local_user()
    envkeys.load(uid)
    settings.delenv("FMP_API_KEY")
    envkeys.load(uid)
    assert [r["provider"] for r in store.get_user_keys(uid, "prices")] == ["fmp"]


def test_the_account_is_the_local_one_or_the_single_allowed_address(store, settings):
    assert envkeys.target_account() == store.ensure_local_user()
    settings.setenv("ALPHADESK_AUTH", "required")
    assert envkeys.target_account() is None                          # accounts, no single address
    settings.setenv("ALPHADESK_ALLOWED_EMAILS", "a@example.com b@example.com")
    assert envkeys.target_account() is None
    settings.setenv("ALPHADESK_ALLOWED_EMAILS", "me@example.com")
    uid = envkeys.target_account()                                   # made if missing, found after
    assert uid and store.get_user_by_email("me@example.com")["user_id"] == uid
    assert envkeys.target_account() == uid


def test_without_a_vault_key_nothing_is_loaded(store, settings):
    settings.delenv("ALPHADESK_VAULT_KEY")
    settings.setenv("POLYGON_API_KEY", "PK-one-1111")
    envkeys.load_at_start()                                          # warns, does not raise
    assert store.get_user_keys(store.ensure_local_user(), "prices") == []

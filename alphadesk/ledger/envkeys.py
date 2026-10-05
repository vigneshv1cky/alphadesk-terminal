"""Vendor keys from the server's settings (2026-10-03).

For a one-person server the settings file is the natural home of its vendor
keys: rebuild or move the server and the same file gives the same setup. At
start the keys found there are sealed into the account the server acts as —
the one local account, or, with sign-in on and exactly one address on the
allow-list, that address's account — so the Account page and every panel read
them the way they read a key typed in by hand.

Rules, kept deliberately small:
  * Settings ADD OR UPDATE; they never delete. A key removed from the settings
    stays until it is removed on the Account page.
  * A key whose value already matches what is stored is left alone, so a
    restart rewrites nothing.
  * Where a key was changed on the Account page and the settings differ, the
    settings win at the next start. They are the record.
  * Nothing is read from the environment while serving a request: the vault
    stays the only place a request finds a key (alphadesk/ledger/vault.py).
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("alphadesk.envkeys")

#: vendor -> (key setting, secret setting) for market data.
PRICES = {"alpaca": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"), "polygon": ("POLYGON_API_KEY", None),
          "finnhub": ("FINNHUB_API_KEY", None), "alphavantage": ("ALPHAVANTAGE_API_KEY", None),
          "fmp": ("FMP_API_KEY", None)}
#: Finnhub is market data only: its general news feed carries almost no
#: tickers, so as a news key it delivered nothing (2026-09-13).
NEWS = {"polygon": ("POLYGON_API_KEY", None), "alpaca": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
        "fmp": ("FMP_API_KEY", None)}


def target_account() -> str | None:
    """The account the settings' keys belong to, or None when there is none to
    give them to: the one local account with sign-in off, or the login's."""
    from alphadesk.app import auth
    from alphadesk.ledger import store
    if not auth.auth_required():
        return store.ensure_local_user()
    row = store.get_user_by_email(auth.login_email()) if auth.login_email() else None
    return row["user_id"] if row else None


def _setting(name: str | None) -> str:
    return (os.environ.get(name) or "").strip() if name else ""


def load(user_id: str) -> dict[str, list[str]]:
    """Seal every key found in the settings into `user_id`. Returns what
    changed and what was already current, as "seam:vendor" names — never a key."""
    from alphadesk.ledger import store, vault
    out: dict[str, list[str]] = {"sealed": [], "current": []}
    for seam, table in (("prices", PRICES), ("news", NEWS)):
        have = {r["provider"]: r for r in store.get_user_keys(user_id, seam)}
        for vendor, (k_env, s_env) in table.items():
            key, secret = _setting(k_env), _setting(s_env)
            if not key:
                continue
            row = have.get(vendor)
            if row is not None:
                try:
                    stored = vault.decrypt(row["config"])
                except vault.VaultError:
                    stored = {}
                if stored.get("api_key") == key and (stored.get("api_secret") or "") == secret:
                    out["current"].append(f"{seam}:{vendor}")
                    continue
            store.set_user_key(user_id, seam, vendor, vault.encrypt({"api_key": key, "api_secret": secret}), key[-4:])
            out["sealed"].append(f"{seam}:{vendor}")
    if out["sealed"]:
        from alphadesk.providers import registry
        registry.forget_user_keys(user_id)
    return out


def load_at_start() -> None:
    """Called once when the server starts. Quiet when there is nothing to do."""
    from alphadesk.ledger import store, vault
    if not any(_setting(k) for k, _ in [*PRICES.values(), *NEWS.values()]):
        return
    if not vault.enabled():
        log.warning("vendor keys are in the settings but ALPHADESK_VAULT_KEY is not set: they were not loaded")
        return
    store.init()
    uid = target_account()
    if uid is None:
        log.warning("vendor keys are in the settings but this server has no single account to give them to "
                    "(sign-in is on and the allow-list does not name exactly one address): they were not loaded")
        return
    done = load(uid)
    log.info("vendor keys from the settings: %d sealed (%s), %d already current",
             len(done["sealed"]), ", ".join(done["sealed"]) or "none", len(done["current"]))

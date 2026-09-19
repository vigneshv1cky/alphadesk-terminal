"""Who may use the terminal: owners, the free trial, and subscriptions
(2026-09-18, groundwork for taking readers on).

Three settings, all inert by default so a deploy changes nothing:

  ALPHADESK_OWNER_EMAILS   comma list. Owners open the admin page and are
                           never gated.
  ALPHADESK_TRIAL_DAYS     the free trial every new account starts (14).
  ALPHADESK_BILLING_ENFORCE  "on" (or "1") turns the gate on — the managed
                           service. Off, the default and what a self-hosted
                           copy runs, every signed-in account keeps full
                           access and the trial is only shown, never applied.

The PAYMENT PROCESSOR is a seam. Stripe is the one shipped (2026-09-19):
with STRIPE_SECRET_KEY set it is the processor unless
ALPHADESK_BILLING_PROVIDER names another. Without a key, checkout answers
"payments are not set up yet" and nothing is charged. Monthly and yearly
plans are two Stripe prices (STRIPE_PRICE_ID_MONTHLY, STRIPE_PRICE_ID_YEARLY).

Access is decided from the account row alone — the trial's end and the
subscription status the processor last reported — so the request gate costs
one cached row read, never a call to the processor.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

DEFAULT_TRIAL_DAYS = 14

# The processor's statuses that keep a reader in. PAST_DUE is a grace: a
# card that failed today should not cut off a reader mid-session while the
# processor retries it. A CANCELED plan runs to the end of the paid period.
PAID_STATUSES = frozenset({"active", "trialing", "past_due"})


# ── settings ────────────────────────────────────────────────────────────────

def owners() -> set[str]:
    raw = os.environ.get("ALPHADESK_OWNER_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_owner(email: str | None) -> bool:
    return bool(email and email.strip().lower() in owners())


def trial_days() -> int:
    try:
        return max(0, int(os.environ.get("ALPHADESK_TRIAL_DAYS", DEFAULT_TRIAL_DAYS)))
    except ValueError:
        return DEFAULT_TRIAL_DAYS


def enforced() -> bool:
    return os.environ.get("ALPHADESK_BILLING_ENFORCE", "").strip().lower() in ("1", "on", "true", "yes")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def trial_end_from_now(days: int | None = None) -> str:
    return (_now() + timedelta(days=trial_days() if days is None else days)).isoformat(timespec="seconds")


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── the decision ────────────────────────────────────────────────────────────

def access(row: dict | None) -> dict:
    """{state, trial_ends_at, days_left, plan_status, plan_period_end,
    enforced, can_subscribe} for one account row (store.user_access_row).

    state: owner | subscribed | trialing | expired. `expired` only BLOCKS
    when `enforced` is true; with the gate off it is a label."""
    row = row or {}
    now = _now()
    trial_end = _parse(row.get("trial_ends_at"))
    period_end = _parse(row.get("plan_period_end"))
    status = (row.get("plan_status") or "").lower() or None
    if is_owner(row.get("email")):
        state = "owner"
    elif status in PAID_STATUSES or (status == "canceled" and period_end and period_end > now):
        state = "subscribed"
    elif trial_end and trial_end > now:
        state = "trialing"
    else:
        state = "expired"
    days_left = None
    if state == "trialing" and trial_end:
        days_left = max(0, (trial_end - now).days + (1 if (trial_end - now).seconds else 0))
    return {
        "state": state,
        "trial_ends_at": row.get("trial_ends_at"),
        "days_left": days_left,
        "plan_status": status,
        "plan_period_end": row.get("plan_period_end"),
        "enforced": enforced(),
        "can_subscribe": provider() is not None,
    }


def blocked(row: dict | None) -> bool:
    return enforced() and access(row)["state"] == "expired"


# A signed-in reader's access, cached briefly: the gate runs on every data
# request, and a trial ends by the day, not the second. An admin change or a
# processor webhook clears the account's entry at once.
_CACHE_TTL_S = 30.0
_cache: dict[str, tuple[float, bool]] = {}
_cache_lock = threading.Lock()


def blocked_user(user_id: str) -> bool:
    if not enforced():
        return False
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(user_id)
        if hit and now - hit[0] < _CACHE_TTL_S:
            return hit[1]
    from alphadesk.ledger import store
    verdict = blocked(store.user_access_row(user_id))
    with _cache_lock:
        if len(_cache) > 10_000:
            _cache.clear()
        _cache[user_id] = (now, verdict)
    return verdict


def forget(user_id: str) -> None:
    with _cache_lock:
        _cache.pop(user_id, None)


# Paths an expired account still reaches: its plan, its keys and its agent
# access (to revoke them), so it can see why it is stopped, subscribe, or
# tidy up. /api/auth is never gated. Owners are never blocked, so /api/admin
# needs no entry.
_EXEMPT = ("/api/billing", "/api/account", "/api/keys", "/api/system", "/api/data/vendors",
           "/api/agent/access-tokens", "/api/agent/connections")


def exempt(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _EXEMPT)


# ── the processor seam ──────────────────────────────────────────────────────

PLANS = ("monthly", "yearly")


class NotConfigured(Exception):
    """A payment setting is missing: the route answers 503 naming it."""


class ProcessorError(Exception):
    """The processor refused or could not be reached: the route answers 502."""


class BillingProvider(Protocol):
    """What a payment processor must do for AlphaDesk."""

    name: str

    def checkout_url(self, user_id: str, email: str, return_url: str, plan: str = "monthly") -> str:
        """A hosted checkout page for one plan (PLANS)."""
        ...

    def portal_url(self, customer_id: str, return_url: str) -> str:
        """The processor's own page to update a card, see invoices, cancel."""
        ...

    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> list[dict]:
        """Verify the processor's signature and return plan updates:
        [{user_id?, customer_id, subscription_id, status, period_end}].
        Raise on a bad signature — an unsigned body must change nothing."""
        ...


_providers: dict[str, BillingProvider] = {}


def register(p: BillingProvider) -> None:
    _providers[p.name] = p


def provider() -> BillingProvider | None:
    """The configured processor (ALPHADESK_BILLING_PROVIDER), when one of
    that name is registered. None means payments are not set up."""
    name = os.environ.get("ALPHADESK_BILLING_PROVIDER", "").strip().lower()
    if not name and os.environ.get("STRIPE_SECRET_KEY", "").strip():
        name = "stripe"
    return _providers.get(name) if name else None


def apply_updates(provider_name: str, updates: list[dict]) -> int:
    """Store what a verified webhook reported. Returns accounts changed."""
    from alphadesk.ledger import store
    changed = 0
    for u in updates:
        uid = u.get("user_id")
        if not uid and u.get("customer_id"):
            hit = store.user_by_plan_customer(provider_name, u["customer_id"])
            uid = hit and hit["user_id"]
        if uid and store.set_plan(uid, provider=provider_name, status=u.get("status"),
                                  customer_id=u.get("customer_id"),
                                  subscription_id=u.get("subscription_id"),
                                  period_end=u.get("period_end")):
            forget(uid)
            changed += 1
    return changed


# ── Stripe ──────────────────────────────────────────────────────────────────

def _ts(value) -> str | None:
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat(timespec="seconds") if value else None
    except (TypeError, ValueError, OSError):
        return None


def stripe_updates(event: dict) -> list[dict]:
    """A verified Stripe event → plan updates for apply_updates. Pure.

    * checkout.session.completed — the reader paid: active, and the
      customer and subscription are recorded against the account named in
      the session (client_reference_id, or metadata.user_id).
    * customer.subscription.created / updated — the status Stripe holds
      now (active, past_due, canceled, unpaid, …) and the paid period's end.
      A renewal, a failed card and a cancel-at-period-end all arrive here.
    * customer.subscription.deleted — the subscription has ended: canceled,
      with the period closed at its end, so access stops now.
    Any other event changes nothing."""
    kind = event.get("type") or ""
    obj = ((event.get("data") or {}).get("object")) or {}
    meta = obj.get("metadata") or {}
    if kind == "checkout.session.completed":
        if obj.get("mode") not in (None, "subscription"):
            return []
        return [{"user_id": obj.get("client_reference_id") or meta.get("user_id"),
                 "customer_id": obj.get("customer"), "subscription_id": obj.get("subscription"),
                 "status": "active", "period_end": None}]
    if kind in ("customer.subscription.created", "customer.subscription.updated",
                "customer.subscription.deleted"):
        # The period's end moved from the subscription to its items in
        # Stripe's 2025-03-31 API version; either is read.
        items = ((obj.get("items") or {}).get("data")) or [{}]
        end = obj.get("current_period_end") or items[0].get("current_period_end")
        status = obj.get("status") or None
        if kind.endswith(".deleted"):
            status, end = "canceled", obj.get("ended_at") or obj.get("canceled_at") or end
        return [{"user_id": meta.get("user_id"), "customer_id": obj.get("customer"),
                 "subscription_id": obj.get("id"), "status": status, "period_end": _ts(end)}]
    return []


class StripeProvider:
    """Stripe Checkout, the Customer Portal and signed webhooks. The SDK is
    imported on first use, so an instance with no key never loads it."""

    name = "stripe"

    @staticmethod
    def _settings() -> dict[str, str]:
        from alphadesk.config import stripe_settings
        return stripe_settings()

    def _key(self) -> str:
        key = self._settings()["STRIPE_SECRET_KEY"]
        if not key:
            raise NotConfigured("payments are not set up yet (STRIPE_SECRET_KEY is not set)")
        return key

    def checkout_url(self, user_id: str, email: str, return_url: str, plan: str = "monthly") -> str:
        key = self._key()
        var = "STRIPE_PRICE_ID_YEARLY" if plan == "yearly" else "STRIPE_PRICE_ID_MONTHLY"
        price = self._settings()[var]
        if not price:
            raise NotConfigured(f"the {plan} plan is not set up yet ({var} is not set)")
        import stripe
        try:
            session = stripe.checkout.Session.create(
                api_key=key, mode="subscription",
                line_items=[{"price": price, "quantity": 1}],
                client_reference_id=user_id, customer_email=email or None,
                metadata={"user_id": user_id, "plan": plan},
                # Carried onto the subscription, so its later events name
                # the account even before the customer is recorded.
                subscription_data={"metadata": {"user_id": user_id}},
                success_url=return_url + "?billing=done", cancel_url=return_url + "?billing=canceled")
        except stripe.StripeError as exc:
            raise ProcessorError(f"Stripe refused the checkout: {exc.user_message or exc}") from None
        return session.url

    def portal_url(self, customer_id: str, return_url: str) -> str:
        key = self._key()
        import stripe
        try:
            session = stripe.billing_portal.Session.create(api_key=key, customer=customer_id,
                                                           return_url=return_url)
        except stripe.StripeError as exc:
            raise ProcessorError(f"Stripe refused the billing portal: {exc.user_message or exc}") from None
        return session.url

    def parse_webhook(self, body: bytes, headers: dict[str, str]) -> list[dict]:
        secret = self._settings()["STRIPE_WEBHOOK_SECRET"]
        if not secret:
            raise NotConfigured("STRIPE_WEBHOOK_SECRET is not set")
        import json

        import stripe
        payload = body.decode("utf-8")
        # Raises on a missing, forged or stale (5-minute tolerance) signature.
        stripe.WebhookSignature.verify_header(payload, headers.get("stripe-signature", ""), secret,
                                              stripe.Webhook.DEFAULT_TOLERANCE)
        return stripe_updates(json.loads(payload))


register(StripeProvider())

"""The owner's admin routes and every reader's plan routes (2026-09-18).

/api/admin/*  OWNER ONLY (ALPHADESK_OWNER_EMAILS): every account, and the
              switches an operator needs — disable, sign out everywhere,
              extend a trial. Anyone else gets 403, not a hint of the list.
/api/billing  the signed-in reader's own access, and the doors to the
              payment processor's checkout and billing portal. With no
              processor configured those answer 503 and charge nothing.
/api/billing/webhook/{provider}  the processor's signed notifications. The
              signature is the processor's own; an unverifiable body changes
              nothing.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Body, HTTPException, Request, Response
from pydantic import BaseModel, Field

from alphadesk import billing
from alphadesk.app import auth
from alphadesk.ledger import store

log = logging.getLogger(__name__)

router = APIRouter()


def _claims(request: Request) -> dict:
    claims = auth.current_user(request)
    if not claims or not claims.get("uid"):
        raise HTTPException(401, "sign in required")
    return claims


def _owner(request: Request) -> dict:
    claims = _claims(request)
    if not billing.is_owner(claims.get("email")):
        raise HTTPException(403, "owners only")
    return claims


# ── the owner's admin page ──────────────────────────────────────────────────

@router.get("/api/admin/users")
def admin_users(request: Request):
    """Every account, newest first, with its access decided exactly as the
    gate decides it — and the totals the page leads with."""
    _owner(request)
    users = []
    for u in store.admin_list_users():
        users.append({
            "user_id": u["user_id"],
            "email": u["email"],
            "disabled": bool(u["disabled"]),
            "created_at": u["created_at"],
            "last_seen_at": u["last_seen_at"],
            "sign_ins": u["sign_ins"],
            "counts": u["counts"],
            "access": billing.access(u),
        })
    totals = {"accounts": len(users), "disabled": sum(1 for u in users if u["disabled"])}
    for state in ("owner", "subscribed", "trialing", "expired"):
        totals[state] = sum(1 for u in users if u["access"]["state"] == state and not u["disabled"])
    return {"users": users, "totals": totals, "enforced": billing.enforced(),
            "trial_days": billing.trial_days(), "payments": billing.provider() is not None}


class DisableIn(BaseModel):
    disabled: bool


@router.post("/api/admin/users/{user_id}/disabled")
def admin_disable(user_id: str, body: DisableIn, request: Request):
    """Disable or re-enable an account. Disabling also signs it out
    everywhere, so an open tab stops at its next request."""
    claims = _owner(request)
    if user_id == claims["uid"] and body.disabled:
        raise HTTPException(422, "you cannot disable your own account")
    if not store.set_user_disabled(user_id, body.disabled):
        raise HTTPException(404, "no such account")
    if body.disabled:
        auth.invalidate_sessions(user_id)
    else:
        auth._session_states.pop(user_id, None)
    billing.forget(user_id)
    log.info("admin %s set disabled=%s on %s", claims["email"], body.disabled, user_id)
    return {"ok": True}


@router.post("/api/admin/users/{user_id}/sign-out")
def admin_sign_out(user_id: str, request: Request):
    claims = _owner(request)
    if not auth.invalidate_sessions(user_id):
        raise HTTPException(404, "no such account")
    log.info("admin %s signed out %s everywhere", claims["email"], user_id)
    return {"ok": True}


class TrialIn(BaseModel):
    days: int = Field(ge=1, le=365)


@router.post("/api/admin/users/{user_id}/trial")
def admin_extend_trial(user_id: str, body: TrialIn, request: Request):
    """Give an account `days` more of trial, counted from the later of now
    and its current end — so extending a live trial adds to it."""
    claims = _owner(request)
    row = store.user_access_row(user_id)
    if not row:
        raise HTTPException(404, "no such account")
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    current = billing._parse(row.get("trial_ends_at"))
    start = current if current and current > now else now
    end = (start + timedelta(days=body.days)).isoformat(timespec="seconds")
    store.set_trial_end(user_id, end)
    billing.forget(user_id)
    log.info("admin %s extended %s's trial to %s", claims["email"], user_id, end)
    return {"ok": True, "trial_ends_at": end}


# ── deleting an account ─────────────────────────────────────────────────────

def _erase(user_id: str) -> dict[str, int] | None:
    """Delete the account and everything it holds (store.delete_account).
    Sessions end first, so an open tab stops at its next request; cached keys
    are dropped. The reader's held news socket is released on the news
    loop's next cycle (the account is no longer an active reader), and a live
    price stream closes with the reader's last tab."""
    from alphadesk.providers import registry
    auth.invalidate_sessions(user_id)
    gone = store.delete_account(user_id)
    registry.forget_user_keys(user_id)
    billing.forget(user_id)
    auth._session_states.pop(user_id, None)
    return gone


class DeleteIn(BaseModel):
    # The account's email, typed back: a delete cannot be a stray click.
    confirm: str


@router.post("/api/account/delete")
def delete_my_account(body: DeleteIn, request: Request, response: Response):
    """A reader deletes their own account and everything in it. Owners are
    refused here — deleting the owner would lock the operator out of the
    admin page; take the address off ALPHADESK_OWNER_EMAILS first."""
    claims = _claims(request)
    if body.confirm.strip().lower() != (claims.get("email") or "").lower():
        raise HTTPException(422, "type your account's email address to confirm")
    if billing.is_owner(claims.get("email")):
        raise HTTPException(422, "an owner account cannot be deleted here")
    if _erase(claims["uid"]) is None:
        raise HTTPException(404, "no such account")
    response.delete_cookie(auth.SESSION_COOKIE)
    log.info("account %s deleted by its reader", claims["uid"])
    return {"ok": True}


@router.post("/api/admin/users/{user_id}/delete")
def admin_delete(user_id: str, body: DeleteIn, request: Request):
    """The owner deletes an account (a reader's written request, or abuse).
    The account's email must be typed back, as for a reader's own delete."""
    claims = _owner(request)
    if user_id == claims["uid"]:
        raise HTTPException(422, "you cannot delete your own account")
    row = store.user_access_row(user_id)
    if not row:
        raise HTTPException(404, "no such account")
    if body.confirm.strip().lower() != row["email"].lower():
        raise HTTPException(422, "type the account's email address to confirm")
    _erase(user_id)
    log.info("admin %s deleted account %s", claims["email"], user_id)
    return {"ok": True}


# ── the reader's own plan ───────────────────────────────────────────────────

def _return_url(request: Request) -> str:
    base = os.environ.get("ALPHADESK_BASE_URL", "").strip().rstrip("/") \
        or f"{request.url.scheme}://{request.url.netloc}"
    return base + "/account"


@router.get("/api/billing")
def my_billing(request: Request):
    claims = _claims(request)
    return billing.access(store.user_access_row(claims["uid"]))


def _processor() -> "billing.BillingProvider":
    p = billing.provider()
    if p is None:
        raise HTTPException(503, "payments are not set up yet")
    return p


def _call(fn, *args, **kwargs) -> dict:
    """A processor call as a route answer: a missing setting is 503 naming
    it, a refusal or an unreachable processor 502 — never a bare 500."""
    try:
        return {"url": fn(*args, **kwargs)}
    except billing.NotConfigured as exc:
        raise HTTPException(503, str(exc)) from None
    except billing.ProcessorError as exc:
        log.warning("billing processor error: %s", exc)
        raise HTTPException(502, str(exc)) from None


@router.post("/api/billing/checkout")
@router.post("/api/billing/create-checkout-session")
def checkout(request: Request, body: dict | None = Body(default=None)):
    """{plan: "monthly" | "yearly"} → {url} of the processor's checkout."""
    claims = _claims(request)
    plan = str((body or {}).get("plan") or "monthly").lower()
    if plan not in billing.PLANS:
        raise HTTPException(400, f"plan must be one of {', '.join(billing.PLANS)}")
    p = _processor()
    return _call(p.checkout_url, claims["uid"], claims["email"], _return_url(request), plan=plan)


@router.post("/api/billing/portal")
@router.post("/api/billing/create-portal-session")
def portal(request: Request):
    claims = _claims(request)
    p = _processor()
    row = store.user_access_row(claims["uid"]) or {}
    if not row.get("plan_customer_id"):
        raise HTTPException(409, "no subscription to manage yet")
    return _call(p.portal_url, row["plan_customer_id"], _return_url(request))


async def _webhook(provider_name: str, request: Request) -> dict:
    p = billing.provider()
    if p is None or p.name != provider_name:
        raise HTTPException(404, "no such processor configured")
    body = await request.body()
    try:
        updates = p.parse_webhook(body, {k.lower(): v for k, v in request.headers.items()})
    except billing.NotConfigured as exc:
        raise HTTPException(503, str(exc)) from None
    except Exception as exc:  # noqa: BLE001 — any verification failure is a refusal
        log.warning("%s webhook refused: %s", provider_name, exc)
        raise HTTPException(400, "webhook could not be verified") from None
    return {"ok": True, "changed": billing.apply_updates(p.name, updates)}


@router.post("/api/billing/webhook")
async def stripe_webhook(request: Request):
    """Stripe's endpoint. Register <base-url>/api/billing/webhook in the
    Stripe dashboard for checkout.session.completed and
    customer.subscription.created / updated / deleted."""
    return await _webhook("stripe", request)


@router.post("/api/billing/webhook/{provider_name}")
async def webhook(provider_name: str, request: Request):
    return await _webhook(provider_name, request)

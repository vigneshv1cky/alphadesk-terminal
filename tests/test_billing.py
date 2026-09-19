"""Access: owners, the free trial, subscriptions, the gate and the admin
routes (alphadesk/billing.py, alphadesk/app/admin.py)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from alphadesk import billing


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    for k in ("ALPHADESK_OWNER_EMAILS", "ALPHADESK_TRIAL_DAYS", "ALPHADESK_BILLING_ENFORCE",
              "ALPHADESK_BILLING_PROVIDER", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
              "STRIPE_PRICE_ID_MONTHLY", "STRIPE_PRICE_ID_YEARLY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ALPHADESK_SECRET", "test-secret-not-for-production")
    billing._cache.clear()
    registered = dict(billing._providers)
    yield
    billing._cache.clear()
    billing._providers.clear()
    billing._providers.update(registered)


def _iso(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def _sign_in(client, store, monkeypatch, email="reader@example.com"):
    from alphadesk.app import auth
    monkeypatch.setenv("ALPHADESK_AUTH", "required")
    uid = uuid.uuid4().hex
    store.create_user(uid, email, auth.hash_password("a-long-password"))
    assert client.post("/api/auth/login", json={"email": email, "password": "a-long-password"}).status_code == 200
    return uid


class TestDecision:
    def test_states(self, monkeypatch):
        monkeypatch.setenv("ALPHADESK_OWNER_EMAILS", "Boss@Example.com, other@x.io")
        assert billing.access({"email": "boss@example.com"})["state"] == "owner"
        assert billing.access({"email": "a@b.c", "plan_status": "active"})["state"] == "subscribed"
        assert billing.access({"email": "a@b.c", "plan_status": "past_due"})["state"] == "subscribed"
        assert billing.access({"email": "a@b.c", "plan_status": "canceled",
                               "plan_period_end": _iso(3)})["state"] == "subscribed"
        assert billing.access({"email": "a@b.c", "plan_status": "canceled",
                               "plan_period_end": _iso(-1)})["state"] == "expired"
        t = billing.access({"email": "a@b.c", "trial_ends_at": _iso(2.5)})
        assert t["state"] == "trialing" and t["days_left"] == 3
        assert billing.access({"email": "a@b.c", "trial_ends_at": _iso(-0.1)})["state"] == "expired"

    def test_expired_blocks_only_when_enforced(self, monkeypatch):
        row = {"email": "a@b.c", "trial_ends_at": _iso(-1)}
        assert not billing.blocked(row)
        monkeypatch.setenv("ALPHADESK_BILLING_ENFORCE", "1")
        assert billing.blocked(row)

    def test_trial_length_setting(self, monkeypatch):
        monkeypatch.setenv("ALPHADESK_TRIAL_DAYS", "30")
        assert billing.trial_days() == 30
        monkeypatch.setenv("ALPHADESK_TRIAL_DAYS", "junk")
        assert billing.trial_days() == billing.DEFAULT_TRIAL_DAYS


class TestAccounts:
    def test_a_new_account_starts_a_trial(self, store):
        store.create_user("u1", "a@b.c", "sso-only")
        row = store.user_access_row("u1")
        assert billing.access(row)["state"] == "trialing"

    def test_an_older_account_gets_a_trial_on_start(self, store):
        store.create_user("u2", "b@b.c", "sso-only")
        with store._lock, store._connect() as conn:
            conn.execute("UPDATE users SET trial_ends_at=NULL WHERE user_id='u2'")
        store.init()
        assert billing.access(store.user_access_row("u2"))["state"] == "trialing"


class TestGate:
    def test_off_by_default_even_when_expired(self, client, store, monkeypatch):
        uid = _sign_in(client, store, monkeypatch)
        store.set_trial_end(uid, _iso(-1))
        assert client.get("/api/board").status_code == 200

    def test_on_blocks_data_but_not_plan_or_keys(self, client, store, monkeypatch):
        uid = _sign_in(client, store, monkeypatch)
        store.set_trial_end(uid, _iso(-1))
        monkeypatch.setenv("ALPHADESK_BILLING_ENFORCE", "1")
        r = client.get("/api/board")
        assert r.status_code == 402 and r.json()["detail"]["subscribe"]
        assert client.get("/api/billing").json()["state"] == "expired"
        assert client.get("/api/keys").status_code == 200
        me = client.get("/api/auth/me").json()["user"]
        assert me["access"]["state"] == "expired" and me["access"]["enforced"] is True

    def test_a_subscription_or_owner_passes(self, client, store, monkeypatch):
        uid = _sign_in(client, store, monkeypatch)
        store.set_trial_end(uid, _iso(-1))
        monkeypatch.setenv("ALPHADESK_BILLING_ENFORCE", "1")
        store.set_plan(uid, provider="test", status="active", customer_id="c1")
        billing.forget(uid)
        assert client.get("/api/board").status_code == 200
        store.set_plan(uid, provider="test", status=None)
        monkeypatch.setenv("ALPHADESK_OWNER_EMAILS", "reader@example.com")
        billing.forget(uid)
        assert client.get("/api/board").status_code == 200

    def test_checkout_without_a_processor_charges_nothing(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        assert client.post("/api/billing/checkout").status_code == 503
        assert client.post("/api/billing/webhook/paddle", content=b"{}").status_code == 404


class TestAdmin:
    def test_non_owner_is_refused(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        assert client.get("/api/admin/users").status_code == 403

    def test_owner_lists_and_manages(self, client, store, monkeypatch):
        monkeypatch.setenv("ALPHADESK_OWNER_EMAILS", "boss@example.com")
        store.create_user("target", "someone@example.com", "sso-only")
        _sign_in(client, store, monkeypatch, email="boss@example.com")
        body = client.get("/api/admin/users").json()
        emails = {u["email"]: u for u in body["users"]}
        assert emails["boss@example.com"]["access"]["state"] == "owner"
        assert emails["someone@example.com"]["access"]["state"] == "trialing"
        assert body["totals"]["accounts"] == 2 and body["enforced"] is False

        before = store.user_access_row("target")["trial_ends_at"]
        r = client.post("/api/admin/users/target/trial", json={"days": 7})
        assert r.status_code == 200 and r.json()["trial_ends_at"] > before

        assert client.post("/api/admin/users/target/disabled", json={"disabled": True}).status_code == 200
        assert store.user_session_state("target")["disabled"]
        assert client.post("/api/admin/users/target/disabled", json={"disabled": False}).status_code == 200
        assert client.post("/api/admin/users/target/sign-out").status_code == 200
        assert client.post("/api/admin/users/nobody/sign-out").status_code == 404

    def test_owner_cannot_disable_themselves(self, client, store, monkeypatch):
        monkeypatch.setenv("ALPHADESK_OWNER_EMAILS", "boss@example.com")
        uid = _sign_in(client, store, monkeypatch, email="boss@example.com")
        assert client.post(f"/api/admin/users/{uid}/disabled", json={"disabled": True}).status_code == 422


class TestProcessorSeam:
    def test_a_verified_webhook_records_the_plan(self, client, store, monkeypatch):
        class Fake:
            name = "fake"

            def checkout_url(self, user_id, email, return_url, plan="monthly"):
                return f"https://pay.example/{plan}/{user_id}"

            def portal_url(self, customer_id, return_url):
                return f"https://portal.example/{customer_id}"

            def parse_webhook(self, body, headers):
                if headers.get("x-sig") != "ok":
                    raise ValueError("bad signature")
                return [{"user_id": body.decode(), "customer_id": "cus_1", "status": "active",
                         "period_end": _iso(30)}]

        billing.register(Fake())
        monkeypatch.setenv("ALPHADESK_BILLING_PROVIDER", "fake")
        uid = _sign_in(client, store, monkeypatch)
        assert client.post("/api/billing/checkout").json()["url"].endswith(uid)
        assert client.post("/api/billing/webhook/fake", content=uid.encode(), headers={"x-sig": "no"}).status_code == 400
        assert store.user_access_row(uid)["plan_status"] is None
        assert client.post("/api/billing/webhook/fake", content=uid.encode(), headers={"x-sig": "ok"}).json()["changed"] == 1
        assert client.get("/api/billing").json()["state"] == "subscribed"
        assert client.post("/api/billing/portal").json()["url"].endswith("cus_1")



class TestStripe:
    SECRET = "whsec_test"

    def _env(self, monkeypatch, **extra):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self.SECRET)
        monkeypatch.setenv("STRIPE_PRICE_ID_MONTHLY", "price_month")
        monkeypatch.setenv("STRIPE_PRICE_ID_YEARLY", "price_year")
        for k, v in extra.items():
            monkeypatch.setenv(k, v)

    def _signed(self, event: dict) -> tuple[bytes, dict]:
        import hashlib
        import hmac
        import json
        import time
        body = json.dumps(event)
        t = int(time.time())
        sig = hmac.new(self.SECRET.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
        return body.encode(), {"stripe-signature": f"t={t},v1={sig}", "content-type": "application/json"}

    def test_the_gate_reads_on_and_off(self, monkeypatch):
        for v, want in (("on", True), ("1", True), ("off", False), ("", False)):
            monkeypatch.setenv("ALPHADESK_BILLING_ENFORCE", v)
            assert billing.enforced() is want

    def test_a_key_makes_stripe_the_processor(self, monkeypatch):
        assert billing.provider() is None
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        assert billing.provider().name == "stripe"

    def test_events_become_plan_updates(self):
        done = billing.stripe_updates({"type": "checkout.session.completed", "data": {"object": {
            "mode": "subscription", "client_reference_id": "u1", "customer": "cus_1", "subscription": "sub_1"}}})
        assert done == [{"user_id": "u1", "customer_id": "cus_1", "subscription_id": "sub_1",
                         "status": "active", "period_end": None}]
        # Stripe's 2025 API version keeps the period end on the items.
        upd = billing.stripe_updates({"type": "customer.subscription.updated", "data": {"object": {
            "id": "sub_1", "customer": "cus_1", "status": "past_due", "metadata": {"user_id": "u1"},
            "items": {"data": [{"current_period_end": 1_900_000_000}]}}}})
        assert upd[0]["status"] == "past_due" and upd[0]["period_end"].startswith("2030-03-17")
        gone = billing.stripe_updates({"type": "customer.subscription.deleted", "data": {"object": {
            "id": "sub_1", "customer": "cus_1", "status": "canceled", "ended_at": 1_700_000_000,
            "current_period_end": 1_900_000_000}}})
        assert gone[0]["status"] == "canceled" and gone[0]["period_end"].startswith("2023-11-14")
        assert billing.stripe_updates({"type": "invoice.created", "data": {"object": {}}}) == []

    def test_unset_settings_answer_503_naming_them(self, client, store, monkeypatch):
        _sign_in(client, store, monkeypatch)
        r = client.post("/api/billing/create-checkout-session", json={"plan": "monthly"})
        assert r.status_code == 503 and "not set up" in r.json()["detail"]
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        r = client.post("/api/billing/create-checkout-session", json={"plan": "yearly"})
        assert r.status_code == 503 and "STRIPE_PRICE_ID_YEARLY" in r.json()["detail"]
        assert client.post("/api/billing/create-checkout-session", json={"plan": "weekly"}).status_code == 400
        assert client.post("/api/billing/create-portal-session").status_code == 409

    def test_checkout_asks_stripe_for_the_plans_price(self, client, store, monkeypatch):
        import stripe
        self._env(monkeypatch)
        seen = {}

        class S:
            url = "https://checkout.stripe.test/c"

        def create(**kw):
            seen.update(kw)
            return S()
        monkeypatch.setattr(stripe.checkout.Session, "create", create)
        uid = _sign_in(client, store, monkeypatch)
        r = client.post("/api/billing/create-checkout-session", json={"plan": "yearly"})
        assert r.json() == {"url": "https://checkout.stripe.test/c"}
        assert seen["line_items"] == [{"price": "price_year", "quantity": 1}]
        assert seen["client_reference_id"] == uid and seen["subscription_data"]["metadata"]["user_id"] == uid
        assert client.post("/api/billing/checkout").status_code == 200    # the old route, monthly
        assert seen["line_items"][0]["price"] == "price_month"

        def refuse(**kw):
            raise stripe.InvalidRequestError("No such price", param="price")
        monkeypatch.setattr(stripe.checkout.Session, "create", refuse)
        assert client.post("/api/billing/create-checkout-session", json={}).status_code == 502

    def test_a_signed_webhook_subscribes_and_a_deletion_ends_it(self, client, store, monkeypatch):
        from fastapi.testclient import TestClient

        from alphadesk.app.dashboard import app
        self._env(monkeypatch)
        uid = _sign_in(client, store, monkeypatch)
        stripe_side = TestClient(app)    # no session: Stripe signs in with its signature
        body, headers = self._signed({"type": "checkout.session.completed", "data": {"object": {
            "mode": "subscription", "client_reference_id": uid, "customer": "cus_9", "subscription": "sub_9"}}})
        forged = dict(headers, **{"stripe-signature": "t=1,v1=00"})
        assert stripe_side.post("/api/billing/webhook", content=body, headers=forged).status_code == 400
        assert store.user_access_row(uid)["plan_status"] is None
        r = stripe_side.post("/api/billing/webhook", content=body, headers=headers)
        assert r.status_code == 200 and r.json()["changed"] == 1
        assert client.get("/api/billing").json()["state"] == "subscribed"

        body, headers = self._signed({"type": "customer.subscription.deleted", "data": {"object": {
            "id": "sub_9", "customer": "cus_9", "status": "canceled", "ended_at": 1_700_000_000}}})
        assert stripe_side.post("/api/billing/webhook", content=body, headers=headers).json()["changed"] == 1
        store.set_trial_end(uid, _iso(-1))
        monkeypatch.setenv("ALPHADESK_BILLING_ENFORCE", "on")
        billing.forget(uid)
        assert client.get("/api/billing").json()["state"] == "expired"
        assert client.get("/api/board").status_code == 402

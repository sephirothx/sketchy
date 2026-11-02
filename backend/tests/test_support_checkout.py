"""The supporter pass's money path: checkout, signed webhook, cancel, grant (#1473)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.errors import install_refusal_handler
from app.api.support import (
    cancel_limiter,
    checkout_address_limiter,
    checkout_limiter,
    create_support_router,
)
from app.auth.account_data import anonymize_account
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AuditEvent, EmailOutboxEntry, SupportPurchase, User
from app.deployment import validate_support_configuration
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.supporter import active_supporters, supporter_status
from app.support.config import STUB_WEBHOOK_SECRET, SupportConfig, support_config
from app.support.grant import SupportGrantError, grant_pass
from app.support.providers import (
    Cancellation,
    BadSignature,
    PaddleProvider,
    ProviderRefused,
    ProviderUnavailable,
    StubProvider,
    parse_paddle_event,
    signature_header,
    verify_signature,
)
from app.support.signals import support_signals

from tests.dbfixtures import create_test_db

NOW = datetime.now(timezone.utc)
STUB = SupportConfig(provider="stub", webhook_secret=STUB_WEBHOOK_SECRET)
PADDLE_FIXTURES = Path(__file__).parent / "fixtures" / "paddle"


@pytest.fixture
async def site(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "support-checkout-test-secret")
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")
    for limiter in (checkout_limiter, checkout_address_limiter, cancel_limiter):
        limiter.reset()
    factory, engine = await create_test_db()
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_support_router(factory, STUB))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, factory
    await engine.dispose()


async def _register(http, name: str = "Marta") -> UUID:
    await http.post("/api/auth/display-name", json={"displayName": name})
    response = await http.post(
        "/api/auth/register", json={"username": name, "password": "a-good-password"}
    )
    return UUID(response.json()["id"])


def _event(event_id: str, event_type: str, data: dict) -> bytes:
    return json.dumps({"event_id": event_id, "event_type": event_type, "data": data}).encode()


def _paid(event_id: str, order: str, account: UUID | None, *, subscription: str | None = "sub_1") -> bytes:
    data: dict = {
        "id": order,
        "currency_code": "EUR",
        "billed_at": NOW.isoformat(),
        "details": {"totals": {"total": "1900"}},
    }
    if account:
        data["custom_data"] = {"account_id": str(account), "product": "year"}
    if subscription:
        data["subscription_id"] = subscription
        data["billing_period"] = {
            "starts_at": (NOW - timedelta(days=1)).isoformat(),
            "ends_at": (NOW + timedelta(days=364)).isoformat(),
        }
    return _event(event_id, "transaction.completed", data)


async def _post(http, body: bytes, *, secret: str = STUB_WEBHOOK_SECRET, at: datetime | None = None):
    return await http.post(
        "/api/support/webhooks/stub",
        content=body,
        headers={"Paddle-Signature": signature_header(secret, body, at or datetime.now(timezone.utc))},
    )


async def _rows(factory) -> list[SupportPurchase]:
    async with factory() as session:
        return list((await session.scalars(select(SupportPurchase))).all())


async def test_a_guest_is_refused_checkout_with_a_code(site):
    http, _ = site
    named = await http.post("/api/auth/display-name", json={"displayName": "Visitor"})
    assert named.status_code == 200, named.text
    response = await http.post("/api/support/checkout", json={"product": "year"})
    assert response.status_code == 403, (response.text, http.cookies)
    assert response.json()["errorCode"] == "account_required"
    assert response.json()["params"]["action"] == "support"


async def test_buying_through_the_stub_makes_a_supporter(site):
    http, factory = site
    user_id = await _register(http)
    response = await http.post("/api/support/checkout", json={"product": "year"})
    assert response.status_code == 200
    url = response.json()["url"]
    assert "/api/support/stub/checkout?token=" in url
    page = await http.get(url[url.index("/api/"):])
    assert page.status_code == 200 and "Pay" in page.text
    token = url.split("token=")[1]
    paid = await http.post(
        "/api/support/stub/pay",
        content=f"token={token}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert paid.status_code == 303 and paid.headers["location"] == "/support/thanks"
    async with factory() as session:
        status = await supporter_status(session, user_id)
    assert status.active and status.renews and status.until is not None
    me = (await http.get("/api/auth/me")).json()
    assert me["supporter"]["active"] is True and me["supporter"]["renews"] is True


async def test_a_forged_stub_token_buys_nothing(site):
    http, factory = site
    await _register(http)
    response = await http.post(
        "/api/support/stub/pay",
        content="token=year.00000000-0000-0000-0000-000000000000.0.forged",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 404
    assert await _rows(factory) == []


async def test_a_bad_signature_is_refused_and_counted(site):
    http, factory = site
    user_id = await _register(http)
    before = support_signals.webhooks["bad_signature"]
    response = await _post(http, _paid("e1", "o1", user_id), secret="not-the-secret")
    assert response.status_code == 401
    assert support_signals.webhooks["bad_signature"] == before + 1
    assert support_signals.last_signature_failure_at is not None
    assert await _rows(factory) == []
    unsigned = await http.post("/api/support/webhooks/stub", content=_paid("e1", "o1", user_id))
    assert unsigned.status_code == 401


async def test_an_old_signature_is_a_replay_and_is_refused(site):
    http, factory = site
    user_id = await _register(http)
    response = await _post(
        http, _paid("e1", "o1", user_id), at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    assert response.status_code == 401
    assert await _rows(factory) == []


async def test_a_replayed_webhook_is_a_200_no_op(site):
    http, factory = site
    user_id = await _register(http)
    body = _paid("e1", "o1", user_id)
    assert (await _post(http, body)).status_code == 200
    assert (await _post(http, body)).status_code == 200
    assert len(await _rows(factory)) == 1


async def test_an_event_kind_nobody_acts_on_is_a_200_that_writes_nothing(site):
    http, factory = site
    await _register(http)
    body = _event("e1", "customer.updated", {"id": "ctm_1", "email": "buyer@example.test"})
    assert (await _post(http, body)).status_code == 200
    assert await _rows(factory) == []


async def test_the_wrong_providers_route_answers_nothing(site):
    http, _ = site
    response = await http.post("/api/support/webhooks/paddle", content=b"{}")
    assert response.status_code == 404


async def test_a_renewal_without_custom_data_finds_its_account_by_subscription(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    await _post(http, _paid("e2", "o2", None))
    rows = {row.provider_event_id: row for row in await _rows(factory)}
    assert rows["e2"].user_id == user_id


async def test_a_refund_ends_the_pass_and_is_attributed_by_order(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    refund = _event(
        "e2",
        "adjustment.updated",
        {
            "id": "adj_1",
            "action": "refund",
            "status": "approved",
            "transaction_id": "o1",
            "currency_code": "EUR",
            "totals": {"total": "1900"},
        },
    )
    assert (await _post(http, refund)).status_code == 200
    async with factory() as session:
        assert not (await supporter_status(session, user_id)).active
    rows = {row.provider_event_id: row for row in await _rows(factory)}
    assert rows["e2"].user_id == user_id and rows["e2"].kind == "refund"


async def test_a_refund_still_awaiting_approval_changes_nothing(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    pending = _event(
        "e2",
        "adjustment.created",
        {"id": "adj_1", "action": "refund", "status": "pending_approval", "transaction_id": "o1"},
    )
    await _post(http, pending)
    async with factory() as session:
        assert (await supporter_status(session, user_id)).active


async def test_nothing_but_a_lifetime_may_come_without_an_end(site):
    http, factory = site
    user_id = await _register(http)
    assert (await _post(http, _paid("e1", "o1", user_id, subscription=None))).status_code == 200
    assert await _rows(factory) == []


async def test_a_second_year_is_refused_while_one_renews(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    response = await http.post("/api/support/checkout", json={"product": "year"})
    assert response.status_code == 409
    assert response.json()["errorCode"] == "support_already_active"
    assert (await http.post("/api/support/checkout", json={"product": "lifetime"})).status_code == 200


async def test_an_extra_is_capped(site):
    http, _ = site
    await _register(http)
    response = await http.post(
        "/api/support/checkout", json={"product": "year", "extraMinor": 50_001}
    )
    assert response.status_code in (400, 422)


async def test_cancelling_stops_the_renewal_and_keeps_the_time(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    response = await http.post("/api/support/cancel")
    assert response.status_code == 200
    assert response.json()["active"] is True and response.json()["renews"] is False
    # Clicking twice, and the webhook about it, are one thing that happened.
    assert (await http.post("/api/support/cancel")).status_code == 200
    webhook = _event("e9", "subscription.canceled", {"id": "sub_1"})
    assert (await _post(http, webhook)).status_code == 200
    kinds = [row.kind for row in await _rows(factory)]
    assert kinds.count("cancellation") == 1
    # And a new year may be bought once nothing renews.
    assert (await http.post("/api/support/checkout", json={"product": "year"})).status_code == 200


async def test_a_signed_in_cancel_mails_a_confirmation(site):
    http, factory = site
    user_id = await _register(http)
    async with factory() as session:
        async with session.begin():
            (await session.get(User, user_id)).email = "marta@example.test"
    await _post(http, _paid("e1", "o1", user_id))
    await http.post("/api/support/cancel")
    async with factory() as session:
        mail = (await session.scalars(select(EmailOutboxEntry))).all()
    assert [entry.template for entry in mail if entry.template == "support_cancelled"] == [
        "support_cancelled"
    ]


async def test_the_signed_out_form_answers_the_same_whatever_it_finds(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    http.cookies.clear()
    named = await http.post("/api/support/cancel/request", json={"identifier": "marta"})
    nobody = await http.post("/api/support/cancel/request", json={"identifier": "nobody"})
    assert named.status_code == nobody.status_code == 200
    assert named.json() == nobody.json()
    async with factory() as session:
        assert not (await supporter_status(session, user_id)).renews
        audit = (
            await session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == "support.cancel_requested")
            )
        ).all()
    assert len(audit) == 1 and audit[0].target_user_id == user_id


async def test_deleting_an_account_returns_what_would_keep_charging_it(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    result = await anonymize_account(factory, user_id=user_id)
    assert result.subscriptions_to_cancel == ("sub_1",)


async def test_a_renewal_after_deletion_names_nobody(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    await anonymize_account(factory, user_id=user_id)
    await _post(http, _paid("e2", "o2", user_id))
    rows = {row.provider_event_id: row for row in await _rows(factory)}
    assert rows["e2"].user_id is None


async def test_the_operator_counts_each_account_once(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    await _post(http, _paid("e2", "o2", user_id, subscription="sub_2"))
    async with factory() as session:
        assert await active_supporters(session) == 1


async def test_a_grant_is_a_stub_purchase_with_an_audit_row(site):
    http, factory = site
    user_id = await _register(http)
    http.cookies.clear()
    admin_id = await _register(http, "Boss")
    async with factory() as session:
        async with session.begin():
            (await session.get(User, admin_id)).role = "admin"
    await grant_pass(factory, username="marta", admin="boss", reason="a refund gone wrong", months=3)
    async with factory() as session:
        status = await supporter_status(session, user_id)
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "support.granted")
        )
    assert status.active and not status.renews
    assert audit.actor_user_id == admin_id and audit.target_user_id == user_id
    with pytest.raises(SupportGrantError):
        await grant_pass(factory, username="marta", admin="marta", reason="me", months=1)
    with pytest.raises(SupportGrantError):
        await grant_pass(factory, username="marta", admin="boss", reason=" ", months=1)


async def test_a_refund_names_its_buyer_not_whoever_has_a_lifetime_pass(site):
    http, factory = site
    buyer = await _register(http)
    await _post(http, _paid("e1", "o1", buyer))
    http.cookies.clear()
    stranger = await _register(http, "Bruno")
    lifetime = _event(
        "e2",
        "transaction.completed",
        {
            "id": "o2",
            "currency_code": "EUR",
            "billed_at": NOW.isoformat(),
            "custom_data": {"account_id": str(stranger), "product": "lifetime"},
            "details": {"totals": {"total": "6900"}},
        },
    )
    await _post(http, lifetime)
    refund = _event(
        "e3",
        "adjustment.updated",
        {"action": "refund", "status": "approved", "transaction_id": "o1", "totals": {"total": "1900"}},
    )
    await _post(http, refund)
    rows = {row.provider_event_id: row for row in await _rows(factory)}
    assert rows["e3"].user_id == buyer


async def test_a_refund_stops_the_subscription_so_nothing_charges_again(site, monkeypatch):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    refund = _event(
        "e2",
        "adjustment.updated",
        {"action": "refund", "status": "approved", "transaction_id": "o1", "totals": {"total": "1900"}},
    )
    await _post(http, refund)
    kinds = [row.kind for row in await _rows(factory)]
    assert kinds.count("cancellation") == 1


async def test_another_products_subscription_is_none_of_our_business(site):
    http, factory = site
    await _register(http)
    assert (await _post(http, _paid("e1", "o1", None, subscription="sub_other"))).status_code == 200
    assert await _rows(factory) == []


async def test_a_refund_that_landed_first_still_stops_the_renewal(site):
    http, factory = site
    user_id = await _register(http)
    refund = _event(
        "e1",
        "adjustment.updated",
        {"action": "refund", "status": "approved", "transaction_id": "o1", "totals": {"total": "1900"}},
    )
    await _post(http, refund)
    await _post(http, _paid("e2", "o1", user_id))
    assert "cancel:sub_1" in {row.provider_event_id for row in await _rows(factory)}


async def test_paying_after_deleting_the_account_stops_what_would_renew(site):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))
    await anonymize_account(factory, user_id=user_id)
    await _post(http, _paid("e2", "o2", user_id, subscription="sub_late"))
    assert "cancel:sub_late" in {row.provider_event_id for row in await _rows(factory)}


async def test_a_failing_provider_does_not_undo_a_recorded_webhook(site, monkeypatch):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))

    async def down(self, subscription_id):
        raise ConnectionResetError("the provider hung up")

    monkeypatch.setattr(StubProvider, "cancel_at_period_end", down)
    refund = _event(
        "e2",
        "adjustment.updated",
        {"action": "refund", "status": "approved", "transaction_id": "o1", "totals": {"total": "1900"}},
    )
    # The fact stands, and the provider is asked to come back for the rest.
    assert (await _post(http, refund)).status_code == 500
    assert "e2" in {row.provider_event_id for row in await _rows(factory)}
    monkeypatch.undo()
    assert (await _post(http, refund)).status_code == 200
    assert "cancel:sub_1" in {row.provider_event_id for row in await _rows(factory)}
    # Once stopped, a further delivery has nothing to ask of the provider.
    calls: list[str] = []

    async def counted(self, subscription_id):
        calls.append(subscription_id)
        raise AssertionError("already stopped")

    monkeypatch.setattr(StubProvider, "cancel_at_period_end", counted)
    assert (await _post(http, refund)).status_code == 200
    assert calls == []


async def test_a_failed_cancel_says_the_renewal_is_still_on(site, monkeypatch):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))

    async def down(self, subscription_id):
        raise ProviderUnavailable("down")

    monkeypatch.setattr(StubProvider, "cancel_at_period_end", down)
    response = await http.post("/api/support/cancel")
    assert response.status_code == 502
    assert response.json()["errorCode"] == "support_cancel_failed"
    async with factory() as session:
        assert (await supporter_status(session, user_id)).renews
    # The signed-out form says nothing either way.
    http.cookies.clear()
    assert (await http.post("/api/support/cancel/request", json={"identifier": "marta"})).status_code == 200


async def test_the_signed_out_form_by_email_cancels_each_subscription_once(site, monkeypatch):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id, subscription="sub_a"))
    await _post(http, _paid("e2", "o2", None, subscription="sub_a"))
    await _post(http, _paid("e3", "o3", user_id, subscription="sub_b"))
    calls: list[str] = []
    real = StubProvider.cancel_at_period_end

    async def counted(self, subscription_id):
        calls.append(subscription_id)
        return await real(self, subscription_id)

    async def known(self, email):
        return ("sub_a", "sub_b", "sub_of_another_product")

    monkeypatch.setattr(StubProvider, "cancel_at_period_end", counted)
    monkeypatch.setattr(StubProvider, "subscriptions_of_email", known)
    http.cookies.clear()
    await http.post("/api/support/cancel/request", json={"identifier": "m@example.test"})
    assert sorted(calls) == ["sub_a", "sub_b"]
    # Sending it again cancels nothing, and so mails nobody.
    await http.post("/api/support/cancel/request", json={"identifier": "m@example.test"})
    assert sorted(calls) == ["sub_a", "sub_b"]


async def test_a_year_arriving_after_the_lifetime_pass_is_stopped(site, monkeypatch):
    http, factory = site
    user_id = await _register(http)
    lifetime = _event(
        "e1",
        "transaction.completed",
        {
            "id": "o1",
            "currency_code": "EUR",
            "billed_at": datetime.now(timezone.utc).isoformat(),
            "custom_data": {"account_id": str(user_id), "product": "lifetime"},
            "details": {"totals": {"total": "6900"}},
        },
    )
    assert (await _post(http, lifetime)).status_code == 200
    assert (await _post(http, _paid("e2", "o2", user_id))).status_code == 200
    assert "cancel:sub_1" in {row.provider_event_id for row in await _rows(factory)}


async def test_a_webhook_recording_the_stop_first_does_not_lose_the_mail(site, monkeypatch):
    http, factory = site
    user_id = await _register(http)
    await _post(http, _paid("e1", "o1", user_id))

    async def webhook_first(self, subscription_id):
        await _post(http, _event("cancel-hook", "subscription.canceled", {"id": subscription_id}))
        return Cancellation(subscription_id=subscription_id, email="m@example.test")

    monkeypatch.setattr(StubProvider, "cancel_at_period_end", webhook_first)
    assert (await http.post("/api/support/cancel")).status_code == 200
    async with factory() as session:
        mail = (
            await session.scalars(
                select(EmailOutboxEntry).where(EmailOutboxEntry.template == "support_cancelled")
            )
        ).all()
    assert len(mail) == 1
    # Asked again, nothing renews and nobody is mailed twice.
    assert (await http.post("/api/support/cancel")).status_code == 200


def test_signature_checks_are_exact():
    body = b'{"a":1}'
    now = datetime.now(timezone.utc)
    verify_signature("s", body, signature_header("s", body, now), now)
    for header in (
        None,
        "",
        "ts=1",
        "h1=abc",
        "ts=x;h1=abc",
        f"ts={int(now.timestamp())};h1=h\u00e9llo",
        signature_header("t", body, now),
    ):
        with pytest.raises(BadSignature):
            verify_signature("s", body, header, now)
    with pytest.raises(BadSignature):
        verify_signature("s", body + b" ", signature_header("s", body, now), now)
    with pytest.raises(BadSignature):
        verify_signature("", body, signature_header("", body, now), now)


def test_paddle_events_parse_from_what_paddle_documents():
    year = parse_paddle_event((PADDLE_FIXTURES / "transaction_completed_year.json").read_bytes())
    assert year.kind.value == "purchase" and year.subscription_id == "sub_01hv8x29kz0t586xy6zn1a62ny"
    assert year.account_id == "01a19d74-2adb-74da-8a29-2c0de57277b7" and year.amount_minor == 1900
    assert year.period_end > year.period_start
    lifetime = parse_paddle_event(
        (PADDLE_FIXTURES / "transaction_completed_lifetime.json").read_bytes()
    )
    assert lifetime.period_end is None and lifetime.subscription_id is None
    refund = parse_paddle_event((PADDLE_FIXTURES / "adjustment_refund.json").read_bytes())
    assert refund.kind.value == "refund" and refund.order_id == "txn_01hv8wptq8987qeep44cyrewp9"
    assert parse_paddle_event(b"not json") is None


async def test_paddle_checkout_sends_the_account_in_custom_data_and_the_extra_once(monkeypatch):
    sent: dict = {}

    async def fake_call(self, method, path, payload=None):
        sent.update(method=method, path=path, payload=payload)
        return {"data": {"checkout": {"url": "https://pay.example.test/?_ptxn=txn_1"}}}

    monkeypatch.setattr(PaddleProvider, "_call", fake_call)
    provider = PaddleProvider(
        SupportConfig(
            provider="paddle",
            webhook_secret="s",
            price_year="pri_year",
            price_lifetime="pri_life",
            extra_product_id="pro_extra",
            checkout_url="https://pay.example.test/",
        )
    )
    url = await provider.create_checkout(
        product="year", account_id="acc", extra_minor=500, base_url="https://x.test"
    )
    assert url == "https://pay.example.test/?_ptxn=txn_1"
    assert "acc" not in url
    assert sent["payload"]["custom_data"] == {"account_id": "acc", "product": "year"}
    assert sent["payload"]["items"][0] == {"price_id": "pri_year", "quantity": 1}
    assert sent["payload"]["items"][1]["price"]["unit_price"]["amount"] == "500"
    assert sent["payload"]["checkout"]["url"] == "https://pay.example.test/"


def _paddle_answering(monkeypatch, answers):
    """A Paddle that answers each call in turn, with an exception or a body."""
    calls: list[tuple] = []

    async def fake_call(self, method, path, payload=None):
        calls.append((method, path, payload))
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(PaddleProvider, "_call", fake_call)
    return PaddleProvider(SupportConfig(provider="paddle", webhook_secret="s")), calls


async def test_cancelling_what_paddle_already_cancelled_succeeds(monkeypatch):
    provider, calls = _paddle_answering(
        monkeypatch, [ProviderRefused("400"), {"data": {"status": "canceled"}}]
    )
    assert (await provider.cancel_at_period_end("sub_1")).subscription_id == "sub_1"
    assert [call[0] for call in calls] == ["POST", "GET"]


async def test_a_paused_subscription_is_cancelled_at_once(monkeypatch):
    provider, calls = _paddle_answering(
        monkeypatch, [ProviderRefused("400"), {"data": {"status": "paused"}}, {"data": {}}]
    )
    await provider.cancel_at_period_end("sub_1")
    assert calls[-1][2] == {"effective_from": "immediately"}


async def test_a_real_refusal_to_cancel_still_fails(monkeypatch):
    provider, _ = _paddle_answering(
        monkeypatch, [ProviderRefused("400"), {"data": {"status": "active"}}]
    )
    with pytest.raises(ProviderRefused):
        await provider.cancel_at_period_end("sub_1")


async def test_paddle_tells_a_no_from_an_outage(monkeypatch):
    provider = PaddleProvider(SupportConfig(provider="paddle", webhook_secret="s"))

    def answering(code):
        def urlopen(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, code, "no", {}, None)

        return urlopen

    monkeypatch.setattr(urllib.request, "urlopen", answering(400))
    with pytest.raises(ProviderRefused):
        await provider._call("GET", "/subscriptions/sub_1")
    for code in (429, 503):
        monkeypatch.setattr(urllib.request, "urlopen", answering(code))
        with pytest.raises(ProviderUnavailable) as caught:
            await provider._call("GET", "/subscriptions/sub_1")
        assert not isinstance(caught.value, ProviderRefused)


def test_production_refuses_a_tier_that_could_give_passes_away():
    production = {"SKETCHY_ENV": "production"}
    with pytest.raises(RuntimeError, match="stub"):
        validate_support_configuration({**production, "SUPPORT_PROVIDER": "stub"})
    with pytest.raises(RuntimeError, match="SUPPORT_WEBHOOK_SECRET"):
        validate_support_configuration({**production, "SUPPORT_PROVIDER": "paddle"})
    with pytest.raises(RuntimeError, match="must be one of"):
        validate_support_configuration({"SUPPORT_PROVIDER": "lemonsqueezy"})
    validate_support_configuration({**production})
    validate_support_configuration({"SUPPORT_PROVIDER": "stub"})
    assert support_config({}) is None

"""Gift a pass (#1540): who may, when it starts, and who is told what."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.errors import install_refusal_handler
from app.api.inbox import create_inbox_router, inbox_payload
from app.api.support import (
    checkout_address_limiter,
    checkout_limiter,
    create_support_router,
)
from app.auth.account_data import anonymize_account
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import InboxEntry, SupportPurchase, UserBlock
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.supporter import supporter_status
from app.support.config import STUB_WEBHOOK_SECRET, SupportConfig
from app.support.providers import ProviderUnavailable, StubProvider, signature_header

from tests.dbfixtures import create_test_db

STUB = SupportConfig(provider="stub", webhook_secret=STUB_WEBHOOK_SECRET)


@pytest.fixture
async def site(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "support-gift-test-secret")
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")
    checkout_limiter.reset()
    checkout_address_limiter.reset()
    factory, engine = await create_test_db()
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_support_router(factory, STUB))
    app.include_router(create_inbox_router(factory))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, factory
    await engine.dispose()


async def _register(http, name: str) -> UUID:
    http.cookies.clear()
    await http.post("/api/auth/display-name", json={"displayName": name})
    response = await http.post(
        "/api/auth/register", json={"username": name, "password": "a-good-password"}
    )
    return UUID(response.json()["id"])


async def _pay_stub(http, url: str):
    token = url.split("token=")[1]
    return await http.post(
        "/api/support/stub/pay",
        content=f"token={token}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


async def _webhook(http, event: str, data: dict):
    body = json.dumps({"event_id": event, "event_type": "transaction.completed", "data": data}).encode()
    return await http.post(
        "/api/support/webhooks/stub",
        content=body,
        headers={
            "Paddle-Signature": signature_header(
                STUB_WEBHOOK_SECRET, body, datetime.now(timezone.utc)
            )
        },
    )


async def _event_ids(factory) -> set[str]:
    async with factory() as session:
        return set((await session.scalars(select(SupportPurchase.provider_event_id))).all())


async def _gift(http, recipient: UUID, **extra):
    return await http.post("/api/support/gift", json={"recipientId": str(recipient), **extra})


async def _inbox(factory, user_id: UUID) -> list[InboxEntry]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(InboxEntry).where(
                        InboxEntry.user_id == user_id, InboxEntry.kind == "supporter_gifted"
                    )
                )
            ).all()
        )


async def test_a_gift_makes_the_recipient_a_supporter_and_names_the_giver(site):
    http, factory = site
    recipient = await _register(http, "Bruno")
    giver = await _register(http, "Marta")
    response = await _gift(http, recipient)
    assert response.status_code == 200
    paid = await _pay_stub(http, response.json()["url"])
    assert paid.status_code == 303 and paid.headers["location"] == "/support/thanks?gift=1"
    async with factory() as session:
        status = await supporter_status(session, recipient)
        assert not (await supporter_status(session, giver)).active
        row = await session.scalar(select(SupportPurchase))
    assert status.active and status.renews is False
    # Never a subscription, never a charge on the recipient.
    assert row.provider_subscription_id is None and row.user_id == recipient
    assert row.gifted_by_user_id == giver
    assert (await _inbox(factory, recipient))[0].subject_id == giver


async def test_an_anonymous_gift_names_nobody_to_the_recipient(site):
    http, factory = site
    recipient = await _register(http, "Bruno")
    await _register(http, "Marta")
    response = await _gift(http, recipient, anonymous=True)
    await _pay_stub(http, response.json()["url"])
    entry = (await _inbox(factory, recipient))[0]
    assert entry.subject_id is None
    # Bruno's inbox says nothing about who.
    await http.post("/api/auth/logout")
    http.cookies.clear()
    await http.post(
        "/api/auth/login", json={"username": "Bruno", "password": "a-good-password"}
    )
    listing = (await http.get("/api/inbox")).json()
    gifted = [item for item in listing["entries"] if item["kind"] == "supporter_gifted"]
    assert len(gifted) == 1 and gifted[0]["person"] is None


async def test_a_gift_to_an_active_supporter_starts_when_their_time_ends(site, monkeypatch):
    moved = []

    async def move(self, subscription_id, when):
        moved.append((subscription_id, when))

    monkeypatch.setattr(StubProvider, "move_renewal", move)
    http, factory = site
    recipient = await _register(http, "Bruno")
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=100)
    await _webhook(
        http,
        "e1",
        {
            "id": "o1",
            "currency_code": "EUR",
            "subscription_id": "sub_1",
            "custom_data": {"account_id": str(recipient), "product": "year"},
            "billing_period": {
                "starts_at": (now - timedelta(days=1)).isoformat(),
                "ends_at": end.isoformat(),
            },
            "details": {"totals": {"total": "1900"}},
        },
    )
    await _register(http, "Marta")
    response = await _gift(http, recipient)
    await _pay_stub(http, response.json()["url"])
    async with factory() as session:
        gift = await session.scalar(
            select(SupportPurchase).where(SupportPurchase.gifted_by_user_id.is_not(None))
        )
        status = await supporter_status(session, recipient)
    assert gift.period_start == end
    assert gift.period_end.year == end.year + 1
    assert status.until == gift.period_end
    # Stopped, the pass would quietly end with the gift. Left alone, it would charge
    # for the months the gift just paid for. So it waits, and carries on.
    assert moved == [("sub_1", gift.period_end)]
    assert status.renews is True
    assert "cancel:sub_1" not in await _event_ids(factory)
    told = (await inbox_payload(factory, str(recipient)))["entries"]
    assert next(e for e in told if e["kind"] == "supporter_gifted")["renews"] is True


async def test_a_renewal_paddle_will_not_move_stops_instead(site, monkeypatch):
    http, factory = site
    recipient = await _register(http, "Bruno")
    await _webhook(
        http,
        "e1",
        {
            "id": "o1",
            "subscription_id": "sub_1",
            "currency_code": "EUR",
            "billed_at": datetime.now(timezone.utc).isoformat(),
            "billing_period": {
                "starts_at": datetime.now(timezone.utc).isoformat(),
                "ends_at": (datetime.now(timezone.utc) + timedelta(days=100)).isoformat(),
            },
            "custom_data": {"account_id": str(recipient), "product": "year"},
            "details": {"totals": {"total": "1900"}},
        },
    )

    async def refused(self, subscription_id, when):
        raise ProviderUnavailable("HTTPError")

    monkeypatch.setattr(StubProvider, "move_renewal", refused)
    await _register(http, "Marta")
    response = await _gift(http, recipient)
    await _pay_stub(http, response.json()["url"])
    async with factory() as session:
        status = await supporter_status(session, recipient)
    assert status.renews is False
    assert "cancel:sub_1" in await _event_ids(factory)


async def test_a_gift_with_no_renewal_moves_nothing(site, monkeypatch):
    http, factory = site
    recipient = await _register(http, "Bruno")
    moved = []

    async def move(self, subscription_id, when):
        moved.append(subscription_id)

    monkeypatch.setattr(StubProvider, "move_renewal", move)
    await _register(http, "Marta")
    await _pay_stub(http, (await _gift(http, recipient)).json()["url"])
    assert moved == []


async def test_a_lifetime_holder_a_blocked_pair_and_oneself_read_the_same(site):
    http, factory = site
    lifetime = await _register(http, "Life")
    await _webhook(
        http,
        "e1",
        {
            "id": "o1",
            "currency_code": "EUR",
            "billed_at": datetime.now(timezone.utc).isoformat(),
            "custom_data": {"account_id": str(lifetime), "product": "lifetime"},
            "details": {"totals": {"total": "6900"}},
        },
    )
    blocker = await _register(http, "Blocker")
    giver = await _register(http, "Marta")
    async with factory() as session:
        async with session.begin():
            session.add(UserBlock(blocker_user_id=blocker, blocked_user_id=giver))
    for target in (lifetime, blocker, giver, UUID("00000000-0000-7000-8000-000000000000")):
        refused = await _gift(http, target)
        assert refused.status_code == 409, target
        assert refused.json()["errorCode"] == "support_gift_refused"
        assert refused.json() == (await _gift(http, lifetime)).json()


async def test_a_guest_cannot_give(site):
    http, _ = site
    recipient = await _register(http, "Bruno")
    http.cookies.clear()
    await http.post("/api/auth/display-name", json={"displayName": "Visitor"})
    refused = await _gift(http, recipient)
    assert refused.status_code == 403 and refused.json()["errorCode"] == "account_required"


async def test_a_refund_of_a_gift_ends_it(site):
    http, factory = site
    recipient = await _register(http, "Bruno")
    await _register(http, "Marta")
    response = await _gift(http, recipient)
    await _pay_stub(http, response.json()["url"])
    async with factory() as session:
        order = (await session.scalar(select(SupportPurchase))).provider_order_id
    body = json.dumps(
        {
            "event_id": "r1",
            "event_type": "adjustment.updated",
            "data": {
                "action": "refund",
                "status": "approved",
                "transaction_id": order,
                "totals": {"total": "1900"},
            },
        }
    ).encode()
    await http.post(
        "/api/support/webhooks/stub",
        content=body,
        headers={
            "Paddle-Signature": signature_header(
                STUB_WEBHOOK_SECRET, body, datetime.now(timezone.utc)
            )
        },
    )
    async with factory() as session:
        assert not (await supporter_status(session, recipient)).active


async def test_deleting_the_giver_keeps_the_gift_and_forgets_who(site):
    http, factory = site
    recipient = await _register(http, "Bruno")
    giver = await _register(http, "Marta")
    response = await _gift(http, recipient)
    await _pay_stub(http, response.json()["url"])
    await anonymize_account(factory, user_id=giver)
    async with factory() as session:
        row = await session.scalar(select(SupportPurchase))
        assert row.gifted_by_user_id is None and row.user_id == recipient
        assert (await supporter_status(session, recipient)).active
    # And the recipient's notice no longer names them.
    assert (await _inbox(factory, recipient))[0].subject_id is None

"""Supporter doodles and name styles: who may choose, what a lapse and a refund do (#1476)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_refusal_handler
from app.api.support import create_support_router
from app.auth.avatar_doodles import DOODLES, SUPPORTER_DOODLES, doodle_key, doodle_name, random_doodle_key
from app.auth.account_data import anonymize_account
from app.auth.avatars import SupporterOnly
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import User
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.avatars import choose_doodle
from app.support.config import STUB_WEBHOOK_SECRET, SupportConfig
from app.support.providers import signature_header

from tests.dbfixtures import create_test_db, lapse_passes

STUB = SupportConfig(provider="stub", webhook_secret=STUB_WEBHOOK_SECRET)
NOW = datetime.now(timezone.utc)


@pytest.fixture
async def site(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "supporter-looks-test-secret")
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")
    factory, engine = await create_test_db()
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_support_router(factory, STUB))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, factory
    await engine.dispose()


async def _register(http, name: str = "Marta") -> UUID:
    await http.post("/api/auth/display-name", json={"displayName": name})
    response = await http.post(
        "/api/auth/register", json={"username": name, "password": "a-good-password"}
    )
    return UUID(response.json()["id"])


async def _webhook(http, event_id: str, event_type: str, data: dict):
    body = json.dumps({"event_id": event_id, "event_type": event_type, "data": data}).encode()
    return await http.post(
        "/api/support/webhooks/stub",
        content=body,
        headers={
            "Paddle-Signature": signature_header(
                STUB_WEBHOOK_SECRET, body, datetime.now(timezone.utc)
            )
        },
    )


async def _buy(http, user_id: UUID, *, event="e1", order="o1", end=NOW + timedelta(days=30)):
    await _webhook(
        http,
        event,
        "transaction.completed",
        {
            "id": order,
            "currency_code": "EUR",
            "subscription_id": f"sub_{order}",
            "custom_data": {"account_id": str(user_id), "product": "year"},
            "billing_period": {
                "starts_at": (NOW - timedelta(days=1)).isoformat(),
                "ends_at": end.isoformat(),
            },
            "details": {"totals": {"total": "1900"}},
        },
    )


async def _refund(http, event="r1", order="o1"):
    await _webhook(
        http,
        event,
        "adjustment.updated",
        {"action": "refund", "status": "approved", "transaction_id": order, "totals": {"total": "1900"}},
    )


async def _style(http, style):
    return await http.post("/api/auth/name-style", json={"nameStyle": style})


async def _lapse(factory, user_id: UUID) -> None:
    await lapse_passes(factory, user_id, NOW - timedelta(hours=1))


def test_a_new_account_never_draws_a_supporter_doodle():
    assert not set(DOODLES) & set(SUPPORTER_DOODLES)
    assert all(doodle_name(random_doodle_key()) in DOODLES for _ in range(200))
    assert doodle_name(doodle_key(SUPPORTER_DOODLES[0])) == SUPPORTER_DOODLES[0]


async def test_a_hand_made_request_for_a_style_gets_supporter_only(site):
    http, _ = site
    await _register(http)
    refused = await _style(http, "sunset")
    assert refused.status_code == 403 and refused.json()["errorCode"] == "supporter_only"
    # An unknown key is not a style at all, and the plain colour is always allowed.
    assert (await _style(http, "rainbow")).status_code in (400, 422)
    assert (await _style(http, None)).status_code == 200


async def test_a_supporter_doodle_needs_a_pass(site):
    http, factory = site
    user_id = await _register(http)
    with pytest.raises(SupporterOnly):
        await choose_doodle(factory, user_id=user_id, name=SUPPORTER_DOODLES[0])
    await _buy(http, user_id)
    key = await choose_doodle(factory, user_id=user_id, name=SUPPORTER_DOODLES[0])
    assert key == doodle_key(SUPPORTER_DOODLES[0])


async def test_a_supporter_sees_the_style_on_their_own_account(site):
    http, _ = site
    user_id = await _register(http)
    await _buy(http, user_id)
    chosen = await _style(http, "ocean")
    assert chosen.status_code == 200 and chosen.json()["nameStyle"] == "ocean"
    assert (await http.get("/api/auth/me")).json()["nameStyle"] == "ocean"


async def test_a_lapse_keeps_the_choices_and_stops_new_ones(site):
    http, factory = site
    user_id = await _register(http)
    await _buy(http, user_id)
    await _style(http, "ocean")
    await choose_doodle(factory, user_id=user_id, name=SUPPORTER_DOODLES[0])
    await _lapse(factory, user_id)

    me = (await http.get("/api/auth/me")).json()
    assert me["nameStyle"] == "ocean" and me["avatarUrl"].endswith(SUPPORTER_DOODLES[0])
    # What they already wear is not a new choice; anything else is.
    assert (await _style(http, "ocean")).status_code == 200
    assert (await _style(http, "berry")).status_code == 403
    await choose_doodle(factory, user_id=user_id, name=SUPPORTER_DOODLES[0])
    with pytest.raises(SupporterOnly):
        await choose_doodle(factory, user_id=user_id, name=SUPPORTER_DOODLES[1])


async def test_a_save_in_flight_cannot_undo_a_refund(site, monkeypatch):
    http, factory = site
    user_id = await _register(http)
    await _buy(http, user_id)
    await _style(http, "ocean")
    real = SqlAlchemyUserRepository.get_by_id
    armed = [True]

    async def refund_after_the_read(self, wanted):
        user = await real(self, wanted)
        if armed:
            armed.clear()
            await _refund(http)
        return user

    monkeypatch.setattr(SqlAlchemyUserRepository, "get_by_id", refund_after_the_read)
    # The account it read still wears Ocean, so this looked like no new choice.
    response = await _style(http, "ocean")
    assert response.status_code == 403 and response.json()["errorCode"] == "supporter_only"
    async with factory() as session:
        assert (await session.get(User, user_id)).name_style is None


async def test_a_refund_puts_the_account_back_on_defaults(site):
    http, factory = site
    user_id = await _register(http)
    await _buy(http, user_id)
    await _style(http, "ocean")
    await choose_doodle(factory, user_id=user_id, name=SUPPORTER_DOODLES[0])
    await _refund(http)
    async with factory() as session:
        user = await session.get(User, user_id)
    assert user.name_style is None
    assert doodle_name(user.avatar_key) in DOODLES


async def test_a_refund_of_one_order_keeps_them_while_another_stands(site):
    http, factory = site
    user_id = await _register(http)
    await _buy(http, user_id)
    await _buy(http, user_id, event="e2", order="o2", end=NOW + timedelta(days=60))
    await _style(http, "ocean")
    await _refund(http)
    async with factory() as session:
        assert (await session.get(User, user_id)).name_style == "ocean"


async def test_a_lapsed_order_does_not_keep_the_choices_a_chargeback_takes(site):
    http, factory = site
    user_id = await _register(http)
    await _buy(http, user_id, event="old", order="old", end=NOW - timedelta(days=30))
    await _buy(http, user_id)
    await _style(http, "ocean")
    await _refund(http)
    async with factory() as session:
        assert (await session.get(User, user_id)).name_style is None


async def test_deleting_an_account_erases_its_style(site):
    http, factory = site
    user_id = await _register(http)
    await _buy(http, user_id)
    await _style(http, "ocean")
    await anonymize_account(factory, user_id=user_id)
    async with factory() as session:
        assert (await session.get(User, user_id)).name_style is None

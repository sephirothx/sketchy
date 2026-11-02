"""What the supporter pass tells a player, and what the pitch reads (#1475)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.errors import install_refusal_handler
from app.api.inbox import create_inbox_router
from app.api.support import create_support_router
from app.api.user_settings import create_user_settings_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import InboxEntry
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.supporter import tell_ending_supporters
from app.support.config import STUB_WEBHOOK_SECRET, SupportConfig
from app.support.providers import signature_header

from tests.dbfixtures import create_test_db

STUB = SupportConfig(
    provider="stub", webhook_secret=STUB_WEBHOOK_SECRET, tip_url="https://ko-fi.com/sketchy"
)


@pytest.fixture
async def site(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "support-pitch-test-secret")
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")
    factory, engine = await create_test_db()
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_support_router(factory, STUB))
    app.include_router(create_inbox_router(factory))
    app.include_router(create_user_settings_router(factory))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, factory
    await engine.dispose()


async def _register(http, name: str = "Marta") -> UUID:
    await http.post("/api/auth/display-name", json={"displayName": name})
    response = await http.post(
        "/api/auth/register", json={"username": name, "password": "a-good-password"}
    )
    return UUID(response.json()["id"])


async def _paid(http, event: str, order: str, account, *, end, subscription="sub_1", product="year"):
    data = {
        "id": order,
        "currency_code": "EUR",
        "billed_at": datetime.now(timezone.utc).isoformat(),
        "custom_data": {"account_id": str(account), "product": product},
        "details": {"totals": {"total": "1900"}},
    }
    if subscription:
        data["subscription_id"] = subscription
        data["billing_period"] = {
            "starts_at": (end - timedelta(days=365)).isoformat(),
            "ends_at": end.isoformat(),
        }
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


async def _entries(factory, kind: str) -> list[InboxEntry]:
    async with factory() as session:
        return list(
            (await session.scalars(select(InboxEntry).where(InboxEntry.kind == kind))).all()
        )


async def test_plans_are_public_and_name_the_tip_link(site):
    http, _ = site
    plans = (await http.get("/api/support/plans")).json()
    assert plans["year"]["price"] == "€19" and plans["lifetime"]["price"] == "€69"
    assert plans["tipUrl"] == "https://ko-fi.com/sketchy"


async def test_a_pass_starting_is_told_once_and_a_renewal_is_not_news(site):
    http, factory = site
    user_id = await _register(http)
    end = datetime.now(timezone.utc) + timedelta(days=300)
    await _paid(http, "e1", "o1", user_id, end=end)
    await _paid(http, "e1", "o1", user_id, end=end)
    await _paid(http, "e2", "o2", user_id, end=end + timedelta(days=365))
    entries = await _entries(factory, "supporter_started")
    assert len(entries) == 1
    assert entries[0].params["renews"] is True
    listing = (await http.get("/api/inbox")).json()
    shown = [entry for entry in listing["entries"] if entry["kind"] == "supporter_started"]
    assert shown[0]["until"] == end.isoformat() and shown[0]["renews"] is True


async def test_a_lifetime_pass_is_told_with_no_end(site):
    http, factory = site
    user_id = await _register(http)
    end = datetime.now(timezone.utc)
    await _paid(http, "e1", "o1", user_id, end=end, subscription=None, product="lifetime")
    entries = await _entries(factory, "supporter_started")
    assert entries[0].params == {"until": None, "renews": False}


async def test_the_sweep_tells_once_fourteen_days_before_the_end(site):
    http, factory = site
    user_id = await _register(http)
    now = datetime.now(timezone.utc)
    await _paid(http, "e1", "o1", user_id, end=now + timedelta(days=20))
    assert await tell_ending_supporters(factory, now=now) == 0
    soon = now + timedelta(days=7)
    assert await tell_ending_supporters(factory, now=soon) == 1
    assert await tell_ending_supporters(factory, now=soon) == 0
    entries = await _entries(factory, "supporter_ending")
    assert len(entries) == 1 and entries[0].params["renews"] is True


async def test_the_sweep_says_a_cancelled_pass_ends(site):
    http, factory = site
    user_id = await _register(http)
    now = datetime.now(timezone.utc)
    await _paid(http, "e1", "o1", user_id, end=now + timedelta(days=10))
    await http.post("/api/support/cancel")
    await tell_ending_supporters(factory, now=now)
    entries = await _entries(factory, "supporter_ending")
    assert entries[0].params["renews"] is False


async def test_the_sweep_skips_a_period_something_later_extends(site):
    http, factory = site
    user_id = await _register(http)
    now = datetime.now(timezone.utc)
    await _paid(http, "e1", "o1", user_id, end=now + timedelta(days=10))
    await _paid(http, "e2", "o2", user_id, end=now + timedelta(days=375))
    assert await tell_ending_supporters(factory, now=now) == 0


async def test_the_nudge_stays_closed_on_the_account(site):
    http, _ = site
    await _register(http)
    closed = await http.patch("/api/users/me/settings", json={"supporterNudgeDismissed": True})
    assert closed.status_code == 200 and closed.json()["supporterNudgeDismissed"] is True
    me = (await http.get("/api/auth/me")).json()
    assert me["settings"]["supporterNudgeDismissed"] is True

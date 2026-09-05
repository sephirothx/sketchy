"""Who gets written down, and when.

Provisioning used to happen on the first page load, which meant a crawler, a
link preview and an uptime check each cost a `users` row and an
`auth_sessions` row. It now happens when somebody chooses a name - an act only
a person about to play performs.
"""
from __future__ import annotations

import contextlib

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AuthSession, User
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db


@contextlib.asynccontextmanager
async def build_site(monkeypatch, **limits):
    """A site whose provisioning ceilings the test chooses."""
    for name, value in limits.items():
        monkeypatch.setenv(name, str(value))
    factory, engine = await create_test_db()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http, factory
    finally:
        await engine.dispose()


async def count(factory, model) -> int:
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def hourly_attempts(factory) -> int:
    """What the per-address provisioning bucket has recorded."""
    from app.db.models import AuthRateLimitBucket

    async with factory() as session:
        return (
            await session.scalar(
                select(func.coalesce(func.sum(AuthRateLimitBucket.attempt_count), 0))
                .where(AuthRateLimitBucket.scope == "guest_provision")
            )
        ) or 0


@pytest_asyncio.fixture
async def site(monkeypatch):
    async with build_site(monkeypatch) as opened:
        yield opened


@pytest.mark.asyncio
async def test_looking_at_the_site_writes_nothing_down(site):
    client, factory = site

    response = await client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() is None
    assert "set-cookie" not in {key.lower() for key in response.headers}
    assert await count(factory, User) == 0
    assert await count(factory, AuthSession) == 0


@pytest.mark.asyncio
async def test_choosing_a_name_is_what_creates_the_account(site):
    client, factory = site

    named = await client.post("/api/auth/display-name", json={"displayName": "Wanderer"})

    assert named.status_code == 200
    body = named.json()
    assert body["isAnonymous"] is True
    assert body["displayName"] == "Wanderer"
    assert await count(factory, User) == 1
    # And that account is then the one `me` answers with, cookie in hand.
    assert (await client.get("/api/auth/me")).json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_provisioning_is_capped_per_caller(monkeypatch):
    async with build_site(monkeypatch, GUEST_PROVISION_LIMIT=2) as (client, factory):
        codes = []
        for index in range(3):
            client.cookies.clear()  # a visitor who keeps no cookie
            codes.append(
                (
                    await client.post(
                        "/api/auth/display-name", json={"displayName": f"Guest{index}"}
                    )
                ).status_code
            )

        assert codes == [200, 200, 429]
        assert await count(factory, User) == 2


@pytest.mark.asyncio
async def test_the_day_has_a_ceiling_of_its_own(monkeypatch):
    """The per-address key is worth little behind a proxy and nothing at all
    against a botnet. This is the number that still holds then."""
    async with build_site(
        monkeypatch, GUEST_PROVISION_LIMIT=100, GUEST_PROVISION_DAILY_LIMIT=1
    ) as (client, factory):
        client.cookies.clear()
        first = await client.post("/api/auth/display-name", json={"displayName": "One"})
        client.cookies.clear()
        second = await client.post("/api/auth/display-name", json={"displayName": "Two"})

        assert first.status_code == 200
        assert second.status_code == 429
        assert await count(factory, User) == 1


@pytest.mark.asyncio
async def test_renaming_an_existing_guest_is_not_provisioning(monkeypatch):
    """The allowance is spent by accounts being created, not by names being
    changed: a guest who renames themselves four times is still one row."""
    async with build_site(monkeypatch, GUEST_PROVISION_LIMIT=1) as (client, factory):
        await client.post("/api/auth/display-name", json={"displayName": "Once"})

        for name in ("Twice", "Thrice", "Again"):
            renamed = await client.post(
                "/api/auth/display-name", json={"displayName": name}
            )
            assert renamed.status_code == 200, name

        assert await count(factory, User) == 1


@pytest.mark.asyncio
async def test_the_application_sweeps_stale_guests_without_being_asked(monkeypatch):
    """An unrun retention policy is not a policy, and the rows it would have
    removed are exactly the ones provisioning creates."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    from app.auth.retention import run_retention_loop
    from app.domain_values import AccountState

    async with build_site(monkeypatch) as (client, factory):
        await client.post("/api/auth/display-name", json={"displayName": "Ghost"})
        assert await count(factory, User) == 1

        # Age the guest past the unused window without waiting thirty days.
        long_ago = datetime.now(timezone.utc) - timedelta(days=90)
        async with factory() as session:
            async with session.begin():
                stale = await session.scalar(select(User))
                stale.created_at = long_ago
                stale.last_login_at = long_ago
                stale.last_active_at = long_ago
                assert stale.state == AccountState.ANONYMOUS.value

        sweep = asyncio.create_task(run_retention_loop(factory, interval_seconds=3600))
        try:
            # Polled on the condition rather than slept through: the driver
            # runs its queries on a thread, so yielding alone never lets the
            # sweep finish.
            for _ in range(200):
                if await count(factory, User) == 0:
                    break
                await asyncio.sleep(0.01)
        finally:
            sweep.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweep

        assert await count(factory, User) == 0, "the sweep left the stale guest behind"


@pytest.mark.asyncio
async def test_a_first_name_cannot_be_a_registered_players_username(monkeypatch):
    """The rename path has always refused this; provisioning skipped it."""
    async with build_site(monkeypatch) as (client, factory):
        registered = await client.post(
            "/api/auth/register",
            json={"username": "Stefano", "password": "a-good-password"},
        )
        assert registered.status_code == 200

        stranger = AsyncClient(
            transport=client._transport, base_url="http://test"
        )
        async with stranger:
            taken = await stranger.post(
                "/api/auth/display-name", json={"displayName": "Stefano"}
            )

        assert taken.status_code == 409
        assert "registered player" in taken.json()["detail"]
        assert await count(factory, User) == 1


@pytest.mark.asyncio
async def test_the_daily_ceiling_does_not_spend_the_hourly_allowance(monkeypatch):
    """A refusal buys nothing, so it must not cost the caller their turn: the
    day rolls over and they would still be blocked by an hour they never used."""
    async with build_site(
        monkeypatch, GUEST_PROVISION_LIMIT=10, GUEST_PROVISION_DAILY_LIMIT=1
    ) as (client, factory):
        client.cookies.clear()
        first = await client.post(
            "/api/auth/display-name", json={"displayName": "First"}
        )
        assert first.status_code == 200
        assert await hourly_attempts(factory) == 1

        client.cookies.clear()
        refused = await client.post(
            "/api/auth/display-name", json={"displayName": "Second"}
        )

        assert refused.status_code == 429
        assert await count(factory, User) == 1
        # The day refused this one, so the hour is untouched by it.
        assert await hourly_attempts(factory) == 1

"""The account's own end of a role change: what it is told, and the receipt.

The administrative half is in `test_admin_controls.py`. What is pinned here is
the part a player touches - that a notice waits for somebody who was offline,
that acknowledging it settles it for good, and that one account cannot read or
dismiss another's.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.role_notices import (
    create_role_notice_router,
    pending_role_notice_payload,
)
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import Base, RoleChangeNotice, User, generate_uuid
from app.domain_values import AccountState, UserRole
from app.repositories.sqlalchemy import SqlAlchemyUserRepository


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "role-notice-test-secret")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_role_notice_router(factory))

    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield new_client, factory
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()


async def add_notice(factory, user_id: str, role: str, *, ago_seconds: int = 0) -> str:
    notice_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(
                RoleChangeNotice(
                    id=notice_id,
                    user_id=UUID(user_id),
                    role=role,
                    created_at=datetime.now(timezone.utc)
                    - timedelta(seconds=ago_seconds),
                )
            )
    return str(notice_id)


async def pending_rows(factory, user_id: str) -> list[RoleChangeNotice]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(RoleChangeNotice).where(
                        RoleChangeNotice.user_id == UUID(user_id),
                        RoleChangeNotice.acknowledged_at.is_(None),
                    )
                )
            ).all()
        )


async def test_an_account_with_nothing_to_be_told_is_told_nothing(env):
    new_client, _ = env
    client = new_client()
    await register(client, "Ordinary")
    assert (await client.get("/api/role-notices/pending")).json() == {"notice": None}


async def test_a_notice_waits_for_a_player_who_was_offline(env):
    """The catch-up route: an administrator acts while nobody is connected,
    and the socket push has nowhere to land."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Away")
    notice_id = await add_notice(factory, account["id"], UserRole.MODERATOR.value)

    body = (await client.get("/api/role-notices/pending")).json()["notice"]
    assert body["id"] == notice_id
    assert body["role"] == "moderator"
    assert body["createdAt"]


async def test_the_newest_notice_is_the_one_shown(env):
    """Where this parts company with a warning. Two warnings are two things a
    moderator said; two role notices are one fact recorded twice, and the older
    one is simply wrong - so an account promoted and then demoted while it was
    away is told once, correctly, rather than congratulated and contradicted.
    """
    new_client, factory = env
    client = new_client()
    account = await register(client, "Both")
    await add_notice(factory, account["id"], UserRole.MODERATOR.value, ago_seconds=60)
    newest = await add_notice(factory, account["id"], UserRole.USER.value)

    body = (await client.get("/api/role-notices/pending")).json()["notice"]
    assert (body["id"], body["role"]) == (newest, "user")


async def test_acknowledging_settles_it_and_everything_before_it(env):
    """The receipt records that the message landed. Anything older has nothing
    left to say, and leaving it pending would pop a stale role up on the next
    visit."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Reader")
    await add_notice(factory, account["id"], UserRole.MODERATOR.value, ago_seconds=60)
    newest = await add_notice(factory, account["id"], UserRole.USER.value)

    assert (
        await client.post(f"/api/role-notices/{newest}/acknowledge")
    ).status_code == 200
    assert await pending_rows(factory, account["id"]) == []
    assert (await client.get("/api/role-notices/pending")).json() == {"notice": None}


async def test_a_newer_notice_survives_an_acknowledgement_of_an_older_one(env):
    """A promotion that arrives while the pop-up is still open is not settled
    by the button that was drawn before it."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Racing")
    older = await add_notice(
        factory, account["id"], UserRole.MODERATOR.value, ago_seconds=60
    )
    await add_notice(factory, account["id"], UserRole.USER.value)

    assert (
        await client.post(f"/api/role-notices/{older}/acknowledge")
    ).status_code == 200
    still_pending = await pending_rows(factory, account["id"])
    assert [row.role for row in still_pending] == ["user"]


async def test_somebody_elses_notice_is_not_there_to_be_read_or_dismissed(env):
    """404 rather than 403: the existence of another account's notice is not
    this caller's to learn either."""
    new_client, factory = env
    mine = new_client()
    theirs = new_client()
    await register(mine, "Mine")
    other = await register(theirs, "Theirs")
    notice_id = await add_notice(factory, other["id"], UserRole.MODERATOR.value)

    assert (
        await mine.post(f"/api/role-notices/{notice_id}/acknowledge")
    ).status_code == 404
    assert (await mine.get("/api/role-notices/pending")).json() == {"notice": None}
    assert len(await pending_rows(factory, other["id"])) == 1


async def test_a_notice_that_does_not_exist_is_the_same_answer(env):
    new_client, _ = env
    client = new_client()
    await register(client, "Curious")
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.post(f"/api/role-notices/{missing}/acknowledge")
    ).status_code == 404


async def test_a_visitor_without_a_session_is_asked_to_sign_in(env):
    new_client, _ = env
    visitor = new_client()
    # No `GET /api/auth/me` first, so this request carries no session cookie
    # and there is no account for the notice to be about.
    assert (await visitor.get("/api/role-notices/pending")).status_code == 401


async def test_the_payload_builder_shrugs_at_a_user_id_that_is_not_one(env):
    """Belt and braces: the socket push hands it whatever the router had."""
    _, factory = env
    assert await pending_role_notice_payload(factory, "not-a-uuid") == {"notice": None}


async def test_a_deleted_account_leaves_nothing_readable_behind(env):
    """`SET NULL` keeps the row for the ledger's sake; the pending query is by
    account, so it is unreachable rather than orphaned into somebody's view."""
    new_client, factory = env
    client = new_client()
    account = await register(client, "Departing")
    await add_notice(factory, account["id"], UserRole.MODERATOR.value)
    async with factory() as session:
        async with session.begin():
            notice = await session.scalar(select(RoleChangeNotice))
            notice.user_id = None
            user = await session.get(User, UUID(account["id"]))
            user.state = AccountState.DELETED.value

    assert await pending_role_notice_payload(factory, account["id"]) == {"notice": None}

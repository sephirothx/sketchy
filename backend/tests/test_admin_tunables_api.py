"""Changing a runtime value: who may, what is refused, and what is recorded.

The panel's whole justification is that a value affecting how the game feels
can only be settled by looking at a running game, so these endpoints change one
without a deploy. That makes them the first administrative *write* in this
codebase - everything under `/api/admin` until now was a read - so the shape
established here is the one the rest will copy: bounded server-side, persisted,
and audited in the same transaction as the change.
"""
from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.admin_settings import create_admin_settings_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AppConfig, AuditEvent, Base, User
from app.domain_values import AuditTargetType, UserRole
from app.handlers.budgets import CommandBudgetPolicy
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.config_store import read_prefixed
from app.services.tunables import build_runtime_settings


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "tunables-test-secret")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    policy = CommandBudgetPolicy()
    settings = build_runtime_settings(budgets=policy, environ={})

    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(create_admin_settings_router(factory, settings))

    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield new_client, factory, policy, settings
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


async def promote(factory, user_id: str) -> None:
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(user_id))
            user.role = UserRole.ADMIN.value


async def an_admin(env) -> AsyncClient:
    new_client, factory, *_ = env
    client = new_client()
    account = await register(client, "Operator")
    await promote(factory, account["id"])
    return client


async def audit_rows(factory) -> list[AuditEvent]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id)
                )
            ).all()
        )


async def stored_rows(factory) -> dict[str, str]:
    async with factory() as session:
        rows = (await session.scalars(select(AppConfig))).all()
    return {row.key: row.value for row in rows}


# ----------------------------------------------------------------- who may look


async def test_an_ordinary_player_is_told_the_page_does_not_exist(env):
    """R-ROLE-01: 404, never 403.

    Whether this deployment has a tuning surface at all is not something an
    ordinary player should be able to establish by asking.
    """
    new_client, *_ = env
    player = new_client()
    await register(player, "Player")
    assert (await player.get("/api/admin/tunables")).status_code == 404
    response = await player.patch(
        "/api/admin/tunables", json={"values": {"budget.drawing": 200}}
    )
    assert response.status_code == 404


async def test_a_visitor_without_an_account_is_asked_to_sign_in(env):
    new_client, *_ = env
    assert (await new_client().get("/api/admin/tunables")).status_code == 401


async def test_a_refused_change_leaves_the_running_value_alone(env):
    new_client, factory, policy, _ = env
    player = new_client()
    await register(player, "Meddler")
    await player.patch("/api/admin/tunables", json={"values": {"budget.drawing": 400}})
    assert policy.limit_of("drawing") == 100
    assert await stored_rows(factory) == {}


# ------------------------------------------------------------------ what it says


async def test_the_read_describes_each_setting_well_enough_to_draw_a_control(env):
    admin = await an_admin(env)
    body = (await admin.get("/api/admin/tunables")).json()
    drawing = next(
        item for item in body["tunables"] if item["name"] == "budget.drawing"
    )
    assert drawing["value"] == 100
    assert drawing["default"] == 100
    assert (drawing["minimum"], drawing["maximum"]) == (50, 400)
    assert drawing["source"] == "default"
    assert drawing["unit"] == "commands per 2s"
    # The description is what makes the panel legible without the page knowing
    # anything about any particular setting.
    assert "flush timer" in drawing["description"]


async def test_every_key_is_camel_case(env):
    """The wire contract test reads identifiers, so a snake_case key would ship."""
    admin = await an_admin(env)
    body = (await admin.get("/api/admin/tunables")).json()
    for item in body["tunables"]:
        assert not any("_" in key for key in item), item


# ------------------------------------------------------------------- changing


async def test_a_change_takes_effect_immediately_and_is_reported_back(env):
    _, _, policy, _ = env
    admin = await an_admin(env)
    response = await admin.patch(
        "/api/admin/tunables", json={"values": {"budget.drawing": 250}}
    )
    assert response.status_code == 200
    assert policy.limit_of("drawing") == 250
    drawing = next(
        item for item in response.json()["tunables"] if item["name"] == "budget.drawing"
    )
    assert drawing["value"] == 250
    assert drawing["source"] == "stored"


async def test_a_change_survives_a_restart(env):
    """The row is what makes the next process start where this one left off."""
    _, factory, _, _ = env
    admin = await an_admin(env)
    await admin.patch("/api/admin/tunables", json={"values": {"budget.action": 75}})
    assert await stored_rows(factory) == {"tunable.budget.action": "75"}

    successor = build_runtime_settings(budgets=CommandBudgetPolicy(), environ={})
    successor.apply_stored(await read_prefixed(factory, "tunable."))
    assert successor.value("budget.action") == 75


async def test_several_settings_change_in_one_request(env):
    _, _, policy, _ = env
    admin = await an_admin(env)
    await admin.patch(
        "/api/admin/tunables",
        json={"values": {"budget.drawing": 200, "budget.conversation": 40}},
    )
    assert (policy.limit_of("drawing"), policy.limit_of("conversation")) == (200, 40)


async def test_one_bad_value_refuses_the_whole_request(env):
    """All or nothing: a half-applied change leaves a state nobody chose."""
    _, factory, policy, _ = env
    admin = await an_admin(env)
    response = await admin.patch(
        "/api/admin/tunables",
        json={"values": {"budget.drawing": 200, "budget.conversation": 9999}},
    )
    assert response.status_code == 400
    assert "budget.conversation" in response.json()["detail"]
    assert policy.limit_of("drawing") == 100
    assert await stored_rows(factory) == {}
    assert await audit_rows(factory) == []


async def test_a_value_outside_the_bounds_is_refused_with_the_bounds(env):
    admin = await an_admin(env)
    response = await admin.patch(
        "/api/admin/tunables", json={"values": {"budget.drawing": 10}}
    )
    assert response.status_code == 400
    assert "between 50 and 400" in response.json()["detail"]


async def test_an_unknown_setting_is_refused(env):
    admin = await an_admin(env)
    response = await admin.patch(
        "/api/admin/tunables", json={"values": {"budget.telepathy": 5}}
    )
    assert response.status_code == 400
    assert "unknown setting" in response.json()["detail"]


async def test_an_empty_request_is_refused_rather_than_recorded(env):
    _, factory, _, _ = env
    admin = await an_admin(env)
    assert (await admin.patch("/api/admin/tunables", json={})).status_code == 400
    assert await audit_rows(factory) == []


async def test_setting_and_resetting_the_same_thing_is_refused(env):
    admin = await an_admin(env)
    response = await admin.patch(
        "/api/admin/tunables",
        json={"values": {"budget.drawing": 200}, "reset": ["budget.drawing"]},
    )
    assert response.status_code == 400
    assert "budget.drawing" in response.json()["detail"]


# ------------------------------------------------------------------- resetting


async def test_a_reset_puts_the_value_back_and_forgets_the_row(env):
    _, factory, policy, _ = env
    admin = await an_admin(env)
    await admin.patch("/api/admin/tunables", json={"values": {"budget.drawing": 250}})
    await admin.patch("/api/admin/tunables", json={"reset": ["budget.drawing"]})
    assert policy.limit_of("drawing") == 100
    assert await stored_rows(factory) == {}


async def test_setting_a_value_back_to_the_default_stores_nothing(env):
    """A row saying "the default" would pin the setting against a later change."""
    _, factory, _, _ = env
    admin = await an_admin(env)
    await admin.patch("/api/admin/tunables", json={"values": {"budget.drawing": 250}})
    await admin.patch("/api/admin/tunables", json={"values": {"budget.drawing": 100}})
    assert await stored_rows(factory) == {}


# ---------------------------------------------------------------- the record


async def test_every_change_names_the_administrator_the_setting_and_the_move(env):
    _, factory, _, _ = env
    admin = await an_admin(env)
    account = (await admin.get("/api/auth/me")).json()
    await admin.patch("/api/admin/tunables", json={"values": {"budget.resync": 4}})

    (event,) = await audit_rows(factory)
    assert event.event_type == "config.changed"
    assert str(event.actor_user_id) == account["id"]
    assert event.target_type == AuditTargetType.APP_CONFIG.value
    assert event.target_id == "budget.resync"
    assert event.details == {"from": 1, "to": 4}
    # R-AUDIT-01: the request and a hashed address, so one change can be
    # correlated without the address ever being stored.
    assert event.request_id and event.ip_hash


async def test_a_request_that_changes_two_settings_records_two_events(env):
    _, factory, _, _ = env
    admin = await an_admin(env)
    await admin.patch(
        "/api/admin/tunables",
        json={"values": {"budget.drawing": 200, "budget.action": 60}},
    )
    events = await audit_rows(factory)
    assert sorted(event.target_id for event in events) == [
        "budget.action",
        "budget.drawing",
    ]
    # One request, so one correlation id across both rows.
    assert len({event.request_id for event in events}) == 1


async def test_submitting_an_unchanged_value_records_nothing(env):
    """A panel that posts its whole form must not bury the one real change."""
    _, factory, _, _ = env
    admin = await an_admin(env)
    await admin.patch("/api/admin/tunables", json={"values": {"budget.drawing": 250}})
    await admin.patch(
        "/api/admin/tunables",
        json={"values": {"budget.drawing": 250, "budget.action": 60}},
    )
    assert sorted(event.target_id for event in await audit_rows(factory)) == [
        "budget.action",
        "budget.drawing",
    ]

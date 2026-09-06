"""What one authenticated request costs the database, pinned (#556).

`/api/auth/me` runs on every page load. Before #556 it sent five statements
in the steady state: the session, an alias lookup, the user, the user again
for the throttled login touch, and a refresh after it. The counts here are
the contract; a change that adds a round trip has to say so.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, update

from app.api.profiles import create_profile_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import User
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio


def _capture(engine) -> list[str]:
    statements: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split("\n")[0])

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    return statements


async def _site(factory, monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "query-shape-test-secret")
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_profile_router(users, history))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _kinds(statements: list[str]) -> list[str]:
    return [s.split(" ")[0] + ":" + s.split(" ")[2 if s.startswith("SELECT") else 1].split(".")[0].strip("(") for s in statements]


async def test_me_is_two_statements_in_the_steady_state_and_three_when_a_login_is_recorded(
    monkeypatch,
):
    factory, engine = await create_test_db()
    try:
        http = await _site(factory, monkeypatch)
        await http.get("/api/auth/me")
        registered = await http.post(
            "/api/auth/register", json={"username": "Shape", "password": "a-good-password"}
        )
        assert registered.status_code == 200
        statements = _capture(engine)

        statements.clear()
        assert (await http.get("/api/auth/me")).status_code == 200
        steady = list(statements)
        assert len(steady) == 2, steady
        assert steady[0].startswith("SELECT auth_sessions")
        assert steady[1].startswith("SELECT users")

        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User)
                    .where(User.id == UUID(registered.json()["id"]))
                    .values(last_login_at=datetime.now(timezone.utc) - timedelta(days=1))
                )
        statements.clear()
        body = (await http.get("/api/auth/me")).json()
        due = list(statements)
        assert len(due) == 3, due
        assert due[2].startswith("UPDATE users") and "RETURNING" in due[2]
        recorded = datetime.fromisoformat(body["lastLoginAt"])
        assert datetime.now(timezone.utc) - recorded < timedelta(minutes=1)
        await http.aclose()
    finally:
        await engine.dispose()


async def test_the_profile_stats_read_is_bounded_too(monkeypatch):
    factory, engine = await create_test_db()
    try:
        http = await _site(factory, monkeypatch)
        await http.get("/api/auth/me")
        registered = await http.post(
            "/api/auth/register", json={"username": "Stats", "password": "a-good-password"}
        )
        user_id = registered.json()["id"]
        statements = _capture(engine)
        statements.clear()
        response = await http.get(f"/api/users/{user_id}/stats")
        assert response.status_code == 200
        # The session, the account, the alias set the projection is keyed by,
        # and the projection sum: no fact table (R-HIST-20).
        assert len(statements) <= 5, statements
        assert not any("game_participants" in s or "turn_records" in s for s in statements)
        await http.aclose()
    finally:
        await engine.dispose()

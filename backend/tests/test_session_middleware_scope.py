"""The session is resolved where a session means something, and nowhere else (#974)."""
from __future__ import annotations


import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "scope-test-secret")
    factory, engine = await create_test_db()
    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))

    def caller(request: Request) -> dict:
        return {
            "user_id": request.state.user_id,
            "session_id": request.state.session_id,
            "auth_session": request.state.auth_session,
            "banned_user_id": request.state.banned_user_id,
            "client_ip_hash": request.state.client_ip_hash,
        }

    @app.get("/assets/index-abc123.js")
    async def asset(request: Request):
        assert caller(request) == {
            "user_id": None, "session_id": None, "auth_session": None,
            "banned_user_id": None, "client_ip_hash": None,
        }
        return PlainTextResponse("console.log(1)")

    @app.get("/api/whoami")
    async def whoami(request: Request):
        return {"userId": request.state.user_id}

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        yield client, statements
    finally:
        await client.aclose()
        await engine.dispose()


async def test_a_static_file_costs_no_statement_even_with_a_session_cookie(env):
    """The cookie is `Path=/`, so the browser sends it with every asset: each
    one used to resolve the session."""
    client, statements = env
    registered = await client.post(
        "/api/auth/register", json={"username": "ScopeTester", "password": "a-good-password"}
    )
    assert registered.status_code == 200 and client.cookies
    statements.clear()
    for _ in range(3):
        assert (await client.get("/assets/index-abc123.js")).status_code == 200
    assert statements == []
    # The same cookie still resolves where a session means something.
    whoami = await client.get("/api/whoami")
    assert whoami.json()["userId"] == registered.json()["id"]
    assert statements


def test_no_middleware_in_the_application_stack_is_a_base_http_middleware():
    """`BaseHTTPMiddleware` costs ~80 µs of loop time per request here; every
    layer the app installs is plain ASGI."""
    from app.main import api

    offenders = [
        middleware.cls.__name__
        for middleware in api.user_middleware
        if isinstance(middleware.cls, type) and issubclass(middleware.cls, BaseHTTPMiddleware)
    ]
    assert offenders == []


async def test_only_the_api_prefix_itself_resolves_a_session(env):
    """`/api/` with its slash: `/apifoo` and a bare `/api` are not the API."""
    client, statements = env
    registered = await client.post(
        "/api/auth/register", json={"username": "BoundaryTester", "password": "a-good-password"}
    )
    assert registered.status_code == 200
    statements.clear()
    for path in ("/apifoo", "/api", "/apifoo/api/x"):
        await client.get(path)
    assert statements == []

"""The session is resolved where a session means something, and nowhere else (#974)."""
from __future__ import annotations

import asyncio

import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, StreamingResponse

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
    """`BaseHTTPMiddleware` costs ~145 µs of loop time per request and buffers
    a streamed body; every layer the app installs is plain ASGI."""
    from app.main import api

    offenders = [
        middleware.cls.__name__
        for middleware in api.user_middleware
        if isinstance(middleware.cls, type) and issubclass(middleware.cls, BaseHTTPMiddleware)
    ]
    assert offenders == []


async def test_a_streamed_api_response_is_passed_through_as_it_is_produced(monkeypatch):
    """Plain ASGI hands each body chunk on as the route sends it."""
    monkeypatch.setenv("IP_HASH_SECRET", "scope-test-secret")
    factory, engine = await create_test_db()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    produced: list[str] = []

    @app.get("/api/stream")
    async def stream():
        async def chunks():
            for index in range(3):
                produced.append(str(index))
                yield f"{index},"
        return StreamingResponse(chunks(), media_type="text/plain")

    seen_when_sent: list[list[str]] = []

    requested = False
    finished = asyncio.Event()

    async def receive():
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await finished.wait()  # the client stays connected until the end
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            seen_when_sent.append(list(produced))

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": "/api/stream", "raw_path": b"/api/stream",
        "root_path": "", "query_string": b"", "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 1), "server": ("test", 80),
    }
    try:
        await asyncio.wait_for(app(scope, receive, send), timeout=5)
    finally:
        finished.set()
        await engine.dispose()
    # Each chunk left before the next was produced.
    assert seen_when_sent == [["0"], ["0", "1"], ["0", "1", "2"]]

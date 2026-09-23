"""The session is resolved where a session means something, and nowhere else.

R-AUTH-25, #974.
"""
from __future__ import annotations


import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Mount

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
        # The cookie is `Path=/`, so it arrives with every asset; a request
        # that resolves nothing must not carry it on to the route either
        # (#974 fourth review).
        assert request.state.session_token == ""
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


def _layers(root) -> list[tuple[object, str]]:
    """Every ASGI layer reachable from `root`, mounts and unbuilt stacks included.

    A linear walk down `.app` stops at the first router, so a
    `BaseHTTPMiddleware` wrapping a mounted sub-application - or one added to a
    router whose stack this process has not built yet - was invisible to it
    (#974 third review).
    """
    found: list[tuple[object, str]] = []
    seen: set[int] = set()
    pending = [root]
    while pending:
        layer = pending.pop()
        if layer is None or id(layer) in seen:
            continue
        seen.add(id(layer))
        found.append((layer, type(layer).__name__))
        pending.append(getattr(layer, "app", None))
        pending.append(getattr(layer, "other_asgi_app", None))
        pending.append(getattr(layer, "middleware_stack", None))
        for route in getattr(layer, "routes", ()) or ():
            pending.append(getattr(route, "app", None))
            # FastAPI attaches an included router as an `_IncludedRouter`
            # route holding the router itself, so a layer added to one is
            # behind `original_router` and nowhere else (#974 fourth review).
            pending.append(getattr(route, "original_router", None))
        for middleware in getattr(layer, "user_middleware", ()) or ():
            cls = getattr(middleware, "cls", None)
            if isinstance(cls, type):
                found.append((cls, cls.__name__))
    return found


def _base_http_middlewares(root) -> list[str]:
    return [
        name
        for layer, name in _layers(root)
        if isinstance(layer, BaseHTTPMiddleware)
        or (isinstance(layer, type) and issubclass(layer, BaseHTTPMiddleware))
    ]


def test_nothing_in_the_exported_application_is_a_base_http_middleware():
    """Walked from `app.main.app`, the object uvicorn serves - not the bare
    router, which does not contain the layers wrapping it (#974 review).
    `BaseHTTPMiddleware` costs ~80 µs of loop time per request here, on every
    request including the static files this PR stops resolving sessions for.
    """
    from app.main import app

    seen = [name for _layer, name in _layers(app)]
    assert _base_http_middlewares(app) == [], seen
    assert "SecurityHeadersMiddleware" in seen and "ASGIApp" in seen, seen
    assert "SessionAuthMiddleware" in seen, seen


def _wrapped(target):
    return _Probe(target)


def _mounted(target):
    outer = FastAPI()
    outer.mount("/sub", _Probe(target))
    return outer


def _added_to_a_router(target):
    outer = FastAPI()
    outer.add_middleware(_Probe)
    outer.mount("/sub", target)
    return outer


def _inside_an_included_router(target):
    """A layer mounted on a router that is then included - how every router in
    this application is attached, and the shape a linear walk cannot see."""
    from fastapi import APIRouter

    inner = APIRouter()
    inner.routes.append(Mount("/sub", app=_Probe(target)))
    outer = FastAPI()
    outer.include_router(inner)
    return outer


class _Probe(BaseHTTPMiddleware):
    pass


@pytest.mark.parametrize(
    "place", [_wrapped, _mounted, _added_to_a_router, _inside_an_included_router]
)
def test_the_walk_would_see_a_probe_anywhere_in_the_exported_stack(place, monkeypatch):
    """The check above is only worth having if it reaches the layers the bare
    router does not contain: one wrapping the export, one inside a mount, one
    added to a router whose stack has not been built, and one behind an
    included router - which is how every router in this application is
    attached (#974 fourth review)."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "app", place(main_module.app))
    assert _base_http_middlewares(main_module.app) == ["_Probe"]
    with pytest.raises(AssertionError):
        test_nothing_in_the_exported_application_is_a_base_http_middleware()


async def test_a_suspension_is_refused_under_a_prefix_too(monkeypatch):
    """The refusal's own `/api/` test is the one that decides whether a
    suspended account is stopped, and on `request.url.path` it is the raw
    path: under a proxy prefix that reads `/sketchy/api/...`, which is not
    `/api/`, so every suspended account was served (#974 fifth review). The
    hatch tests run on plain paths, where the two are identical, so they
    discriminate nothing here.
    """
    import app.auth.middleware as middleware_module
    from app.auth.sessions import SessionResolution

    monkeypatch.setenv("IP_HASH_SECRET", "prefix-suspension-secret")
    factory, engine = await create_test_db()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)

    @app.get("/api/whoami")
    async def whoami(request: Request):
        return {"userId": request.state.user_id}

    async def suspended(*_args, **_kwargs):
        return SessionResolution(session=None, banned_user_id="banned-account")

    async def payload(*_args, **_kwargs):
        return {"reason": "suspended"}

    monkeypatch.setattr(middleware_module, "resolve_session_status", suspended)
    monkeypatch.setattr(middleware_module, "suspension_payload", payload)

    client = AsyncClient(
        transport=ASGITransport(app=app, root_path="/sketchy"), base_url="http://test"
    )
    try:
        assert (await client.get("/sketchy/api/whoami")).status_code == 403
    finally:
        await client.aclose()
        await engine.dispose()


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


async def test_a_prefix_deployment_still_resolves_its_api(monkeypatch):
    """Behind a proxy that serves Sketchy under a prefix, uvicorn's
    `--root-path` leaves the prefix on the raw path. Gating on that path would
    let every `/api/` request past unresolved: no session, no suspension, and
    the routes would still route (#974 third review)."""
    monkeypatch.setenv("IP_HASH_SECRET", "prefix-test-secret")
    factory, engine = await create_test_db()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))

    @app.get("/api/whoami")
    async def whoami(request: Request):
        return {"userId": request.state.user_id}

    transport = ASGITransport(app=app, root_path="/sketchy")
    client = AsyncClient(transport=transport, base_url="http://test")
    try:
        registered = await client.post(
            "/sketchy/api/auth/register",
            json={"username": "PrefixTester", "password": "a-good-password"},
        )
        assert registered.status_code == 200
        answer = await client.get("/sketchy/api/whoami")
        assert answer.json()["userId"] == registered.json()["id"]
    finally:
        await client.aclose()
        await engine.dispose()


async def test_a_suspension_is_refused_on_a_path_holding_an_encoded_question_mark(env, monkeypatch):
    """The escape hatches are matched on the path the gate resolved, not on
    `request.url.path`, which is re-parsed from a rebuilt URL and comes back
    cut at the first `?` - including one that arrived percent-encoded. Cut,
    `/api/auth/account%3Fx` reads as the account route and a suspended caller
    is let through it (#974 third review)."""
    import app.auth.middleware as middleware_module
    from app.auth.sessions import SessionResolution

    client, _statements = env

    async def suspended(*_args, **_kwargs):
        return SessionResolution(session=None, banned_user_id="banned-account")

    async def payload(*_args, **_kwargs):
        return {"reason": "suspended"}

    monkeypatch.setattr(middleware_module, "resolve_session_status", suspended)
    monkeypatch.setattr(middleware_module, "suspension_payload", payload)

    assert (await client.get("/api/whoami")).status_code == 403
    # The hatches matched whole: cut at a decoded `?`, a path that only looks
    # like one let a suspended caller through it.
    for path in ("/api/auth/account", "/api/auth/logout"):
        assert (await client.get(f"{path}%3Fx")).status_code == 403, path
        assert (await client.get(path)).status_code != 403, path
    # And the ones matched by prefix, which any suffix belongs to.
    for path in ("/api/auth/data-exports", "/api/suspension/drawings/whatever"):
        assert (await client.get(path)).status_code != 403, path
    assert (await client.delete("/api/auth/account")).status_code != 403

"""Every request counted, by the route it matched and not the path it carried."""
from __future__ import annotations

import logging
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from httpx import ASGITransport, AsyncClient
from starlette.middleware.gzip import GZipMiddleware

from app import correlation
from app.request_limits import RequestSizeLimitMiddleware
from app.request_timing import RequestTimingMiddleware
from app.services.telemetry import STATIC_ROUTE, UNROUTED_ROUTE, Telemetry


pytestmark = pytest.mark.asyncio


@pytest.fixture
def env(tmp_path):
    """An app stacked the way `main.py` stacks it: timing outermost, gzip inside."""
    store = Telemetry()
    app = FastAPI()

    @app.get("/api/things/{thing_id}")
    async def thing(thing_id: str):
        return {"id": thing_id, "padding": "x" * 2000}

    @app.get("/api/broken")
    async def broken():
        raise RuntimeError("boom")

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.mount("/", StaticFiles(directory=str(tmp_path)), name="frontend")
    app.add_middleware(RequestTimingMiddleware, telemetry=store)
    return app, store


def client(app, *, raise_app_exceptions: bool = True) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
        base_url="http://test",
    )


async def test_the_label_is_the_route_template_not_the_path(env):
    app, store = env
    async with client(app) as http:
        for thing_id in ("42", "43", "a-name"):
            assert (await http.get(f"/api/things/{thing_id}")).status_code == 200

    assert store.http_requests.get(("GET", "/api/things/{thing_id}", "2xx")) == 3
    assert store.http_requests.get(("GET", "/api/things/42", "2xx")) == 0
    assert store.http_duration.count() == 3
    assert store.in_flight == 0


async def test_a_raised_exception_is_counted_as_a_server_error_and_still_raised(env):
    app, store = env
    async with client(app, raise_app_exceptions=False) as http:
        response = await http.get("/api/broken")
    assert response.status_code == 500
    assert store.http_requests.get(("GET", "/api/broken", "5xx")) == 1
    assert store.in_flight == 0

    with pytest.raises(RuntimeError):
        async with client(app) as http:
            await http.get("/api/broken")
    assert store.http_requests.get(("GET", "/api/broken", "5xx")) == 2
    assert store.in_flight == 0


async def test_probes_are_counted_but_not_timed(env):
    app, store = env
    async with client(app) as http:
        assert (await http.get("/api/health")).status_code == 200
    assert store.http_requests.get(("GET", "/api/health", "2xx")) == 1
    assert store.http_duration.count() == 0


async def test_static_files_and_misses_fall_into_two_fixed_labels(env):
    app, store = env
    async with client(app) as http:
        assert (await http.get("/assets/app.js")).status_code == 200
        assert (await http.get("/no/such/page")).status_code == 404
        assert (await http.get("/api/no/such/route")).status_code == 404
    assert store.http_requests.get(("GET", STATIC_ROUTE, "2xx")) == 1
    assert store.http_requests.get(("GET", UNROUTED_ROUTE, "4xx")) == 2
    # And no series per missing path, which is what a scanner would produce.
    assert len(store.http_requests.items()) == 2


async def test_a_compressed_response_is_timed_as_a_whole(env):
    app, store = env
    async with client(app) as http:
        response = await http.get(
            "/api/things/1", headers={"accept-encoding": "gzip"}
        )
    assert response.headers.get("content-encoding") == "gzip"
    assert store.http_requests.get(("GET", "/api/things/{thing_id}", "2xx")) == 1


# --- identity ------------------------------------------------------------------


async def test_a_request_id_is_minted_echoed_and_logged(env, caplog):
    app, store = env
    caplog.set_level(logging.INFO, logger="sketchy.http")
    async with client(app) as http:
        response = await http.get("/api/things/7")
    minted = response.headers["x-request-id"]
    assert str(UUID(minted)) == minted
    line = next(rec for rec in caplog.records if rec.name == "sketchy.http")
    assert line.request_id == minted
    assert line.fields["route"] == "/api/things/{thing_id}"
    assert line.fields["status"] == 200
    assert line.levelno == logging.INFO
    # Gone again once the request is over: the next thing logged is not ours.
    assert correlation.request_id.get() is None


async def test_a_supplied_uuid_is_kept_and_anything_else_is_replaced(env):
    app, _ = env
    given = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    async with client(app) as http:
        kept = await http.get("/api/things/1", headers={"x-request-id": given})
        replaced = await http.get("/api/things/1", headers={"x-request-id": "<script>"})
    assert kept.headers["x-request-id"] == given
    assert replaced.headers["x-request-id"] != "<script>"
    assert str(UUID(replaced.headers["x-request-id"]))


async def test_probes_and_static_files_are_logged_quietly(env, caplog):
    app, _ = env
    caplog.set_level(logging.DEBUG, logger="sketchy.http")
    async with client(app) as http:
        await http.get("/api/health")
        await http.get("/assets/app.js")
        await http.get("/api/things/1")
    levels = {rec.fields["route"]: rec.levelno for rec in caplog.records if rec.name == "sketchy.http"}
    assert levels["/api/health"] == logging.DEBUG
    assert levels["static"] == logging.DEBUG
    assert levels["/api/things/{thing_id}"] == logging.INFO


async def test_a_handler_sees_the_request_id_it_will_be_logged_under(tmp_path):
    seen: dict[str, str | None] = {}
    app = FastAPI()

    @app.get("/api/whoami")
    async def whoami():
        seen["id"] = correlation.request_id.get()
        return {"ok": True}

    app.add_middleware(RequestTimingMiddleware, telemetry=Telemetry())
    async with client(app) as http:
        response = await http.get("/api/whoami")
    assert seen["id"] == response.headers["x-request-id"]

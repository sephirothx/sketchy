"""The ceiling on request bodies, and that it holds before anything reads one."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.request_limits import (
    BUG_REPORT_MAX_BODY_BYTES,
    DEFAULT_MAX_BODY_BYTES,
    RequestSizeLimitMiddleware,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture
def env():
    """An app that records whether the handler was reached, and with what."""
    seen: dict = {"calls": 0, "body_bytes": None}
    app = FastAPI()

    @app.post("/api/anything")
    async def anything(request: Request):
        seen["calls"] += 1
        body = await request.body()
        seen["body_bytes"] = len(body)
        return {"read": len(body)}

    @app.post("/api/bug-reports")
    async def bug_reports(request: Request):
        seen["calls"] += 1
        body = await request.body()
        seen["body_bytes"] = len(body)
        return {"read": len(body)}

    app.add_middleware(RequestSizeLimitMiddleware)
    return app, seen


def client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_an_ordinary_body_passes_untouched(env):
    app, seen = env
    async with client(app) as http:
        response = await http.post("/api/anything", json={"note": "x" * 1000})
    assert response.status_code == 200
    assert seen["calls"] == 1
    # Whole and unmodified: the guard counts, it does not trim what fits.
    assert seen["body_bytes"] > 1000
    assert response.json()["read"] == seen["body_bytes"]


async def test_an_oversized_body_is_refused_before_the_handler_runs(env):
    """The point of the limit: nothing downstream is invoked at all.

    Not routing, not the session lookup, not the handler - so an oversized
    request costs a header parse rather than its own size in memory.
    """
    app, seen = env
    async with client(app) as http:
        response = await http.post(
            "/api/anything", content=b"x" * (DEFAULT_MAX_BODY_BYTES + 1)
        )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]
    assert seen["calls"] == 0


async def test_the_bug_report_route_is_allowed_its_screenshot(env):
    """A route that legitimately carries megabytes says so by name."""
    app, seen = env
    generous = b"x" * (DEFAULT_MAX_BODY_BYTES * 4)
    async with client(app) as http:
        allowed = await http.post("/api/bug-reports", content=generous)
        refused = await http.post("/api/anything", content=generous)
    assert allowed.status_code == 200
    assert refused.status_code == 413
    assert seen["calls"] == 1


async def test_even_the_generous_route_has_a_ceiling(env):
    app, _ = env
    async with client(app) as http:
        response = await http.post(
            "/api/bug-reports", content=b"x" * (BUG_REPORT_MAX_BODY_BYTES + 1)
        )
    assert response.status_code == 413


async def test_a_body_that_lies_about_its_length_is_still_cut_off(env):
    """No Content-Length, or a false one, must not buy unbounded memory.

    The handler sees a truncated body rather than a tidy refusal - by the time
    the bytes are streaming the response belongs to the application - but the
    memory is bounded, which is the part that matters.
    """
    app, seen = env
    oversized = DEFAULT_MAX_BODY_BYTES * 3

    async def chunks():
        for _ in range(oversized // 4096):
            yield b"x" * 4096

    async with client(app) as http:
        # An async iterable body makes httpx use chunked encoding, so there is
        # no length for the cheap check to catch.
        await http.post("/api/anything", content=chunks())

    assert seen["calls"] == 1
    assert seen["body_bytes"] is not None
    assert seen["body_bytes"] <= DEFAULT_MAX_BODY_BYTES, seen["body_bytes"]


async def test_the_default_covers_the_largest_body_the_api_accepts():
    """The transport limit is tied to the domain limits, not to a guess.

    The biggest declared payload is a prompt list: 500 prompts, each with a
    bounded answer and up to 20 aliases. If somebody raises one of those caps,
    this fails here rather than as a save that silently stops working.
    """
    from app.prompt_content import MAX_PROMPT_LENGTH
    from app.repositories.sqlalchemy import MAX_PROMPTS_PER_OWNED_LIST

    # Per prompt: a concept id, the answer, twenty aliases, and the JSON
    # punctuation around them, generously rounded up.
    per_prompt = 36 + MAX_PROMPT_LENGTH + 20 * (MAX_PROMPT_LENGTH + 4) + 80
    worst_case = MAX_PROMPTS_PER_OWNED_LIST * per_prompt + 1024

    assert DEFAULT_MAX_BODY_BYTES > worst_case, (
        f"the default body limit ({DEFAULT_MAX_BODY_BYTES}) no longer covers a "
        f"full prompt list ({worst_case}); raise it or lower the prompt caps"
    )


async def test_a_malformed_length_falls_through_to_the_streaming_count(env):
    app, seen = env
    async with client(app) as http:
        response = await http.post(
            "/api/anything",
            content=b"x" * (DEFAULT_MAX_BODY_BYTES + 10),
            headers={"content-length": "not-a-number"},
        )
    # However it is answered, it did not get to hold more than the cap.
    assert seen["body_bytes"] is None or seen["body_bytes"] <= DEFAULT_MAX_BODY_BYTES
    assert response.status_code in {200, 400, 413, 422}

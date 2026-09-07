"""Browser hardening headers, and production's refusal of plain HTTP (#467)."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.security_headers import (
    HSTS_MAX_AGE_SECONDS,
    HTTPS_EXEMPT_PATHS,
    HeaderPolicy,
    HttpsOnly,
    HttpsOnlyMiddleware,
    SecurityHeadersMiddleware,
    inline_script_hashes,
    public_origin,
)


def _directives(policy: str) -> dict[str, str]:
    pairs = (part.strip().split(" ", 1) for part in policy.split(";"))
    return {name: (rest[0] if rest else "") for name, *rest in pairs}


def test_the_inline_scripts_of_the_built_shell_are_admitted_by_hash(tmp_path: Path):
    """The pre-paint theme script is the one inline script the page has; it
    is hashed exactly as written, and an external script is not an inline one."""
    body = '\n      try { document.documentElement.dataset.theme = "dark"; } catch (e) {}\n    '
    shell = tmp_path / "index.html"
    shell.write_text(
        f"<html><head><script>{body}</script>"
        '<script type="module" crossorigin src="/assets/index-abc123.js"></script>'
        "</head><body></body></html>",
        encoding="utf-8",
    )
    expected = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    assert inline_script_hashes(shell) == (f"'sha256-{expected}'",)
    assert inline_script_hashes(tmp_path / "missing.html") == (), "no build, no inline script"


def test_the_policy_is_one_same_origin_bundle_with_the_socket_named():
    policy = HeaderPolicy(script_hashes=("'sha256-abc'",))
    directives = _directives(policy.content_security_policy(host="play.example.com"))
    assert directives["default-src"] == "'self'"
    assert directives["script-src"] == "'self' 'sha256-abc'"
    assert directives["style-src"] == "'self'"
    assert directives["img-src"] == "'self' data: blob:"
    assert directives["font-src"] == "'self' data:", "the built stylesheet inlines the typefaces"
    assert directives["connect-src"] == "'self' wss://play.example.com ws://play.example.com"
    assert directives["frame-ancestors"] == "'none'"
    assert directives["object-src"] == "'none'"
    assert directives["base-uri"] == "'none'"
    assert directives["form-action"] == "'self'"
    # A Host that is not a host is left out rather than written into a header.
    bare = _directives(policy.content_security_policy(host="evil host; script-src *"))
    assert bare["connect-src"] == "'self'"
    assert _directives(policy.content_security_policy(host=None))["connect-src"] == "'self'"


def test_strict_transport_security_is_production_only_and_resource_policy_follows_the_origins():
    names = lambda policy: {name for name, _ in policy.headers(host=None)}  # noqa: E731
    assert b"strict-transport-security" not in names(HeaderPolicy())
    hardened = dict(HeaderPolicy(strict_transport_security=True).headers(host=None))
    assert hardened[b"strict-transport-security"] == f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains".encode()
    assert dict(HeaderPolicy().headers(host=None))[b"cross-origin-resource-policy"] == b"same-origin"
    assert dict(HeaderPolicy(cross_origin_resources=True).headers(host=None))[b"cross-origin-resource-policy"] == b"cross-origin"


@pytest.mark.asyncio
async def test_every_response_carries_the_headers_and_a_route_may_override_one():
    api = FastAPI()

    @api.get("/api/thing")
    async def thing():
        return {"ok": True}

    @api.get("/api/framed")
    async def framed():
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": True}, headers={"X-Frame-Options": "SAMEORIGIN"})

    app = SecurityHeadersMiddleware(api, policy=HeaderPolicy(script_hashes=("'sha256-abc'",)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/api/thing")
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "same-origin"
        assert response.headers["cross-origin-opener-policy"] == "same-origin"
        assert "camera=()" in response.headers["permissions-policy"]
        assert "strict-transport-security" not in response.headers
        directives = _directives(response.headers["content-security-policy"])
        assert directives["script-src"] == "'self' 'sha256-abc'"
        assert directives["connect-src"] == "'self' wss://test ws://test"
        missing = await http.get("/api/nothing-here")
        assert missing.status_code == 404 and missing.headers["x-frame-options"] == "DENY"
        overridden = await http.get("/api/framed")
        assert overridden.headers["x-frame-options"] == "SAMEORIGIN"
        assert overridden.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_the_real_application_sends_the_headers_and_no_hsts_outside_production():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        health = await http.get("/api/health")
        assert health.status_code == 200
        assert "content-security-policy" in health.headers
        assert health.headers["x-content-type-options"] == "nosniff"
        assert "strict-transport-security" not in health.headers
        # The Socket.IO mount is inside the wrapper too.
        handshake = await http.get("/socket.io/?EIO=4&transport=polling")
        assert handshake.status_code == 200
        assert handshake.headers["x-frame-options"] == "DENY"


def test_the_rule_applies_to_plain_requests_in_production_only_and_spares_the_probes():
    rule = HttpsOnly(enabled=True, public_origin="https://sketchy.example")
    assert rule.applies({"type": "http", "scheme": "http", "path": "/"})
    assert rule.applies({"type": "websocket", "scheme": "ws", "path": "/socket.io/"})
    assert not rule.applies({"type": "http", "scheme": "https", "path": "/"})
    assert not rule.applies({"type": "websocket", "scheme": "wss", "path": "/socket.io/"})
    assert not rule.applies({"type": "lifespan"})
    for path in HTTPS_EXEMPT_PATHS:
        assert not rule.applies({"type": "http", "scheme": "http", "path": path}), path
    assert not HttpsOnly(enabled=False, public_origin="https://sketchy.example").applies(
        {"type": "http", "scheme": "http", "path": "/"}
    )


def test_the_redirect_goes_to_the_canonical_origin_keeping_path_and_query():
    rule = HttpsOnly(enabled=True, public_origin="https://sketchy.example")
    assert rule.location({"path": "/room/ABC123", "raw_path": b"/room/ABC123", "query_string": b"a=1&b=2"}) == (
        "https://sketchy.example/room/ABC123?a=1&b=2"
    )
    # Percent-encoding survives (raw_path), and is re-applied in its absence.
    assert rule.location({"path": "/r/é", "raw_path": b"/r/%C3%A9", "query_string": b""}) == "https://sketchy.example/r/%C3%A9"
    assert rule.location({"path": "/r/é", "query_string": b""}) == "https://sketchy.example/r/%C3%A9"
    assert public_origin("https://sketchy.example/") == "https://sketchy.example"
    assert public_origin("https://sketchy.example:8443") == "https://sketchy.example:8443"


@pytest.mark.asyncio
async def test_a_plain_request_is_sent_to_https_with_its_method_kept_and_a_probe_is_answered():
    api = FastAPI()
    seen: list[str] = []

    @api.get("/api/health")
    async def health():
        return {"ok": True}

    @api.post("/api/thing")
    async def thing():
        seen.append("made")
        return {"ok": True}

    app = HttpsOnlyMiddleware(api, rule=HttpsOnly(enabled=True, public_origin="https://sketchy.example"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        moved = await http.post("/api/thing?x=1")
        assert moved.status_code == 308
        assert moved.headers["location"] == "https://sketchy.example/api/thing?x=1"
        assert (await http.get("/api/health")).status_code == 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as http:
        assert (await http.post("/api/thing")).status_code == 200
    assert seen == ["made"], "the plain POST never reached the route"


@pytest.mark.asyncio
async def test_a_plain_websocket_handshake_is_closed_before_it_is_accepted():
    accepted: list[str] = []

    async def inner(scope, receive, send):
        accepted.append(scope["type"])
        await send({"type": "websocket.accept"})

    app = HttpsOnlyMiddleware(inner, rule=HttpsOnly(enabled=True, public_origin="https://sketchy.example"))
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "websocket.connect"}

    await app({"type": "websocket", "scheme": "ws", "path": "/socket.io/"}, receive, send)
    assert sent == [{"type": "websocket.close"}]
    await app({"type": "websocket", "scheme": "wss", "path": "/socket.io/"}, receive, send)
    assert accepted == ["websocket"] and sent[-1] == {"type": "websocket.accept"}

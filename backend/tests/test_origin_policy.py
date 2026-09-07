"""Which origins may act as a signed-in browser (#465)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.origin_policy import (
    OriginPolicyMiddleware,
    configured_origins,
    normalize_origin,
    origin_allowed,
    request_origin_allowed,
    socket_origins,
)


def test_origins_are_normalized_and_the_configured_list_is_parsed():
    assert normalize_origin("HTTPS://Play.Example.com:8443/") == "https://play.example.com:8443"
    assert normalize_origin("wss://play.example.com") == "https://play.example.com"
    assert normalize_origin("null") is None
    assert normalize_origin("javascript:alert(1)") is None
    assert normalize_origin("") is None
    assert configured_origins({"ALLOWED_ORIGINS": " https://a.example , http://b.example:3000,,"}) == frozenset(
        {"https://a.example", "http://b.example:3000"}
    )
    assert configured_origins({}) == frozenset()


def test_the_serving_origin_is_always_allowed_and_a_stranger_never():
    assert origin_allowed("https://play.example.com", scheme="https", host="play.example.com", extra=frozenset())
    assert origin_allowed("http://localhost:8000", scheme="http", host="localhost:8000", extra=frozenset())
    assert not origin_allowed("https://evil.example", scheme="https", host="play.example.com", extra=frozenset())
    assert not origin_allowed("https://play.example.com.evil.example", scheme="https", host="play.example.com", extra=frozenset())
    assert origin_allowed("https://app.example", scheme="https", host="api.example", extra=frozenset({"https://app.example"}))
    # Behind a TLS-terminating proxy not named in FORWARDED_ALLOW_IPS the
    # scope stays plain while the browser says https: the same host is ours,
    # for a REST request exactly as for a handshake.
    assert origin_allowed("https://play.example.com", scheme="http", host="play.example.com", extra=frozenset())
    assert not origin_allowed("http://play.example.com", scheme="https", host="play.example.com", extra=frozenset()), "the other way round is a downgrade, not ours"
    assert request_origin_allowed(method="POST", origin="https://play.example.com", referer=None, scheme="http", host="play.example.com", extra=frozenset())


@pytest.mark.parametrize(
    "method,origin,referer,allowed",
    [
        ("GET", "https://evil.example", None, True),  # safe methods are never judged
        ("POST", "https://play.example.com", None, True),
        ("POST", "https://evil.example", None, False),
        ("POST", None, "https://play.example.com/room/ABC", True),
        ("POST", None, "https://evil.example/page", False),
        ("POST", None, None, True),  # a non-browser client; it cannot carry a victim's cookie
        ("POST", "null", None, False),  # an opaque origin is not this page
        ("DELETE", "https://evil.example", None, False),
    ],
)
def test_the_rule_for_one_request(method, origin, referer, allowed):
    assert request_origin_allowed(
        method=method, origin=origin, referer=referer, scheme="https", host="play.example.com", extra=frozenset()
    ) is allowed


@pytest.mark.asyncio
async def test_the_middleware_refuses_a_foreign_unsafe_request_before_anything_else():
    app = FastAPI()
    seen: list[str] = []

    @app.post("/api/thing")
    async def make_thing():
        seen.append("made")
        return {"ok": True}

    @app.get("/api/thing")
    async def read_thing():
        return {"ok": True}

    app.add_middleware(OriginPolicyMiddleware, extra=frozenset({"https://app.example"}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.post("/api/thing", headers={"Origin": "http://test"})).status_code == 200
        assert (await http.post("/api/thing", headers={"Origin": "https://app.example"})).status_code == 200
        assert (await http.post("/api/thing")).status_code == 200, "a non-browser client"
        refused = await http.post("/api/thing", headers={"Origin": "https://evil.example"})
        assert refused.status_code == 403
        assert refused.json() == {"detail": "This request did not come from Sketchy."}
        assert (await http.post("/api/thing", headers={"Referer": "https://evil.example/x"})).status_code == 403
        assert (await http.get("/api/thing", headers={"Origin": "https://evil.example"})).status_code == 200
    assert seen == ["made", "made", "made"]


def test_the_socket_handshake_admits_the_serving_origin_and_the_configured_ones_only():
    allowed = socket_origins(frozenset({"https://app.example"}))
    served = {"wsgi.url_scheme": "https", "HTTP_HOST": "play.example.com"}
    assert allowed("https://play.example.com", served) is True
    assert allowed("https://app.example", served) is True
    assert allowed("https://evil.example", served) is False
    assert allowed("https://play.example.com.evil.example", served) is False
    assert allowed("null", served) is False
    # A plain scheme behind a proxy that was not trusted to say otherwise:
    # the browser's https spelling of the same host is this server's.
    plain = {"wsgi.url_scheme": "http", "HTTP_HOST": "play.example.com"}
    assert allowed("https://play.example.com", plain) is True
    assert allowed("http://play.example.com", plain) is True
    assert allowed("https://evil.example", plain) is False


@pytest.mark.asyncio
async def test_the_real_socket_server_refuses_a_foreign_origin_and_admits_its_own():
    """Through the ASGI app itself: Engine.IO answers a handshake whose
    Origin is another site with 400 and never opens a session."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        refused = await http.get("/socket.io/?EIO=4&transport=polling", headers={"Origin": "https://evil.example"})
        assert refused.status_code == 400
        assert b"not an accepted origin" in refused.content
        opened = await http.get("/socket.io/?EIO=4&transport=polling", headers={"Origin": "http://test"})
        assert opened.status_code == 200 and opened.text.startswith("0{")
        bare = await http.get("/socket.io/?EIO=4&transport=polling")
        assert bare.status_code == 200, "a non-browser client sends no Origin"

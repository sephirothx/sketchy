"""What "one address" means to every per-address limit (#1233).

Every home line and every VPS is handed at least an IPv6 /64, and a host may
answer from any address in it. Keyed on the full address, each of those is a
fresh bucket - so the /64 is the key, and an IPv4-mapped address is the IPv4
address it carries.
"""
from __future__ import annotations

import contextlib

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.middleware import SessionAuthMiddleware
from app.auth.rate_limit import address_key
from app.auth.routes import create_auth_router
from app.repositories.sqlalchemy import SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db

PASSWORD = "correct horse battery staple"


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("2001:db8::1", "2001:db8::/64"),
        ("2001:db8::ffff:1:2", "2001:db8::/64"),
        ("2001:db8:0:0:8000::9", "2001:db8::/64"),
        ("2001:db8:0:1::1", "2001:db8:0:1::/64"),
        ("::ffff:192.0.2.1", "192.0.2.1"),
        ("192.0.2.1", "192.0.2.1"),
        # A scope names an interface on this host, not another caller.
        ("fe80::1%eth0", "fe80::/64"),
        ("testclient", "testclient"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_an_address_keys_as_its_subscriber(host, key):
    assert address_key(host) == key


@contextlib.asynccontextmanager
async def build_site(monkeypatch, **limits):
    for name, value in limits.items():
        monkeypatch.setenv(name, str(value))
    factory, engine = await create_test_db()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    clients: list[AsyncClient] = []

    def from_address(host: str) -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app, client=(host, 40000)),
            base_url="http://test",
        )
        clients.append(client)
        return client

    try:
        yield from_address
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


# Two addresses one subscriber could pick between, and a neighbour's.
SAME_64 = ("2001:db8:1:2::10", "2001:db8:1:2:ffff:ffff:ffff:ffff")
NEIGHBOUR = "2001:db8:1:3::10"


async def test_guest_provisioning_holds_across_a_64(monkeypatch):
    async with build_site(monkeypatch, GUEST_PROVISION_LIMIT=2) as from_address:
        first, second = (from_address(host) for host in SAME_64)
        codes = [
            (await first.post("/api/auth/display-name", json={"displayName": "Hop1"})).status_code,
            (await second.post("/api/auth/display-name", json={"displayName": "Hop2"})).status_code,
            (await from_address(SAME_64[1]).post(
                "/api/auth/display-name", json={"displayName": "Hop3"}
            )).status_code,
        ]
        assert codes == [200, 200, 429]

        neighbour = await from_address(NEIGHBOUR).post(
            "/api/auth/display-name", json={"displayName": "Next1"}
        )
        assert neighbour.status_code == 200, "the next /64 is somebody else"


async def test_registration_holds_across_a_64(monkeypatch):
    async with build_site(monkeypatch, AUTH_REGISTER_LIMIT=1) as from_address:
        first = await from_address(SAME_64[0]).post(
            "/api/auth/register", json={"username": "Hopper1", "password": PASSWORD}
        )
        second = await from_address(SAME_64[1]).post(
            "/api/auth/register", json={"username": "Hopper2", "password": PASSWORD}
        )
        neighbour = await from_address(NEIGHBOUR).post(
            "/api/auth/register", json={"username": "Hopper3", "password": PASSWORD}
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 429
        assert neighbour.status_code == 200, neighbour.text


async def test_forgot_password_holds_across_a_64(monkeypatch):
    async with build_site(monkeypatch, AUTH_RESET_LIMIT=1) as from_address:
        body = {"identifier": "Nobody"}
        first = await from_address(SAME_64[0]).post("/api/auth/password/forgot", json=body)
        second = await from_address(SAME_64[1]).post("/api/auth/password/forgot", json=body)
        neighbour = await from_address(NEIGHBOUR).post("/api/auth/password/forgot", json=body)

        assert first.status_code == 200
        assert second.status_code == 429
        assert neighbour.status_code == 200


async def test_an_ipv4_caller_is_one_caller_on_either_listener(monkeypatch):
    """A dual-stack socket reports an IPv4 peer as `::ffff:a.b.c.d`; the same
    caller must not get a second bucket from the other listener."""
    async with build_site(monkeypatch, GUEST_PROVISION_LIMIT=1) as from_address:
        plain = await from_address("192.0.2.40").post(
            "/api/auth/display-name", json={"displayName": "Dual1"}
        )
        mapped = await from_address("::ffff:192.0.2.40").post(
            "/api/auth/display-name", json={"displayName": "Dual2"}
        )

        assert plain.status_code == 200
        assert mapped.status_code == 429

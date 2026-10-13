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
from app.auth.rate_limit import address_key, prefix_key
from app.auth.routes import create_auth_router
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.telemetry import telemetry

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


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("2001:db8:1:2::10", "2001:db8:1::/48"),
        ("2001:db8:1:ffff:ffff::1", "2001:db8:1::/48"),
        ("2001:db8:2::1", "2001:db8:2::/48"),
        ("192.0.2.77", "192.0.2.0/24"),
        ("::ffff:192.0.2.77", "192.0.2.0/24"),
        ("fe80::1%eth0", "fe80::/48"),
        ("testclient", "testclient"),
        (None, "unknown"),
    ],
)
def test_an_address_keys_as_its_network(host, key):
    """The few limits that bound a site rather than a subscriber (#1418)."""
    assert prefix_key(host) == key


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

    # For a test that reads what the routes wrote.
    from_address.factory = factory
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


async def test_one_network_cannot_spend_the_whole_day_of_guests(monkeypatch):
    """#1418: 90 /64s under one routed /48, 60 guests each, spent the
    deployment's day in 34 s and closed the door on everybody. Each /64 is a
    fresh address bucket; the /48 is not."""
    async with build_site(
        monkeypatch,
        GUEST_PROVISION_LIMIT=10,
        GUEST_PROVISION_PREFIX_DAILY_LIMIT=2,
        GUEST_PROVISION_DAILY_LIMIT=100,
    ) as from_address:
        before = telemetry.capacity_refusals.get(("guests_per_prefix",))
        codes = [
            (await from_address(f"2001:db8:1:{subnet}::10").post(
                "/api/auth/display-name", json={"displayName": f"Site{subnet}"}
            )).status_code
            for subnet in (1, 2, 3)
        ]
        elsewhere = await from_address("2001:db8:2::10").post(
            "/api/auth/display-name", json={"displayName": "Elsewhere"}
        )
        assert codes == [200, 200, 429]
        assert elsewhere.status_code == 200
        assert telemetry.capacity_refusals.get(("guests_per_prefix",)) == before + 1


async def test_the_day_turning_visitors_away_is_counted_for_the_page(monkeypatch):
    """The only trace was a WARNING line and a 429 that reads like a rejected
    name (#1418). The counter is what SketchyTurningVisitorsAway reads, and a
    refusal by the day gives the network's share back."""
    async with build_site(
        monkeypatch, GUEST_PROVISION_LIMIT=10, GUEST_PROVISION_DAILY_LIMIT=1
    ) as from_address:
        before = telemetry.capacity_refusals.get(("guests_per_day",))
        first = await from_address("192.0.2.1").post("/api/auth/display-name", json={"displayName": "Early"})
        late = await from_address("192.0.2.2").post("/api/auth/display-name", json={"displayName": "Late"})
        assert (first.status_code, late.status_code) == (200, 429)
        assert "not taking new visitors" in late.json()["detail"]
        assert telemetry.capacity_refusals.get(("guests_per_day",)) == before + 1
        from sqlalchemy import func, select
        from app.db.models import AuthRateLimitBucket

        async with from_address.factory() as session:
            spent = await session.scalar(
                select(func.sum(AuthRateLimitBucket.attempt_count)).where(
                    AuthRateLimitBucket.scope == "guest_provision_prefix_day"
                )
            )
        assert spent == 1

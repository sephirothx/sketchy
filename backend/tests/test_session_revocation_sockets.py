"""A revocation reaches the sockets the revoked sessions opened (#1007)."""
from __future__ import annotations

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from tests.dbfixtures import create_test_db
from tests.test_account_socket_sweep import FakeServer

PASSWORD = "marmalade-frog-lantern"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "revocation-test-secret")
    factory, engine = await create_test_db()
    revoked: list[tuple[str, list[str] | None, str | None]] = []

    async def record(
        user_id: str, session_ids: list[str] | None, keep: str | None
    ) -> None:
        revoked.append((user_id, session_ids, keep))

    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(
        create_auth_router(SqlAlchemyUserRepository(factory), factory, on_sessions_revoked=record)
    )
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield new_client, factory, revoked
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_signing_out_everywhere_closes_every_socket_of_the_account(env):
    new_client, _, revoked = env
    browser = new_client()
    account = await register(browser, "Everywhere")
    assert (await browser.post("/api/auth/logout-all")).status_code == 200
    assert revoked == [(account["id"], None, None)]


async def test_signing_out_closes_the_sockets_of_that_session_alone(env):
    """Another tab of the same browser shares the session, and its socket is
    signed out with it; the other devices play on."""
    new_client, _, revoked = env
    browser = new_client()
    account = await register(browser, "OneDevice")
    sessions = (await browser.get("/api/auth/sessions")).json()["sessions"]
    [current] = [row["id"] for row in sessions if row["current"]]
    assert (await browser.post("/api/auth/logout")).status_code == 200
    assert revoked == [(account["id"], [current], None)]


async def test_revoking_a_device_closes_that_devices_sockets(env):
    new_client, _, revoked = env
    laptop, phone = new_client(), new_client()
    account = await register(laptop, "TwoDevices")
    assert (
        await phone.post("/api/auth/login", json={"username": "TwoDevices", "password": PASSWORD})
    ).status_code == 200
    sessions = (await laptop.get("/api/auth/sessions")).json()["sessions"]
    [other] = [row["id"] for row in sessions if not row["current"]]
    assert (await laptop.delete(f"/api/auth/sessions/{other}")).status_code == 200
    assert revoked == [(account["id"], [other], None)]


async def test_revoking_a_rotated_device_closes_the_sockets_it_opened_before(env):
    """A rotation mints a new session under a socket that stays open, so the
    device list names an id no socket carries; the sockets opened with the
    session it was rotated from go too (#1083)."""
    from app.auth.sessions import rotate_session

    new_client, factory, revoked = env
    laptop, phone = new_client(), new_client()
    account = await register(laptop, "Rotated")
    assert (
        await phone.post("/api/auth/login", json={"username": "Rotated", "password": PASSWORD})
    ).status_code == 200
    sessions = (await laptop.get("/api/auth/sessions")).json()["sessions"]
    [opened_with] = [row["id"] for row in sessions if not row["current"]]
    middle = await rotate_session(
        factory, session_id=opened_with, user_id=account["id"], device_label="Phone"
    )
    latest = await rotate_session(
        factory, session_id=middle.session.id, user_id=account["id"], device_label="Phone"
    )
    listed = (await laptop.get("/api/auth/sessions")).json()["sessions"]
    assert [row["id"] for row in listed if not row["current"]] == [latest.session.id]

    assert (await laptop.delete(f"/api/auth/sessions/{latest.session.id}")).status_code == 200
    assert revoked == [
        (account["id"], [latest.session.id, middle.session.id, opened_with], None)
    ]


async def test_a_password_change_closes_every_other_browsers_sockets(env):
    """This browser's session is revoked with the rest, but its sockets are
    kept: the notice would beat the response carrying the new cookie, and
    the tab would take its own change for a sign-out."""
    new_client, _, revoked = env
    browser = new_client()
    account = await register(browser, "Changing")
    sessions = (await browser.get("/api/auth/sessions")).json()["sessions"]
    [current] = [row["id"] for row in sessions if row["current"]]
    changed = await browser.post(
        "/api/auth/password/change",
        json={"currentPassword": PASSWORD, "password": "another-good-password-42"},
    )
    assert changed.status_code == 200, changed.text
    assert revoked == [(account["id"], None, current)]


async def test_the_sockets_of_the_named_sessions_are_told_and_closed(monkeypatch):
    from app import main

    class Server(FakeServer):
        def __init__(self, rooms, sessions):
            super().__init__(rooms)
            self._sessions = sessions

        async def get_session(self, sid):
            return self._sessions.get(sid)

    server = Server(
        {"user:u1": ["laptop-sid", "phone-sid", "laptop-tab-2"]},
        {
            "laptop-sid": {"user_id": "u1", "session_id": "s-laptop"},
            "laptop-tab-2": {"user_id": "u1", "session_id": "s-laptop"},
            "phone-sid": {"user_id": "u1", "session_id": "s-phone"},
        },
    )
    monkeypatch.setattr(main, "sio", server)

    await main.close_sockets_of_revoked_sessions("u1", ["s-laptop"])
    assert server.disconnected == ["laptop-sid", "laptop-tab-2"]
    assert [to for _, _, to in server.emitted] == ["laptop-sid", "laptop-tab-2"]
    assert server.emitted[0][:2] == (
        "session_superseded",
        {"code": "signed_out", "reason": "You were signed out on this device."},
    )

    server.disconnected.clear()
    await main.close_sockets_of_revoked_sessions("u1", None)
    assert server.disconnected == ["laptop-sid", "phone-sid", "laptop-tab-2"]

    # The acting browser keeps its sockets, every tab of it.
    server.disconnected.clear()
    await main.close_sockets_of_revoked_sessions("u1", None, keep="s-laptop")
    assert server.disconnected == ["phone-sid"]


async def test_a_socket_whose_opening_session_is_gone_is_closed_too(monkeypatch):
    """The rotation walk stops where a link was purged, 30 days after an
    expiry; a socket opened with such a session can be traced to no device,
    so a named revocation on the account closes it as well (#1083 review)."""
    from app import main

    class Server(FakeServer):
        async def get_session(self, sid):
            return {
                "laptop-sid": {"user_id": "u1", "session_id": "s-laptop"},
                "ancient-sid": {"user_id": "u1", "session_id": "s-purged"},
                "phone-sid": {"user_id": "u1", "session_id": "s-phone"},
            }[sid]

    server = Server({"user:u1": ["laptop-sid", "ancient-sid", "phone-sid"]})
    monkeypatch.setattr(main, "sio", server)
    asked: list[set[str]] = []

    async def untraceable(ids):
        asked.append(ids)
        return {"s-purged"}

    monkeypatch.setattr(main, "untraceable_sessions", untraceable)

    await main.close_sockets_of_revoked_sessions("u1", ["s-laptop"])
    assert server.disconnected == ["laptop-sid", "ancient-sid"]
    assert asked == [{"s-purged", "s-phone"}]


async def test_untraceable_sessions_are_the_missing_and_the_expired():
    from datetime import datetime, timedelta, timezone
    from uuid import UUID, uuid4

    from sqlalchemy import update

    from app.auth.sessions import create_session, rotate_session
    from app.db.models import AuthSession
    from app.main import untraceable_sessions

    factory, engine = await create_test_db()
    try:
        user = await SqlAlchemyUserRepository(factory).create_anonymous("Old")
        live = await create_session(factory, user_id=user.id, device_label="A")
        rotated = await create_session(factory, user_id=user.id, device_label="B")
        await rotate_session(
            factory, session_id=rotated.session.id, user_id=user.id, device_label="B"
        )
        expired = await create_session(factory, user_id=user.id, device_label="C")
        idle = await create_session(factory, user_id=user.id, device_label="D")
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(AuthSession)
                    .where(AuthSession.id == UUID(expired.session.id))
                    .values(
                        created_at=past - timedelta(days=1),
                        last_used_at=past - timedelta(days=1),
                        expires_at=past,
                        idle_expires_at=past,
                    )
                )
                await session.execute(
                    update(AuthSession)
                    .where(AuthSession.id == UUID(idle.session.id))
                    .values(
                        created_at=past - timedelta(days=1),
                        last_used_at=past - timedelta(days=1),
                        idle_expires_at=past,
                    )
                )
        purged = str(uuid4())
        ids = {
            live.session.id,
            rotated.session.id,
            expired.session.id,
            idle.session.id,
            purged,
            "not-a-uuid",
        }
        # Revoked by a rotation is still traceable: its device lives on.
        assert await untraceable_sessions(ids, factory) == {
            expired.session.id,
            idle.session.id,
            purged,
        }
    finally:
        await engine.dispose()


async def test_a_socket_gone_mid_sweep_does_not_stop_the_rest(monkeypatch):
    """`get_session` raises for a sid that left between the walk and the
    read; the sockets after it in the list are still told and closed."""
    from app import main

    class Server(FakeServer):
        async def get_session(self, sid):
            if sid == "gone-sid":
                raise KeyError("Session not found")
            return {"user_id": "u1", "session_id": "s-phone"}

    server = Server({"user:u1": ["gone-sid", "phone-sid"]})
    monkeypatch.setattr(main, "sio", server)

    await main.close_sockets_of_revoked_sessions("u1", ["s-phone"])
    assert server.disconnected == ["phone-sid"]


async def test_a_seated_socket_still_names_the_session_that_opened_it():
    """Room entry and exit rewrite the socket session; the session id has to
    survive both, or a targeted revocation skips every seated socket and the
    acting browser's own change closes its seat (review of #1066)."""
    from unittest.mock import AsyncMock

    import socketio

    from app.handlers import register_all_handlers as register_handlers
    from app.rooms import RoomManager
    from tests.handlers.helpers import SessionStore

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, RoomManager())
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()

    await sessions.save("laptop-sid", {"user_id": "u1", "session_id": "s-laptop"})
    created = await sio.handlers["/"]["create_room"]("laptop-sid", {"nickname": "Host"})
    assert created["ok"], created
    seated = await sessions.get("laptop-sid")
    assert seated["room_id"] == created["roomId"]
    assert seated["session_id"] == "s-laptop"

    await sio.handlers["/"]["leave_room"]("laptop-sid", {})
    assert await sessions.get("laptop-sid") == {"user_id": "u1", "session_id": "s-laptop"}

"""Sockets and rooms are capped per address and per account, not only per process (#1232).

Before this, admission counted only the process ceiling, and only at the
Socket.IO CONNECT: one address opened 600 cookieless sockets in 0.2 s and every
other visitor was told the server was full; a transport that never sent a
CONNECT was never counted at all. These drive the real Engine.IO handshake
through `BoundedSocketServer.handle_request` - polling and WebSocket - with the
ledger the application wires in.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio

from app import socket_server
from app.handlers import register_all_handlers as register_handlers
from app.protocol import PROTOCOL_VERSION
from app.rooms import RoomManager
from app.services import room_quotas
from app.services.room_quotas import RoomCapacityService, RoomQuotaExceeded, RoomQuotaService
from app.services.telemetry import Telemetry
from app.socket_server import BoundedSocketServer
from app.socket_transport import handshake_address


def capacity(**limits) -> RoomCapacityService:
    return RoomCapacityService(environ={name: str(value) for name, value in limits.items()})


# --- the ledger -------------------------------------------------------------------


def test_an_address_is_refused_past_its_allowance_while_others_still_connect():
    ledger = capacity(SOCKET_PER_ADDRESS_LIMIT=2).transports
    first, _ = ledger.admit("192.0.2.1")
    second, _ = ledger.admit("192.0.2.1")
    third, reason = ledger.admit("192.0.2.1")
    other, _ = ledger.admit("198.51.100.7")

    assert first and second and third is None and reason == "address"
    assert other is not None
    assert ledger.held_by("192.0.2.1") == 2 and ledger.open == 3


def test_past_the_ceiling_a_bounded_few_are_admitted_only_to_be_told(monkeypatch):
    monkeypatch.setattr(room_quotas, "TURNED_AWAY_ALLOWANCE", 1)
    ledger = capacity(SOCKET_LIMIT=10, SOCKET_PER_ADDRESS_LIMIT=100).transports
    tickets = [ledger.admit(f"192.0.2.{index}")[0] for index in range(10)]
    assert not any(ticket.over_capacity for ticket in tickets)
    told, _ = ledger.admit("192.0.2.200")
    refused, reason = ledger.admit("192.0.2.201")
    assert told is not None and told.over_capacity
    assert refused is None and reason == "server"


def test_a_ticket_is_given_back_exactly_once():
    ledger = capacity(SOCKET_PER_ADDRESS_LIMIT=3).transports
    ticket, _ = ledger.admit("192.0.2.1")
    ledger.bind(ticket, "sid-1")
    ledger.release(ticket)
    ledger.release(ticket)
    ledger.release_sid("sid-1")
    assert ledger.open == 0 and ledger.held_by("192.0.2.1") == 0
    # A pending ticket, never bound, gives back the same way.
    pending, _ = ledger.admit("192.0.2.1")
    ledger.release(pending)
    ledger.release(pending)
    assert ledger.open == 0


def test_a_stranded_ticket_is_reconciled_against_the_sockets_that_exist():
    ledger = capacity().transports
    for sid in ("a", "b", "c"):
        ticket, _ = ledger.admit("192.0.2.1")
        ledger.bind(ticket, sid)
    assert ledger.reconcile(["b"]) == 2
    assert ledger.open == 1


# --- the handshake ----------------------------------------------------------------


def build_server(monkeypatch, **limits):
    store = Telemetry()
    monkeypatch.setattr(socket_server, "telemetry", store)
    from app import socket_transport

    monkeypatch.setattr(socket_transport, "telemetry", store)
    sio = BoundedSocketServer(async_mode="asgi", ping_interval=0.05, ping_timeout=5)
    room_capacity = capacity(**limits)
    sio.eio.admission = room_capacity.transports
    return sio, room_capacity, store


async def poll_handshake(sio, host: str) -> tuple[int, str | None]:
    sent: list[dict] = []
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "method": "GET", "path": "/socket.io/",
        "query_string": b"EIO=4&transport=polling",
        "headers": [(b"host", b"test")], "client": (host, 5000),
    }
    await sio.handle_request(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    sid = json.loads(body.decode()[1:])["sid"] if status == 200 else None
    return status, sid


async def websocket_handshake(sio, host: str) -> tuple[asyncio.Task, list[dict], asyncio.Queue]:
    inbound: asyncio.Queue = asyncio.Queue()
    sent: list[dict] = []
    inbound.put_nowait({"type": "websocket.connect"})

    async def send(message):
        sent.append(message)

    scope = {
        "type": "websocket", "path": "/socket.io/",
        "query_string": b"EIO=4&transport=websocket",
        "headers": [(b"host", b"test"), (b"upgrade", b"websocket"), (b"connection", b"upgrade")],
        "client": (host, 5000),
    }
    task = asyncio.create_task(sio.handle_request(scope, inbound.get, send))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if sent:
            break
    return task, sent, inbound


def rejected(store) -> dict[str, int]:
    return {labels[0]: count for labels, count in store.socket_admissions_refused.items()}


async def test_with_a_ceiling_of_two_a_third_polling_handshake_allocates_nothing(monkeypatch):
    """The review's reproduction: four handshakes against a ceiling of two
    were four retained sockets with the application's count at zero."""
    monkeypatch.setattr(room_quotas, "TURNED_AWAY_ALLOWANCE", 0)
    sio, room_capacity, store = build_server(monkeypatch, SOCKET_LIMIT=10, SOCKET_PER_ADDRESS_LIMIT=100)
    room_capacity.sockets = 2
    results = [await poll_handshake(sio, f"192.0.2.{index}") for index in range(4)]
    assert [status for status, _ in results] == [200, 200, 503, 503]
    assert len(sio.eio.sockets) == 2
    assert room_capacity.transports.open == 2
    assert rejected(store) == {"server": 2}


async def test_with_a_ceiling_of_two_a_third_websocket_handshake_allocates_nothing(monkeypatch):
    monkeypatch.setattr(room_quotas, "TURNED_AWAY_ALLOWANCE", 0)
    sio, room_capacity, store = build_server(monkeypatch, SOCKET_LIMIT=10, SOCKET_PER_ADDRESS_LIMIT=100)
    room_capacity.sockets = 2
    opened = [await websocket_handshake(sio, f"192.0.2.{index}") for index in range(3)]
    third_task, third_sent, _ = opened[2]
    await asyncio.wait({third_task}, timeout=1)
    assert third_task.done(), "refused before any WebSocket was accepted"
    assert [m["type"] for m in third_sent] == ["websocket.close"]
    assert len(sio.eio.sockets) == 2 and room_capacity.transports.open == 2
    for task, _, inbound in opened[:2]:
        inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait({task}, timeout=1)
    assert room_capacity.transports.open == 0, "each given back on its close"


async def test_one_address_flooding_cannot_make_another_address_full(monkeypatch):
    sio, room_capacity, store = build_server(monkeypatch, SOCKET_PER_ADDRESS_LIMIT=4)
    flood = await asyncio.gather(*(poll_handshake(sio, "2001:db8:1:1::5") for _ in range(20)))
    # A neighbour in the same /64 is the same subscriber.
    neighbour, _ = await poll_handshake(sio, "2001:db8:1:1::ffff")
    visitor, _ = await poll_handshake(sio, "198.51.100.9")

    assert sorted(status for status, _ in flood) == [200] * 4 + [429] * 16
    assert neighbour == 429
    assert visitor == 200
    assert room_capacity.transports.held_by("2001:db8:1:1::/64") == 4


async def test_an_upgrade_is_the_same_transport_not_a_second_one(monkeypatch):
    sio, room_capacity, store = build_server(monkeypatch, SOCKET_PER_ADDRESS_LIMIT=1)
    status, sid = await poll_handshake(sio, "192.0.2.50")
    assert status == 200
    inbound: asyncio.Queue = asyncio.Queue()
    sent: list[dict] = []
    inbound.put_nowait({"type": "websocket.connect"})

    async def send(message):
        sent.append(message)

    scope = {
        "type": "websocket", "path": "/socket.io/",
        "query_string": f"EIO=4&transport=websocket&sid={sid}".encode(),
        "headers": [(b"host", b"test"), (b"upgrade", b"websocket"), (b"connection", b"upgrade")],
        "client": ("192.0.2.50", 5001),
    }
    upgrade = asyncio.create_task(sio.handle_request(scope, inbound.get, send))
    await asyncio.sleep(0.05)
    assert sent and sent[0]["type"] == "websocket.accept", "an upgrade is not a new admission"
    assert room_capacity.transports.open == 1
    inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
    await asyncio.wait({upgrade}, timeout=1)


async def test_every_way_a_transport_ends_gives_its_ticket_back(monkeypatch):
    sio, room_capacity, store = build_server(monkeypatch, SOCKET_PER_ADDRESS_LIMIT=10)
    ledger = room_capacity.transports

    # Closed by the server.
    _, sid = await poll_handshake(sio, "192.0.2.60")
    await sio.eio.terminate(sid)
    assert ledger.open == 0

    # Refused by the application at the Engine.IO connect.
    async def reject(eio_sid, environ):
        return False

    sio.eio.on("connect", reject)
    status, _ = await poll_handshake(sio, "192.0.2.60")
    assert status == 401 and ledger.open == 0

    # A handshake the address was refused never held one.
    assert ledger.held_by("192.0.2.60") == 0


def test_the_address_is_read_off_the_scope_the_proxy_vouched_for():
    assert handshake_address({"asgi.scope": {"client": ("2001:db8::1", 1)}, "REMOTE_ADDR": "127.0.0.1"}) == "2001:db8::/64"
    assert handshake_address({"asgi.scope": {}}) == "unknown"


# --- the account ------------------------------------------------------------------


async def test_one_account_is_told_past_its_sockets_and_gets_a_place_back(monkeypatch):
    import app.handlers.connection as connection_module

    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    ctx.room_capacity = capacity(SOCKET_PER_ACCOUNT_LIMIT=2)
    sio.emit = AsyncMock()
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.disconnect = AsyncMock()
    ctx.session_factory = object()

    async def signed_in(*_args, **_kwargs):
        return SimpleNamespace(session=SimpleNamespace(user_id="user-1", id="s-1"), banned_user_id=None)

    monkeypatch.setattr(connection_module, "resolve_session_status", signed_in)
    monkeypatch.setattr(connection_module, "_record_last_seen", lambda *_: None)
    monkeypatch.setattr(ctx.presence_identities, "warm", AsyncMock())

    for sid in ("tab-1", "tab-2", "tab-3"):
        await sio.handlers["/"]["connect"](sid, {}, {"protocol": PROTOCOL_VERSION})

    told = [call for call in sio.emit.await_args_list if call.args[0] == "server_full"]
    assert len(told) == 1
    assert told[0].args[1]["limit"] == "account"
    assert told[0].kwargs["to"] == "tab-3"
    assert ctx.is_turned_away("tab-3")
    assert ctx.room_capacity.account_sockets("user-1") == 2

    await sio.handlers["/"]["disconnect"]("tab-1")
    await sio.handlers["/"]["connect"]("tab-4", {}, {"protocol": PROTOCOL_VERSION})
    assert ctx.room_capacity.account_sockets("user-1") == 2
    assert not ctx.is_turned_away("tab-4")


# --- rooms ------------------------------------------------------------------------


def test_one_address_holds_only_so_many_rooms_whatever_accounts_it_mints():
    room_manager = RoomManager()
    quotas = RoomQuotaService(room_manager, environ={"ROOM_PER_ADDRESS_LIMIT": "2"})
    for index in range(2):
        quotas.check_capacity(f"guest-{index}", "192.0.2.9")
        room_manager.create_room(created_by_user_id=f"guest-{index}", created_from="192.0.2.9")
    with pytest.raises(RoomQuotaExceeded):
        quotas.check_capacity("guest-3", "192.0.2.9")
    quotas.check_capacity("guest-3", "198.51.100.1")


async def test_a_room_that_never_starts_a_game_is_closed_and_says_why():
    from tests.handlers.test_room_capacity import build_stack, open_room

    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    idle = room_manager.get_room((await open_room(sio, sessions, "idle-host"))["roomId"])
    fresh = room_manager.get_room((await open_room(sio, sessions, "fresh-host"))["roomId"])
    played = room_manager.get_room((await open_room(sio, sessions, "played-host"))["roomId"])
    idle.created_at -= ctx.idle_rooms.idle_seconds + 1
    played.created_at -= ctx.idle_rooms.idle_seconds + 1
    played.started_a_game = True

    assert await ctx.idle_rooms.flush() == 1

    assert room_manager.get_room(idle.id) is None
    assert room_manager.get_room(fresh.id) is fresh
    assert room_manager.get_room(played.id) is played
    notices = [call.args for call in sio.emit.await_args_list if call.args[0] == "kicked"]
    assert notices and notices[-1][1]["code"] == "room_expired"


# --- review of #1232: dead connections, and a start at the deadline ----------------


async def test_an_address_at_its_ceiling_gets_the_place_a_dead_connection_held(monkeypatch):
    """After a network blip a whole room reconnects while its old transports
    wait out Engine.IO's 45 s ping timeout: counted, they refused the room."""
    import time

    sio, room_capacity, store = build_server(monkeypatch, SOCKET_PER_ADDRESS_LIMIT=2)
    _, live = await poll_handshake(sio, "192.0.2.70")
    _, dead = await poll_handshake(sio, "192.0.2.70")
    # Asked, and never answered inside Engine.IO's own ping timeout.
    sio.eio.sockets[dead].last_ping = time.time() - sio.eio.ping_timeout - 1

    status, fresh = await poll_handshake(sio, "192.0.2.70")

    assert status == 200
    assert dead not in sio.eio.sockets and live in sio.eio.sockets
    assert room_capacity.transports.held_by("192.0.2.70") == 2


async def test_a_live_connection_is_never_taken_for_a_dead_one(monkeypatch):
    import time

    sio, room_capacity, store = build_server(monkeypatch, SOCKET_PER_ADDRESS_LIMIT=1)
    _, live = await poll_handshake(sio, "192.0.2.71")
    sio.eio.sockets[live].last_ping = time.time() - 1  # a ping in flight, answered soon
    status, _ = await poll_handshake(sio, "192.0.2.71")
    assert status == 429
    assert live in sio.eio.sockets


async def test_an_address_never_ends_somebody_elses_socket_whose_pong_is_only_late(monkeypatch):
    """#1290 review: the address is everybody behind it, so a pong 10 s late -
    a slow network, not a dead one - is somebody else's live game. Only past
    Engine.IO's own ping timeout is it gone."""
    import time

    sio, room_capacity, store = build_server(monkeypatch, SOCKET_PER_ADDRESS_LIMIT=1)
    sio.eio.ping_timeout = 20  # production's, not the fixture's
    _, slow = await poll_handshake(sio, "192.0.2.72")
    sio.eio.sockets[slow].last_ping = time.time() - 10
    status, _ = await poll_handshake(sio, "192.0.2.72")
    assert status == 429
    assert slow in sio.eio.sockets


async def test_an_account_at_its_ceiling_gets_the_place_a_dead_tab_held(monkeypatch):
    import time

    import app.handlers.connection as connection_module

    room_manager = RoomManager()
    sio = BoundedSocketServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    ctx.room_capacity = capacity(SOCKET_PER_ACCOUNT_LIMIT=1)
    sio.emit = AsyncMock()
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    ctx.session_factory = object()

    async def signed_in(*_args, **_kwargs):
        return SimpleNamespace(session=SimpleNamespace(user_id="user-2", id="s-2"), banned_user_id=None)

    monkeypatch.setattr(connection_module, "resolve_session_status", signed_in)
    monkeypatch.setattr(connection_module, "_record_last_seen", lambda *_: None)
    monkeypatch.setattr(ctx.presence_identities, "warm", AsyncMock())

    class DeadEngineSocket:
        closed = False
        last_ping = time.time() - 10

        def __init__(self, sid):
            self.sid = sid
            self.closes = []

        async def close(self, wait=True, abort=False, reason=None):
            self.closes.append(abort)
            self.closed = True
            await sio._handle_eio_disconnect(self.sid, reason)

    old = DeadEngineSocket("eio-old")
    sio.eio.sockets["eio-old"] = old
    await sio.manager.connect("eio-old", "/")
    old_sid = sio.manager.sid_from_eio_sid("eio-old", "/")
    await sio.handlers["/"]["connect"](old_sid, {}, {"protocol": PROTOCOL_VERSION})
    assert ctx.room_capacity.account_sockets("user-2") == 1

    await sio.handlers["/"]["connect"]("new-tab", {}, {"protocol": PROTOCOL_VERSION})

    assert old.closes == [True], "the dead tab was ended"
    assert not ctx.is_turned_away("new-tab")
    assert ctx.room_capacity.account_sids("user-2") == ["new-tab"]


async def test_a_game_started_at_the_deadline_is_not_closed_under_it():
    from tests.handlers.test_room_capacity import build_stack, open_room

    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    room = room_manager.get_room((await open_room(sio, sessions, "late-host"))["roomId"])
    room.created_at -= ctx.idle_rooms.idle_seconds + 1

    await room.lock.acquire()  # a start, drawing its prompts
    sweep = asyncio.create_task(ctx.idle_rooms.flush())
    await asyncio.sleep(0.01)
    room.started_a_game = True
    room.lock.release()

    assert await sweep == 0
    assert room_manager.get_room(room.id) is room

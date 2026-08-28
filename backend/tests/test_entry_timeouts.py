"""A hung database must not pin the gate a seat is reconciled through.

Seat transitions hold the socket's seating gate, and its disconnect queues at
the same gate so that a socket dropping mid-entry reconciles against a seat
that already exists. An entry that never returns therefore holds the gate for
ever, and a socket that drops during it never reconciles - which is the leak
#480 closed, reopened by a stall.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.handlers.rooms import ENTRY_DB_TIMEOUT_SECONDS
from app.rooms import RoomManager
from app.services.room_quotas import RoomQuotaExceeded
from tests.handlers.helpers import SessionStore


def build_stack(room_manager: RoomManager, **kwargs):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, **kwargs)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return ctx, sio, sessions


def never_answers():
    """A database call that is not slow but stopped."""

    async def hang(*_args, **_kwargs):
        await asyncio.sleep(3600)

    return AsyncMock(side_effect=hang)


@pytest.mark.asyncio
async def test_a_hung_code_allocation_refuses_rather_than_hanging(monkeypatch):
    monkeypatch.setattr("app.handlers.rooms.ENTRY_DB_TIMEOUT_SECONDS", 0.05)
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = SimpleNamespace(
        allocate=never_answers(),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )
    await sessions.save("host-sid", {"user_id": "user-1"})

    answer = await asyncio.wait_for(
        sio.handlers["/"]["create_room"]("host-sid", {"nickname": "Host"}), timeout=5
    )

    assert answer["ok"] is False
    assert "database" in answer["error"]
    assert room_manager.rooms == {}


@pytest.mark.asyncio
async def test_a_socket_that_drops_during_a_stall_is_still_reconciled(monkeypatch):
    """The failure this is really about: the socket drops while the entry is
    stuck, and its disconnect is waiting at the same gate."""
    monkeypatch.setattr("app.handlers.rooms.ENTRY_DB_TIMEOUT_SECONDS", 0.05)
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = SimpleNamespace(
        allocate=never_answers(),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )
    await sessions.save("host-sid", {"user_id": "user-1"})

    entering = asyncio.create_task(
        sio.handlers["/"]["create_room"]("host-sid", {"nickname": "Host"})
    )
    await asyncio.sleep(0)
    dropping = asyncio.create_task(sio.handlers["/"]["disconnect"]("host-sid"))

    # Both finish: the entry gives up, and the disconnect it was blocking runs.
    await asyncio.wait_for(asyncio.gather(entering, dropping), timeout=5)

    assert room_manager.rooms == {}
    await ctx.timers.close()


def test_the_bound_matches_the_one_the_history_write_already_uses():
    """Not a new number: the same ten seconds a finished-game write allows."""
    from app.services.game_flow import HISTORY_WRITE_TIMEOUT_SECONDS

    assert ENTRY_DB_TIMEOUT_SECONDS == HISTORY_WRITE_TIMEOUT_SECONDS


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["join_room", "get_room_preview"])
async def test_a_hung_code_lookup_refuses_rather_than_raising(monkeypatch, command):
    """Both paths that ask whether a code has been retired reach the database,
    and a handler that raises answers nothing at all: the client waits out its
    acknowledgement instead of being told."""
    monkeypatch.setattr("app.handlers.rooms.ENTRY_DB_TIMEOUT_SECONDS", 0.05)
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = SimpleNamespace(
        allocate=AsyncMock(return_value="CODE01"),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=never_answers(),
    )
    await sessions.save("visitor-sid", {"user_id": "user-1"})

    answer = await asyncio.wait_for(
        sio.handlers["/"][command]("visitor-sid", {"code": "ABC123"}), timeout=5
    )

    assert answer["ok"] is False
    assert "database" in answer["error"]


def quotas_that_refuse_the_second_capacity_check(**overrides):
    """Quotas that let the room through, then refuse it after the code exists.

    That is the one refusal reachable with a reservation already made, so it is
    how the cleanup paths are entered.
    """
    quotas = SimpleNamespace(
        check_capacity=Mock(
            side_effect=[None, RoomQuotaExceeded("You already have too many rooms")]
        ),
        check_retained_prompts=Mock(return_value=None),
        check_creation_rate=AsyncMock(),
        refund_creation=AsyncMock(),
    )
    for name, value in overrides.items():
        setattr(quotas, name, value)
    return quotas


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "broken",
    ["release_unpublished", "refund_creation"],
    ids=["releasing the code", "returning the allowance"],
)
async def test_a_broken_cleanup_still_answers_the_refusal(broken):
    """Cleanup runs while a refusal is already on its way to the client. A
    database error there must not replace it - the refund runs in a `finally`,
    where a raise would swallow the reason the entry was refused, and both
    would leave the socket waiting out an acknowledgement that never comes."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    exploding = AsyncMock(side_effect=RuntimeError("database is gone"))
    ctx.room_codes = SimpleNamespace(
        allocate=AsyncMock(return_value="CODE01"),
        release_unpublished=exploding if broken == "release_unpublished" else AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )
    ctx.room_quotas = quotas_that_refuse_the_second_capacity_check(
        **({"refund_creation": exploding} if broken == "refund_creation" else {})
    )
    await sessions.save("host-sid", {"user_id": "user-1"})

    answer = await asyncio.wait_for(
        sio.handlers["/"]["create_room"]("host-sid", {"nickname": "Host"}), timeout=5
    )

    assert answer == {"ok": False, "error": "You already have too many rooms"}
    assert room_manager.rooms == {}


def held_at_the_database(monkeypatch):
    """Stop an entry mid-flight, at a call every entry path makes.

    Deterministic on purpose: the window this is about is "the gate is held",
    not "0.05 seconds have passed".
    """
    from app.handlers import rooms

    real = rooms.resolve_identity
    reached, release = asyncio.Event(), asyncio.Event()

    async def gated(*args, **kwargs):
        reached.set()
        await release.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(rooms, "resolve_identity", gated)
    return reached, release


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["create_room", "join_room"])
async def test_an_account_ending_mid_entry_is_not_seated(monkeypatch, command):
    """The sweep that closes an account's sockets waits at each seating gate,
    so an entry already holding one finishes first. R-BAN-02 says the account
    stops playing immediately; an entry that seats itself after the sweep has
    walked past would be a seat created after the ban."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.room_codes = SimpleNamespace(
        allocate=AsyncMock(return_value="CODE01"),
        release_unpublished=AsyncMock(),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )
    await sessions.save("host-sid", {"user_id": "user-1"})
    if command == "join_room":
        room_manager.create_room("Somewhere", code="CODE01")
        payload = {"code": "CODE01", "nickname": "Latecomer"}
    else:
        payload = {"nickname": "Host"}
    reached, release = held_at_the_database(monkeypatch)

    entry = asyncio.create_task(sio.handlers["/"][command]("host-sid", payload))
    await asyncio.wait_for(reached.wait(), timeout=5)

    # What the sweep does: mark, then close - and the close waits behind the
    # entry, which is why the mark has to be what the entry sees.
    with ctx.ending(["host-sid"]):
        closing = asyncio.create_task(sio.handlers["/"]["disconnect"]("host-sid"))
        await asyncio.sleep(0)
        release.set()
        answer = await asyncio.wait_for(entry, timeout=5)
        await asyncio.wait_for(closing, timeout=5)

    assert answer["ok"] is False
    assert answer["error"] == "This account is no longer active."
    seats = [p for r in room_manager.rooms.values() for p in r.players.values()]
    assert seats == []


def a_database_that_never_answers(monkeypatch):
    """A settings read that hangs, which is what makes the fallback matter."""

    class HangingSession:
        async def get(self, *_args, **_kwargs):
            await asyncio.sleep(3600)

    class HangingFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return HangingSession()

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr("app.handlers.rooms.ENTRY_DB_TIMEOUT_SECONDS", 0.05)
    return HangingFactory()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_anonymous, expected",
    [(False, True), (True, False)],
    ids=["a registered seat keeps its own", "a guest seat is its own authority"],
)
async def test_a_stalled_colour_read_does_not_let_a_payload_decide(
    monkeypatch, is_anonymous, expected
):
    """A registered account's colour preference lives in the database
    precisely so a Socket.IO payload cannot set it. A slow database must not
    become the way to set it anyway."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    ctx.session_factory = a_database_that_never_answers(monkeypatch)
    room = room_manager.create_room("Somewhere", code="CODE01")
    player = room_manager.add_player(
        room,
        "Returning",
        user_id="1e1a4c9c-6f52-4a37-9f28-2f7a1b0d5c11",
        is_anonymous=is_anonymous,
        colorblind_safe_colors=True,
    )
    player.sid = "seat-sid"
    player.connected = True
    await sessions.save("seat-sid", {"room_id": room.id, "player_id": player.id})

    answer = await asyncio.wait_for(
        sio.handlers["/"]["join_room"](
            "seat-sid",
            {"code": "CODE01", "nickname": "Returning", "colorblind_safe_colors": False},
        ),
        timeout=5,
    )

    assert answer["ok"] is True
    assert player.colorblind_safe_colors is expected

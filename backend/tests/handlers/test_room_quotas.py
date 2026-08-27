"""Ceilings on who may open a room, how many, and how much they may hold.

Room creation is the one anonymous socket command that allocates unbounded
process memory and a durable code reservation. These are the limits that stop
one client from spending the whole server, and the checks that a legitimate
player still reaches the game.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager
from tests.handlers.helpers import SessionStore


def build_stack(room_manager: RoomManager, *, user_id: str | None, **kwargs):
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


async def seat(sessions: SessionStore, sid: str, user_id: str | None) -> None:
    await sessions.save(sid, {"user_id": user_id})


@pytest.mark.asyncio
async def test_a_socket_with_no_account_cannot_open_a_room_but_can_still_play():
    """R-HIST-10 keeps its accountless seat; only creation is withheld."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager, user_id=None)
    await seat(sessions, "cookieless-sid", None)
    await seat(sessions, "host-sid", "user-host")

    refused = await sio.handlers["/"]["create_room"](
        "cookieless-sid", {"nickname": "Nomad"}
    )
    assert refused["ok"] is False
    assert room_manager.rooms == {}

    hosted = await sio.handlers["/"]["create_room"]("host-sid", {"nickname": "Host"})
    joined = await sio.handlers["/"]["join_room"](
        "cookieless-sid", {"roomId": hosted["roomId"], "nickname": "Nomad"}
    )
    assert joined["ok"] is True, "a cookie-less player must still be able to play"


@pytest.mark.asyncio
async def test_an_account_cannot_hold_more_live_rooms_than_its_ceiling():
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager, user_id="user-1")
    ctx.room_quotas.per_account_rooms = 2
    for sid in ("sid-1", "sid-2", "sid-3"):
        await seat(sessions, sid, "user-1")

    first = await sio.handlers["/"]["create_room"]("sid-1", {"nickname": "Ann"})
    second = await sio.handlers["/"]["create_room"]("sid-2", {"nickname": "Ann"})
    third = await sio.handlers["/"]["create_room"]("sid-3", {"nickname": "Ann"})

    assert first["ok"] is True and second["ok"] is True
    assert third["ok"] is False
    assert len(room_manager.rooms) == 2

    # A room that ends gives its share back.
    await sio.handlers["/"]["leave_room"]("sid-1")
    assert len(room_manager.rooms) == 1
    again = await sio.handlers["/"]["create_room"]("sid-3", {"nickname": "Ann"})
    assert again["ok"] is True


@pytest.mark.asyncio
async def test_another_account_is_unaffected_by_a_neighbours_ceiling():
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager, user_id="user-1")
    ctx.room_quotas.per_account_rooms = 1
    await seat(sessions, "sid-1", "user-1")
    await seat(sessions, "sid-2", "user-2")

    await sio.handlers["/"]["create_room"]("sid-1", {"nickname": "Ann"})
    blocked = await sio.handlers["/"]["create_room"]("sid-1", {"nickname": "Ann"})
    neighbour = await sio.handlers["/"]["create_room"]("sid-2", {"nickname": "Bob"})

    assert blocked["ok"] is False
    assert neighbour["ok"] is True


@pytest.mark.asyncio
async def test_the_server_refuses_to_open_more_rooms_than_it_will_hold():
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager, user_id="user-1")
    ctx.room_quotas.global_rooms = 1
    ctx.room_quotas.per_account_rooms = 10
    await seat(sessions, "sid-1", "user-1")
    await seat(sessions, "sid-2", "user-2")

    await sio.handlers["/"]["create_room"]("sid-1", {"nickname": "Ann"})
    refused = await sio.handlers["/"]["create_room"]("sid-2", {"nickname": "Bob"})

    assert refused["ok"] is False
    assert len(room_manager.rooms) == 1


@pytest.mark.asyncio
async def test_quick_prompts_are_capped_across_every_live_room():
    """The per-room limit bounds one room; this bounds the process."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager, user_id="user-1")
    ctx.room_quotas.per_account_rooms = 10
    ctx.room_quotas.prompt_characters = 200
    for sid in ("sid-1", "sid-2"):
        await seat(sessions, sid, "user-1")

    prompts = "\n".join(f"prompt{n:03d}" for n in range(15))  # ~150 bytes
    first = await sio.handlers["/"]["create_room"](
        "sid-1", {"nickname": "Ann", "customPrompts": prompts}
    )
    second = await sio.handlers["/"]["create_room"](
        "sid-2", {"nickname": "Ann", "customPrompts": prompts}
    )

    assert first["ok"] is True
    assert second["ok"] is False
    assert len(room_manager.rooms) == 1


@pytest.mark.asyncio
async def test_editing_settings_cannot_walk_past_the_retained_prompt_ceiling():
    """Otherwise the cap is bypassed by opening a small room and growing it."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager, user_id="user-1")
    ctx.room_quotas.prompt_characters = 200
    await seat(sessions, "sid-1", "user-1")

    created = await sio.handlers["/"]["create_room"]("sid-1", {"nickname": "Ann"})
    room = room_manager.get_room(created["roomId"])
    assert room is not None

    grown = await sio.handlers["/"]["update_room_settings"](
        "sid-1",
        {"customPrompts": "\n".join(f"prompt{n:03d}" for n in range(40))},
    )

    assert grown["ok"] is False
    assert room.custom_prompts == []


@pytest.mark.asyncio
async def test_the_retained_prompt_count_never_drifts_from_the_rooms():
    """The total is kept incrementally, so it has to be checked against truth."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager, user_id="user-1")
    ctx.room_quotas.per_account_rooms = 10
    for sid in ("sid-1", "sid-2"):
        await seat(sessions, sid, "user-1")

    def recount() -> int:
        return sum(
            len(prompt)
            for room in room_manager.rooms.values()
            for prompt in room.custom_prompts
        )

    first = await sio.handlers["/"]["create_room"](
        "sid-1", {"nickname": "Ann", "customPrompts": "apple\nbanana"}
    )
    await sio.handlers["/"]["create_room"](
        "sid-2", {"nickname": "Ann", "customPrompts": "cherry"}
    )
    assert room_manager.retained_prompt_characters() == recount()

    await sessions.save(
        "sid-1",
        {
            "user_id": "user-1",
            "room_id": first["roomId"],
            "player_id": first["playerId"],
        },
    )
    edited = await sio.handlers["/"]["update_room_settings"](
        "sid-1", {"customPrompts": "elderberry\nfig\ngrape"}
    )
    assert edited["ok"] is True
    assert room_manager.retained_prompt_characters() == recount()

    await sio.handlers["/"]["leave_room"]("sid-1")
    assert room_manager.retained_prompt_characters() == recount()


@pytest.mark.asyncio
async def test_an_account_cannot_open_rooms_faster_than_its_hourly_allowance():
    """Persistent, so a restart is not a way to get a fresh allowance."""
    from app.services.room_quotas import RoomQuotaService
    from tests.dbfixtures import create_test_db

    factory, engine = await create_test_db()
    try:
        room_manager = RoomManager()
        ctx, sio, sessions = build_stack(
            room_manager, user_id="user-1", session_factory=factory
        )
        ctx.room_quotas = RoomQuotaService(
            room_manager, factory, environ={"ROOM_CREATE_LIMIT": "2"}
        )
        ctx.room_quotas.per_account_rooms = 10
        # One account, three sockets: a second room from the *same* socket
        # would replace the first rather than add to it (#480), and the point
        # here is that the allowance follows the account across its tabs.
        for sid in ("tab-1", "tab-2", "tab-3"):
            await seat(sessions, sid, "user-1")
        await seat(sessions, "neighbour-sid", "user-2")

        first = await sio.handlers["/"]["create_room"]("tab-1", {"nickname": "Ann"})
        second = await sio.handlers["/"]["create_room"]("tab-2", {"nickname": "Ann"})
        third = await sio.handlers["/"]["create_room"]("tab-3", {"nickname": "Ann"})
        neighbour = await sio.handlers["/"]["create_room"](
            "neighbour-sid", {"nickname": "Bob"}
        )

        assert first["ok"] is True and second["ok"] is True
        assert third["ok"] is False
        assert "recently" in third["error"]
        assert neighbour["ok"] is True, "the allowance is per account, not global"
        assert len(room_manager.rooms) == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_refused_room_gives_back_the_code_it_had_already_claimed():
    """The ceiling can only be reached after the reservation is made."""
    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager, user_id="user-1")
    ctx.room_quotas.per_account_rooms = 1
    await seat(sessions, "sid-1", "user-1")
    await seat(sessions, "sid-2", "user-1")

    released: list[str] = []
    ctx.room_codes = SimpleNamespace(
        allocate=AsyncMock(side_effect=["FIRST1", "SECOND"]),
        release_unpublished=AsyncMock(side_effect=lambda code: released.append(code)),
        retire_ephemeral=AsyncMock(),
        is_retired=AsyncMock(return_value=False),
    )

    allocations = 0

    async def steal_the_last_place(*_args, **_kwargs):
        # The second socket arrives in the gap the code allocation opens,
        # which is the race the capacity re-check exists for. Only the first
        # allocation is interrupted: the one it lets in needs a code too.
        nonlocal allocations
        allocations += 1
        if allocations > 1:
            return f"CODE{allocations}"
        await sio.handlers["/"]["create_room"]("sid-2", {"nickname": "Ann"})
        return "FIRST1"

    ctx.room_codes.allocate = AsyncMock(side_effect=steal_the_last_place)
    refused = await sio.handlers["/"]["create_room"]("sid-1", {"nickname": "Ann"})

    assert refused["ok"] is False
    assert len(room_manager.rooms) == 1
    assert released == ["FIRST1"], "the refused room kept its reservation"


@pytest.mark.asyncio
async def test_an_attempt_that_opens_no_room_does_not_spend_the_allowance():
    from app.services.room_quotas import RoomQuotaService
    from tests.dbfixtures import create_test_db

    factory, engine = await create_test_db()
    try:
        room_manager = RoomManager()
        ctx, sio, sessions = build_stack(
            room_manager, user_id="user-1", session_factory=factory
        )
        ctx.room_quotas = RoomQuotaService(
            room_manager, factory, environ={"ROOM_CREATE_LIMIT": "2"}
        )
        ctx.room_quotas.per_account_rooms = 1
        await seat(sessions, "tab-1", "user-1")
        await seat(sessions, "tab-2", "user-1")

        allocations = 0

        async def steal_the_last_place(*_args, **_kwargs):
            nonlocal allocations
            allocations += 1
            if allocations > 1:
                return f"CODE{allocations}"
            await sio.handlers["/"]["create_room"]("tab-2", {"nickname": "Ann"})
            return "FIRST1"

        ctx.room_codes = SimpleNamespace(
            allocate=AsyncMock(side_effect=steal_the_last_place),
            release_unpublished=AsyncMock(),
            retire_ephemeral=AsyncMock(),
            is_retired=AsyncMock(return_value=False),
        )

        refused = await sio.handlers["/"]["create_room"]("tab-1", {"nickname": "Ann"})
        assert refused["ok"] is False

        # Two attempts were made and one room exists, so one allowance was
        # spent. The second must still be there.
        ctx.room_quotas.per_account_rooms = 10
        await seat(sessions, "tab-3", "user-1")
        after = await sio.handlers["/"]["create_room"]("tab-3", {"nickname": "Ann"})
        assert after["ok"] is True, "a refused attempt kept the allowance it spent"
    finally:
        await engine.dispose()

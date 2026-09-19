"""How many messages a room change costs (#880).

Every message pays a deflate flush and WebSocket, TLS and TCP framing that no
payload change removes, so these count messages, not bytes: one `room_state`
per room per action however many times the action changed it, one message for
a turn's start, and the host's colorblind suggestion only when it changes.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import suppress
from unittest.mock import AsyncMock

import socketio

from app.game import Game
from app.handlers import register_all_handlers as register_handlers
from app.handlers.connection import disconnect
from app.rooms import RoomManager


def emitted(sio) -> Counter:
    return Counter(call.args[0] for call in sio.emit.await_args_list)


def server(room_manager, session):
    sio = socketio.AsyncServer(async_mode="asgi")
    context = register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(return_value=session)
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.emit = AsyncMock()
    return sio, context


async def stop_phase_timer(context, room) -> None:
    timer = context.timers.phase_timers.pop(room.id, None)
    if timer is not None:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


async def test_a_game_start_is_one_room_state_and_one_turn_starting():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host")
    guest = room_manager.add_player(room, "Guest")
    host.sid, guest.sid = "host-sid", "guest-sid"
    sio, context = server(room_manager, {"room_id": room.id, "player_id": host.id})

    assert (await sio.handlers["/"]["start_game"](host.sid)) == {"ok": True}

    counts = emitted(sio)
    assert counts["room_state"] == 1
    assert counts["turn_starting"] == 1
    # The room turning to play mounts the game view, canvas included, so it
    # goes before the turn whose canvas identity the canvas has to catch.
    events = [call.args[0] for call in sio.emit.await_args_list]
    assert events.index("room_state") < events.index("turn_starting")
    assert counts["game_started"] == 0 and counts["canvas_reset"] == 0
    starting = next(c.args[1] for c in sio.emit.await_args_list if c.args[0] == "turn_starting")
    assert starting["gameStarted"] is True
    game = room.game
    assert starting["canvas"] == [game.canvas.revision, game.canvas.generation, game.canvas.sequence, game.canvas.hash]
    await stop_phase_timer(context, room)


async def test_a_join_is_one_room_state_however_many_times_the_join_changed_the_room():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host", user_id="host-user")
    host.sid = "host-sid"
    sio, context = server(room_manager, {"user_id": "new-user"})

    assert (await sio.handlers["/"]["join_room"]("new-sid", {"code": room.code, "nickname": "New"}))["ok"]

    assert emitted(sio)["room_state"] == 1
    # The arrival rides the snapshot (#880): no player_joined of its own.
    assert emitted(sio)["player_joined"] == 0
    state = next(c.args[1] for c in sio.emit.await_args_list if c.args[0] == "room_state")
    assert [cause["presence"] for cause in state["causes"]] == ["joined"]
    await context.timers.close()


async def test_a_flap_is_one_room_state_each_way():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host", user_id="host-user")
    guest = room_manager.add_player(room, "Guest", user_id="guest-user")
    host.sid, guest.sid = "host-sid", "guest-sid"
    sio, context = server(room_manager, {"user_id": "guest-user"})

    await sio._trigger_event("disconnect", "/", "guest-sid", sio.reason.TRANSPORT_CLOSE)
    # One room message each way, the flap its cause (the host's first
    # colorblind suggestion aside, which goes once and to them alone).
    counts = emitted(sio)
    counts.pop("colorblind_safe_suggestion", None)
    assert dict(counts) == {"room_state": 1}
    sio.emit.reset_mock()
    assert (await sio.handlers["/"]["join_room"]("guest-new", {"code": room.code, "nickname": "Guest"}))["ok"]
    assert emitted(sio)["room_state"] == 1
    assert emitted(sio)["player_reconnected"] == 0
    await context.timers.close()


async def test_a_rename_is_one_message_that_carries_its_line():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio, context = server(room_manager, {"room_id": room.id, "player_id": host.id})

    answer = await sio.handlers["/"]["rename_player"](host.sid, {"nickname": "Hosted"})
    assert answer["ok"] is True
    counts = emitted(sio)
    assert counts["room_state"] == 1 and counts["chat_message"] == 0
    state = next(c.args[1] for c in sio.emit.await_args_list if c.args[0] == "room_state")
    # The same payload a chat_message announcement carries, so the client
    # writes it the same way.
    [line] = state["causes"]
    assert line["system"] is True and line["code"] == "nickname_changed"
    assert line["params"] == {"previous": "Host", "nickname": "Hosted"}
    await context.timers.close()


async def test_a_drawer_evicted_on_the_last_turn_is_one_room_state(monkeypatch):
    """The case the issue names: the game ends because the drawer left, which
    used to send game_ended, room_state, player_left, room_state."""
    from app.flow_timing import timing

    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, rounds=1)
    players = [room_manager.add_player(room, name, user_id=f"{name}-user") for name in ("Ann", "Bob", "Cy")]
    for player in players:
        player.sid = f"{player.nickname}-sid"
    sio, context = server(room_manager, {})
    room.state = "playing"
    room.game = Game(turn_order=[p.id for p in players], rounds_total=1)
    for _ in players:  # to the last turn
        room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    drawer = room.players[room.game.current_drawer]
    monkeypatch.setattr(timing, "reconnect_grace_seconds", 0.01)

    await disconnect(context, drawer.sid, sio.reason.TRANSPORT_CLOSE)
    sio.emit.reset_mock()
    await asyncio.sleep(0.05)

    assert emitted(sio)["room_state"] == 1
    events = [call.args[0] for call in sio.emit.await_args_list]
    # The snapshot lands after the action's other events, as the room ended up.
    assert events[-1] == "room_state"
    await stop_phase_timer(context, room)
    await context.timers.close()


async def test_the_host_hears_the_colorblind_suggestion_only_when_it_changes():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host")
    host.sid = "host-sid"
    sio, context = server(room_manager, {})
    flow = context.game_flow

    for _ in range(3):
        await flow._emit_room_state(room)
    assert emitted(sio)["colorblind_safe_suggestion"] == 1
    assert emitted(sio)["room_state"] == 3  # no batch open here: each goes at once

    guest = room_manager.add_player(room, "Guest")
    guest.colorblind_safe_colors = True
    await flow._emit_room_state(room)
    await flow._emit_room_state(room)
    suggestions = [c.args[1] for c in sio.emit.await_args_list if c.args[0] == "colorblind_safe_suggestion"]
    assert suggestions == [{"active": False}, {"active": True}]

    host.sid = "host-reloaded"  # a new socket is told again
    await flow._emit_room_state(room)
    assert emitted(sio)["colorblind_safe_suggestion"] == 3
    await context.timers.close()


async def test_a_task_that_outlives_its_action_still_sends_its_snapshot():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    room_manager.add_player(room, "Host").sid = "host-sid"
    sio, context = server(room_manager, {})
    flow = context.game_flow
    later = asyncio.Event()

    async def after_the_action():
        await later.wait()
        await flow._emit_room_state(room)

    async with flow.room_state_batch():
        task = asyncio.create_task(after_the_action())
        await flow._emit_room_state(room)
        await flow._emit_room_state(room)
    assert emitted(sio)["room_state"] == 1
    later.set()
    await task
    assert emitted(sio)["room_state"] == 2
    await context.timers.close()


async def test_a_joining_socket_gets_the_room_before_its_own_catch_up():
    """A client meets a new room through its first room_state, which clears
    what belonged to the room before; a sync_game held back behind it was
    wiped as soon as it was applied (a reload lost its correct guess)."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    drawer = room_manager.add_player(room, "Drawer", user_id="drawer-user")
    room_manager.add_player(room, "Guesser", user_id="guesser-user").sid = "guesser-sid"
    drawer.sid = "drawer-sid"
    room.state = "playing"
    room.game = Game(turn_order=list(room.players))
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.force_prompt_choice()
    sio, context = server(room_manager, {"user_id": "late-user"})

    assert (await sio.handlers["/"]["join_room"]("late-sid", {"code": room.code, "nickname": "Late"}))["ok"]

    events = [call.args[0] for call in sio.emit.await_args_list]
    assert events.index("room_state") < events.index("sync_game")
    assert events.count("room_state") == 1
    await context.timers.close()


def presence_sequence(sio) -> list[tuple[str, str]]:
    """Every presence cause the room was told, in order, with the snapshot's
    view of that seat when it was sent: (event, seat state)."""
    seen = []
    for call in sio.emit.await_args_list:
        if call.args[0] != "room_state":
            continue
        seats = {p["playerId"]: p for p in call.args[1]["players"]}
        for cause in call.args[1].get("causes", []):
            if "presence" in cause:
                assert "account" not in cause, "the account id never leaves the server"
                seat = seats.get(cause["playerId"])
                seen.append((cause["presence"], "absent" if seat is None else ("connected" if seat["connected"] else "away")))
    return seen


async def test_a_reconnect_inside_the_disconnect_is_not_followed_by_the_disconnect(monkeypatch):
    """The review's race: the disconnect awaits while ending the turn, the
    seat reconnects in that gap, and the disconnect's snapshot used to follow
    with its stale cause."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    host = room_manager.add_player(room, "Host", user_id="host-user")
    guest = room_manager.add_player(room, "Guest", user_id="guest-user")
    host.sid, guest.sid = "host-sid", "guest-sid"
    sio, context = server(room_manager, {"user_id": "guest-user"})
    join = sio.handlers["/"]["join_room"]

    async def reconnect_meanwhile(_room):
        assert (await join("guest-new", {"code": room.code, "nickname": "Guest"}))["ok"]

    monkeypatch.setattr(context.game_flow, "_end_turn_if_all_guessed", reconnect_meanwhile)
    await sio._trigger_event("disconnect", "/", "guest-sid", sio.reason.TRANSPORT_CLOSE)

    assert presence_sequence(sio) == [("disconnected", "away"), ("reconnected", "connected")]
    await context.timers.close()


async def test_a_rejoin_inside_an_eviction_is_not_answered_by_the_departure(monkeypatch):
    from app.flow_timing import timing

    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    players = [room_manager.add_player(room, name, user_id=f"{name}-user") for name in ("Ann", "Bob", "Cydney")]
    for player in players:
        player.sid = f"{player.nickname}-sid"
    gone = players[2]
    sio, context = server(room_manager, {"user_id": gone.user_id})
    join = sio.handlers["/"]["join_room"]
    monkeypatch.setattr(timing, "reconnect_grace_seconds", 0.01)

    async def rejoin_meanwhile(_room, _token):
        assert (await join("cyd-new", {"code": room.code, "nickname": "Cydney"}))["ok"]

    await disconnect(context, gone.sid, sio.reason.TRANSPORT_CLOSE)
    monkeypatch.setattr(context.game_flow, "_remove_player_from_game", rejoin_meanwhile)
    sio.emit.reset_mock()
    await asyncio.sleep(0.05)

    sequence = presence_sequence(sio)
    assert sequence[0] == ("joined", "connected")
    assert ("left", "absent") not in sequence[1:], sequence
    await context.timers.close()


def messages_to(sio, room, sid: str) -> list[str]:
    """Every message the socket receives: its own emits, and room broadcasts
    it is not skipped from. The acknowledgement is not an emit; callers add it."""
    received = []
    for call in sio.emit.await_args_list:
        to = call.kwargs.get("to")
        targets = to if isinstance(to, list) else [to] if to else []
        broadcast = call.kwargs.get("room") == room.id and call.kwargs.get("skip_sid") != sid
        if sid in targets or broadcast:
            received.append(call.args[0])
    return received


def guessing_room(hint_mode="purchase"):
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True, hint_mode=hint_mode)
    drawer = room_manager.add_player(room, "Drawer")
    guesser = room_manager.add_player(room, "Guesser")
    other = room_manager.add_player(room, "Other")
    drawer.sid, guesser.sid, other.sid = "drawer-sid", "guesser-sid", "other-sid"
    room.state = "playing"
    room.game = Game(turn_order=[drawer.id, guesser.id, other.id], prompt_pool=["banana"], hint_mode=hint_mode)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game.choose_prompt(drawer.id, "banana")
    room.game.set_phase_deadline(room.game.drawing_seconds)
    sio, context = server(room_manager, {"room_id": room.id, "player_id": guesser.id})
    return room, sio, context


async def test_a_private_result_is_one_message_with_its_acknowledgement():
    """#884: what only the acting seat sees rides the answer to its command.
    Counted as the seat receives it, the acknowledgement included."""
    room, sio, context = guessing_room()
    answer = await sio.handlers["/"]["buy_hint"]("guesser-sid", {"slot": 0})
    assert answer["ok"] and messages_to(sio, room, "guesser-sid") == []  # + the ack: 1, was 2

    sio.emit.reset_mock()
    answer = await sio.handlers["/"]["guess"]("guesser-sid", {"text": "bananas", "id": 1})
    assert answer["verdict"]["code"] == "guess_very_close"
    assert messages_to(sio, room, "guesser-sid") == []  # + the ack: 1, was 3

    sio.emit.reset_mock()
    answer = await sio.handlers["/"]["guess"]("guesser-sid", {"text": "banana", "id": 2})
    assert answer["correct"]["prompt"] == "banana"
    assert messages_to(sio, room, "guesser-sid") == ["correct_guess"]  # + the ack: 2, was 4
    await stop_phase_timer(context, room)
    await context.timers.close()


async def test_a_wheel_letter_is_one_message_with_its_acknowledgement():
    room, sio, context = guessing_room(hint_mode="wheel")
    answer = await sio.handlers["/"]["buy_wheel_letter"]("guesser-sid", {"letter": "a"})
    assert answer["ok"] and answer["line"]["code"] == "hint_letter_found"
    assert messages_to(sio, room, "guesser-sid") == []  # + the ack: 1, was 3
    await context.timers.close()

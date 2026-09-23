"""Audience-aware chat persistence and bounded cleanup.

R-MOD-21 for the flush a report waits on, #972 for the batching.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
import socketio
from sqlalchemy import select

from app.db.models import (
    GameParticipant,
    GameRecord,
    RoomMessage,
    TurnParticipantOutcome,
    TurnRecord,
    User,
    generate_uuid,
)
from app.game import Game
from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager
from app.services.message_retention import (
    MESSAGE_RETENTION,
    SHUTDOWN_DRAIN_SECONDS,
    MessageRetentionService,
    purge_expired_room_messages,
)

from tests.dbfixtures import create_test_db


async def test_wrong_guess_is_retained_with_runtime_ids_and_actual_audience():
    factory, engine = await create_test_db()
    room_manager = RoomManager()
    try:
        user_ids = [UUID(int=index + 1) for index in range(3)]
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    User(id=user_id, display_name=f"Player {index}")
                    for index, user_id in enumerate(user_ids)
                )

        room = room_manager.create_room(name="Retained messages")
        drawer = room_manager.add_player(room, "Drawer", user_id=str(user_ids[0]))
        guesser = room_manager.add_player(room, "Guesser", user_id=str(user_ids[1]))
        observer = room_manager.add_player(room, "Observer", user_id=str(user_ids[2]))
        for player in (drawer, guesser, observer):
            player.sid = f"sid-{player.nickname.lower()}"
        room.state = "playing"
        room.game = Game(
            turn_order=[drawer.id, guesser.id, observer.id], prompt_pool=["panda"]
        )
        room.game.start_next_turn(
            canvas_generation=room.allocate_canvas_generation()
        )
        room.game.choose_prompt(drawer.id, "panda")
        room.game.set_phase_deadline(room.game.drawing_seconds)
        runtime_turn_id = room.game.current_turn_id

        sio = socketio.AsyncServer(async_mode="asgi")
        context = register_handlers(sio, room_manager, session_factory=factory)
        sio.get_session = AsyncMock(
            return_value={"room_id": room.id, "player_id": guesser.id}
        )
        sio.emit = AsyncMock()

        await sio.handlers["/"]["guess"](guesser.sid, {"text": "stone"})
        # Retention no longer holds up the message it retains, so the
        # write it queued is what this waits for.
        await context.message_retention.drain()

        async with factory() as session:
            message = await session.scalar(select(RoomMessage))
        assert message is not None
        assert UUID(str(message.id)).version == 7
        assert str(message.game_id) == room.game.id
        assert str(message.turn_id) == runtime_turn_id
        assert str(message.sender_seat_id) == room.game.history_seat_ids[guesser.id]
        assert message.message_kind == "wrong_guess"
        assert message.audience == "room"
        assert message.near_miss_kind is None
        assert message.text == "stone"
        assert set(message.audience_user_ids) == {str(value) for value in user_ids}
        assert message.expires_at - message.created_at == MESSAGE_RETENTION
        emitted = next(
            call
            for call in sio.emit.await_args_list
            if call.args[0] == "chat_message"
        )
        # Retained, but not cited on the wire: nothing in a room reports a
        # line by id, and the UUID was most of a viewer's chat bytes (#869).
        assert "retainedMessageId" not in emitted.args[1]
        assert emitted.kwargs["room"] == room.id
        await context.timers.close()
    finally:
        await engine.dispose()


async def test_near_miss_audience_excludes_prompt_unaware_players_and_cleanup_is_bounded():
    factory, engine = await create_test_db()
    room_manager = RoomManager()
    try:
        user_ids = [UUID(int=index + 10) for index in range(3)]
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    User(id=user_id, display_name=f"Player {index}")
                    for index, user_id in enumerate(user_ids)
                )
        room = room_manager.create_room(name="Near misses")
        drawer = room_manager.add_player(room, "Drawer", user_id=str(user_ids[0]))
        guesser = room_manager.add_player(room, "Guesser", user_id=str(user_ids[1]))
        unaware = room_manager.add_player(room, "Unaware", user_id=str(user_ids[2]))
        for player in (drawer, guesser, unaware):
            player.sid = f"sid-{player.nickname.lower()}"
        room.state = "playing"
        room.game = Game(
            turn_order=[drawer.id, guesser.id, unaware.id], prompt_pool=["panda"]
        )
        room.game.start_next_turn(
            canvas_generation=room.allocate_canvas_generation()
        )
        room.game.choose_prompt(drawer.id, "panda")
        room.game.set_phase_deadline(room.game.drawing_seconds)

        sio = socketio.AsyncServer(async_mode="asgi")
        context = register_handlers(sio, room_manager, session_factory=factory)
        sio.get_session = AsyncMock(
            return_value={"room_id": room.id, "player_id": guesser.id}
        )
        sio.emit = AsyncMock()
        await sio.handlers["/"]["guess"](guesser.sid, {"text": "pandas"})
        # Retention no longer holds up the message it retains, so the
        # write it queued is what this waits for.
        await context.message_retention.drain()

        async with factory() as session:
            message = await session.scalar(select(RoomMessage))
        assert message is not None
        assert message.message_kind == "wrong_guess"
        assert message.audience == "prompt_aware"
        assert message.near_miss_kind == "close"
        assert set(message.audience_user_ids) == {
            str(user_ids[0]),
            str(user_ids[1]),
        }
        assert str(user_ids[2]) not in message.audience_user_ids

        removed = await purge_expired_room_messages(
            factory, now=message.created_at + timedelta(days=31)
        )
        assert removed == 1
        async with factory() as session:
            assert await session.scalar(select(RoomMessage)) is None
        await context.timers.close()
    finally:
        await engine.dispose()


async def test_wrong_guess_text_expires_but_per_seat_outcomes_remain():
    factory, engine = await create_test_db()
    now = datetime.now(timezone.utc)
    drawer_id = generate_uuid()
    guesser_id = generate_uuid()
    game_id = generate_uuid()
    turn_id = generate_uuid()
    drawer_seat_id = generate_uuid()
    guesser_seat_id = generate_uuid()
    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        User(id=drawer_id, display_name="Drawer"),
                        User(id=guesser_id, display_name="Guesser"),
                    ]
                )
                await session.flush()
                session.add_all(
                    [
                        GameRecord(
                            id=game_id,
                            room_name="Retention decision",
                            scoring_mode="default",
                            hint_mode="none",
                            drawing_seconds=90,
                            total_rounds=1,
                            player_count=2,
                            started_at=now - timedelta(days=31, minutes=2),
                            finished_at=now - timedelta(days=31),
                        ),
                        GameParticipant(
                            id=drawer_seat_id,
                            game_id=game_id,
                            user_id=drawer_id,
                            final_score=0,
                            final_rank=1,
                        ),
                        GameParticipant(
                            id=guesser_seat_id,
                            game_id=game_id,
                            user_id=guesser_id,
                            final_score=0,
                            final_rank=1,
                        ),
                        TurnRecord(
                            id=turn_id,
                            game_id=game_id,
                            round_number=1,
                            turn_number=1,
                            drawer_user_id=drawer_id,
                            drawer_participant_id=drawer_seat_id,
                            prompt="panda",
                            duration_seconds=90,
                            wrong_guess_count=20,
                            near_miss_count=3,
                        ),
                        TurnParticipantOutcome(
                            game_id=game_id,
                            turn_id=turn_id,
                            participant_id=guesser_seat_id,
                            eligible=True,
                            eligibility_reason="eligible",
                            outcome="incorrect",
                            terminal_state="active",
                            wrong_guess_count=20,
                            near_miss_count=3,
                        ),
                        RoomMessage(
                            id=generate_uuid(),
                            room_instance_id=generate_uuid(),
                            game_id=game_id,
                            turn_id=turn_id,
                            sender_user_id=guesser_id,
                            sender_player_id=generate_uuid(),
                            sender_seat_id=guesser_seat_id,
                            sender_display_name_snapshot="Guesser",
                            sender_is_anonymous_snapshot=False,
                            is_spectator=False,
                            message_kind="wrong_guess",
                            audience="prompt_aware",
                            audience_user_ids=[str(drawer_id), str(guesser_id)],
                            near_miss_kind="close",
                            text="panther",
                            created_at=now - timedelta(days=31),
                            expires_at=now - timedelta(days=1),
                        ),
                    ]
                )

        assert await purge_expired_room_messages(factory, now=now) == 1
        async with factory() as session:
            assert await session.scalar(select(RoomMessage)) is None
            outcome = await session.scalar(select(TurnParticipantOutcome))
            assert outcome is not None
            assert outcome.outcome == "incorrect"
            assert outcome.wrong_guess_count == 20
            assert outcome.near_miss_count == 3
            turn = await session.get(TurnRecord, turn_id)
            assert turn is not None
            assert turn.wrong_guess_count == 20
            assert turn.near_miss_count == 3
    finally:
        await engine.dispose()


class HangingFactory:
    """A database that accepts the connection and then never answers."""

    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    def __call__(self):
        return self

    async def __aenter__(self):
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.cancelled.set()

    async def __aexit__(self, *_exc):
        return False


async def close_hanging_service(service, monkeypatch):
    # The availability/queue assertions have finished. Exercise expiration
    # through the same aclose path, without waiting out its five-second
    # production budget in every test. Successful draining stays real below.
    monkeypatch.setattr(service._queue, "join", AsyncMock(side_effect=TimeoutError))
    await service.aclose()


async def test_a_hung_database_does_not_delay_the_message_it_retains(monkeypatch):
    """The boundary this service exists for: live availability does not depend
    on retention. Chat used to wait for the transaction, so a lock or a slow
    disk was chat latency for every room at once."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Still talking")
    player = room_manager.add_player(room, "Talker", user_id=str(generate_uuid()))
    player.sid = "sid-talker"
    sio = socketio.AsyncServer(async_mode="asgi")
    context = register_handlers(sio, room_manager, session_factory=HangingFactory())
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": player.id}
    )
    sio.emit = AsyncMock()

    answer = await asyncio.wait_for(
        sio.handlers["/"]["send_chat"](player.sid, {"text": "anyone there?"}),
        timeout=5,
    )

    assert answer == {"ok": True}
    emitted = next(
        call for call in sio.emit.await_args_list if call.args[0] == "chat_message"
    )
    assert emitted.args[1]["text"] == "anyone there?"
    await context.timers.close()
    await close_hanging_service(context.message_retention, monkeypatch)


async def test_a_message_is_not_promised_when_the_queue_is_already_full(monkeypatch):
    """A database that has stopped answering costs bounded memory and nothing
    else. The line still goes out; what it does not get is an identifier
    promising it can be reported."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Backed up")
    player = room_manager.add_player(room, "Talker", user_id=str(generate_uuid()))
    player.sid = "sid-talker"
    service = MessageRetentionService(HangingFactory(), queue_depth=1)

    first = await service.record(
        room=room,
        player=player,
        text="one",
        message_kind="chat",
        audience="room",
        recipient_sids=[player.sid],
    )
    await asyncio.sleep(0)  # let the worker take the first one off the queue
    second = await service.record(
        room=room,
        player=player,
        text="two",
        message_kind="chat",
        audience="room",
        recipient_sids=[player.sid],
    )
    third = await service.record(
        room=room,
        player=player,
        text="three",
        message_kind="chat",
        audience="room",
        recipient_sids=[player.sid],
    )

    assert first is not None and second is not None
    assert third is None
    await close_hanging_service(service, monkeypatch)


async def test_shutdown_uses_the_production_budget_and_cancels_a_hung_writer(monkeypatch, caplog):
    factory = HangingFactory()
    service = MessageRetentionService(factory, queue_depth=1)
    await service.record_lobby(
        user_id=str(generate_uuid()), display_name="Ada", name_color=None,
        is_anonymous=True, text="waiting", sent_at=datetime.now(timezone.utc),
    )
    await asyncio.wait_for(factory.started.wait(), timeout=5)
    worker = service._worker
    try:
        assert SHUTDOWN_DRAIN_SECONDS == 5
        with patch.object(asyncio, "wait_for", wraps=asyncio.wait_for) as wait_for:
            await close_hanging_service(service, monkeypatch)
        assert wait_for.call_args.kwargs == {"timeout": SHUTDOWN_DRAIN_SECONDS}
        assert worker.done() and worker.cancelled()
        assert factory.cancelled.is_set()
        assert "Gave up retaining" in caplog.text
        assert service._worker is None
        await service.aclose()  # closing again is harmless
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_what_is_still_queued_at_shutdown_is_written():
    factory, engine = await create_test_db()
    room_manager = RoomManager()
    try:
        room = room_manager.create_room(name="Last words")
        talker_id = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(User(id=talker_id, display_name="Talker"))
        player = room_manager.add_player(room, "Talker", user_id=str(talker_id))
        player.sid = "sid-talker"
        service = MessageRetentionService(factory)

        retained_id = await service.record(
            room=room,
            player=player,
            text="goodbye",
            message_kind="chat",
            audience="room",
            recipient_sids=[player.sid],
        )
        await service.aclose()

        async with factory() as session:
            message = await session.scalar(select(RoomMessage))
        assert message is not None
        assert str(message.id) == retained_id
        assert message.text == "goodbye"
    finally:
        await engine.dispose()


async def test_a_lobby_line_is_kept_with_no_room_and_a_public_audience():
    """Said to every lobby that was open: no room to scope it to, no seat that
    said it, and no recipient list worth writing down - the audience value is
    what the moderation API reads instead."""
    factory, engine = await create_test_db()
    try:
        speaker = UUID(int=7)
        async with factory() as session:
            async with session.begin():
                session.add(User(id=speaker, display_name="Ada"))
        service = MessageRetentionService(factory)
        said_at = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)

        message_id = await service.record_lobby(
            user_id=str(speaker),
            display_name="Ada",
            name_color="#4f9",
            is_anonymous=False,
            text="anyone up for a round?",
            sent_at=said_at,
        )
        assert message_id is not None
        await service.drain()

        async with factory() as session:
            message = await session.scalar(select(RoomMessage))
        assert message is not None
        assert str(message.id) == message_id
        assert UUID(message_id).version == 7
        assert message.room_instance_id is None
        assert message.sender_player_id is None
        assert message.sender_seat_id is None
        assert message.game_id is None and message.turn_id is None
        assert message.sender_user_id == speaker
        assert message.sender_display_name_snapshot == "Ada"
        assert message.sender_name_color_snapshot == "#4f9"
        assert message.message_kind == "chat"
        assert message.audience == "lobby"
        assert message.audience_user_ids == []
        assert message.text == "anyone up for a round?"
        assert message.created_at == said_at
        assert message.expires_at - message.created_at == MESSAGE_RETENTION
        await service.aclose()
    finally:
        await engine.dispose()


async def test_a_lobby_line_is_not_promised_when_the_queue_is_already_full(monkeypatch):
    """The same bargain as room chat: the line goes out, the identifier does
    not, and nothing waits on the database to find that out."""
    service = MessageRetentionService(HangingFactory(), queue_depth=1)
    said_at = datetime.now(timezone.utc)

    def line(text):
        return service.record_lobby(
            user_id=str(generate_uuid()),
            display_name="Ada",
            name_color=None,
            is_anonymous=True,
            text=text,
            sent_at=said_at,
        )

    first = await line("one")
    await asyncio.sleep(0)
    second = await line("two")
    third = await line("three")
    assert first is not None and second is not None
    assert third is None
    await close_hanging_service(service, monkeypatch)


async def test_a_lobby_line_with_no_account_behind_it_is_not_kept():
    service = MessageRetentionService(HangingFactory())
    assert (
        await service.record_lobby(
            user_id="not-an-id",
            display_name="Ada",
            name_color=None,
            is_anonymous=True,
            text="hello",
            sent_at=datetime.now(timezone.utc),
        )
        is None
    )
    await service.aclose()


async def _talking_room(factory):
    """A room with one account-backed seat that can be retained."""
    room = RoomManager().create_room(name="Chatty")
    talker_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(User(id=talker_id, display_name="Talker"))
    player = RoomManager().add_player(room, "Talker", user_id=str(talker_id))
    player.sid = "sid-talker"
    return room, player


def _counting_writes(service) -> list[int]:
    """Record the size of every batch the service writes."""
    sizes: list[int] = []
    write = service._write

    async def counted(batch):
        sizes.append(len(batch))
        await write(batch)

    service._write = counted
    return sizes


async def _say(service, room, player, text):
    return await service.record(
        room=room, player=player, text=text, message_kind="chat",
        audience="room", recipient_sids=[player.sid],
    )


async def test_lines_said_a_moment_apart_are_written_in_one_batch():
    """Rooms talk a line at a time, never two in one instant, so taking only
    what was already queued wrote a transaction per line (#972). The writer
    waits a moment after the first line for the rest of its batch."""
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=0.5)
        sizes = _counting_writes(service)
        for index in range(5):
            await _say(service, room, player, f"line {index}")
            await asyncio.sleep(0.02)
        # Not `drain`, which cuts the linger short: this waits the way the
        # production writer does between two ordinary lines.
        await asyncio.wait_for(service._queue.join(), timeout=5)
        assert sizes == [5]
        async with factory() as session:
            kept = (await session.scalars(select(RoomMessage.text))).all()
        assert sorted(kept) == [f"line {index}" for index in range(5)]
        await service.aclose()
    finally:
        await engine.dispose()


async def test_drain_does_not_wait_out_the_linger():
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=60)
        await _say(service, room, player, "now, please")
        await asyncio.sleep(0)  # the writer holds the line and starts to linger
        await asyncio.wait_for(service.drain(), timeout=5)
        async with factory() as session:
            assert await session.scalar(select(RoomMessage.text)) == "now, please"
        await asyncio.wait_for(service.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_a_full_batch_is_written_without_waiting_out_the_linger():
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, batch_size=3, linger_seconds=60)
        sizes = _counting_writes(service)
        await _say(service, room, player, "one")
        await asyncio.sleep(0)
        await _say(service, room, player, "two")
        await _say(service, room, player, "three")
        await asyncio.wait_for(service._queue.join(), timeout=5)
        assert sizes == [3]
        await asyncio.wait_for(service.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_flush_waits_for_what_was_queued_and_no_longer():
    """Not `queue.join()`: that waits for lines other rooms enqueue while the
    report is waiting, and on a busy server a report could wait a long time
    for messages it never cited (#972 review).

    The first write is stalled, so the flush is genuinely in flight while the
    rest of the server talks: against a `join()`-based flush the chatter's
    rows are part of what it waits for, and it does not return here.
    """
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=0.01)
        held = asyncio.Event()
        released = asyncio.Event()
        real_write = service._write

        async def stalled_write(batch):
            held.set()
            await released.wait()
            await real_write(batch)

        service._write = stalled_write
        await _say(service, room, player, "cited line")
        await asyncio.wait_for(held.wait(), timeout=2)
        service._write = real_write
        target = service._enqueued
        assert target == 1

        keep_talking = True
        said = 0

        async def another_room_keeps_talking():
            nonlocal said
            while keep_talking:
                await _say(service, room, player, "somebody else")
                said += 1
                await asyncio.sleep(0.005)

        chatter = asyncio.create_task(another_room_keeps_talking())
        flushing = asyncio.create_task(service.flush())
        await asyncio.sleep(0.05)
        # A flush is not a drain: everyone else keeps lingering while it waits.
        assert service._draining == 0
        assert not flushing.done() and said > 0
        released.set()
        await asyncio.wait_for(flushing, timeout=2)
        # It returned on its own row, with the chatter's still outstanding.
        assert service._written >= target
        assert service._enqueued > target
        keep_talking = False
        await chatter
        async with factory() as session:
            kept = (await session.scalars(select(RoomMessage.text))).all()
        assert "cited line" in kept
        await asyncio.wait_for(service.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_a_flush_that_lands_before_the_linger_still_cuts_it():
    """The cut is state the writer reads, not a signal it can clear: a flush
    arriving between the line and the writer's linger used to be swallowed by
    the `clear()` at the top of it, and paid the whole window (#972 third
    review)."""
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=30)
        await _say(service, room, player, "cited line")
        # No `await` in between: the writer has not run at all yet, so it
        # reaches its linger after the flush has asked for the cut.
        started = time.monotonic()
        await asyncio.wait_for(service.flush(), timeout=5)
        assert time.monotonic() - started < 1
        async with factory() as session:
            assert await session.scalar(select(RoomMessage.text)) == "cited line"
        await asyncio.wait_for(service.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_a_flush_lands_on_a_writer_already_inside_its_linger():
    """The other half of the cut. Once the writer is suspended in the linger
    it has already read `_cut`, so only the event reaches it: deleting
    `_wake.set()` from `flush` left every test green (#972 fourth review)."""
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=30)
        await _say(service, room, player, "cited line")
        # Long enough for the writer to take the row and suspend itself inside
        # `wait_for(self._wake.wait())`, which is the case `_cut` cannot cut.
        for _ in range(50):
            await asyncio.sleep(0.005)
            if not service._wake.is_set() and service._queue.qsize() == 0:
                break
        started = time.monotonic()
        await asyncio.wait_for(service.flush(), timeout=5)
        assert time.monotonic() - started < 1
        async with factory() as session:
            assert await session.scalar(select(RoomMessage.text)) == "cited line"
        await asyncio.wait_for(service.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_a_cancelled_writer_settles_the_batch_it_was_holding():
    """Counted where it happens, not repaired later: `_ensure_worker`'s
    reconciliation rescued the observable behaviour, so the settle on the way
    out was dead to every test (#972 fourth review)."""
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=30)
        await _say(service, room, player, "lost to the cancellation")
        await asyncio.sleep(0)
        service._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await service._worker

        assert service._written == service._enqueued == 1
        assert service._queue._unfinished_tasks == 0, "join would wait for ever"
    finally:
        await engine.dispose()


async def test_a_flush_that_gave_up_stops_holding_the_linger_open():
    """The cut is process-wide: left standing by a flush that timed out on a
    stalled database, it would go on cutting every room's linger short - the
    batching this exists for - until the writer caught up (#972 fourth
    review)."""
    factory, engine = await create_test_db()
    monkey = MessageRetentionService(factory, linger_seconds=30)
    try:
        room, player = await _talking_room(factory)
        held = asyncio.Event()

        async def never(_batch):
            await held.wait()

        monkey._write = never
        await _say(monkey, room, player, "unwritable")
        with patch("app.services.message_retention.EVIDENCE_FLUSH_SECONDS", 0.05):
            await asyncio.wait_for(monkey.flush(), timeout=5)

        assert monkey._cut == monkey._written, "the cut is not left standing"
        held.set()
        await asyncio.wait_for(monkey.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_a_line_said_during_shutdown_leaves_no_writer_behind():
    """`aclose` used to let go of the writer before draining, so a line
    recorded while it drained started a second one - which nothing cancelled,
    and which the lost-row reconciliation, written for a single writer, could
    not account for (#972 fourth review)."""
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=0)
        await _say(service, room, player, "before the shutdown")
        worker = service._worker

        closing = asyncio.create_task(service.aclose())
        await asyncio.sleep(0)
        await _say(service, room, player, "said during the shutdown")
        await asyncio.wait_for(closing, timeout=5)

        assert service._worker is None
        assert worker.done(), "the writer aclose held is the one it stopped"
        writers = [
            task
            for task in asyncio.all_tasks()
            if not task.done() and "_write_queued" in repr(task.get_coro())
        ]
        assert writers == [], "no second writer outlives the shutdown"
    finally:
        await engine.dispose()


async def test_the_counters_follow_the_whole_batch_not_one_row():
    """`_written` counts rows, not batches: counting one per batch leaves it
    permanently behind `_enqueued`, and a cut that stays above it suppresses
    every linger in the process with nothing logged (#972 fifth review)."""
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, batch_size=10, linger_seconds=0.02)
        for index in range(5):
            await _say(service, room, player, f"line {index}")
        await asyncio.wait_for(service.drain(), timeout=5)

        assert service._enqueued == 5
        assert service._written == 5
        assert service._queue._unfinished_tasks == 0
        await asyncio.wait_for(service.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_a_flush_that_finishes_first_leaves_the_others_their_cut():
    """The cut is shared. Lowering it when *a* reader is done, rather than
    when the last one is, drops the cut the others are still waiting on and
    they pay the whole linger - the 254 ms regression, one layer along. It
    passed every test (#972 fifth review)."""
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, batch_size=1, linger_seconds=30)
        gates: list[asyncio.Event] = []
        real_write = service._write

        async def one_gate_per_batch(batch):
            gate = asyncio.Event()
            gates.append(gate)
            await gate.wait()
            await real_write(batch)

        service._write = one_gate_per_batch
        await _say(service, room, player, "first")
        await asyncio.sleep(0.02)
        early = asyncio.create_task(service.flush())  # needs one row
        await asyncio.sleep(0.02)
        await _say(service, room, player, "second")
        later = asyncio.create_task(service.flush())  # needs both
        await asyncio.sleep(0.02)

        gates[0].set()  # the first batch lands; the early reader is satisfied
        await asyncio.wait_for(early, timeout=5)
        assert not later.done()
        assert service._cut == 2, "the reader still waiting keeps its cut"

        for gate in gates[1:]:
            gate.set()
        await asyncio.wait_for(later, timeout=5)
        assert service._flushing == 0
        assert service._cut == service._written, "and nothing is left holding it"
        service._write = real_write
        await asyncio.wait_for(service.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_a_line_said_while_closing_is_not_kept(caplog):
    """`aclose` stops the writer; a line taken meanwhile would start a second
    one that nothing cancels and that the counters do not describe (#972 fifth
    review)."""
    import logging

    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=0)
        await _say(service, room, player, "before the shutdown")
        await asyncio.wait_for(service.aclose(), timeout=5)

        with caplog.at_level(logging.WARNING):
            assert await _say(service, room, player, "after the shutdown") is None
        assert "closing" in caplog.text
        assert service._worker is None
    finally:
        await engine.dispose()


async def test_a_flush_after_a_writer_was_lost_does_not_wait_out_its_bound(caplog):
    """A writer cancelled while lingering takes its batch with it. Unaccounted,
    those rows leave `flush` waiting its whole bound - and `drain` waiting for
    ever - on rows nobody holds any more (#972 third review)."""
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=30)
        await _say(service, room, player, "lost to the cancellation")
        await asyncio.sleep(0)  # the writer holds the line and starts to linger
        service._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await service._worker

        await _say(service, room, player, "cited line")
        started = time.monotonic()
        await asyncio.wait_for(service.flush(), timeout=5)
        assert time.monotonic() - started < 1
        await asyncio.wait_for(service.drain(), timeout=5)
        async with factory() as session:
            kept = (await session.scalars(select(RoomMessage.text))).all()
        assert "cited line" in kept
        await asyncio.wait_for(service.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_a_writer_that_died_another_way_is_reconciled_too(caplog):
    """Not only cancellation: a writer that ends any other way took rows with
    it, and the replacement counts them against what is still queued rather
    than leaving every later flush short (#972 third review)."""
    factory, engine = await create_test_db()
    try:
        room, player = await _talking_room(factory)
        service = MessageRetentionService(factory, linger_seconds=30)
        failing = asyncio.Event()

        async def die(self=service):
            failing.set()
            raise RuntimeError("the writer stopped")

        service._linger = die
        await _say(service, room, player, "lost to the failure")
        await asyncio.wait_for(failing.wait(), timeout=2)
        with contextlib.suppress(RuntimeError):
            await service._worker
        del service._linger

        await _say(service, room, player, "cited line")
        started = time.monotonic()
        await asyncio.wait_for(service.flush(), timeout=5)
        assert time.monotonic() - started < 1
        async with factory() as session:
            kept = (await session.scalars(select(RoomMessage.text))).all()
        assert "cited line" in kept
        await asyncio.wait_for(service.aclose(), timeout=5)
    finally:
        await engine.dispose()


async def test_flush_gives_up_on_a_database_that_has_stopped_answering(monkeypatch, caplog):
    """Bounded: a report reads what is there rather than waiting for ever."""
    import logging

    from app.services.message_retention import EVIDENCE_FLUSH_SECONDS

    assert EVIDENCE_FLUSH_SECONDS == 2
    monkeypatch.setattr(
        "app.services.message_retention.EVIDENCE_FLUSH_SECONDS", 0.05
    )
    room_manager = RoomManager()
    room = room_manager.create_room(name="Hung")
    player = room_manager.add_player(room, "Talker", user_id=str(generate_uuid()))
    player.sid = "sid-talker"
    service = MessageRetentionService(HangingFactory())
    caplog.set_level(logging.WARNING)
    await _say(service, room, player, "never written")
    await asyncio.wait_for(service.flush(), timeout=2)
    assert "not flushed" in caplog.text
    await close_hanging_service(service, monkeypatch)


async def test_the_linger_is_skipped_while_anybody_is_draining_and_when_a_batch_is_full():
    """The two early exits, directly: without them a drain waits out the
    linger, and a full batch sits still while more arrives (#972 review)."""
    factory, engine = await create_test_db()
    try:
        service = MessageRetentionService(factory, batch_size=2, linger_seconds=60)
        service._draining = 1
        await asyncio.wait_for(service._linger(), timeout=1)  # draining: no wait
        service._draining = 0
        service._queue.put_nowait(object())  # qsize 1 >= batch_size - 1
        await asyncio.wait_for(service._linger(), timeout=1)  # full: no wait
        service._queue.get_nowait()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(service._linger(), timeout=0.2)  # otherwise it waits
    finally:
        await engine.dispose()

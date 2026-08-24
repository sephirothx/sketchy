import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.game import Game, Phase
from app.rooms import RoomManager


@pytest.mark.asyncio
async def test_toggle_afk_socket_handler_and_not_waited_for():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    room.state = "playing"
    room.game = Game(turn_order=[p1.id, p2.id, p3.id], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    room.game._set_prompt("banana")

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "p1-sid": {"room_id": room.id, "player_id": p1.id},
        "p2-sid": {"room_id": room.id, "player_id": p2.id},
        "p3-sid": {"room_id": room.id, "player_id": p3.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    toggle_afk = sio.handlers["/"]["toggle_afk"]
    guess = sio.handlers["/"]["guess"]

    # P2 guesses correctly
    await guess("p2-sid", {"text": "banana"})
    # Round is not ended yet because P3 hasn't guessed
    assert room.game.phase == Phase.DRAWING

    # P3 goes AFK -> P3 is no longer waited for -> round ends immediately!
    await toggle_afk("p3-sid", {"afk": True})
    assert p3.is_afk is True
    assert room.game.phase == Phase.TURN_RESULTS

    timer = timers.phase_timers.pop(room.id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer

@pytest.mark.asyncio
async def test_vote_kick_and_vote_afk_socket_handlers():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "player_id": p1.id},
        "p2-sid": {"room_id": room.id, "player_id": p2.id},
        "p3-sid": {"room_id": room.id, "player_id": p3.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    vote_player = sio.handlers["/"]["vote_player"]

    # P1 votes to AFK P2 (required = 2 votes because 2 other connected players)
    res1 = await vote_player("p1-sid", {"targetPlayerId": p2.id, "action": "afk"})
    assert res1["ok"] is True
    assert res1["executed"] is False
    assert p1.id in p2.afk_votes
    assert p2.is_afk is False

    # P3 votes to AFK P2 -> threshold reached -> P2 is marked AFK
    res2 = await vote_player("p3-sid", {"targetPlayerId": p2.id, "action": "afk"})
    assert res2["ok"] is True
    assert res2["executed"] is True
    assert p2.is_afk is True

    # P1 votes to Kick P2
    res3 = await vote_player("p1-sid", {"targetPlayerId": p2.id, "action": "kick"})
    assert res3["ok"] is True
    assert res3["executed"] is False

    # P3 votes to Kick P2 -> threshold reached -> P2 is kicked
    res4 = await vote_player("p3-sid", {"targetPlayerId": p2.id, "action": "kick"})
    assert res4["ok"] is True
    assert res4["executed"] is True
    assert p2.id not in room.players

    # Emitted kicked event to P2
    kicked_calls = [call for call in sio.emit.await_args_list if call.args[0] == "kicked" and call.kwargs.get("to") == "p2-sid"]
    assert len(kicked_calls) == 1

@pytest.mark.asyncio
async def test_direct_socket_moderation_rejects_spectator_voters_and_targets():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    voter = room_manager.add_player(room, "Voter")
    target = room_manager.add_player(room, "Target")
    afk_voter = room_manager.add_player(room, "AFK voter")
    spectator = room_manager.add_player(room, "Spectator", is_spectator=True)
    voter.sid = "voter-sid"
    target.sid = "target-sid"
    afk_voter.sid = "afk-sid"
    spectator.sid = "spectator-sid"
    afk_voter.is_afk = True

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "voter-sid": {"room_id": room.id, "player_id": voter.id},
        "target-sid": {"room_id": room.id, "player_id": target.id},
        "afk-sid": {"room_id": room.id, "player_id": afk_voter.id},
        "spectator-sid": {"room_id": room.id, "player_id": spectator.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()
    vote_player = sio.handlers["/"]["vote_player"]

    spectator_vote = await vote_player(
        "spectator-sid", {"targetPlayerId": target.id, "action": "kick"}
    )
    assert spectator_vote == {"ok": False, "error": "Spectators cannot vote"}
    assert target.kick_votes == set()

    spectator_target = await vote_player(
        "voter-sid", {"targetPlayerId": spectator.id, "action": "kick"}
    )
    assert spectator_target == {
        "ok": False,
        "error": "Spectators cannot be moderation targets",
    }
    assert spectator.kick_votes == set()

    first_vote = await vote_player(
        "voter-sid", {"targetPlayerId": target.id, "action": "afk"}
    )
    assert first_vote == {"ok": True, "action": "afk", "executed": False}

    # AFK players remain eligible. The spectator does not raise the threshold
    # beyond two votes from the three connected non-spectator players.
    second_vote = await vote_player(
        "afk-sid", {"targetPlayerId": target.id, "action": "afk"}
    )
    assert second_vote == {"ok": True, "action": "afk", "executed": True}
    assert target.is_afk is True

@pytest.mark.asyncio
async def test_votes_removed_when_player_leaves_or_disconnects():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "player_id": p1.id},
        "p2-sid": {"room_id": room.id, "player_id": p2.id},
        "p3-sid": {"room_id": room.id, "player_id": p3.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()

    vote_player = sio.handlers["/"]["vote_player"]
    disconnect = sio.handlers["/"]["disconnect"]

    # P1 votes to AFK P2
    await vote_player("p1-sid", {"targetPlayerId": p2.id, "action": "afk"})
    assert p1.id in p2.afk_votes

    # P1 disconnects -> P1's votes are removed from P2
    await disconnect("p1-sid")
    assert p1.id not in p2.afk_votes


async def _drain_phase_timer(timers, room_id: str) -> None:
    timer = timers.phase_timers.pop(room_id, None)
    if timer:
        timer.cancel()
        with suppress(asyncio.CancelledError):
            await timer


def _afk_room_on_its_final_turn():
    """A three-player, one-round game sitting on turn 3 of 3, still choosing."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    room.state = "playing"
    room.game = Game(turn_order=[p1.id, p2.id, p3.id], rounds_total=1)
    for _ in range(3):
        room.game.start_next_turn(
            canvas_generation=room.allocate_canvas_generation()
        )
    assert room.game.is_finished()
    assert room.game.current_drawer == p3.id
    assert room.game.phase == Phase.CHOOSING_PROMPT

    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sessions = {
        "p1-sid": {"room_id": room.id, "player_id": p1.id},
        "p2-sid": {"room_id": room.id, "player_id": p2.id},
        "p3-sid": {"room_id": room.id, "player_id": p3.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()
    return room_manager, room, (p1, p2, p3), sio, ctx


def _emitted(sio, event: str) -> bool:
    return any(call.args[0] == event for call in sio.emit.await_args_list)


@pytest.mark.asyncio
async def test_afk_toggle_by_final_drawer_ends_the_game_instead_of_overrunning():
    """Going AFK while choosing the last prompt must not buy the room a bonus turn."""
    _, room, (_, _, p3), sio, ctx = _afk_room_on_its_final_turn()

    await sio.handlers["/"]["toggle_afk"]("p3-sid", {"afk": True})

    assert p3.is_afk is True
    assert room.game is None
    assert room.state == "waiting"
    assert _emitted(sio, "game_ended")
    # Advancing instead would have wrapped the rotation and reported round 2
    # of a one-round game.
    assert not _emitted(sio, "turn_starting")
    # Ending never reaches _start_turn, so nothing else retires the pending
    # prompt-choice timer.
    assert room.id not in ctx.timers.phase_timers


@pytest.mark.asyncio
async def test_vote_afk_on_final_drawer_ends_the_game_instead_of_overrunning():
    """The voted-AFK path has to end the game on the last turn as well."""
    _, room, (_, _, p3), sio, ctx = _afk_room_on_its_final_turn()
    vote_player = sio.handlers["/"]["vote_player"]

    await vote_player("p1-sid", {"targetPlayerId": p3.id, "action": "afk"})
    assert room.game is not None, "one vote is short of the majority"

    await vote_player("p2-sid", {"targetPlayerId": p3.id, "action": "afk"})

    assert p3.is_afk is True
    assert room.game is None
    assert room.state == "waiting"
    assert _emitted(sio, "game_ended")
    assert not _emitted(sio, "turn_starting")
    assert room.id not in ctx.timers.phase_timers


@pytest.mark.asyncio
async def test_afk_toggle_mid_game_still_advances_to_the_next_turn():
    """The fix must not end games early: only the final turn ends the game."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"

    room.state = "playing"
    room.game = Game(turn_order=[p1.id, p2.id, p3.id], rounds_total=2)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    assert not room.game.is_finished()
    assert room.game.current_drawer == p1.id

    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        side_effect=lambda sid: {"room_id": room.id, "player_id": p1.id}
    )
    sio.emit = AsyncMock()

    await sio.handlers["/"]["toggle_afk"]("p1-sid", {"afk": True})

    assert room.game is not None
    assert room.state == "playing"
    assert room.game.turn_index == 1
    assert room.game.current_drawer == p2.id
    assert room.game.phase == Phase.CHOOSING_PROMPT
    assert _emitted(sio, "turn_starting")
    assert not _emitted(sio, "game_ended")

    await _drain_phase_timer(ctx.timers, room.id)


@pytest.mark.asyncio
async def test_reporting_names_a_seat_and_never_an_account():
    """The room tells nobody another player's account id. A complaint is not a
    reason to start, so the seat is resolved server-side."""
    from uuid import UUID, uuid4

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import (
        AuditEvent,
        Base,
        PlayerReport,
        PlayerReportMessageEvidence,
        RoomMessage,
        User,
        generate_uuid,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    reporter_id, target_id = uuid4(), uuid4()
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    reporter = room_manager.add_player(
        room, "Reporter", user_id=str(reporter_id), is_anonymous=False
    )
    target = room_manager.add_player(
        room, "Target", user_id=str(target_id), is_anonymous=False
    )
    reporter.sid, target.sid = "reporter-sid", "target-sid"

    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        User(
                            id=reporter_id,
                            username="Reporter",
                            password_hash="hash",
                            display_name="Reporter",
                            state="registered",
                        ),
                        User(
                            id=target_id,
                            username="Target",
                            password_hash="hash",
                            display_name="Target",
                            state="registered",
                        ),
                    ]
                )
                now = datetime.now(timezone.utc)
                session.add_all(
                    [
                        RoomMessage(
                            id=generate_uuid(),
                            room_instance_id=UUID(room.retention_scope_id),
                            sender_user_id=target_id,
                            sender_player_id=UUID(target.id),
                            sender_display_name_snapshot="Target",
                            sender_is_anonymous_snapshot=False,
                            message_kind="chat",
                            audience="room",
                            text="something worth reporting",
                            audience_user_ids=[str(reporter_id), str(target_id)],
                            created_at=now,
                            expires_at=now + timedelta(hours=1),
                        ),
                        # Not shown to the reporter, so not theirs to submit.
                        RoomMessage(
                            id=generate_uuid(),
                            room_instance_id=UUID(room.retention_scope_id),
                            sender_user_id=target_id,
                            sender_player_id=UUID(target.id),
                            sender_display_name_snapshot="Target",
                            sender_is_anonymous_snapshot=False,
                            message_kind="chat",
                            audience="prompt_aware",
                            text="never delivered to the reporter",
                            audience_user_ids=[str(target_id)],
                            created_at=now,
                            expires_at=now + timedelta(hours=1),
                        ),
                    ]
                )

        sio = socketio.AsyncServer(async_mode="asgi")
        ctx = register_handlers(sio, room_manager)
        ctx.session_factory = factory
        sio.get_session = AsyncMock(
            return_value={"room_id": room.id, "player_id": reporter.id}
        )
        sio.emit = AsyncMock()

        result = await sio.handlers["/"]["report_player"](
            "reporter-sid",
            {
                "targetPlayerId": target.id,
                "reason": "harassment",
                "details": "Said the thing above.",
            },
        )

        assert result["ok"] is True
        # Only the message the reporter actually received.
        assert result["evidenceCount"] == 1

        async with factory() as session:
            report = await session.scalar(select(PlayerReport))
            assert report.reporter_user_id == reporter_id
            assert report.reported_user_id == target_id
            assert report.reason == "harassment"
            evidence = (
                await session.scalars(select(PlayerReportMessageEvidence))
            ).all()
            assert [line.text_snapshot for line in evidence] == [
                "something worth reporting"
            ]
            event = await session.scalar(
                select(AuditEvent).where(AuditEvent.event_type == "report.submitted")
            )
            assert event.target_id == str(target_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_same_player_cannot_be_reported_twice_while_it_waits():
    """Saying it again adds no evidence and buries the queue. Once a moderator
    has decided, the same reporter may raise a new one - that is a new
    incident rather than the same complaint repeated."""
    from uuid import uuid4

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.models import Base, PlayerReport, User
    from app.domain_values import ReportStatus

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    reporter_id, target_id = uuid4(), uuid4()
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    reporter = room_manager.add_player(
        room, "Reporter", user_id=str(reporter_id), is_anonymous=False
    )
    target = room_manager.add_player(
        room, "Target", user_id=str(target_id), is_anonymous=False
    )
    reporter.sid = "reporter-sid"

    try:
        async with factory() as session:
            async with session.begin():
                session.add_all(
                    User(
                        id=user_id,
                        username=name,
                        password_hash="hash",
                        display_name=name,
                        state="registered",
                    )
                    for user_id, name in (
                        (reporter_id, "Reporter"),
                        (target_id, "Target"),
                    )
                )

        sio = socketio.AsyncServer(async_mode="asgi")
        ctx = register_handlers(sio, room_manager)
        ctx.session_factory = factory
        sio.get_session = AsyncMock(
            return_value={"room_id": room.id, "player_id": reporter.id}
        )
        sio.emit = AsyncMock()

        body = {
            "targetPlayerId": target.id,
            "reason": "harassment",
            "details": "Said the thing.",
        }
        first = await sio.handlers["/"]["report_player"]("reporter-sid", body)
        second = await sio.handlers["/"]["report_player"]("reporter-sid", body)

        assert first["ok"] is True
        assert second["ok"] is False
        assert "already reported" in second["error"]
        async with factory() as session:
            assert await session.scalar(select(func.count(PlayerReport.id))) == 1

        # Reviewed, so the next complaint is a new incident.
        async with factory() as session:
            async with session.begin():
                report = await session.scalar(select(PlayerReport))
                report.status = ReportStatus.DISMISSED.value

        third = await sio.handlers["/"]["report_player"]("reporter-sid", body)
        assert third["ok"] is True
        async with factory() as session:
            assert await session.scalar(select(func.count(PlayerReport.id))) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_report_cannot_be_used_to_discover_who_is_in_a_room():
    """An unknown seat and your own seat answer identically."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    reporter = room_manager.add_player(
        room, "Reporter", user_id="00000000-0000-4000-8000-000000000001", is_anonymous=False
    )
    reporter.sid = "reporter-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": reporter.id}
    )
    sio.emit = AsyncMock()

    body = {"reason": "spam", "details": "x"}
    unknown = await sio.handlers["/"]["report_player"](
        "reporter-sid", {**body, "targetPlayerId": "not-a-seat"}
    )
    myself = await sio.handlers["/"]["report_player"](
        "reporter-sid", {**body, "targetPlayerId": reporter.id}
    )

    assert unknown == myself
    assert unknown["ok"] is False


@pytest.mark.asyncio
async def test_a_guest_is_told_to_claim_an_account_first():
    """There would be nobody for a moderator to follow up with."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    guest = room_manager.add_player(room, "Guest")
    other = room_manager.add_player(room, "Other")
    guest.sid = "guest-sid"

    sio = socketio.AsyncServer(async_mode="asgi")
    register_handlers(sio, room_manager)
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": guest.id}
    )
    sio.emit = AsyncMock()

    result = await sio.handlers["/"]["report_player"](
        "guest-sid",
        {"targetPlayerId": other.id, "reason": "spam", "details": "x"},
    )

    assert result["ok"] is False
    assert "account" in result["error"]

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import socketio

from app.handlers import register_all_handlers as register_handlers
from app.game import Game, Phase
from app.refusals import ErrorCode
from app.rooms import RoomManager

from tests.dbfixtures import create_test_db
from tests.handlers.helpers import SessionStore


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
    # The client says it from the code; the reason is English for a log.
    assert kicked_calls[0].args[1]["code"] == "kicked_by_vote"

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
    assert spectator_vote == {"ok": False, "errorCode": "spectators_cannot_vote", "error": "Spectators cannot vote"}
    assert target.kick_votes == set()

    spectator_target = await vote_player(
        "voter-sid", {"targetPlayerId": spectator.id, "action": "kick"}
    )
    assert spectator_target == {
        "ok": False,
        "errorCode": "spectators_cannot_be_targets",
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


async def test_reporting_names_a_seat_and_never_an_account():
    """The room tells nobody another player's account id. A complaint is not a
    reason to start, so the seat is resolved server-side."""
    from uuid import UUID, uuid4

    from sqlalchemy import select

    from app.db.models import (
        AuditEvent,
        PlayerReport,
        PlayerReportMessageEvidence,
        RoomMessage,
        User,
        generate_uuid,
    )

    factory, engine = await create_test_db()

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
                await session.flush()
                now = datetime.now(timezone.utc)
                session.add_all(
                    [
                        # What the reporter said just before: context, so
                        # the reported line reads as the answer it was.
                        RoomMessage(
                            id=generate_uuid(),
                            room_instance_id=UUID(room.retention_scope_id),
                            sender_user_id=reporter_id,
                            sender_player_id=UUID(reporter.id),
                            sender_display_name_snapshot="Reporter",
                            sender_is_anonymous_snapshot=False,
                            message_kind="chat",
                            audience="room",
                            text="nice drawing",
                            audience_user_ids=[str(reporter_id), str(target_id)],
                            created_at=now - timedelta(seconds=5),
                            expires_at=now + timedelta(hours=1),
                        ),
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
        # Only the message the reporter actually received, and only the
        # target's: the context around it is not counted as evidence.
        assert result["evidenceCount"] == 1

        async with factory() as session:
            report = await session.scalar(select(PlayerReport))
            assert report.reporter_user_id == reporter_id
            assert report.reported_user_id == target_id
            assert report.reason == "harassment"
            # The room this seat is sitting in, so this report meets the
            # others about the same incident (#620). Taken from the live
            # room, never from anything the client said.
            assert report.scope == "room"
            assert report.room_instance_id == UUID(room.retention_scope_id)
            evidence = (
                await session.scalars(
                    select(PlayerReportMessageEvidence).order_by(
                        PlayerReportMessageEvidence.position
                    )
                )
            ).all()
            # The thread, in the order it was said: the reporter's own line
            # as context, the target's as the cited one, and the line the
            # reporter never received in neither role.
            assert [(line.role, line.text_snapshot) for line in evidence] == [
                ("context", "nice drawing"),
                ("cited", "something worth reporting"),
            ]
            event = await session.scalar(
                select(AuditEvent).where(AuditEvent.event_type == "report.submitted")
            )
            assert event.target_id == str(target_id)
    finally:
        await engine.dispose()


async def test_the_same_player_cannot_be_reported_twice_while_it_waits():
    """Saying it again adds no evidence and buries the queue. Once a moderator
    has decided, the same reporter may raise a new one - that is a new
    incident rather than the same complaint repeated."""
    from uuid import uuid4

    from sqlalchemy import func, select

    from app.db.models import PlayerReport, User, generate_uuid
    from app.domain_values import ReportStatus

    factory, engine = await create_test_db()

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
                report.reviewed_at = datetime.now(timezone.utc)
                report.decision_group_id = generate_uuid()

        third = await sio.handlers["/"]["report_player"]("reporter-sid", body)
        assert third["ok"] is True
        async with factory() as session:
            assert await session.scalar(select(func.count(PlayerReport.id))) == 2
    finally:
        await engine.dispose()


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


def _report_room_with_a_drawer():
    """A registered reporter watching a registered drawer mid-turn."""
    from uuid import uuid4

    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    reporter = room_manager.add_player(
        room, "Reporter", user_id=str(uuid4()), is_anonymous=False
    )
    drawer = room_manager.add_player(
        room, "Drawer", user_id=str(uuid4()), is_anonymous=False
    )
    reporter.sid, drawer.sid = "reporter-sid", "drawer-sid"
    room.state = "playing"
    room.game = Game(turn_order=[drawer.id, reporter.id], rounds_total=1)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    assert room.game.current_drawer == drawer.id
    room.game.phase = Phase.DRAWING
    room.game.prompt = "cat"
    canvas = room.game.canvas
    assert canvas.record_stroke(
        "draw_start", {"x": 0.1, "y": 0.1, "color": "#000000", "width": 4}
    )
    assert canvas.record_stroke("draw_end", {})
    return room_manager, room, reporter, drawer


async def _users_for(factory, *players):
    from uuid import UUID

    from app.db.models import User

    async with factory() as session:
        async with session.begin():
            session.add_all(
                User(
                    id=UUID(player.user_id),
                    username=player.nickname,
                    password_hash="hash",
                    display_name=player.nickname,
                    state="registered",
                )
                for player in players
            )


async def test_a_report_about_the_drawer_can_carry_the_canvas():
    """Asked for by the reporter, taken by the server: the frame is the one
    on the canvas at the moment of the report, and it is the drawer's by
    construction because only the seat holding the pen is copied."""
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import undefer

    from app.canvas_storage import stored_drawing_checksum
    from app.db.models import AuditEvent, PlayerReportDrawingEvidence

    factory, engine = await create_test_db()
    room_manager, room, reporter, drawer = _report_room_with_a_drawer()
    frame = room.game.canvas.sync_payload()

    try:
        await _users_for(factory, reporter, drawer)
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
                "targetPlayerId": drawer.id,
                "reason": "offensive_drawing",
                "details": "Look at what they drew.",
                "includeDrawing": True,
            },
        )

        assert result["ok"] is True
        assert result["drawingAttached"] is True

        async with factory() as session:
            evidence = await session.scalar(
                select(PlayerReportDrawingEvidence).options(
                    undefer(PlayerReportDrawingEvidence.payload)
                )
            )
            assert evidence is not None
            assert evidence.report_id == UUID(result["id"])
            assert evidence.payload == frame
            assert evidence.byte_size == len(frame)
            assert evidence.checksum_sha256 == stored_drawing_checksum(frame)
            assert (evidence.format_magic, evidence.format_version) == ("SKCH", 1)
            assert evidence.turn_id_snapshot == UUID(room.game.current_turn_id)
            assert evidence.round_number == 1
            assert evidence.prompt_snapshot == "cat"
            assert evidence.action_count == 1
            event = await session.scalar(
                select(AuditEvent).where(AuditEvent.event_type == "report.submitted")
            )
            # The ledger says a drawing was attached and never what it shows.
            assert event.details["has_drawing"] is True
    finally:
        await engine.dispose()


async def test_the_canvas_is_copied_only_for_the_seat_that_is_drawing():
    """A guesser has nothing on the canvas that is theirs, and once the next
    drawer is choosing a prompt the canvas no longer shows the turn. Both
    are refused quietly: the report is filed and the acknowledgement says
    the drawing did not come with it."""
    from sqlalchemy import func, select

    from app.db.models import PlayerReport, PlayerReportDrawingEvidence

    factory, engine = await create_test_db()
    room_manager, room, reporter, drawer = _report_room_with_a_drawer()

    try:
        await _users_for(factory, reporter, drawer)
        sio = socketio.AsyncServer(async_mode="asgi")
        ctx = register_handlers(sio, room_manager)
        ctx.session_factory = factory
        sio.emit = AsyncMock()
        report_player = sio.handlers["/"]["report_player"]

        # The drawer reports the guesser, drawing included: nothing to copy.
        sio.get_session = AsyncMock(
            return_value={"room_id": room.id, "player_id": drawer.id}
        )
        about_a_guesser = await report_player(
            "drawer-sid",
            {
                "targetPlayerId": reporter.id,
                "reason": "harassment",
                "details": "Rude in chat.",
                "includeDrawing": True,
            },
        )
        assert about_a_guesser["ok"] is True
        assert about_a_guesser["drawingAttached"] is False

        # The guesser reports the drawer, but the turn has moved on.
        room.game.phase = Phase.CHOOSING_PROMPT
        sio.get_session = AsyncMock(
            return_value={"room_id": room.id, "player_id": reporter.id}
        )
        after_the_turn = await report_player(
            "reporter-sid",
            {
                "targetPlayerId": drawer.id,
                "reason": "offensive_drawing",
                "details": "What they drew just now.",
                "includeDrawing": True,
            },
        )
        assert after_the_turn["ok"] is True
        assert after_the_turn["drawingAttached"] is False

        async with factory() as session:
            assert await session.scalar(select(func.count(PlayerReport.id))) == 2
            assert (
                await session.scalar(
                    select(func.count(PlayerReportDrawingEvidence.report_id))
                )
                == 0
            )
    finally:
        await engine.dispose()


async def test_a_room_report_needs_no_words_of_its_own():
    """The server attaches the evidence, so the reporter's text is optional;
    blank is stored as empty rather than refused or padded."""
    from sqlalchemy import select

    from app.db.models import PlayerReport

    factory, engine = await create_test_db()
    room_manager, room, reporter, drawer = _report_room_with_a_drawer()

    try:
        await _users_for(factory, reporter, drawer)
        sio = socketio.AsyncServer(async_mode="asgi")
        ctx = register_handlers(sio, room_manager)
        ctx.session_factory = factory
        sio.get_session = AsyncMock(
            return_value={"room_id": room.id, "player_id": reporter.id}
        )
        sio.emit = AsyncMock()

        result = await sio.handlers["/"]["report_player"](
            "reporter-sid",
            {"targetPlayerId": drawer.id, "reason": "offensive_drawing", "details": "   "},
        )
        assert result["ok"] is True
        async with factory() as session:
            report = await session.scalar(select(PlayerReport))
            assert report.details == ""
    finally:
        await engine.dispose()


async def test_a_line_reported_the_moment_it_was_said_is_in_the_evidence():
    """The retention writer lingers a quarter of a second for the rest of a
    batch (#972), and report evidence reads `room_messages` directly: a
    report filed at once found nothing to cite until the queue is flushed."""
    from uuid import uuid4

    from app.db.models import User

    factory, engine = await create_test_db()
    reporter_id, target_id = uuid4(), uuid4()
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    reporter = room_manager.add_player(room, "Reporter", user_id=str(reporter_id), is_anonymous=False)
    target = room_manager.add_player(room, "Target", user_id=str(target_id), is_anonymous=False)
    reporter.sid, target.sid = "reporter-sid", "target-sid"
    try:
        async with factory() as session:
            async with session.begin():
                session.add_all([
                    User(id=account, username=name, password_hash="hash", display_name=name, state="registered")
                    for account, name in ((reporter_id, "Reporter"), (target_id, "Target"))
                ])
        sio = socketio.AsyncServer(async_mode="asgi")
        ctx = register_handlers(sio, room_manager, session_factory=factory)
        sessions = {
            "reporter-sid": {"room_id": room.id, "player_id": reporter.id},
            "target-sid": {"room_id": room.id, "player_id": target.id},
        }
        sio.get_session = AsyncMock(side_effect=lambda sid, namespace=None: sessions[sid])
        sio.emit = AsyncMock()

        said = await sio.handlers["/"]["send_chat"]("target-sid", {"text": "something worth reporting"})
        assert said == {"ok": True}
        result = await sio.handlers["/"]["report_player"](
            "reporter-sid",
            {"targetPlayerId": target.id, "reason": "harassment", "details": "Just now."},
        )
        assert result["ok"] is True
        assert result["evidenceCount"] == 1
        await ctx.message_retention.aclose()
        await ctx.timers.close()
    finally:
        await engine.dispose()


async def test_a_report_holds_no_connection_while_it_waits_for_the_queue(tmp_path, caplog):
    """The flush waits for the retention writer to get a connection, so a
    report that waits for it *while holding one* deadlocks against its own
    evidence - and the lines the report is about are exactly what goes
    missing (#972 fourth review). It held the erasure barrier's lock across
    that wait, too.

    On a pool of one, which is what the production pool becomes under enough
    concurrent reports; the suite's usual fixture is a `StaticPool`, where
    writer and report share one connection and the deadlock cannot appear.
    """
    import logging
    from uuid import uuid4

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import AsyncAdaptedQueuePool

    from app.db.models import Base, User

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'one-connection.db'}",
        poolclass=AsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=5,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    reporter_id, target_id = uuid4(), uuid4()
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    reporter = room_manager.add_player(room, "Reporter", user_id=str(reporter_id), is_anonymous=False)
    target = room_manager.add_player(room, "Target", user_id=str(target_id), is_anonymous=False)
    reporter.sid, target.sid = "reporter-sid", "target-sid"
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            async with session.begin():
                session.add_all([
                    User(id=account, username=name, password_hash="hash", display_name=name, state="registered")
                    for account, name in ((reporter_id, "Reporter"), (target_id, "Target"))
                ])
        sio = socketio.AsyncServer(async_mode="asgi")
        ctx = register_handlers(sio, room_manager, session_factory=factory)
        sessions = {
            "reporter-sid": {"room_id": room.id, "player_id": reporter.id},
            "target-sid": {"room_id": room.id, "player_id": target.id},
        }
        sio.get_session = AsyncMock(side_effect=lambda sid, namespace=None: sessions[sid])
        sio.emit = AsyncMock()

        await sio.handlers["/"]["send_chat"]("target-sid", {"text": "something worth reporting"})
        with caplog.at_level(logging.WARNING):
            result = await sio.handlers["/"]["report_player"](
                "reporter-sid",
                {"targetPlayerId": target.id, "reason": "harassment", "details": "Just now."},
            )

        assert result["ok"] is True
        assert result["evidenceCount"] == 1, "the cited line was written before the read"
        assert "not flushed" not in caplog.text
        await ctx.message_retention.aclose()
        await ctx.timers.close()
    finally:
        await engine.dispose()


async def test_an_account_erased_during_the_flush_files_no_report():
    """The re-lock in the writing transaction is the whole reason that
    transaction is separate: the first one has ended by the time the flush
    returns, so what is written must be written under a lock that still holds
    (R-PRIV-15). Deleting it left 2823 tests passing (#972 fifth review)."""
    from uuid import uuid4

    from sqlalchemy import func, select

    from app.api.errors import ErrorCode
    from app.db.models import PlayerReport, User

    factory, engine = await create_test_db()
    reporter_id, target_id = uuid4(), uuid4()
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    reporter = room_manager.add_player(room, "Reporter", user_id=str(reporter_id), is_anonymous=False)
    target = room_manager.add_player(room, "Target", user_id=str(target_id), is_anonymous=False)
    reporter.sid, target.sid = "reporter-sid", "target-sid"
    try:
        async with factory() as session:
            async with session.begin():
                session.add_all([
                    User(id=account, username=name, password_hash="hash", display_name=name, state="registered")
                    for account, name in ((reporter_id, "Reporter"), (target_id, "Target"))
                ])
        sio = socketio.AsyncServer(async_mode="asgi")
        ctx = register_handlers(sio, room_manager, session_factory=factory)
        sessions = {
            "reporter-sid": {"room_id": room.id, "player_id": reporter.id},
            "target-sid": {"room_id": room.id, "player_id": target.id},
        }
        sio.get_session = AsyncMock(side_effect=lambda sid, namespace=None: sessions[sid])
        sio.emit = AsyncMock()
        await sio.handlers["/"]["send_chat"]("target-sid", {"text": "something worth reporting"})

        # The reporter's account is erased while the report waits for the
        # retention queue - the window the two transactions open.
        real_flush = ctx.message_retention.flush

        async def erase_meanwhile():
            await real_flush()
            async with factory() as session:
                async with session.begin():
                    reporter_row = await session.get(User, reporter_id)
                    # As erasure leaves it: deleted, with the credentials gone
                    # (the row's own CHECK insists the two go together).
                    reporter_row.state = "deleted"
                    reporter_row.username = None
                    reporter_row.password_hash = None

        ctx.message_retention.flush = erase_meanwhile

        result = await sio.handlers["/"]["report_player"](
            "reporter-sid",
            {"targetPlayerId": target.id, "reason": "harassment", "details": "Just now."},
        )

        assert result["ok"] is False
        assert result["errorCode"] == ErrorCode.ACCOUNT_REQUIRED
        async with factory() as session:
            assert await session.scalar(select(func.count(PlayerReport.id))) == 0
        await ctx.message_retention.aclose()
        await ctx.timers.close()
    finally:
        await engine.dispose()


async def _reporting_room(factory):
    """A room with a reporter and a target, both registered, and their rows."""
    from uuid import uuid4

    from app.db.models import User

    reporter_id, target_id = uuid4(), uuid4()
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    reporter = room_manager.add_player(room, "Reporter", user_id=str(reporter_id), is_anonymous=False)
    target = room_manager.add_player(room, "Target", user_id=str(target_id), is_anonymous=False)
    reporter.sid, target.sid = "reporter-sid", "target-sid"
    async with factory() as session:
        async with session.begin():
            session.add_all([
                User(id=account, username=name, password_hash="hash", display_name=name, state="registered")
                for account, name in ((reporter_id, "Reporter"), (target_id, "Target"))
            ])
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, session_factory=factory)
    sessions = {
        "reporter-sid": {"room_id": room.id, "player_id": reporter.id},
        "target-sid": {"room_id": room.id, "player_id": target.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid, namespace=None: sessions[sid])
    sio.emit = AsyncMock()
    return sio, ctx, room, reporter, target, reporter_id, target_id


async def test_the_picture_stored_is_the_one_the_complaint_was_about():
    """`reported_avatar_key` is evidence about a past moment: a reviewer is
    told "replaced" or "removed" by comparing it with the live picture
    (R-AVA-04). Read again after the flush it would store whatever the account
    put up during that window and read as unchanged, with the complained-of
    bytes already deleted (#972 sixth review)."""
    from sqlalchemy import select, update

    from app.db.models import PlayerReport, User

    factory, engine = await create_test_db()
    try:
        sio, ctx, room, reporter, target, _reporter_id, target_id = await _reporting_room(factory)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User).where(User.id == target_id).values(avatar_key="a" * 64 + ".png")
                )

        real_flush = ctx.message_retention.flush

        async def replace_the_picture_meanwhile():
            await real_flush()
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        update(User).where(User.id == target_id).values(avatar_key="b" * 64 + ".png")
                    )

        ctx.message_retention.flush = replace_the_picture_meanwhile
        result = await sio.handlers["/"]["report_player"](
            "reporter-sid",
            {"targetPlayerId": target.id, "reason": "inappropriate_avatar", "details": "That."},
        )

        assert result["ok"] is True, result
        async with factory() as session:
            stored = await session.scalar(select(PlayerReport.reported_avatar_key))
        assert stored == "a" * 64 + ".png", "the picture complained about"
        await ctx.message_retention.aclose()
        await ctx.timers.close()
    finally:
        await engine.dispose()


async def test_an_account_merged_during_the_flush_is_reported_as_the_account_it_became():
    """The opposite rule for the identity: that one has to be current, because
    it is what the partial unique index sees - one open report per reporter
    per reported account (#972 sixth review)."""
    from uuid import uuid4

    from sqlalchemy import select

    from app.db.models import IdentityAlias, PlayerReport, User

    factory, engine = await create_test_db()
    try:
        sio, ctx, room, reporter, target, _reporter_id, target_id = await _reporting_room(factory)
        claimed_id = uuid4()
        async with factory() as session:
            async with session.begin():
                session.add(
                    User(
                        id=claimed_id, username="Claimed", password_hash="hash",
                        display_name="Claimed", state="registered",
                    )
                )

        real_flush = ctx.message_retention.flush

        async def claim_the_account_meanwhile():
            await real_flush()
            async with factory() as session:
                async with session.begin():
                    session.add(
                        IdentityAlias(source_user_id=target_id, target_user_id=claimed_id)
                    )

        ctx.message_retention.flush = claim_the_account_meanwhile
        result = await sio.handlers["/"]["report_player"](
            "reporter-sid",
            {"targetPlayerId": target.id, "reason": "harassment", "details": "That."},
        )

        assert result["ok"] is True, result
        async with factory() as session:
            stored = await session.scalar(select(PlayerReport.reported_user_id))
        assert stored == claimed_id, "the account the seat resolves to now"
        await ctx.message_retention.aclose()
        await ctx.timers.close()
    finally:
        await engine.dispose()


async def test_a_picture_cleared_during_the_flush_is_reported_as_removed():
    """The other direction of the same rule: the key stored is the one the
    complaint was about, so a picture *taken down* during the flush window is
    still reported - as "removed", which is what a reviewer needs to see. Only
    the "replaced" direction shipped (#972 seventh review)."""
    from sqlalchemy import select, update

    from app.db.models import PlayerReport, User

    factory, engine = await create_test_db()
    try:
        sio, ctx, room, reporter, target, _reporter_id, target_id = await _reporting_room(factory)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User).where(User.id == target_id).values(avatar_key="c" * 64 + ".png")
                )

        real_flush = ctx.message_retention.flush

        async def clear_the_picture_meanwhile():
            await real_flush()
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        update(User).where(User.id == target_id).values(avatar_key=None)
                    )

        ctx.message_retention.flush = clear_the_picture_meanwhile
        result = await sio.handlers["/"]["report_player"](
            "reporter-sid",
            {"targetPlayerId": target.id, "reason": "inappropriate_avatar", "details": "That."},
        )

        assert result["ok"] is True, result
        async with factory() as session:
            stored = await session.scalar(select(PlayerReport.reported_avatar_key))
        assert stored == "c" * 64 + ".png", "the picture complained about, now gone"
        await ctx.message_retention.aclose()
        await ctx.timers.close()
    finally:
        await engine.dispose()


async def test_a_seat_with_no_picture_cannot_be_reported_for_one():
    """R-AVA-09: a doodle is this deployment's drawing, not something the
    player put up, so there is nothing to report - and the refusal had no test
    (#972 seventh review)."""
    factory, engine = await create_test_db()
    try:
        sio, ctx, room, reporter, target, _reporter_id, _target_id = await _reporting_room(factory)

        result = await sio.handlers["/"]["report_player"](
            "reporter-sid",
            {"targetPlayerId": target.id, "reason": "inappropriate_avatar", "details": "That."},
        )

        assert result["ok"] is False
        assert result["error"] == "That player has no picture to report."
        await ctx.message_retention.aclose()
        await ctx.timers.close()
    finally:
        await engine.dispose()


def _stack(room_manager: RoomManager):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return ctx, sio, sessions


async def _three_seated(sio, sessions):
    """A host and two guests, each on a socket bound to its own account."""
    await sessions.save("host-sid", {"user_id": "user-host"})
    created = await sio.handlers["/"]["create_room"]("host-sid", {"nickname": "Host"})
    assert created["ok"], created
    for name in ("Two", "Three"):
        sid = f"{name.lower()}-sid"
        await sessions.save(sid, {"user_id": f"user-{name.lower()}"})
        joined = await sio.handlers["/"]["join_room"](
            sid, {"roomId": created["roomId"], "nickname": name}
        )
        assert joined["ok"], joined
    return created["roomId"]


async def _kick(sio, room, target_sid: str, voters: list[str]) -> dict:
    target = next(p for p in room.player_list() if p.sid == target_sid)
    answer = None
    for voter in voters:
        answer = await sio.handlers["/"]["vote_player"](
            voter, {"targetPlayerId": target.id, "action": "kick"}
        )
        assert answer["ok"], answer
    return answer


async def test_a_kicked_player_stays_out_for_the_rooms_lifetime():
    """The seat is gone, so the invite link used to seat them again at once,
    with a clean score (#1010). Barred as a spectator too: the vote was about
    the person, not the seat."""
    room_manager = RoomManager()
    ctx, sio, sessions = _stack(room_manager)
    room = room_manager.get_room(await _three_seated(sio, sessions))

    kicked = await _kick(sio, room, "two-sid", ["host-sid", "three-sid"])
    assert kicked["executed"] is True
    assert room_manager.get_player_by_user_id(room, "user-two") is None

    # Back through the link, on the same socket and on a fresh one.
    for sid in ("two-sid", "two-again-sid"):
        await sessions.save(sid, {"user_id": "user-two"})
        refused = await sio.handlers["/"]["join_room"](
            sid, {"roomId": room.id, "nickname": "Two"}
        )
        assert refused["ok"] is False
        assert refused["errorCode"] == ErrorCode.KICKED_FROM_ROOM
        as_spectator = await sio.handlers["/"]["join_room"](
            sid, {"roomId": room.id, "nickname": "Two", "asSpectator": True}
        )
        assert as_spectator["errorCode"] == ErrorCode.KICKED_FROM_ROOM
    assert room_manager.get_player_by_user_id(room, "user-two") is None
    assert len(room.players) == 2
    # The join was never charged, so the refusal cannot turn into "too fast".
    assert ctx.room_capacity.admits_a_join("two-again-sid")


async def test_quick_play_routes_a_kicked_player_past_that_room():
    room_manager = RoomManager()
    ctx, sio, sessions = _stack(room_manager)
    room = room_manager.get_room(await _three_seated(sio, sessions))
    await _kick(sio, room, "two-sid", ["host-sid", "three-sid"])

    await sessions.save("two-again-sid", {"user_id": "user-two"})
    answer = await sio.handlers["/"]["quick_play"](
        "two-again-sid", {"nickname": "Two", "promptLanguage": room.prompt_language}
    )
    assert answer["ok"] is True, answer
    assert answer["roomId"] != room.id
    assert room_manager.get_player_by_user_id(room, "user-two") is None


async def test_kicking_the_drawer_sends_the_roster_before_the_next_turn():
    """`turn_starting` for the next turn must not reach a client whose player
    list still holds the drawer it just lost (#883, #1010)."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    p1 = room_manager.add_player(room, "P1")
    p2 = room_manager.add_player(room, "P2")
    p3 = room_manager.add_player(room, "P3")
    p1.sid, p2.sid, p3.sid = "p1-sid", "p2-sid", "p3-sid"
    room.state = "playing"
    room.game = Game(turn_order=[p1.id, p2.id, p3.id], rounds_total=2)
    room.game.start_next_turn(canvas_generation=room.allocate_canvas_generation())
    assert room.game.current_drawer == p1.id

    sio = socketio.AsyncServer(async_mode="asgi")
    timers = register_handlers(sio, room_manager).timers
    sessions = {
        "p1-sid": {"room_id": room.id, "player_id": p1.id},
        "p2-sid": {"room_id": room.id, "player_id": p2.id},
        "p3-sid": {"room_id": room.id, "player_id": p3.id},
    }
    sio.get_session = AsyncMock(side_effect=lambda sid: sessions.get(sid))
    sio.emit = AsyncMock()
    sio.leave_room = AsyncMock()

    kicked = await _kick(sio, room, "p1-sid", ["p2-sid", "p3-sid"])
    assert kicked["executed"] is True

    events = [call.args[0] for call in sio.emit.await_args_list]
    assert "turn_starting" in events
    first_turn_starting = events.index("turn_starting")
    rosters_before = [
        {player["playerId"] for player in call.args[1]["players"]}
        for call in sio.emit.await_args_list[:first_turn_starting]
        if call.args[0] == "room_state"
    ]
    assert rosters_before, "no room_state reached the room before turn_starting"
    assert p1.id not in rosters_before[-1]
    assert room.game.current_drawer == p2.id

    for timer in (timers.phase_timers.pop(room.id, None),):
        if timer:
            timer.cancel()
            with suppress(asyncio.CancelledError):
                await timer


async def test_a_kick_landing_while_a_second_tab_rebinds_does_not_seat_a_ghost(monkeypatch):
    """The rebind path reads the account before binding the socket; a kick
    passing in that window used to bind the socket to a seat the room had
    already dropped, sitting in every broadcast with nothing to act from."""
    from app.handlers import rooms as rooms_handlers

    room_manager = RoomManager()
    ctx, sio, sessions = _stack(room_manager)
    room = room_manager.get_room(await _three_seated(sio, sessions))

    async def kicked_meanwhile(ctx_, player, requested):
        await _kick(sio, room, "two-sid", ["host-sid", "three-sid"])
        return None, False

    monkeypatch.setattr(rooms_handlers, "_rebound_account", kicked_meanwhile)
    await sessions.save("two-tab-2", {"user_id": "user-two"})
    answer = await sio.handlers["/"]["join_room"](
        "two-tab-2", {"roomId": room.id, "nickname": "Two"}
    )
    assert answer["errorCode"] == ErrorCode.KICKED_FROM_ROOM
    assert room_manager.get_player_by_user_id(room, "user-two") is None
    assert not any(call.args[0] == "two-tab-2" for call in sio.enter_room.await_args_list)

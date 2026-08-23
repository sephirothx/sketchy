"""Audience-aware chat persistence and bounded cleanup."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import socketio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, RoomMessage, User
from app.game import Game
from app.handlers import register_all_handlers as register_handlers
from app.rooms import RoomManager
from app.services.message_retention import (
    MESSAGE_RETENTION,
    purge_expired_room_messages,
)


pytestmark = pytest.mark.asyncio


async def test_wrong_guess_is_retained_with_runtime_ids_and_actual_audience():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
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
        assert emitted.args[1]["retainedMessageId"] == str(message.id)
        assert emitted.kwargs["room"] == room.id
        await context.timers.close()
    finally:
        await engine.dispose()


async def test_near_miss_audience_excludes_prompt_unaware_players_and_cleanup_is_bounded():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
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

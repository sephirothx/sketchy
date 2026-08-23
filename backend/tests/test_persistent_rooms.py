"""Persistent rooms store configuration without pretending live state is durable."""

from datetime import datetime, timezone
from uuid import UUID
from unittest.mock import AsyncMock

import pytest
import socketio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, PersistentRoom, PromptList, RoomCodeReservation, User
from app.auth.account_data import anonymize_account
from app.identifiers import generate_uuid7
from app.handlers import register_all_handlers
from app.repositories.interfaces import BundledPromptDefinition
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from app.rooms import RoomManager
from app.services.persistent_rooms import (
    PersistentRoomError,
    PersistentRoomService,
    PersistentRoomUnavailable,
)


pytestmark = pytest.mark.asyncio


async def _fixture():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    prompts = SqlAlchemyPromptListRepository(factory)
    owner_id = generate_uuid7()
    async with factory() as session:
        async with session.begin():
            session.add(
                User(
                    id=owner_id,
                    username="owner",
                    password_hash="not-used-here",
                    display_name="owner",
                    state="registered",
                    role="user",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    last_login_at=datetime.now(timezone.utc),
                    last_active_at=datetime.now(timezone.utc),
                )
            )
            session.add(RoomCodeReservation(code="GROUP1", kind="persistent"))
    await prompts.upsert_bundled(
        "english_standard",
        "English standard",
        "Test list",
        "en",
        [
            BundledPromptDefinition(
                concept_id=str(generate_uuid7()),
                answer="apple",
            ),
            BundledPromptDefinition(
                concept_id=str(generate_uuid7()),
                answer="bicycle",
            ),
            BundledPromptDefinition(
                concept_id=str(generate_uuid7()),
                answer="castle",
            ),
        ],
        1,
    )
    return engine, factory, prompts, str(owner_id)


def _settings(**overrides):
    values = {
        "name": "Friday artists",
        "is_public": False,
        "max_players": 8,
        "rounds": 3,
        "drawing_seconds": 90,
        "custom_prompts": [],
        "custom_prompts_only": False,
        "hint_mode": "checkpoints",
        "scoring_mode": "default",
        "spectators_see_prompt": False,
        "hide_masked_prompt": False,
        "allowed_tools": ["brush", "shapes", "fill"],
        "color_mode": "all",
        "prompt_list_slugs": ["english_standard"],
    }
    values.update(overrides)
    return values


async def test_restart_materializes_fresh_live_state_from_saved_configuration():
    engine, factory, prompts, owner_id = await _fixture()
    service = PersistentRoomService(factory, prompts)
    try:
        config = await service.create(
            owner_user_id=owner_id,
            code="GROUP1",
            settings=_settings(),
        )
        first_process = RoomManager()
        first = await service.materialize(first_process, "group1")
        assert first is not None
        assert first.persistent_room_id == config.id
        assert first.code == "GROUP1"
        assert first.players == {}
        assert first.game is None
        assert first.last_game_drawings == []

        visitor = first_process.add_player(
            first, "Visitor", user_id=str(generate_uuid7())
        )
        assert visitor.is_host is False
        owner = first_process.add_player(first, "Owner", user_id=owner_id)
        assert owner.is_host is True
        assert visitor.is_host is False

        updated = _settings(rounds=5)
        next_version = await service.update(
            room=first,
            owner_user_id=owner_id,
            settings=updated,
        )
        first.persistent_config_version = next_version
        first.rounds = 5

        # A second process is the restart boundary: configuration returns, but
        # live identity, membership, scores, games, and canvases do not.
        restarted_process = RoomManager()
        restored = await service.materialize(restarted_process, "GROUP1")
        assert restored is not None
        assert restored.id != first.id
        assert restored.rounds == 5
        assert restored.players == {}
        assert restored.game is None
        assert restored.last_game_scores == []
        assert restored.last_game_drawings == []
    finally:
        await engine.dispose()


async def test_quick_custom_prompts_and_guest_ownership_are_rejected():
    engine, factory, prompts, owner_id = await _fixture()
    service = PersistentRoomService(factory, prompts)
    try:
        with pytest.raises(PersistentRoomError, match="private prompt list"):
            await service.create(
                owner_user_id=owner_id,
                code="GROUP1",
                settings=_settings(custom_prompts=["secret"]),
            )
        async with factory() as session:
            async with session.begin():
                owner = await session.get(User, UUID(owner_id))
                assert owner is not None
                owner.state = "anonymous"
        with pytest.raises(PersistentRoomError, match="Create an account"):
            await service.create(
                owner_user_id=owner_id,
                code="GROUP1",
                settings=_settings(),
            )
    finally:
        await engine.dispose()


async def test_archived_or_broken_configuration_never_silently_falls_back():
    engine, factory, prompts, owner_id = await _fixture()
    service = PersistentRoomService(factory, prompts)
    try:
        config = await service.create(
            owner_user_id=owner_id,
            code="GROUP1",
            settings=_settings(),
        )
        room = await service.materialize(RoomManager(), "GROUP1")
        assert room is not None
        await service.archive(room=room, owner_user_id=owner_id)
        assert await service.get_active_by_code("GROUP1") is None
        assert await service.materialize(RoomManager(), "GROUP1") is None

        async with factory() as session:
            async with session.begin():
                stored = await session.get(PersistentRoom, UUID(config.id))
                assert stored is not None
                stored.archived_at = None
                await session.execute(delete(PromptList))
        with pytest.raises(PersistentRoomUnavailable, match="prompt lists"):
            await service.materialize(RoomManager(), "GROUP1")
    finally:
        await engine.dispose()


async def test_socket_flow_creates_updates_restarts_and_archives_persistent_room():
    engine, factory, prompts, owner_id = await _fixture()
    manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    register_all_handlers(
        sio,
        manager,
        user_repo=SqlAlchemyUserRepository(factory),
        prompt_list_repo=prompts,
        session_factory=factory,
    )
    sio.get_session = AsyncMock(return_value={"user_id": owner_id})
    sio.save_session = AsyncMock()
    sio.enter_room = AsyncMock()
    sio.emit = AsyncMock()
    try:
        created = await sio.handlers["/"]["create_room"](
            "owner-sid",
            {
                "persistent": True,
                "nickname": "ignored",
                "name": "Friday artists",
                "isPublic": False,
                "promptListSlugs": ["english_standard"],
            },
        )
        assert created["ok"] is True
        room = manager.get_room(created["roomId"])
        assert room is not None
        assert room.persistent_room_id is not None
        assert room.to_state_payload()["isPersistent"] is True
        owner = room.players[created["playerId"]]
        assert owner.is_host is True

        sio.get_session = AsyncMock(
            return_value={
                "user_id": owner_id,
                "room_id": room.id,
                "player_id": owner.id,
            }
        )
        assert await sio.handlers["/"]["update_room_settings"](
            "owner-sid", {"rounds": 4}
        ) == {"ok": True}
        assert room.rounds == 4

        # Simulate process loss by discarding only the in-memory manager entry.
        manager.rooms.clear()
        preview = await sio.handlers["/"]["get_room_preview"](
            "visitor-sid", {"code": created["code"]}
        )
        assert preview["ok"] is True
        restored = manager.get_room_by_code(created["code"])
        assert restored is not None
        assert restored.id != room.id
        assert restored.rounds == 4
        assert restored.players == {}

        restored_owner = manager.add_player(restored, "owner", user_id=owner_id)
        restored_owner.sid = "owner-sid"
        sio.get_session = AsyncMock(
            return_value={
                "user_id": owner_id,
                "room_id": restored.id,
                "player_id": restored_owner.id,
            }
        )
        assert await sio.handlers["/"]["archive_persistent_room"](
            "owner-sid", {}
        ) == {"ok": True}
        assert restored.persistent_room_id is None
        manager.rooms.clear()
        unavailable = await sio.handlers["/"]["get_room_preview"](
            "visitor-sid", {"code": created["code"]}
        )
        assert unavailable == {"ok": False, "error": "Room not found"}
    finally:
        await engine.dispose()


async def test_account_deletion_archives_owned_configuration_and_keeps_code_reserved():
    engine, factory, prompts, owner_id = await _fixture()
    service = PersistentRoomService(factory, prompts)
    try:
        config = await service.create(
            owner_user_id=owner_id,
            code="GROUP1",
            settings=_settings(),
        )

        await anonymize_account(factory, user_id=owner_id)

        async with factory() as session:
            stored = await session.get(PersistentRoom, UUID(config.id))
            reservation = await session.get(RoomCodeReservation, "GROUP1")
        assert stored is not None
        assert stored.archived_at is not None
        assert reservation is not None
        assert reservation.kind == "persistent"
        assert reservation.retired_until is None
        assert await service.materialize(RoomManager(), "GROUP1") is None
    finally:
        await engine.dispose()

"""Persistent directional blocks, merge behavior, and live chat filtering."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
import pytest_asyncio
import socketio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.user_blocks import create_user_blocks_router
from app.auth.blocks import BlockService
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AuditEvent, Base, UserBlock, generate_uuid
from app.handlers import register_all_handlers
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.rooms import RoomManager


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "blocks-test-secret")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    blocks = BlockService(factory, max_cached_senders=2)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_user_blocks_router(factory, blocks))
    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        clients.append(client)
        return client

    try:
        yield new_client, factory, users, blocks
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()


async def test_block_list_is_idempotent_persistent_and_audited(env):
    new_client, factory, _, blocks = env
    blocker_http = new_client()
    target_http = new_client()
    blocker = await register(blocker_http, "BlockOwner")
    target = await register(target_http, "MutedPlayer")

    # Warm the negative cache to prove the REST mutation invalidates it.
    assert await blocks.blockers_of(target["id"]) == frozenset()
    created = await blocker_http.post(
        "/api/users/me/blocks",
        headers={"x-request-id": "019c1000-0000-7000-8000-000000000003"},
        json={"userId": target["id"]},
    )
    assert created.status_code == 201
    assert created.json()["userId"] == target["id"]
    assert created.json()["displayName"] == "MutedPlayer"
    assert await blocks.blockers_of(target["id"]) == frozenset({blocker["id"]})

    duplicate = await blocker_http.post(
        "/api/users/me/blocks", json={"userId": target["id"]}
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == created.json()["id"]
    listing = await blocker_http.get("/api/users/me/blocks")
    assert listing.status_code == 200
    assert listing.json()["blocks"] == [created.json()]

    removed = await blocker_http.delete(f"/api/users/me/blocks/{target['id']}")
    assert removed.status_code == 204
    assert await blocks.blockers_of(target["id"]) == frozenset()
    assert (
        await blocker_http.delete(f"/api/users/me/blocks/{target['id']}")
    ).status_code == 204

    async with factory() as session:
        assert await session.scalar(select(func.count(UserBlock.id))) == 0
        events = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.event_type.in_(("block.created", "block.deleted"))
                )
            )
        )
        assert {event.event_type for event in events} == {
            "block.created",
            "block.deleted",
        }
        assert all(len(event.ip_hash or "") == 64 for event in events)
        created_event = next(
            event for event in events if event.event_type == "block.created"
        )
        assert created_event.request_id == "019c1000-0000-7000-8000-000000000003"


async def test_self_unknown_and_database_duplicate_blocks_are_rejected(env):
    new_client, factory, _, _ = env
    owner_http = new_client()
    target_http = new_client()
    owner = await register(owner_http, "BlockBoundary")
    target = await register(target_http, "BlockTarget")
    assert (
        await owner_http.post(
            "/api/users/me/blocks", json={"userId": owner["id"]}
        )
    ).status_code == 422
    assert (
        await owner_http.post(
            "/api/users/me/blocks",
            json={"userId": str(generate_uuid())},
        )
    ).status_code == 404

    with pytest.raises(IntegrityError):
        async with factory() as session:
            async with session.begin():
                session.add(
                    UserBlock(
                        id=generate_uuid(),
                        blocker_user_id=UUID(owner["id"]),
                        blocked_user_id=UUID(owner["id"]),
                    )
                )

    async with factory() as session:
        async with session.begin():
            session.add(
                UserBlock(
                    id=generate_uuid(),
                    blocker_user_id=UUID(owner["id"]),
                    blocked_user_id=UUID(target["id"]),
                )
            )
    with pytest.raises(IntegrityError):
        async with factory() as session:
            async with session.begin():
                session.add(
                    UserBlock(
                        id=generate_uuid(),
                        blocker_user_id=UUID(owner["id"]),
                        blocked_user_id=UUID(target["id"]),
                    )
                )


async def test_guest_merge_carries_and_deduplicates_both_block_directions(env):
    _, factory, users, _ = env
    account_guest = await users.create_anonymous("Account")
    account = await users.claim_account(account_guest.id, "MergeBlocks", "hash")
    source = await users.create_anonymous("RoadGuest")
    third = await users.create_anonymous("Third")
    async with factory() as session:
        async with session.begin():
            for blocker_id, blocked_id in (
                (source.id, third.id),
                (account.id, third.id),
                (third.id, source.id),
                (third.id, account.id),
                (source.id, account.id),
                (account.id, source.id),
            ):
                session.add(
                    UserBlock(
                        id=generate_uuid(),
                        blocker_user_id=UUID(blocker_id),
                        blocked_user_id=UUID(blocked_id),
                    )
                )

    await users.merge_guest_into_account(source.id, account.id)
    async with factory() as session:
        pairs = {
            (str(block.blocker_user_id), str(block.blocked_user_id))
            for block in await session.scalars(select(UserBlock))
        }
    assert pairs == {
        (account.id, third.id),
        (third.id, account.id),
    }


async def test_blocked_sender_chat_is_filtered_but_room_state_and_system_chat_are_not():
    room_manager = RoomManager()
    room = room_manager.create_room(name="Block room")
    sender = room_manager.add_player(room, "Sender", user_id="sender-user")
    blocker = room_manager.add_player(room, "Blocker", user_id="blocker-user")
    observer = room_manager.add_player(room, "Observer", user_id="observer-user")
    for player, sid in (
        (sender, "sender-sid"),
        (blocker, "blocker-sid"),
        (observer, "observer-sid"),
    ):
        player.sid = sid

    block_service = SimpleNamespace(
        blockers_of=AsyncMock(return_value=frozenset({"blocker-user"}))
    )
    sio = socketio.AsyncServer(async_mode="asgi")
    context = register_all_handlers(
        sio, room_manager, block_service=block_service
    )
    sio.get_session = AsyncMock(
        return_value={"room_id": room.id, "player_id": sender.id}
    )
    sio.emit = AsyncMock()

    result = await sio.handlers["/"]["send_chat"](
        "sender-sid", {"text": "ordinary message"}
    )
    assert result == {"ok": True}
    player_chat = next(
        call
        for call in sio.emit.await_args_list
        if call.args[0] == "chat_message" and call.args[1].get("playerId") == sender.id
    )
    assert player_chat.kwargs["to"] == ["sender-sid", "observer-sid"]
    assert "blocker-sid" not in player_chat.kwargs["to"]

    await context.game_flow._emit_room_state(room)
    await context.game_flow.announce(room, "A game-critical announcement")
    assert any(
        call.args[0] == "room_state" and call.kwargs.get("room") == room.id
        for call in sio.emit.await_args_list
    )
    assert any(
        call.args[0] == "chat_message"
        and call.args[1].get("system") is True
        and call.kwargs.get("room") == room.id
        for call in sio.emit.await_args_list
    )


# --- the cache's own failure and eviction behaviour -------------------------
#
# Blocking is a presentation filter, not a security boundary, and the service
# says so: when the lookup cannot answer it delivers the line unfiltered rather
# than dropping it. That is a deliberate trade - silence is the worse failure,
# and the one the sender cannot see - but nothing exercised it, so the branch
# that makes the trade was never taken in a test.


async def test_an_absent_sender_is_never_looked_up(env):
    """No id means no query, not a query for nothing."""
    _, factory, _, _ = env
    looked_up = AsyncMock()
    service = BlockService(factory)
    service._read_blockers = looked_up

    assert await service.blockers_of(None) == frozenset()
    assert await service.blockers_of("") == frozenset()
    looked_up.assert_not_awaited()


async def test_a_cached_sender_is_answered_without_touching_the_database(env):
    _, factory, _, _ = env
    sender = str(generate_uuid())
    blocker = str(generate_uuid())
    service = BlockService(factory)
    service._read_blockers = AsyncMock(return_value=frozenset({blocker}))

    assert await service.blockers_of(sender) == frozenset({blocker})
    assert await service.blockers_of(sender) == frozenset({blocker})
    # One read for two lines: the point of the cache.
    assert service._read_blockers.await_count == 1


async def test_a_lookup_that_times_out_delivers_unfiltered(env):
    """A room going quiet is worse than a line that should have been hidden."""
    _, factory, _, _ = env
    service = BlockService(factory)

    async def never_answers(_db_user_id):
        await asyncio.sleep(3600)

    service._read_blockers = never_answers
    monkeypatched_timeout = 0.01
    with patch("app.auth.blocks.LOOKUP_TIMEOUT_SECONDS", monkeypatched_timeout):
        assert await service.blockers_of(str(generate_uuid())) == frozenset()


async def test_a_lookup_that_raises_delivers_unfiltered(env):
    _, factory, _, _ = env
    service = BlockService(factory)
    service._read_blockers = AsyncMock(side_effect=RuntimeError("database is gone"))

    assert await service.blockers_of(str(generate_uuid())) == frozenset()


async def test_a_failed_lookup_is_not_remembered_as_an_answer(env):
    """Caching the empty set a failure returned leaves a block broken for good."""
    _, factory, _, _ = env
    sender = str(generate_uuid())
    blocker = str(generate_uuid())
    service = BlockService(factory)
    service._read_blockers = AsyncMock(side_effect=RuntimeError("transient"))

    assert await service.blockers_of(sender) == frozenset()
    assert service.cached_senders() == 0

    service._read_blockers = AsyncMock(return_value=frozenset({blocker}))
    assert await service.blockers_of(sender) == frozenset({blocker})


async def test_a_malformed_sender_id_is_not_looked_up(env):
    _, factory, _, _ = env
    service = BlockService(factory)
    service._read_blockers = AsyncMock()

    assert await service.blockers_of("not-a-uuid") == frozenset()
    service._read_blockers.assert_not_awaited()


async def test_the_cache_evicts_the_least_recently_used_sender(env):
    """The bound is what keeps a long-lived process from growing for ever."""
    _, factory, _, _ = env
    service = BlockService(factory, max_cached_senders=2)
    first, second, third = (str(generate_uuid()) for _ in range(3))
    service._read_blockers = AsyncMock(return_value=frozenset())

    await service.blockers_of(first)
    await service.blockers_of(second)
    assert service.cached_senders() == 2

    # Touching `first` makes `second` the least recently used.
    await service.blockers_of(first)
    await service.blockers_of(third)
    assert service.cached_senders() == 2

    reads_before = service._read_blockers.await_count
    await service.blockers_of(second)
    assert service._read_blockers.await_count == reads_before + 1, (
        "the least recently used sender should have been evicted"
    )


async def test_invalidating_and_clearing_drop_what_was_cached(env):
    _, factory, _, _ = env
    sender = str(generate_uuid())
    service = BlockService(factory)
    service._read_blockers = AsyncMock(return_value=frozenset())

    await service.warm(sender)
    assert service.cached_senders() == 1

    service.invalidate(sender)
    assert service.cached_senders() == 0

    await service.warm(sender)
    service.clear()
    assert service.cached_senders() == 0

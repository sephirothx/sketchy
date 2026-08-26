"""Opaque session storage, rotation, revocation, and privacy behavior."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.sessions import (
    ROTATE_AFTER,
    create_session,
    device_label_from_user_agent,
    hash_session_token,
    list_active_sessions,
    resolve_session,
    revoke_all_sessions,
    revoke_session,
    rotate_session,
    should_rotate,
)
from app.db.models import AuthSession, Base
from app.handlers.connection import connect as socket_connect
from app.repositories.sqlalchemy import SqlAlchemyUserRepository


@pytest_asyncio.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user = await SqlAlchemyUserRepository(factory).create_anonymous("Guest")
    try:
        yield factory, user
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_raw_token_is_never_stored(database):
    factory, user = database
    issued = await create_session(
        factory, user_id=user.id, device_label="Firefox on Linux"
    )
    async with factory() as session:
        record = await session.scalar(select(AuthSession))
    assert record is not None
    assert record.token_hash == hash_session_token(issued.token)
    assert issued.token != record.token_hash
    assert user.id not in issued.token


@pytest.mark.asyncio
async def test_rotation_revokes_predecessor_and_preserves_device(database):
    factory, user = database
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    issued = await create_session(
        factory,
        user_id=user.id,
        device_label="Safari on macOS",
        now=started,
    )
    assert should_rotate(
        issued.session, now=started + ROTATE_AFTER + timedelta(seconds=1)
    )

    replacement = await rotate_session(
        factory,
        session_id=issued.session.id,
        user_id=user.id,
        device_label=issued.session.device_label,
        now=started + ROTATE_AFTER + timedelta(seconds=1),
    )
    assert replacement is not None
    assert await resolve_session(factory, issued.token) is None
    assert await resolve_session(factory, replacement.token) is not None


@pytest.mark.asyncio
async def test_session_revocation_is_scoped_to_owner(database):
    factory, user = database
    other = await SqlAlchemyUserRepository(factory).create_anonymous("Other")
    issued = await create_session(factory, user_id=user.id, device_label="Browser")
    assert not await revoke_session(
        factory, session_id=issued.session.id, user_id=other.id
    )
    assert await resolve_session(factory, issued.token) is not None
    assert await revoke_session(
        factory, session_id=issued.session.id, user_id=user.id
    )
    assert await resolve_session(factory, issued.token) is None


@pytest.mark.asyncio
async def test_list_and_revoke_all_exclude_revoked_sessions(database):
    factory, user = database
    first = await create_session(factory, user_id=user.id, device_label="One")
    second = await create_session(factory, user_id=user.id, device_label="Two")
    assert {item.id for item in await list_active_sessions(factory, user_id=user.id)} == {
        first.session.id,
        second.session.id,
    }
    assert await revoke_all_sessions(factory, user_id=user.id) == 2
    assert await list_active_sessions(factory, user_id=user.id) == []


def test_device_label_is_coarse_and_drops_versions():
    label = device_label_from_user_agent(
        "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
    )
    assert label == "Chrome on macOS"
    assert "140" not in label


@pytest.mark.asyncio
async def test_socket_handshake_uses_the_same_revocation_record(database):
    factory, user = database
    issued = await create_session(factory, user_id=user.id, device_label="Browser")
    sio = SimpleNamespace(save_session=AsyncMock(), enter_room=AsyncMock())
    context = SimpleNamespace(sio=sio, session_factory=factory)
    environ = {"HTTP_COOKIE": f"sketchy_session={issued.token}"}

    await socket_connect(context, "first", environ, None)
    sio.save_session.assert_awaited_with("first", {"user_id": user.id})
    # The account broadcast room is what account-level news (a suspension, a
    # moderator warning) is emitted to, wherever the socket is in the app.
    sio.enter_room.assert_awaited_with("first", f"user:{user.id}")

    await revoke_session(
        factory, session_id=issued.session.id, user_id=user.id
    )
    await socket_connect(context, "second", environ, None)
    sio.save_session.assert_awaited_with("second", {"user_id": None})

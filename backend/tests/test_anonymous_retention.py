"""Tiered anonymous-account retention and meaningful activity signals."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.retention import purge_stale_anonymous_accounts
from app.auth.sessions import create_session
from app.db.models import AuditEvent, AuthSession, Base, GameParticipant, User, generate_uuid
from app.db import create_db_engine
from app.repositories.interfaces import GameParticipantInput, GameRecordInput, TurnRecordInput
from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository, SqlAlchemyUserRepository


@pytest.mark.asyncio
async def test_retention_previews_then_removes_stale_guest_tiers():
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    try:
        unused = await users.create_anonymous("DriveBy")
        player = await users.create_anonymous("PastPlayer")
        recent = await users.create_anonymous("Recent")
        await create_session(factory, user_id=unused.id, device_label="Old browser")
        game_id = await history.save_game(
            GameRecordInput(
                room_name="Old game",
                scoring_mode="default",
                hint_mode="none",
                drawing_seconds=60,
                total_rounds=1,
                player_count=1,
                started_at=now - timedelta(days=400),
                finished_at=now - timedelta(days=400, minutes=-5),
            ),
            [GameParticipantInput(user_id=player.id, final_score=10, final_rank=1)],
            [
                TurnRecordInput(
                    id=str(generate_uuid()),
                    round_number=1,
                    turn_number=1,
                    drawer_user_id=player.id,
                    prompt="archive",
                    duration_seconds=10,
                )
            ],
            [],
        )

        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User)
                    .where(User.id == UUID(unused.id))
                    .values(last_active_at=now - timedelta(days=31))
                )
                await session.execute(
                    update(User)
                    .where(User.id == UUID(player.id))
                    .values(last_active_at=now - timedelta(days=366))
                )
                await session.execute(
                    update(User)
                    .where(User.id == UUID(recent.id))
                    .values(last_active_at=now - timedelta(days=2))
                )

        preview = await purge_stale_anonymous_accounts(factory, now=now)
        assert preview.total == 2
        assert preview.unused_accounts == 1
        assert preview.player_accounts == 1
        async with factory() as session:
            assert await session.scalar(select(func.count(User.id))) == 3

        applied = await purge_stale_anonymous_accounts(factory, now=now, apply=True)
        assert applied.total == 2 and applied.applied
        async with factory() as session:
            assert await session.get(User, UUID(unused.id)) is None
            assert await session.get(User, UUID(player.id)) is None
            assert await session.get(User, UUID(recent.id)) is not None
            assert await session.scalar(select(func.count(AuthSession.id))) == 0
            participant = await session.scalar(
                select(GameParticipant).where(GameParticipant.game_id == UUID(game_id))
            )
            assert participant is not None
            assert participant.user_id is None
            assert participant.display_name_snapshot == "PastPlayer"
            event = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.event_type == "retention.anonymous_purge"
                )
            )
            assert event is not None
            assert event.details["unused_accounts"] == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_touch_last_active_is_distinct_from_login_activity():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    try:
        guest = await users.create_anonymous("Player")
        old_activity = datetime(2020, 1, 1, tzinfo=timezone.utc)
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(User)
                    .where(User.id == UUID(guest.id))
                    .values(last_active_at=old_activity)
                )
        logged_in = await users.touch_last_login(guest.id)
        assert logged_in is not None and logged_in.last_active_at == old_activity
        active = await users.touch_last_active(guest.id)
        assert active is not None and active.last_active_at > old_activity
    finally:
        await engine.dispose()

"""Tiered anonymous-account retention and meaningful activity signals."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.retention import (
    purge_expired_auth_sessions,
    purge_expired_data_exports,
    purge_stale_anonymous_accounts,
)
from app.auth.sessions import create_session
from app.db.models import (
    AuditEvent,
    AuthSession,
    Base,
    DataExport,
    GameParticipant,
    User,
    UserBan,
    generate_uuid,
)
from app.db import create_db_engine
from app.repositories.interfaces import GameParticipantInput, GameRecordInput, TurnRecordInput
from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository, SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db


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
    factory, engine = await create_test_db()
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


async def _session_row(session, user_id, *, expires_at, revoked_at=None):
    row = AuthSession(
        id=generate_uuid(),
        user_id=user_id,
        token_hash=generate_uuid().hex,
        device_label="test",
        expires_at=expires_at,
        revoked_at=revoked_at,
    )
    session.add(row)
    return row


@pytest.mark.asyncio
async def test_expired_sessions_go_but_revoked_live_ones_stay():
    """The condition is expiry, not revocation: a revoked but unexpired row is
    still what keeps a ban-time token recognisable rather than looking like a
    new cookieless guest, and rotation leaves one behind on purpose."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as session:
            async with session.begin():
                user = User(id=generate_uuid(), display_name="Player")
                session.add(user)
                # Nothing relates AuthSession to User at the ORM level, so the
                # parent has to land before its children.
                await session.flush()
                long_dead = await _session_row(
                    session, user.id, expires_at=now - timedelta(days=400)
                )
                just_expired = await _session_row(
                    session, user.id, expires_at=now - timedelta(days=1)
                )
                revoked_but_live = await _session_row(
                    session,
                    user.id,
                    expires_at=now + timedelta(days=200),
                    revoked_at=now - timedelta(days=5),
                )

        removed = await purge_expired_auth_sessions(factory, now=now, batch_size=1)
        assert removed == 1

        async with factory() as session:
            surviving = set(
                (await session.scalars(select(AuthSession.id))).all()
            )
        assert long_dead.id not in surviving, "past the grace window"
        assert just_expired.id in surviving, "inside the grace window"
        assert revoked_but_live.id in surviving, "revoked is not expired"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_suspended_account_keeps_its_route_to_export_and_deletion():
    """R-BAN-04: export, deletion, and logout stay available through the
    ban-time credential. A suspended account cannot log in to make a new
    session, so retention must not take away its only one - moderation may not
    erase privacy rights, and neither may a sweep."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as session:
            async with session.begin():
                banned = User(id=generate_uuid(), display_name="Suspended")
                # More than one, so the protected set is genuinely a set: with
                # a single row a broken membership test still looks right.
                also_banned = User(id=generate_uuid(), display_name="AlsoSuspended")
                lapsed = User(id=generate_uuid(), display_name="ServedTheirTime")
                session.add_all([banned, also_banned, lapsed])
                await session.flush()
                banned_row = await _session_row(
                    session, banned.id, expires_at=now - timedelta(days=400)
                )
                also_banned_row = await _session_row(
                    session, also_banned.id, expires_at=now - timedelta(days=400)
                )
                lapsed_row = await _session_row(
                    session, lapsed.id, expires_at=now - timedelta(days=400)
                )
                for suspended in (banned, also_banned):
                    session.add(
                        UserBan(
                            id=generate_uuid(),
                            user_id=suspended.id,
                            reason="harassment",
                            is_active=True,
                            expires_at=None,
                        )
                    )
                # A ban whose subject was deleted keeps the row and drops the
                # link (SET NULL). One NULL on the right of NOT IN makes the
                # predicate never true, so without the is_not(None) filter the
                # sweep would silently stop removing anything at all.
                session.add(
                    UserBan(
                        id=generate_uuid(),
                        user_id=None,
                        reason="account deleted",
                        is_active=True,
                        expires_at=None,
                    )
                )
                session.add(
                    UserBan(
                        id=generate_uuid(),
                        user_id=lapsed.id,
                        reason="spam",
                        is_active=True,
                        created_at=now - timedelta(days=30),
                        expires_at=now - timedelta(days=1),
                    )
                )

        await purge_expired_auth_sessions(factory, now=now)

        async with factory() as session:
            surviving = set(
                (await session.scalars(select(AuthSession.id))).all()
            )
        assert banned_row.id in surviving, "the suspension is still in force"
        assert also_banned_row.id in surviving, "so is this one"
        assert lapsed_row.id not in surviving, "the suspension has lapsed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_an_uncollected_export_does_not_outlive_its_own_window():
    """An export used to go only when its owner asked for another one, so one
    generated and never collected kept the largest non-blob value in the
    schema indefinitely."""
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with factory() as session:
            async with session.begin():
                user = User(id=generate_uuid(), display_name="Player")
                session.add(user)
                await session.flush()
                stale = DataExport(
                    id=generate_uuid(),
                    user_id=user.id,
                    status="ready",
                    artifact=b"\x1f\x8b" + b"x" * 20,
                    artifact_encoding="gzip+json",
                    expires_at=now - timedelta(days=1),
                )
                live = DataExport(
                    id=generate_uuid(),
                    user_id=user.id,
                    status="ready",
                    artifact=b"\x1f\x8b" + b"y" * 20,
                    artifact_encoding="gzip+json",
                    expires_at=now + timedelta(days=6),
                )
                session.add_all([stale, live])

        removed = await purge_expired_data_exports(factory, now=now)
        assert removed == 1

        async with factory() as session:
            surviving = set((await session.scalars(select(DataExport.id))).all())
        assert surviving == {live.id}
    finally:
        await engine.dispose()

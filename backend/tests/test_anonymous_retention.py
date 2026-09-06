"""Tiered anonymous-account retention and meaningful activity signals."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import UUID

import pytest
from sqlalchemy import func, select, update

from app.auth.retention import (
    purge_expired_auth_sessions,
    purge_expired_data_exports,
    purge_stale_anonymous_accounts,
)
from app.auth.sessions import create_session
from app.db.models import (
    AuditEvent,
    AuthSession,
    DataExport,
    GameParticipant,
    GameRecord,
    User,
    UserBan,
    generate_uuid,
)
from app.repositories.interfaces import GameParticipantInput, GameRecordInput, TurnRecordInput
from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository, SqlAlchemyUserRepository

from tests.dbfixtures import create_test_db


@pytest.mark.asyncio
async def test_retention_previews_then_removes_stale_guest_tiers():
    factory, engine = await create_test_db()
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
        # Created before it expires, as the row now insists (#553).
        created_at=expires_at - timedelta(days=30),
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
    factory, engine = await create_test_db()
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
    factory, engine = await create_test_db()
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
                        expires_at=None,
                    )
                )
                session.add(
                    UserBan(
                        id=generate_uuid(),
                        user_id=lapsed.id,
                        reason="spam",
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
    factory, engine = await create_test_db()
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
                    started_at=now - timedelta(days=8),
                    completed_at=now - timedelta(days=8),
                    expires_at=now - timedelta(days=1),
                )
                live = DataExport(
                    id=generate_uuid(),
                    user_id=user.id,
                    status="ready",
                    artifact=b"\x1f\x8b" + b"y" * 20,
                    artifact_encoding="gzip+json",
                    started_at=now - timedelta(days=1),
                    completed_at=now - timedelta(days=1),
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


# --- #608: candidates are revalidated at the delete ---------------------------


async def _stale_guest(users, factory, name: str, *, now: datetime, days: int):
    guest = await users.create_anonymous(name)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(User)
                .where(User.id == UUID(guest.id))
                .values(last_active_at=now - timedelta(days=days))
            )
    return guest


@pytest.mark.asyncio
async def test_a_candidate_claimed_between_selection_and_deletion_is_kept(monkeypatch):
    """The delete repeats the predicates: a registration that lands after the
    select is a registered account, and the sweep is for guests only."""
    import app.auth.retention as retention

    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    try:
        stale = await _stale_guest(users, factory, "Stale", now=now, days=40)
        claimed = await _stale_guest(users, factory, "Claimed", now=now, days=45)
        real = retention._select_candidates

        async def select_then_claim(session, cutoff, **kwargs):
            ids = await real(session, cutoff, **kwargs)
            if UUID(claimed.id) in ids:
                # In the sweep's own transaction: on PostgreSQL the row is
                # locked by the select, so a claim from another session would
                # wait for the sweep instead - this is the interleaving that
                # a select-then-delete-by-id got wrong.
                await session.execute(
                    update(User)
                    .where(User.id == UUID(claimed.id))
                    .values(state="registered", username="claimed", password_hash="x")
                )
            return ids

        monkeypatch.setattr(retention, "_select_candidates", select_then_claim)
        result = await purge_stale_anonymous_accounts(factory, now=now, apply=True)

        assert (result.unused_accounts, result.player_accounts) == (1, 0)
        async with factory() as session:
            assert await session.get(User, UUID(stale.id)) is None
            survivor = await session.get(User, UUID(claimed.id))
            assert survivor is not None and survivor.state == "registered"
            event = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.event_type == "retention.anonymous_purge"
                )
            )
            assert event.details["unused_accounts"] == 1, "what was removed, not selected"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_candidate_seated_or_written_into_a_game_before_the_delete_is_kept(
    monkeypatch,
):
    import app.auth.retention as retention

    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    try:
        seated = await _stale_guest(users, factory, "Seated", now=now, days=40)
        played = await _stale_guest(users, factory, "Played", now=now, days=40)
        gone = await _stale_guest(users, factory, "Gone", now=now, days=40)
        real = retention._select_candidates

        async def select_then_move(session, cutoff, **kwargs):
            ids = await real(session, cutoff, **kwargs)
            if UUID(seated.id) in ids:
                await session.execute(
                    update(User)
                    .where(User.id == UUID(seated.id))
                    .values(last_active_at=now)
                )
                game_id = generate_uuid()
                session.add(
                    GameRecord(
                        id=game_id,
                        room_name="Just finished",
                        scoring_mode="default",
                        hint_mode="none",
                        drawing_seconds=60,
                        total_rounds=1,
                        player_count=1,
                        started_at=now - timedelta(minutes=10),
                        finished_at=now,
                    )
                )
                await session.flush()
                session.add(
                    GameParticipant(
                        id=generate_uuid(),
                        game_id=game_id,
                        user_id=UUID(played.id),
                        final_score=0,
                        final_rank=1,
                    )
                )
                await session.flush()
            return ids

        monkeypatch.setattr(retention, "_select_candidates", select_then_move)
        result = await purge_stale_anonymous_accounts(factory, now=now, apply=True)

        assert (result.unused_accounts, result.player_accounts) == (1, 0)
        async with factory() as session:
            assert await session.get(User, UUID(gone.id)) is None
            assert await session.get(User, UUID(seated.id)) is not None
            assert await session.get(User, UUID(played.id)) is not None
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="skip-locked selection is only real on PostgreSQL",
)
@pytest.mark.asyncio
async def test_a_sweep_skips_a_guest_another_write_holds_and_a_preview_never_waits():
    """Whatever is holding the row - a claim, a merge, a seat, a game write -
    the sweep leaves it for next time instead of queueing gameplay behind
    retention; a preview counts it, because it takes no lock at all."""
    import asyncio

    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    try:
        held = await _stale_guest(users, factory, "Held", now=now, days=40)
        async with factory() as holder:
            async with holder.begin():
                await holder.execute(
                    select(User).where(User.id == UUID(held.id)).with_for_update()
                )
                preview = await asyncio.wait_for(
                    purge_stale_anonymous_accounts(factory, now=now), timeout=5
                )
                assert preview.total == 1
                applied = await asyncio.wait_for(
                    purge_stale_anonymous_accounts(factory, now=now, apply=True),
                    timeout=5,
                )
                assert applied.total == 0, "held rows are skipped, not waited for"
        applied = await purge_stale_anonymous_accounts(factory, now=now, apply=True)
        assert applied.total == 1
    finally:
        await engine.dispose()

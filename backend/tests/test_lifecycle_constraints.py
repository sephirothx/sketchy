"""The lifecycle invariants the database holds, proven on both engines (#553).

Each is a row shape no writer produces and a second writer, a repair script
or a partial restore might: the row refuses it. Every case pairs the shape
the constraint admits with the one it rejects.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.bans import active_ban_filter
from app.db.models import (
    AuthSession,
    DataExport,
    EmailOutboxEntry,
    Friendship,
    GameParticipant,
    GameRecord,
    PlayerReport,
    PromptList,
    PromptUsageFact,
    TurnDrawing,
    TurnPromptOffer,
    TurnRecord,
    UploadedAvatarAsset,
    User,
    UserBan,
    generate_uuid,
)
from app.services.friends import friendship_key

from tests.dbfixtures import create_test_db


NOW = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)


async def _rejects(factory, row) -> None:
    async with factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(row)


async def _accepts(factory, row) -> None:
    async with factory() as session:
        async with session.begin():
            session.add(row)


async def _user(factory, **fields) -> UUID:
    user_id = generate_uuid()
    await _accepts(factory, User(id=user_id, display_name="Someone", **fields))
    return user_id


async def test_a_registered_account_is_the_one_with_credentials_and_only_it():
    factory, engine = await create_test_db()
    try:
        await _accepts(factory, User(id=generate_uuid(), display_name="Guest"))
        await _accepts(
            factory,
            User(id=generate_uuid(), display_name="R", username="r", password_hash="h", state="registered"),
        )
        # A deleted account is representable: no credentials, tombstoned name.
        await _accepts(factory, User(id=generate_uuid(), display_name="Deleted player", state="deleted"))
        await _rejects(factory, User(id=generate_uuid(), display_name="Half", username="half", state="registered"))
        await _rejects(factory, User(id=generate_uuid(), display_name="Ghost", username="g", password_hash="h"))
        await _rejects(
            factory,
            User(id=generate_uuid(), display_name="Gone", username="gone", password_hash="h", state="deleted"),
        )
    finally:
        await engine.dispose()


async def test_a_curated_offer_names_its_version_and_nothing_else_does():
    from app.db.models import PromptConcept, PromptVersion

    factory, engine = await create_test_db()
    try:
        user_id = await _user(factory)
        game_id, seat_id, turn_id = generate_uuid(), generate_uuid(), generate_uuid()
        concept_id, version_id = generate_uuid(), generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(GameRecord(id=game_id, room_name="r", scoring_mode="default", hint_mode="none",
                                       drawing_seconds=60, total_rounds=1, player_count=1,
                                       started_at=NOW, finished_at=NOW))
                await session.flush()
                session.add(GameParticipant(id=seat_id, game_id=game_id, user_id=user_id, final_score=0, final_rank=1))
                await session.flush()
                session.add(TurnRecord(id=turn_id, game_id=game_id, round_number=1, turn_number=1,
                                       drawer_user_id=user_id, drawer_participant_id=seat_id, prompt="p",
                                       duration_seconds=10))
                session.add(PromptConcept(id=concept_id))
                await session.flush()
                session.add(PromptVersion(id=version_id, concept_id=concept_id, language="en", version=1,
                                          canonical_answer="p", match_key="p"))
        await _accepts(factory, TurnPromptOffer(id=generate_uuid(), turn_id=turn_id, position=0, prompt_snapshot="p",
                                                selected=True, source_kind="curated", prompt_version_id=version_id))
        await _accepts(factory, TurnPromptOffer(id=generate_uuid(), turn_id=turn_id, position=1, prompt_snapshot="q",
                                                selected=False, source_kind="custom"))
        await _rejects(factory, TurnPromptOffer(id=generate_uuid(), turn_id=turn_id, position=2, prompt_snapshot="r",
                                                selected=False, source_kind="curated"))
        await _rejects(factory, TurnPromptOffer(id=generate_uuid(), turn_id=turn_id, position=3, prompt_snapshot="s",
                                                selected=False, source_kind="custom", prompt_version_id=version_id))

        # Usage totals: picked at most as often as offered, guessed by at most everyone.
        list_id, revision_id = generate_uuid(), generate_uuid()
        from app.db.models import PromptListRevision

        async with factory() as session:
            async with session.begin():
                session.add(PromptList(id=list_id, slug="l", name="L", is_bundled=True))
                await session.flush()
                session.add(PromptListRevision(id=revision_id, prompt_list_id=list_id, version=1, language="en",
                                               content_hash="0" * 64, letter_counts={}, letter_total=0))
        fact = dict(prompt_list_revision_id=revision_id, prompt_version_id=version_id, occurred_at=NOW,
                    scoring_mode="default", hint_mode="none")
        await _accepts(factory, PromptUsageFact(batch_id=generate_uuid(), offer_count=3, pick_count=1,
                                                correct_guess_count=2, total_guesser_count=2, **fact))
        await _rejects(factory, PromptUsageFact(batch_id=generate_uuid(), offer_count=1, pick_count=2,
                                                correct_guess_count=0, total_guesser_count=2, **fact))
        await _rejects(factory, PromptUsageFact(batch_id=generate_uuid(), offer_count=1, pick_count=1,
                                                correct_guess_count=3, total_guesser_count=2, **fact))

        # The drawing belongs to a turn of its own game.
        other_game = generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(GameRecord(id=other_game, room_name="o", scoring_mode="default", hint_mode="none",
                                       drawing_seconds=60, total_rounds=1, player_count=1,
                                       started_at=NOW, finished_at=NOW))
        await _rejects(factory, TurnDrawing(turn_id=turn_id, game_id=other_game, status="unavailable",
                                            unavailable_reason="recap_budget"))
        await _accepts(factory, TurnDrawing(turn_id=turn_id, game_id=game_id, status="unavailable",
                                            unavailable_reason="recap_budget"))
        async with factory() as session:
            async with session.begin():
                drawing = await session.get(TurnDrawing, turn_id)
                drawing.status = "deleted"
                drawing.unavailable_reason = None
                with pytest.raises(IntegrityError):
                    await session.flush()
        async with factory() as session:
            async with session.begin():
                drawing = await session.get(TurnDrawing, turn_id)
                drawing.status = "deleted"
                drawing.unavailable_reason = None
                drawing.deleted_at = NOW
    finally:
        await engine.dispose()


async def test_a_stored_drawing_says_when_and_its_size_is_its_bytes():
    from tests.test_repositories import _skch_bytes

    factory, engine = await create_test_db()
    try:
        user_id = await _user(factory)
        game_id, seat_id, turn_id = generate_uuid(), generate_uuid(), generate_uuid()
        async with factory() as session:
            async with session.begin():
                session.add(GameRecord(id=game_id, room_name="r", scoring_mode="default", hint_mode="none",
                                       drawing_seconds=60, total_rounds=1, player_count=1,
                                       started_at=NOW, finished_at=NOW))
                await session.flush()
                session.add(GameParticipant(id=seat_id, game_id=game_id, user_id=user_id, final_score=0, final_rank=1))
                await session.flush()
                session.add(TurnRecord(id=turn_id, game_id=game_id, round_number=1, turn_number=1,
                                       drawer_user_id=user_id, drawer_participant_id=seat_id, prompt="p",
                                       duration_seconds=10))
        blob = _skch_bytes()
        ready = dict(turn_id=turn_id, game_id=game_id, status="ready", format_magic="SKCH", format_version=1,
                     payload=blob, checksum_sha256="0" * 64)
        await _rejects(factory, TurnDrawing(byte_size=len(blob), **ready))  # no stored_at
        await _rejects(factory, TurnDrawing(byte_size=len(blob) + 1, stored_at=NOW, **ready))
        await _accepts(factory, TurnDrawing(byte_size=len(blob), stored_at=NOW, **ready))
    finally:
        await engine.dispose()


async def test_reports_friendships_exports_mail_sessions_and_avatars_hold_their_lifecycle():
    factory, engine = await create_test_db()
    try:
        a = await _user(factory, username="a", password_hash="h", state="registered")
        b = await _user(factory, username="b", password_hash="h", state="registered")
        low, high = friendship_key(a, b)
        report = dict(reporter_user_id=a, reported_user_id=b, reason="spam", details="", context_snapshot={})
        await _accepts(factory, PlayerReport(id=generate_uuid(), status="pending", **report))
        await _rejects(factory, PlayerReport(id=generate_uuid(), status="resolved", **report))
        # A decided report carries when it was decided and which decision
        # covered it; neither on its own is enough (#620).
        await _rejects(
            factory, PlayerReport(id=generate_uuid(), status="resolved", reviewed_at=NOW, **report)
        )
        await _rejects(
            factory,
            PlayerReport(
                id=generate_uuid(), status="resolved", decision_group_id=generate_uuid(), **report
            ),
        )
        await _accepts(
            factory,
            PlayerReport(
                id=generate_uuid(),
                status="resolved",
                reviewed_at=NOW,
                decision_group_id=generate_uuid(),
                **report,
            ),
        )

        await _accepts(factory, Friendship(user_low_id=low, user_high_id=high, requested_by_id=a, status="pending"))
        async with factory() as session:
            async with session.begin():
                row = await session.get(Friendship, (low, high))
                row.status = "accepted"
                with pytest.raises(IntegrityError):
                    await session.flush()
        async with factory() as session:
            async with session.begin():
                row = await session.get(Friendship, (low, high))
                row.status = "accepted"
                row.responded_at = NOW

        export = dict(user_id=a, schema_version=1, expires_at=NOW + timedelta(days=7))
        await _accepts(factory, DataExport(id=generate_uuid(), status="pending", **export))
        await _rejects(factory, DataExport(id=generate_uuid(), status="processing", **export))
        await _rejects(factory, DataExport(id=generate_uuid(), status="ready", started_at=NOW, completed_at=NOW, **export))
        await _rejects(factory, DataExport(id=generate_uuid(), status="failed", started_at=NOW, completed_at=NOW, **export))
        await _rejects(factory, DataExport(id=generate_uuid(), status="failed", started_at=NOW, failure_code="x", **export))
        await _accepts(factory, DataExport(id=generate_uuid(), status="failed", started_at=NOW, completed_at=NOW,
                                           failure_code="x", **export))

        mail = dict(user_id=a, to_address="a@b.c", template="verify_email", payload={}, attempts=1, next_attempt_at=NOW)
        await _rejects(factory, EmailOutboxEntry(id=generate_uuid(), state="failed", **mail))
        await _accepts(factory, EmailOutboxEntry(id=generate_uuid(), state="failed", last_error="gave up", **mail))

        await _rejects(factory, AuthSession(id=generate_uuid(), user_id=a, token_hash="1" * 64, device_label="d",
                                            created_at=NOW, expires_at=NOW - timedelta(seconds=1),
                                            idle_expires_at=NOW - timedelta(seconds=1)))
        await _accepts(factory, AuthSession(id=generate_uuid(), user_id=a, token_hash="2" * 64, device_label="d",
                                            created_at=NOW, expires_at=NOW + timedelta(days=1),
                                            idle_expires_at=NOW + timedelta(days=1)))
        # Silence may end a session early, never later than its own expiry.
        await _rejects(factory, AuthSession(id=generate_uuid(), user_id=a, token_hash="3" * 64, device_label="d",
                                            created_at=NOW, expires_at=NOW + timedelta(days=1),
                                            idle_expires_at=NOW + timedelta(days=2)))

        avatar = dict(user_id=a, object_key="k", content_type="image/png", checksum_sha256="0" * 64, payload=b"x")
        await _rejects(factory, UploadedAvatarAsset(id=generate_uuid(), byte_size=0, width=1, height=1, **avatar))
        await _rejects(factory, UploadedAvatarAsset(id=generate_uuid(), byte_size=131073, width=1, height=1, **avatar))
        await _rejects(factory, UploadedAvatarAsset(id=generate_uuid(), byte_size=1, width=0, height=1, **avatar))

        await _rejects(factory, PromptList(id=generate_uuid(), slug="pub", name="P", is_bundled=False, owner_user_id=a,
                                           visibility="public"))
    finally:
        await engine.dispose()


async def test_an_expired_but_unrevoked_ban_is_history_and_not_active():
    """One predicate for active - not revoked, not expired - and the expired
    row stays as what happened rather than being rewritten."""
    factory, engine = await create_test_db()
    try:
        a = await _user(factory)
        expired = UserBan(id=generate_uuid(), user_id=a, reason="spam", created_at=NOW - timedelta(days=10),
                          expires_at=NOW - timedelta(days=1))
        live = UserBan(id=generate_uuid(), user_id=a, reason="spam", created_at=NOW - timedelta(days=1))
        revoked = UserBan(id=generate_uuid(), user_id=a, reason="spam", created_at=NOW - timedelta(days=2),
                          revoked_at=NOW - timedelta(hours=1), revoke_reason="sorry")
        for row in (expired, live, revoked):
            await _accepts(factory, row)
        await _rejects(factory, UserBan(id=generate_uuid(), user_id=a, reason="spam", created_at=NOW,
                                        revoke_reason="without a revocation"))
        async with factory() as session:
            active = (await session.scalars(select(UserBan.id).where(*active_ban_filter(NOW)))).all()
            kept = await session.scalar(select(UserBan.id).where(UserBan.id == expired.id))
        assert active == [live.id]
        assert kept == expired.id, "expired but unrevoked bans remain valid history"
    finally:
        await engine.dispose()

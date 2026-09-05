"""The erasure barrier (#606): nothing composed before a deletion is written after it.

`app.auth.erasure` is the contract; these are its proofs. A deletion erases
what is in the database, and every writer of account-owned content re-reads
the account's lifecycle inside its own transaction, under a shared lock, so
a queued message, a game being written, or a retry from after the deletion
cannot put the erased name, text or pixels back.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth.account_data import anonymize_account
from app.auth.erasure import (
    DELETED_DISPLAY_NAME,
    AccountErasedError,
    erased_identity_ids,
    require_live_account,
)
from app.db.models import (
    GameParticipant,
    IdentityAlias,
    RoomMessage,
    TurnDrawing,
    TurnDrawingReaction,
    TurnGuess,
    TurnRecord,
    User,
    generate_uuid,
)
from app.domain_values import REACTION_EMOJI_CODES, REACTION_SET_VERSION
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    PromptListEntryInput,
    TurnDrawingInput,
    TurnDrawingReactionInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from app.rooms import RoomManager
from app.services.avatars import AvatarError, set_avatar
from app.services.message_retention import MessageRetentionService

from tests.dbfixtures import create_test_db
from tests.test_account_data import _skch_drawing, record_private_game

pytestmark = pytest.mark.asyncio

ON_POSTGRESQL = bool(os.environ.get("TEST_DATABASE_URL"))


async def _accounts(factory) -> tuple[str, str]:
    """A registered account (the one that will be erased) and another player."""
    users = SqlAlchemyUserRepository(factory)
    owner = await users.create_anonymous("Erased soon")
    other = await users.create_anonymous("Other player")
    return owner.id, other.id


async def _seat_rows(factory, game_id: str):
    async with factory() as session:
        seats = (
            await session.scalars(
                select(GameParticipant).where(GameParticipant.game_id == UUID(game_id))
            )
        ).all()
        turns = (
            await session.scalars(
                select(TurnRecord).where(TurnRecord.game_id == UUID(game_id))
            )
        ).all()
        drawings = (
            await session.scalars(
                select(TurnDrawing).where(TurnDrawing.game_id == UUID(game_id))
            )
        ).all()
        guesses = (
            await session.scalars(
                select(TurnGuess).where(
                    TurnGuess.turn_id.in_([turn.id for turn in turns])
                )
            )
        ).all()
    return seats, turns, drawings, guesses


def _assert_erased_only_for(owner_id: str, seats, turns, drawings, guesses):
    owner = UUID(owner_id)
    by_drawer = {turn.drawer_user_id: turn for turn in turns}
    for seat in seats:
        if seat.user_id == owner:
            assert seat.display_name_snapshot == DELETED_DISPLAY_NAME
            assert seat.name_color_snapshot is None
            assert seat.is_anonymous_snapshot is True
        else:
            assert seat.display_name_snapshot == "Other player"
        assert seat.final_score == 250, "scores are facts, and they stay"
    assert by_drawer[owner].drawer_display_name_snapshot == DELETED_DISPLAY_NAME
    for drawing in drawings:
        turn = next(turn for turn in turns if turn.id == drawing.turn_id)
        if turn.drawer_user_id == owner:
            assert drawing.status == "deleted"
            assert drawing.payload is None and drawing.checksum_sha256 is None
            assert drawing.deleted_at is not None
        else:
            assert drawing.status == "ready" and drawing.payload is not None
    for guess in guesses:
        if guess.user_id == owner:
            assert guess.display_name_snapshot == DELETED_DISPLAY_NAME
        assert guess.points_awarded is not None


# --- queued messages ---------------------------------------------------------


async def test_a_queued_lobby_line_by_an_erased_account_is_not_written():
    """The reproduction from #606: compose, erase, flush - and nothing comes back."""
    factory, engine = await create_test_db()
    try:
        owner_id, _ = await _accounts(factory)
        service = MessageRetentionService(factory)
        # Hold the writer back so the line is still queued when the account goes.
        service._ensure_worker = lambda: None  # type: ignore[method-assign]
        message_id = await service.record_lobby(
            user_id=owner_id,
            display_name="Erased soon",
            name_color="#4f9",
            is_anonymous=True,
            text="you will not read this later",
            sent_at=datetime.now(timezone.utc),
        )
        assert message_id is not None

        await anonymize_account(factory, user_id=owner_id)

        del service._ensure_worker
        service._ensure_worker()
        await service.drain()
        await service.aclose()

        async with factory() as session:
            assert await session.scalar(select(RoomMessage)) is None
            owner = await session.get(User, UUID(owner_id))
            assert owner.state == "deleted"
            assert owner.display_name == DELETED_DISPLAY_NAME
    finally:
        await engine.dispose()


async def test_a_queued_batch_keeps_the_lines_of_accounts_still_there():
    factory, engine = await create_test_db()
    try:
        owner_id, other_id = await _accounts(factory)
        room_manager = RoomManager()
        room = room_manager.create_room(name="Mixed batch")
        erased = room_manager.add_player(room, "Erased soon", user_id=owner_id)
        kept = room_manager.add_player(room, "Other player", user_id=other_id)
        erased.sid, kept.sid = "sid-erased", "sid-kept"
        service = MessageRetentionService(factory)
        service._ensure_worker = lambda: None  # type: ignore[method-assign]
        for player, text in ((erased, "gone"), (kept, "stays"), (erased, "gone too")):
            assert (
                await service.record(
                    room=room,
                    player=player,
                    text=text,
                    message_kind="chat",
                    audience="room",
                    recipient_sids=[erased.sid, kept.sid],
                )
                is not None
            )

        await anonymize_account(factory, user_id=owner_id)

        del service._ensure_worker
        service._ensure_worker()
        await service.drain()
        await service.aclose()

        async with factory() as session:
            rows = (await session.scalars(select(RoomMessage))).all()
        assert [row.text for row in rows] == ["stays"]
        assert rows[0].sender_user_id == UUID(other_id)
    finally:
        await engine.dispose()


# --- the finished-game write --------------------------------------------------


async def test_a_game_written_after_erasure_carries_tombstones_and_no_pixels():
    """A game that finished in memory before the deletion and is written after
    it: every fact stays (R-PRIV-05), the erased identity's name, colour,
    drawing and reactions do not."""
    factory, engine = await create_test_db()
    try:
        owner_id, other_id = await _accounts(factory)
        history = SqlAlchemyGameHistoryRepository(factory)

        await anonymize_account(factory, user_id=owner_id)
        game_id = await record_private_game(history, owner_id=owner_id, other_id=other_id)

        _assert_erased_only_for(owner_id, *await _seat_rows(factory, game_id))
    finally:
        await engine.dispose()


async def test_a_game_written_under_a_merged_alias_of_an_erased_account_is_tombstoned():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        account = await users.create_anonymous("Account")
        guest = await users.create_anonymous("Guest identity")
        _, other_id = await _accounts(factory)
        async with factory() as session:
            async with session.begin():
                guest_row = await session.get(User, UUID(guest.id))
                guest_row.state = "merged"
                session.add(
                    IdentityAlias(
                        source_user_id=UUID(guest.id), target_user_id=UUID(account.id)
                    )
                )
        history = SqlAlchemyGameHistoryRepository(factory)

        await anonymize_account(factory, user_id=account.id)
        # The room still knew the seat by the guest identity it sat down with.
        game_id = await record_private_game(history, owner_id=guest.id, other_id=other_id)

        _assert_erased_only_for(guest.id, *await _seat_rows(factory, game_id))
    finally:
        await engine.dispose()


def _same_game_every_time(owner_id: str, other_id: str) -> dict:
    """One game, with fixed ids, so a second `save_game` is a retry of the first.

    Each player draws once and reacts to the other's drawing, which is the
    shape that tells the two reaction rules apart: a reaction *on* an erased
    drawing goes with it, a reaction the erased seat *gave* stays.
    """
    owner_seat, other_seat = str(UUID(int=11)), str(UUID(int=12))
    owner_turn, other_turn = str(UUID(int=21)), str(UUID(int=22))
    started = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    return dict(
        game_record=GameRecordInput(
            id=str(UUID(int=1)),
            room_name="Replayed",
            scoring_mode="default",
            hint_mode="none",
            drawing_seconds=60,
            total_rounds=1,
            player_count=2,
            started_at=started,
            finished_at=started + timedelta(minutes=5),
        ),
        participants=[
            GameParticipantInput(
                user_id=owner_id,
                final_score=250,
                final_rank=1,
                seat_id=owner_seat,
                display_name="Erased soon",
                is_anonymous=False,
            ),
            GameParticipantInput(
                user_id=other_id,
                final_score=250,
                final_rank=1,
                seat_id=other_seat,
                display_name="Other player",
                is_anonymous=False,
            ),
        ],
        turns=[
            TurnRecordInput(
                id=owner_turn,
                round_number=1,
                turn_number=1,
                drawer_user_id=owner_id,
                drawer_seat_id=owner_seat,
                prompt="bridge",
                duration_seconds=60,
            ),
            TurnRecordInput(
                id=other_turn,
                round_number=1,
                turn_number=2,
                drawer_user_id=other_id,
                drawer_seat_id=other_seat,
                prompt="tower",
                duration_seconds=60,
            ),
        ],
        guesses=[],
        drawings=[
            TurnDrawingInput(turn_id=owner_turn, payload=_skch_drawing()),
            TurnDrawingInput(turn_id=other_turn, payload=_skch_drawing()),
        ],
        reactions=[
            TurnDrawingReactionInput(
                turn_id=owner_turn,
                seat_id=other_seat,
                user_id=other_id,
                emoji=REACTION_EMOJI_CODES[0],
                set_version=REACTION_SET_VERSION,
            ),
            TurnDrawingReactionInput(
                turn_id=other_turn,
                seat_id=owner_seat,
                user_id=owner_id,
                emoji=REACTION_EMOJI_CODES[0],
                set_version=REACTION_SET_VERSION,
            ),
        ],
    )


async def _reactions(factory, game_id: str) -> dict[UUID, UUID]:
    """turn id -> reacting seat id, for the reactions the game still has."""
    async with factory() as session:
        rows = (
            await session.scalars(
                select(TurnDrawingReaction).where(
                    TurnDrawingReaction.game_id == UUID(game_id)
                )
            )
        ).all()
    return {row.turn_id: row.participant_id for row in rows}


async def test_a_retry_of_a_game_written_before_erasure_restores_nothing():
    """The delayed-history case (#541): the same write again, after the
    deletion, is the same game - the payload hash is taken from the input,
    so it is neither a conflict nor a restoration."""
    factory, engine = await create_test_db()
    try:
        owner_id, other_id = await _accounts(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        game = _same_game_every_time(owner_id, other_id)
        first = await history.save_game(**game)
        assert await _reactions(factory, first) == {UUID(int=21): UUID(int=12), UUID(int=22): UUID(int=11)}

        await anonymize_account(factory, user_id=owner_id)
        assert await history.save_game(**game) == first

        _assert_erased_only_for(owner_id, *await _seat_rows(factory, first))
        # The reaction on the erased drawing went with it; the one the erased
        # seat gave, on the other drawing, is a fact about that drawing.
        assert await _reactions(factory, first) == {UUID(int=22): UUID(int=11)}
    finally:
        await engine.dispose()


async def test_a_game_first_written_after_erasure_keeps_only_the_reactions_it_gave():
    factory, engine = await create_test_db()
    try:
        owner_id, other_id = await _accounts(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        game = _same_game_every_time(owner_id, other_id)

        await anonymize_account(factory, user_id=owner_id)
        game_id = await history.save_game(**game)

        _assert_erased_only_for(owner_id, *await _seat_rows(factory, game_id))
        assert await _reactions(factory, game_id) == {UUID(int=22): UUID(int=11)}
        # The same game again is still the same game.
        assert await history.save_game(**game) == game_id
    finally:
        await engine.dispose()


# --- request-scoped writes ----------------------------------------------------


async def test_writes_authorized_before_a_deletion_are_refused_after_it():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        owner = await users.create_anonymous("Registered soon")
        async with factory() as session:
            async with session.begin():
                row = await session.get(User, UUID(owner.id))
                row.state = "registered"
                row.username = "registered"
        lists = SqlAlchemyPromptListRepository(factory)
        created = await lists.create_owned(
            owner.id,
            name="Mine",
            description="",
            language="en",
            visibility="private",
            prompts=(PromptListEntryInput(answer="otter"),),
        )

        await anonymize_account(factory, user_id=owner.id)

        with pytest.raises(AccountErasedError):
            await lists.create_owned(
                owner.id,
                name="Too late",
                description="",
                language="en",
                visibility="private",
                prompts=(PromptListEntryInput(answer="otter"),),
            )
        with pytest.raises((AccountErasedError, Exception)):
            await lists.update_owned(
                owner.id,
                created.id,
                expected_version=1,
                name="Too late",
                description="",
                visibility="private",
                prompts=(PromptListEntryInput(answer="otter"),),
            )
        with pytest.raises(AvatarError):
            await set_avatar(factory, user_id=owner.id, payload=b"not even a picture")
        async with factory() as session:
            with pytest.raises(AccountErasedError):
                await require_live_account(session, owner.id)
    finally:
        await engine.dispose()


async def test_an_identity_is_erased_when_its_row_its_account_or_itself_is_gone():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        live = await users.create_anonymous("Live")
        account = await users.create_anonymous("Account")
        alias = await users.create_anonymous("Alias")
        async with factory() as session:
            async with session.begin():
                alias_row = await session.get(User, UUID(alias.id))
                alias_row.state = "merged"
                session.add(
                    IdentityAlias(
                        source_user_id=UUID(alias.id), target_user_id=UUID(account.id)
                    )
                )
        never = generate_uuid()

        async with factory() as session:
            assert await erased_identity_ids(
                session, [UUID(live.id), UUID(alias.id), never]
            ) == {never}

        await anonymize_account(factory, user_id=account.id)
        async with factory() as session:
            assert await erased_identity_ids(
                session, [UUID(live.id), UUID(account.id), UUID(alias.id), never]
            ) == {UUID(account.id), UUID(alias.id), never}
    finally:
        await engine.dispose()


# --- lock ordering, PostgreSQL only -------------------------------------------


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_a_deletion_waits_for_a_game_write_that_holds_the_seats_then_erases_it(
    monkeypatch,
):
    """Writer first: its shared lock makes the deletion's FOR UPDATE wait, and
    the deletion then erases what was just committed."""
    import app.repositories.sqlalchemy as repository

    factory, engine = await create_test_db()
    try:
        owner_id, other_id = await _accounts(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        real = repository.erased_identity_ids
        writer_holds_the_rows = asyncio.Event()
        let_the_writer_commit = asyncio.Event()

        async def paused(session, user_ids):
            result = await real(session, user_ids)
            writer_holds_the_rows.set()
            await let_the_writer_commit.wait()
            return result

        monkeypatch.setattr(repository, "erased_identity_ids", paused)
        write = asyncio.create_task(
            record_private_game(history, owner_id=owner_id, other_id=other_id)
        )
        await writer_holds_the_rows.wait()
        erase = asyncio.create_task(anonymize_account(factory, user_id=owner_id))
        await asyncio.sleep(0.3)
        assert not erase.done(), "the deletion must wait for the writer's shared lock"
        let_the_writer_commit.set()
        game_id, _ = await asyncio.gather(write, erase)

        _assert_erased_only_for(owner_id, *await _seat_rows(factory, game_id))
    finally:
        await engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_a_game_write_waits_for_a_deletion_in_flight_then_writes_tombstones(
    monkeypatch,
):
    """Deletion first: the writer's shared lock waits for the FOR UPDATE, and
    what it then reads is `deleted`."""
    import app.auth.account_data as account_data

    factory, engine = await create_test_db()
    try:
        owner_id, other_id = await _accounts(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        real = account_data.delete_avatars_for
        deletion_holds_the_row = asyncio.Event()
        let_the_deletion_commit = asyncio.Event()

        async def paused(session, identity_ids):
            deletion_holds_the_row.set()
            await let_the_deletion_commit.wait()
            return await real(session, identity_ids)

        monkeypatch.setattr(account_data, "delete_avatars_for", paused)
        erase = asyncio.create_task(anonymize_account(factory, user_id=owner_id))
        await deletion_holds_the_row.wait()
        write = asyncio.create_task(
            record_private_game(history, owner_id=owner_id, other_id=other_id)
        )
        await asyncio.sleep(0.3)
        assert not write.done(), "the writer must wait for the deletion's lock"
        let_the_deletion_commit.set()
        _, game_id = await asyncio.gather(erase, write)

        _assert_erased_only_for(owner_id, *await _seat_rows(factory, game_id))
    finally:
        await engine.dispose()

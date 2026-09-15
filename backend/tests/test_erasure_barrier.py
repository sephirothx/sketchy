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
    LockSetChangedError,
    erased_identity_ids,
    require_live_account,
)
from app.db.models import (
    GameParticipant,
    GameRecord,
    IdentityAlias,
    ProfileDrawingPin,
    RoomMessage,
    TurnDrawing,
    TurnDrawingReaction,
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
    return seats, turns, drawings


def _assert_erased_only_for(owner_id: str, seats, turns, drawings):
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
                row.password_hash = "hash"
        lists = SqlAlchemyPromptListRepository(factory)
        created = await lists.create_owned(
            owner.id,
            name="Mine",
            description="",
            language="en",
            prompts=(PromptListEntryInput(answer="otter"),),
        )

        await anonymize_account(factory, user_id=owner.id)

        with pytest.raises(AccountErasedError):
            await lists.create_owned(
                owner.id,
                name="Too late",
                description="",
                language="en",
                prompts=(PromptListEntryInput(answer="otter"),),
            )
        with pytest.raises((AccountErasedError, Exception)):
            await lists.update_owned(
                owner.id,
                created.id,
                expected_version=1,
                name="Too late",
                description="",
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


async def _merged_guest(factory) -> tuple[str, str]:
    users = SqlAlchemyUserRepository(factory)
    account = await users.create_anonymous("Account")
    guest = await users.create_anonymous("Guest identity")
    async with factory() as session:
        async with session.begin():
            guest_row = await session.get(User, UUID(guest.id))
            guest_row.state = "merged"
            session.add(
                IdentityAlias(source_user_id=UUID(guest.id), target_user_id=UUID(account.id))
            )
    return account.id, guest.id


async def test_both_sides_lock_the_merged_identity_set_in_one_ordered_statement():
    """A seat may carry a guest merged into an account mid-game. The write
    resolves the account before locking and the deletion resolves the guests
    before locking, so each takes one FOR UPDATE over the whole set in
    ascending id order and neither can hold what the other waits for."""
    from sqlalchemy import event

    factory, engine = await create_test_db()
    try:
        account_id, guest_id = await _merged_guest(factory)
        _, other_id = await _accounts(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        captured: list[tuple[str, tuple]] = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            captured.append((statement, parameters))

        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        try:
            await record_private_game(history, owner_id=guest_id, other_id=other_id)
            write_lock = _first_users_lock(captured)
            captured.clear()
            await anonymize_account(factory, user_id=account_id)
            delete_lock = _first_users_lock(captured)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture)

        both = {UUID(account_id), UUID(guest_id)}
        assert both <= write_lock, "the write locks the seat's account beside the seat"
        assert both <= delete_lock, "the deletion locks the merged guest beside the account"
    finally:
        await engine.dispose()


def _first_users_lock(captured) -> set[UUID]:
    """The ids the first SELECT over `users` in the capture asked for."""
    for statement, parameters in captured:
        if statement.startswith("SELECT") and "FROM users" in statement and " IN " in statement:
            values = parameters if isinstance(parameters, (tuple, list)) else tuple(parameters.values())
            return {UUID(hex=str(value)) if not isinstance(value, UUID) else value for value in values}
    raise AssertionError("no locking select over users was captured")


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_a_deletion_cannot_deadlock_with_a_write_under_a_merged_seat(monkeypatch):
    """Writer first, holding the guest seat and its account: the deletion of
    the account waits on the ordered lock instead of taking the account and
    then waiting for the guest the writer holds."""
    import app.repositories.sqlalchemy as repository

    factory, engine = await create_test_db()
    try:
        account_id, guest_id = await _merged_guest(factory)
        _, other_id = await _accounts(factory)
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
            record_private_game(history, owner_id=guest_id, other_id=other_id)
        )
        await writer_holds_the_rows.wait()
        erase = asyncio.create_task(anonymize_account(factory, user_id=account_id))
        await asyncio.sleep(0.3)
        assert not erase.done(), "the deletion must wait for the writer's locks"
        let_the_writer_commit.set()
        game_id, _ = await asyncio.gather(write, erase)

        _assert_erased_only_for(guest_id, *await _seat_rows(factory, game_id))
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


async def _public_game_between(factory, history, pinner_id: str, drawer_id: str) -> tuple[str, UUID, UUID]:
    """A public game the two played, and the turn each drew: (game, drawer's turn, pinner's turn)."""
    game_id = await record_private_game(history, owner_id=drawer_id, other_id=pinner_id)
    async with factory() as session:
        async with session.begin():
            game = await session.get(GameRecord, UUID(game_id))
            game.visibility = "public"
            turns = {
                turn.drawer_user_id: turn.id
                for turn in (
                    await session.scalars(select(TurnRecord).where(TurnRecord.game_id == UUID(game_id)))
                ).all()
            }
    return game_id, turns[UUID(drawer_id)], turns[UUID(pinner_id)]


async def _pins(factory) -> list[tuple[UUID, UUID]]:
    async with factory() as session:
        rows = (await session.scalars(select(ProfileDrawingPin))).all()
    return sorted((row.user_id, row.turn_id) for row in rows)


async def test_a_pin_authorized_before_a_deletion_is_refused_after_it():
    """Both accounts a pin is about are behind the barrier: the pinner, whose
    tombstoned profile must not get a shelf back, and the drawer, whose
    erased drawing must not be pinned after the fact (#811 review)."""
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        drawer_guest = await users.create_anonymous("Drawer")
        drawer = await users.claim_account(drawer_guest.id, "drawer", "hash")
        pinner_guest = await users.create_anonymous("Pinner")
        pinner = await users.claim_account(pinner_guest.id, "pinner", "hash")
        history = SqlAlchemyGameHistoryRepository(factory)
        _, drawers_turn, pinners_turn = await _public_game_between(factory, history, pinner.id, drawer.id)

        assert await history.set_profile_pins(
            requesting_user_id=pinner.id, turn_ids=[str(drawers_turn), str(pinners_turn)]
        )

        await anonymize_account(factory, user_id=drawer.id)
        assert await _pins(factory) == [(UUID(pinner.id), pinners_turn)], "the erased drawing's pin went"
        assert (
            await history.set_profile_pins(requesting_user_id=pinner.id, turn_ids=[str(drawers_turn)])
        ) is None, "an erased drawing cannot be pinned after the fact"
        assert await history.set_profile_pins(requesting_user_id=pinner.id, turn_ids=[str(pinners_turn)])

        await anonymize_account(factory, user_id=pinner.id)
        assert await _pins(factory) == [], "a tombstoned account keeps no shelf"
        assert (
            await history.set_profile_pins(requesting_user_id=pinner.id, turn_ids=[str(pinners_turn)])
        ) is None, "and gets none back"
        assert await _pins(factory) == []
    finally:
        await engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_a_pin_write_waits_for_the_drawers_deletion_in_flight_then_refuses(monkeypatch):
    """The drawer's deletion holds their row FOR UPDATE; a pin of their
    drawing validated under the shared lock waits, then reads the drawing as
    erased and writes nothing - no pin outlives the drawing it names."""
    import app.auth.account_data as account_data

    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        drawer_guest = await users.create_anonymous("Drawer")
        drawer = await users.claim_account(drawer_guest.id, "drawer", "hash")
        pinner_guest = await users.create_anonymous("Pinner")
        pinner = await users.claim_account(pinner_guest.id, "pinner", "hash")
        history = SqlAlchemyGameHistoryRepository(factory)
        _, drawers_turn, _ = await _public_game_between(factory, history, pinner.id, drawer.id)

        real = account_data.delete_avatars_for
        deletion_holds_the_row = asyncio.Event()
        let_the_deletion_commit = asyncio.Event()

        async def paused(session, identity_ids):
            deletion_holds_the_row.set()
            await let_the_deletion_commit.wait()
            return await real(session, identity_ids)

        monkeypatch.setattr(account_data, "delete_avatars_for", paused)
        erase = asyncio.create_task(anonymize_account(factory, user_id=drawer.id))
        await deletion_holds_the_row.wait()
        write = asyncio.create_task(
            history.set_profile_pins(requesting_user_id=pinner.id, turn_ids=[str(drawers_turn)])
        )
        await asyncio.sleep(0.3)
        assert not write.done(), "the pin write must wait for the deletion's lock"
        let_the_deletion_commit.set()
        _, result = await asyncio.gather(erase, write)

        assert result is None
        assert await _pins(factory) == []
    finally:
        await engine.dispose()


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_two_shelf_writes_for_one_account_serialize_instead_of_colliding():
    """Two tabs replacing the same shelf at once: under a shared lock both
    delete nothing and both insert position 0, and the second dies on the
    unique position. Under the exclusive lock the second waits, then replaces
    the first, and the shelf ends as one of the two lists (#811 review)."""
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        drawer_guest = await users.create_anonymous("Drawer")
        drawer = await users.claim_account(drawer_guest.id, "drawer", "hash")
        pinner_guest = await users.create_anonymous("Pinner")
        pinner = await users.claim_account(pinner_guest.id, "pinner", "hash")
        history = SqlAlchemyGameHistoryRepository(factory)
        _, drawers_turn, pinners_turn = await _public_game_between(factory, history, pinner.id, drawer.id)

        for _ in range(5):
            first, second = await asyncio.gather(
                history.set_profile_pins(requesting_user_id=pinner.id, turn_ids=[str(drawers_turn)]),
                history.set_profile_pins(requesting_user_id=pinner.id, turn_ids=[str(pinners_turn)]),
            )
            assert first is not None and second is not None, "both replacements complete"
            pins = await _pins(factory)
            assert pins in (
                [(UUID(pinner.id), drawers_turn)],
                [(UUID(pinner.id), pinners_turn)],
            ), "the shelf is whichever list committed last, whole"
    finally:
        await engine.dispose()


async def _claimed_from_a_merged_guest(users, factory, name: str) -> tuple[str, str]:
    """A registered account and the guest identity merged into it: (account, guest)."""
    account_guest = await users.create_anonymous(name)
    account = await users.claim_account(account_guest.id, name.lower(), "hash")
    guest = await users.create_anonymous(f"{name} as guest")
    async with factory() as session:
        async with session.begin():
            guest_row = await session.get(User, UUID(guest.id))
            guest_row.state = "merged"
            session.add(IdentityAlias(source_user_id=UUID(guest.id), target_user_id=UUID(account.id)))
    return account.id, guest.id


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_crossed_pin_writes_over_merged_drawers_do_not_deadlock():
    """A and B played as guests A' and B', since merged. A pins B''s drawing
    while B pins A''s: each write locks its pinner and the other's guest, and
    reaching for the guest's account in a second statement made a cycle.
    Resolved before locking, both complete (#811 review)."""
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        a, a_guest = await _claimed_from_a_merged_guest(users, factory, "Alpha")
        b, b_guest = await _claimed_from_a_merged_guest(users, factory, "Bravo")
        history = SqlAlchemyGameHistoryRepository(factory)
        _, a_guests_turn, b_guests_turn = await _public_game_between(factory, history, b_guest, a_guest)

        for _ in range(5):
            first, second = await asyncio.gather(
                history.set_profile_pins(requesting_user_id=a, turn_ids=[str(b_guests_turn)]),
                history.set_profile_pins(requesting_user_id=b, turn_ids=[str(a_guests_turn)]),
            )
            assert first is not None and second is not None, "neither write is a deadlock victim"
        assert await _pins(factory) == sorted([(UUID(a), b_guests_turn), (UUID(b), a_guests_turn)])
    finally:
        await engine.dispose()


async def _four_seat_public_game(history, factory, *, a: str, b: str, a_guest: str, b_guest: str) -> tuple[UUID, UUID]:
    """A public game with A and B seated as themselves and two guests drawing:
    (the turn A' drew, the turn B' drew)."""
    seats = {uid: str(generate_uuid()) for uid in (a, b, a_guest, b_guest)}
    turn_a_guest, turn_b_guest = str(generate_uuid()), str(generate_uuid())
    game_id = await history.save_game(
        GameRecordInput(
            room_name="Crossed", scoring_mode="default", scoring_version=1,
            score_ledger_version=1, rule_snapshot_version=1, hint_mode="checkpoints",
            drawing_seconds=90, total_rounds=1, player_count=4,
            started_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 8, 21, 12, 10, tzinfo=timezone.utc),
            prompt_source_mode="custom", visibility="public",
        ),
        [
            GameParticipantInput(user_id=uid, final_score=0, final_rank=1, seat_id=seat, display_name=uid[:6])
            for uid, seat in seats.items()
        ],
        [
            TurnRecordInput(
                id=turn_a_guest, round_number=1, turn_number=1, drawer_user_id=a_guest,
                drawer_seat_id=seats[a_guest], prompt="one", duration_seconds=10,
                prompt_source_kind="custom", guesser_count=0,
            ),
            TurnRecordInput(
                id=turn_b_guest, round_number=1, turn_number=2, drawer_user_id=b_guest,
                drawer_seat_id=seats[b_guest], prompt="two", duration_seconds=10,
                prompt_source_kind="custom", guesser_count=0,
            ),
        ],
        [],
        [
            TurnDrawingInput(turn_id=turn_a_guest, payload=_skch_drawing()),
            TurnDrawingInput(turn_id=turn_b_guest, payload=_skch_drawing()),
        ],
    )
    assert game_id
    return UUID(turn_a_guest), UUID(turn_b_guest)


async def _merge(factory, guest_id: str, into: str) -> None:
    async with factory() as session:
        async with session.begin():
            row = await session.get(User, UUID(guest_id))
            row.state = "merged"
            session.add(IdentityAlias(source_user_id=UUID(guest_id), target_user_id=UUID(into)))


@pytest.mark.skipif(not ON_POSTGRESQL, reason="row locks are only real on PostgreSQL")
async def test_a_merge_inside_the_barriers_window_restarts_the_pin_write_instead_of_locking_more(
    monkeypatch,
):
    """A and B sit in a public game where guests A' and B' drew. A pins B''s
    turn and B pins A''s, and both merges commit after each write's unlocked
    alias read and before its lock. Locking the newly found targets in a
    second statement gave each writer one of {A, B} while wanting the other;
    the exclusive barrier now abandons the transaction and the write starts
    again with the whole set (#811 review)."""
    import app.auth.erasure as erasure

    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        a = (await users.claim_account((await users.create_anonymous("A")).id, "alpha", "hash")).id
        b = (await users.claim_account((await users.create_anonymous("B")).id, "bravo", "hash")).id
        a_guest = (await users.create_anonymous("A as guest")).id
        b_guest = (await users.create_anonymous("B as guest")).id
        history = SqlAlchemyGameHistoryRepository(factory)
        turn_a_guest, turn_b_guest = await _four_seat_public_game(
            history, factory, a=a, b=b, a_guest=a_guest, b_guest=b_guest
        )

        # The first pass of each write pauses after its alias read; the
        # merges commit in that window; the retries run through untouched.
        paused = 0
        both_paused = asyncio.Event()
        merges_committed = asyncio.Event()

        async def pause_once() -> None:
            nonlocal paused
            paused += 1
            if paused <= 2:
                if paused == 2:
                    both_paused.set()
                await merges_committed.wait()

        monkeypatch.setattr(erasure, "_after_alias_resolution", pause_once)
        writes = asyncio.gather(
            history.set_profile_pins(requesting_user_id=a, turn_ids=[str(turn_b_guest)]),
            history.set_profile_pins(requesting_user_id=b, turn_ids=[str(turn_a_guest)]),
        )
        await asyncio.wait_for(both_paused.wait(), timeout=5)
        await _merge(factory, a_guest, into=a)
        await _merge(factory, b_guest, into=b)
        merges_committed.set()
        first, second = await asyncio.wait_for(writes, timeout=10)

        assert first is not None and second is not None, "neither write is a deadlock victim"
        assert paused > 2, "at least one write started over"
        assert await _pins(factory) == sorted([(UUID(a), turn_b_guest), (UUID(b), turn_a_guest)])
    finally:
        await engine.dispose()


async def test_an_exclusive_barrier_refuses_to_lock_a_target_found_under_its_lock(monkeypatch):
    """The abort itself, on any engine: a merge landing in the window makes
    the exclusive barrier raise rather than take a second lock; the shared
    barrier still resolves it in place, as every other writer relies on."""
    import app.auth.erasure as erasure

    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        account = (await users.claim_account((await users.create_anonymous("Acct")).id, "acct", "hash")).id
        guest = (await users.create_anonymous("Guest")).id

        merged = False

        async def merge_now() -> None:
            # Once: the shared read below runs through the same seam.
            nonlocal merged
            if merged:
                return
            merged = True
            await _merge(factory, guest, into=account)

        monkeypatch.setattr(erasure, "_after_alias_resolution", merge_now)
        async with factory() as session:
            async with session.begin():
                with pytest.raises(LockSetChangedError):
                    await erased_identity_ids(session, (UUID(guest),), exclusive=True)
        async with factory() as session:
            async with session.begin():
                assert await erased_identity_ids(session, (UUID(guest),)) == set()
    finally:
        await engine.dispose()

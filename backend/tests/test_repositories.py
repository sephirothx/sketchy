"""Unit tests for repository implementations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    GameParticipant,
    GamePromptSource,
    GameRecord,
    Prompt,
    PromptList,
    ScoreEvent,
    TurnDrawing,
    TurnGuess,
    TurnParticipantOutcome,
    TurnPromptOffer,
    TurnPromptOfferSource,
    TurnRecord,
    PromptListLocalization,
    PromptListRevision,
    PromptUsageFact,
    PromptVersion,
    generate_uuid,
)
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    BundledPromptDefinition,
    GameHistoryConflictError,
    GameParticipantInput,
    GameRecordInput,
    InvalidProfileDataError,
    TurnGuessInput,
    TurnParticipantOutcomeInput,
    TurnDrawingInput,
    TurnRecordInput,
    UsernameTakenError,
    PromptPickTotals,
    PromptListSelectionError,
    PromptOfferInput,
    ScoreEventInput,
    PromptSeedConflictError,
    PromptUsage,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyPromptListRepository,
)

from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio


async def test_user_repository_crud_and_stats():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyUserRepository(factory)

        # 1. Create anonymous user
        anon = await repo.create_anonymous("Bob", name_color=None)
        assert isinstance(anon.id, str)
        assert UUID(anon.id).version == 7
        assert anon.display_name == "Bob"
        assert anon.is_anonymous is True
        assert anon.username is None

        # 2. Get by ID (no password hash attribute in UserData)
        fetched = await repo.get_by_id(anon.id)
        assert fetched is not None
        assert fetched.id == anon.id
        assert not hasattr(fetched, "password_hash")

        # 3. Claim account
        claimed = await repo.claim_account(anon.id, "bob123", "hashed_pw")
        assert claimed.username == "bob123"
        assert claimed.is_anonymous is False

        # 4. Cannot claim an already claimed account
        with pytest.raises(AccountAlreadyClaimedError):
            await repo.claim_account(anon.id, "bob999", "another_hash")

        # 5. Username uniqueness on claim (case-insensitive)
        anon2 = await repo.create_anonymous("Alice")
        with pytest.raises(UsernameTakenError):
            await repo.claim_account(anon2.id, "BOB123", "hash2")

        # 6. Fetch credentials separately via auth-specific method
        creds = await repo.get_credentials_by_username("BOB123")
        assert creds is not None
        assert creds.user.id == anon.id
        assert creds.password_hash == "hashed_pw"

        assert await repo.replace_password_hash(
            anon.id, "wrong-current-hash", "replacement"
        ) is False
        assert await repo.replace_password_hash(
            anon.id, "hashed_pw", "replacement"
        ) is True
        creds = await repo.get_credentials_by_username("BOB123")
        assert creds is not None and creds.password_hash == "replacement"

        # 7. Get by username (case-insensitive) returns UserData without password_hash
        by_name = await repo.get_by_username("BOB123")
        assert by_name is not None
        assert by_name.id == anon.id
        assert not hasattr(by_name, "password_hash")

        # 8. Update profile with a deployment-hosted avatar key.
        updated = await repo.update_profile(
            anon.id, name_color="#00ff00", avatar_key="PENCIL"
        )
        assert updated is not None
        assert updated.name_color == "#00ff00"
        assert updated.avatar_key == "pencil"

        # Arbitrary URLs and unrecognized asset names never reach a browser.
        with pytest.raises(InvalidProfileDataError):
            await repo.update_profile(
                anon.id, avatar_key="https://example.com/avatar.png"
            )

        with pytest.raises(InvalidProfileDataError):
            await repo.update_profile(anon.id, avatar_key="unknown")

        # 9. Stats with 0 games
        stats = await repo.get_stats(anon.id)
        assert stats.games_played == 0
        assert stats.total_score == 0
        assert stats.win_rate == 0.0
    finally:
        await engine.dispose()


async def test_game_history_repository():
    factory, engine = await create_test_db()
    try:
        user_repo = SqlAlchemyUserRepository(factory)
        history_repo = SqlAlchemyGameHistoryRepository(factory)

        u1 = await user_repo.create_anonymous("Player1")
        u2 = await user_repo.create_anonymous("Player2")
        u3 = await user_repo.create_anonymous("Player3_NonParticipant")
        u1 = await user_repo.update_profile(
            u1.id, name_color="#112233", avatar_key="pencil"
        )
        u2 = await user_repo.update_profile(
            u2.id, name_color="#223344", avatar_key="spark"
        )
        assert u1 is not None and u2 is not None

        now = datetime.now(timezone.utc)
        game_input = GameRecordInput(
            room_name="Test Room",
            scoring_mode="default",
            hint_mode="checkpoints",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=now,
            finished_at=now,
        )
        participants = [
            GameParticipantInput(user_id=u1.id, final_score=350, final_rank=1),
            GameParticipantInput(user_id=u2.id, final_score=200, final_rank=2),
        ]
        turn_id = str(generate_uuid())
        rounds = [
            TurnRecordInput(
                id=turn_id,
                round_number=1,
                turn_number=1,
                drawer_user_id=u1.id,
                prompt="guitar",
                duration_seconds=30.0,
            )
        ]
        guesses = [
            TurnGuessInput(
                turn_id=turn_id,
                user_id=u2.id,
                points_awarded=200,
                guess_time_seconds=10.0,
            )
        ]

        game_id = await history_repo.save_game(game_input, participants, rounds, guesses)
        assert game_id is not None
        async with factory() as session:
            stored_game = await session.get(GameRecord, UUID(game_id))
            stored_participants = (
                await session.scalars(
                    select(GameParticipant).where(
                        GameParticipant.game_id == UUID(game_id)
                    )
                )
            ).all()
            stored_turn = await session.get(TurnRecord, UUID(turn_id))
            stored_guess = await session.scalar(
                select(TurnGuess).where(TurnGuess.turn_id == UUID(turn_id))
            )
            assert stored_game is not None and stored_game.persisted_at is not None
            assert all(item.created_at is not None for item in stored_participants)
            assert stored_turn is not None and stored_turn.created_at is not None
            assert stored_guess is not None and stored_guess.created_at is not None

        # A guess cannot reference a turn outside this write.
        invalid_guesses = [
            TurnGuessInput(
                turn_id=str(generate_uuid()),
                user_id=u2.id,
                points_awarded=100,
                guess_time_seconds=5.0,
            )
        ]
        with pytest.raises(ValueError, match="unknown turn_id"):
            await history_repo.save_game(game_input, participants, rounds, invalid_guesses)

        await user_repo.update_profile(
            u1.id,
            display_name="RenamedLater",
            name_color="#aabbcc",
            avatar_key="palette",
        )
        await user_repo.update_profile(
            u2.id,
            display_name="AlsoRenamed",
            name_color="#bbccdd",
            avatar_key="initial",
        )

        # Check user games list with pagination clamping
        u1_games = await history_repo.get_user_games(u1.id, limit=999999, offset=-5)
        assert len(u1_games) == 1
        assert u1_games[0].id == game_id
        assert len(u1_games[0].participants) == 2
        assert u1_games[0].participants[0].user_id == u1.id
        assert u1_games[0].participants[0].seat_id
        assert u1_games[0].participants[0].display_name == "Player1"
        assert u1_games[0].participants[0].name_color == "#112233"

        # Check game detail for participant (authorized)
        detail = await history_repo.get_game_detail(game_id, requesting_user_id=u1.id)
        assert detail is not None
        assert detail.summary.id == game_id
        assert len(detail.turns) == 1
        assert detail.turns[0].prompt == "guitar"
        assert detail.turns[0].drawer_display_name == "Player1"
        assert detail.turns[0].drawer_name_color == "#112233"
        assert detail.turns[0].drawer_is_anonymous
        assert detail.turns[0].drawer_user_id == u1.id
        assert len(detail.turns[0].guesses) == 1
        assert detail.turns[0].guesses[0].user_id == u2.id
        assert detail.turns[0].guesses[0].display_name == "Player2"
        assert detail.turns[0].guesses[0].name_color == "#223344"
        assert detail.turns[0].guesses[0].is_anonymous
        assert detail.turns[0].guesses[0].points_awarded == 200

        # Check game detail for non-participant (scoped out)
        unauthorized_detail = await history_repo.get_game_detail(game_id, requesting_user_id=u3.id)
        assert unauthorized_detail is None

        # Check aggregated stats for users
        u1_stats = await user_repo.get_stats(u1.id)
        assert u1_stats.games_played == 1
        assert u1_stats.games_won == 1
        assert u1_stats.win_rate == 1.0
        assert u1_stats.total_score == 350
        assert u1_stats.drawings_made == 1
        assert u1_stats.prompts_guessed == 0

        u2_stats = await user_repo.get_stats(u2.id)
        assert u2_stats.games_played == 1
        assert u2_stats.games_won == 0
        assert u2_stats.win_rate == 0.0
        assert u2_stats.total_score == 200
        assert u2_stats.prompts_guessed == 1
        assert u2_stats.drawings_made == 0
    finally:
        await engine.dispose()


async def test_game_history_preserves_distinct_accountless_seats():
    factory, engine = await create_test_db()
    try:
        user_repo = SqlAlchemyUserRepository(factory)
        history_repo = SqlAlchemyGameHistoryRepository(factory)
        account = await user_repo.create_anonymous("Account player")
        account_seat_id = str(generate_uuid())
        drawer_seat_id = str(generate_uuid())
        guesser_seat_id = str(generate_uuid())
        turn_id = str(generate_uuid())
        now = datetime.now(timezone.utc)

        game_id = await history_repo.save_game(
            GameRecordInput(
                room_name="Accountless seats",
                scoring_mode="default",
                hint_mode="none",
                drawing_seconds=90,
                total_rounds=1,
                player_count=3,
                started_at=now,
                finished_at=now,
            ),
            [
                GameParticipantInput(
                    account.id, 50, 3, seat_id=account_seat_id,
                    display_name="Account player",
                ),
                GameParticipantInput(
                    None,
                    300,
                    1,
                    seat_id=drawer_seat_id,
                    display_name="No-cookie drawer",
                    name_color="#112233",
                ),
                GameParticipantInput(
                    None,
                    200,
                    2,
                    seat_id=guesser_seat_id,
                    display_name="No-cookie guesser",
                    name_color="#445566",
                ),
            ],
            [
                TurnRecordInput(
                    id=turn_id,
                    round_number=1,
                    turn_number=1,
                    drawer_user_id=None,
                    drawer_seat_id=drawer_seat_id,
                    prompt="guitar",
                    duration_seconds=12.0,
                    guesser_count=2,
                    wrong_guess_count=1,
                    participant_outcomes=(
                        TurnParticipantOutcomeInput(
                            seat_id=guesser_seat_id,
                            user_id=None,
                            eligible=True,
                            eligibility_reason="eligible",
                            outcome="correct",
                            terminal_state="active",
                            correct_guess_time_seconds=8.0,
                            wrong_guess_count=1,
                        ),
                        TurnParticipantOutcomeInput(
                            seat_id=account_seat_id,
                            user_id=account.id,
                            eligible=True,
                            eligibility_reason="eligible",
                            outcome="no_attempt",
                            terminal_state="active",
                        ),
                    ),
                )
            ],
            [
                TurnGuessInput(
                    turn_id=turn_id,
                    user_id=None,
                    seat_id=guesser_seat_id,
                    points_awarded=200,
                    guess_time_seconds=8.0,
                    wrong_guesses_before=1,
                )
            ],
        )

        detail = await history_repo.get_game_detail(game_id, account.id)
        assert detail is not None
        assert len(detail.summary.participants) == 3
        accountless = {
            participant.seat_id: participant
            for participant in detail.summary.participants
            if participant.user_id is None
        }
        assert set(accountless) == {drawer_seat_id, guesser_seat_id}
        assert accountless[drawer_seat_id].display_name == "No-cookie drawer"
        assert accountless[guesser_seat_id].display_name == "No-cookie guesser"
        assert detail.turns[0].drawer_user_id is None
        assert detail.turns[0].drawer_seat_id == drawer_seat_id
        assert detail.turns[0].drawer_display_name == "No-cookie drawer"
        assert detail.turns[0].guesses[0].user_id is None
        assert detail.turns[0].guesses[0].seat_id == guesser_seat_id
        assert detail.turns[0].guesses[0].display_name == "No-cookie guesser"
        outcomes = {
            outcome.seat_id: outcome
            for outcome in detail.turns[0].participant_outcomes
        }
        assert outcomes[guesser_seat_id].outcome == "correct"
        assert outcomes[guesser_seat_id].wrong_guess_count == 1
        assert outcomes[account_seat_id].outcome == "no_attempt"

        async with factory() as session:
            stored_turn = await session.get(TurnRecord, UUID(turn_id))
            stored_guess = await session.scalar(
                select(TurnGuess).where(TurnGuess.turn_id == UUID(turn_id))
            )
            stored_outcomes = (
                await session.scalars(
                    select(TurnParticipantOutcome).where(
                        TurnParticipantOutcome.turn_id == UUID(turn_id)
                    )
                )
            ).all()
        assert stored_turn is not None
        assert stored_turn.drawer_user_id is None
        assert str(stored_turn.drawer_participant_id) == drawer_seat_id
        assert stored_guess is not None
        assert stored_guess.user_id is None
        assert str(stored_guess.participant_id) == guesser_seat_id
        assert stored_guess.outcome_id is not None
        assert len(stored_outcomes) == 2
    finally:
        await engine.dispose()


async def test_game_history_stable_id_is_idempotent_and_rejects_conflicts():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        first = await users.create_anonymous("Stable one")
        second = await users.create_anonymous("Stable two")
        now = datetime.now(timezone.utc)
        game_id = str(generate_uuid())
        record = GameRecordInput(
            id=game_id,
            room_name="Stable room",
            scoring_mode="default",
            hint_mode="none",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=now,
            finished_at=now,
        )
        participants = [
            GameParticipantInput(first.id, 100, 1),
            GameParticipantInput(second.id, 50, 2),
        ]

        assert await history.save_game(record, participants, [], []) == game_id
        assert (
            await history.save_game(record, list(reversed(participants)), [], [])
            == game_id
        )
        async with factory() as session:
            assert await session.scalar(select(func.count(GameRecord.id))) == 1
            stored = await session.get(GameRecord, UUID(game_id))
            assert stored is not None and len(stored.payload_hash) == 64
            assert stored.persisted_at is not None

        changed = GameRecordInput(
            id=game_id,
            room_name="Conflicting room",
            scoring_mode=record.scoring_mode,
            hint_mode=record.hint_mode,
            drawing_seconds=record.drawing_seconds,
            total_rounds=record.total_rounds,
            player_count=record.player_count,
            started_at=record.started_at,
            finished_at=record.finished_at,
        )
        with pytest.raises(GameHistoryConflictError, match="different content"):
            await history.save_game(changed, participants, [], [])
    finally:
        await engine.dispose()


async def test_score_event_ledger_reconciles_and_is_returned_in_order():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        drawer = await users.create_anonymous("Ledger drawer")
        guesser = await users.create_anonymous("Ledger guesser")
        drawer_seat = str(generate_uuid())
        guesser_seat = str(generate_uuid())
        turn_id = str(generate_uuid())
        event_ids = [str(generate_uuid()) for _ in range(3)]
        stable_game_id = str(generate_uuid())
        now = datetime.now(timezone.utc)
        record = GameRecordInput(
            id=stable_game_id,
            room_name="Ledger room",
            scoring_mode="default",
            scoring_version=1,
            score_ledger_version=1,
            rule_snapshot_version=1,
            hint_mode="purchase",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=now,
            finished_at=now,
        )
        participants = [
            GameParticipantInput(
                drawer.id, 250, 1, seat_id=drawer_seat, display_name="Ledger drawer"
            ),
            GameParticipantInput(
                guesser.id,
                249,
                1,
                seat_id=guesser_seat,
                display_name="Ledger guesser",
            ),
        ]
        turns = [
            TurnRecordInput(
                id=turn_id,
                round_number=1,
                turn_number=1,
                drawer_user_id=drawer.id,
                drawer_seat_id=drawer_seat,
                prompt="guitar",
                duration_seconds=20,
                guesser_count=1,
                participant_outcomes=(
                    TurnParticipantOutcomeInput(
                        seat_id=guesser_seat,
                        user_id=guesser.id,
                        eligible=True,
                        eligibility_reason="eligible",
                        outcome="correct",
                        terminal_state="active",
                        correct_guess_time_seconds=10,
                        hints_used=1,
                        points_spent_on_hints=50,
                    ),
                ),
            )
        ]
        guesses = [
            TurnGuessInput(
                turn_id=turn_id,
                user_id=guesser.id,
                seat_id=guesser_seat,
                points_awarded=250,
                guess_time_seconds=10,
                hints_used=1,
                points_spent_on_hints=50,
            )
        ]
        events = [
            ScoreEventInput(
                id=event_ids[0],
                participant_seat_id=guesser_seat,
                participant_user_id=guesser.id,
                turn_id=turn_id,
                event_order=1,
                event_type="guess_award",
                points_delta=300,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            ScoreEventInput(
                id=event_ids[1],
                participant_seat_id=guesser_seat,
                participant_user_id=guesser.id,
                turn_id=turn_id,
                event_order=2,
                event_type="hint_charge",
                points_delta=-50,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            ScoreEventInput(
                id=event_ids[2],
                participant_seat_id=drawer_seat,
                participant_user_id=drawer.id,
                turn_id=turn_id,
                event_order=3,
                event_type="drawer_bonus",
                points_delta=250,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
        ]

        with pytest.raises(ValueError, match="does not reconcile"):
            await history.save_game(record, participants, turns, guesses, events)

        participants[1] = GameParticipantInput(
            guesser.id,
            250,
            1,
            seat_id=guesser_seat,
            display_name="Ledger guesser",
        )
        game_id = await history.save_game(record, participants, turns, guesses, events)
        assert (
            await history.save_game(
                record, participants, turns, guesses, list(reversed(events))
            )
            == game_id
        )
        detail = await history.get_game_detail(game_id, drawer.id)
        assert detail is not None
        assert detail.summary.score_ledger_version == 1
        assert [event.id for event in detail.score_events] == event_ids
        assert [event.points_delta for event in detail.score_events] == [300, -50, 250]
        async with factory() as session:
            assert await session.scalar(select(func.count(ScoreEvent.id))) == 3
    finally:
        await engine.dispose()


async def test_game_history_records_the_actual_prompt_pool_and_every_offer():
    factory, engine = await create_test_db()
    try:
        users = SqlAlchemyUserRepository(factory)
        history = SqlAlchemyGameHistoryRepository(factory)
        prompts = SqlAlchemyPromptListRepository(factory)
        drawer = await users.create_anonymous("Source drawer")
        guesser = await users.create_anonymous("Source guesser")
        await prompts.upsert_bundled(
            slug="source-list",
            name="Source list",
            description="",
            language="en",
            prompts=[
                BundledPromptDefinition(str(generate_uuid()), answer)
                for answer in ("apple", "banana", "castle")
            ],
            version=1,
        )
        selection = await prompts.resolve_selection(["source-list"])
        revision_id = selection.revision_ids[0]
        turn_id = str(generate_uuid())
        now = datetime.now(timezone.utc)
        game_id = await history.save_game(
            GameRecordInput(
                room_name="Exact source room",
                scoring_mode="default",
                hint_mode="none",
                drawing_seconds=90,
                total_rounds=1,
                player_count=2,
                started_at=now,
                finished_at=now,
                prompt_source_mode="curated",
                prompt_source_revision_ids=(revision_id,),
            ),
            [
                GameParticipantInput(drawer.id, 300, 1),
                GameParticipantInput(guesser.id, 100, 2),
            ],
            [
                TurnRecordInput(
                    id=turn_id,
                    round_number=1,
                    turn_number=1,
                    drawer_user_id=drawer.id,
                    prompt="banana",
                    duration_seconds=20,
                    prompt_version_id=selection.prompt_version_ids["banana"],
                    prompt_source_kind="curated",
                    prompt_offers=tuple(
                        PromptOfferInput(
                            position=position,
                            prompt=answer,
                            selected=answer == "banana",
                            source_kind="curated",
                            prompt_version_id=selection.prompt_version_ids[answer],
                            source_revision_ids=selection.prompt_source_revision_ids[
                                answer
                            ],
                        )
                        for position, answer in enumerate(selection.prompts)
                    ),
                )
            ],
            [],
        )

        async with factory() as session:
            assert (
                await session.scalar(select(func.count(GamePromptSource.game_id)))
                == 1
            )
            assert (
                await session.scalar(select(func.count(TurnPromptOffer.id))) == 3
            )
            assert (
                await session.scalar(
                    select(func.count(TurnPromptOfferSource.offer_id))
                )
                == 3
            )
        detail = await history.get_game_detail(game_id, drawer.id)
        assert detail is not None
        assert detail.summary.prompt_source_mode == "curated"
        assert detail.turns[0].prompt_version_id == selection.prompt_version_ids[
            "banana"
        ]
        assert detail.turns[0].prompt_source_kind == "curated"
        assert [offer.prompt for offer in detail.turns[0].prompt_offers] == [
            "apple",
            "banana",
            "castle",
        ]
        assert [
            offer.prompt for offer in detail.turns[0].prompt_offers if offer.selected
        ] == ["banana"]
        assert all(
            offer.source_revision_ids == (revision_id,)
            for offer in detail.turns[0].prompt_offers
        )
    finally:
        await engine.dispose()


async def test_prompt_list_repository():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)

        # 1. Upsert bundled prompt list
        apple_concept = str(generate_uuid())
        banana_concept = str(generate_uuid())
        cherry_concept = str(generate_uuid())
        wl = await repo.upsert_bundled(
            slug="standard",
            name="Standard List",
            description="Standard curated words",
            language="en",
            prompts=[
                BundledPromptDefinition(
                    apple_concept,
                    "apple",
                    aliases=("malus",),
                    tags=("fruit",),
                ),
                BundledPromptDefinition(banana_concept, "banana"),
                BundledPromptDefinition(cherry_concept, "cherry"),
            ],
            version=1,
        )
        assert wl.slug == "standard"
        assert wl.prompt_count == 3
        async with factory() as session:
            stored_list = await session.get(PromptList, UUID(wl.id))
            assert stored_list is not None
            assert stored_list.owner_user_id is None
            assert stored_list.visibility == "public"
            assert stored_list.moderation_state == "active"

        # 2. List all
        all_lists = await repo.list_all()
        assert len(all_lists) == 1
        assert all_lists[0].slug == "standard"

        # A write outside the bundled-list helper cannot make the count stale.
        async with factory() as session:
            async with session.begin():
                session.add(
                    Prompt(
                        id=generate_uuid(),
                        prompt_list_id=UUID(wl.id),
                        text="dragonfruit",
                    )
                )
        assert (await repo.get_by_slug("standard")).prompt_count == 4
        assert (await repo.list_all())[0].prompt_count == 4
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(Prompt).where(
                        Prompt.prompt_list_id == UUID(wl.id),
                        Prompt.text == "dragonfruit",
                    )
                )

        # 3. Get words
        words = await repo.get_prompts(wl.id)
        assert words == ["apple", "banana", "cherry"]

        # 4. Get by slugs
        slug_words = await repo.get_prompts_by_slugs(["standard"])
        assert slug_words == ["apple", "banana", "cherry"]
        resolved = await repo.resolve_selection(["standard"])
        assert resolved.language == "en"
        assert resolved.prompts == ("apple", "banana", "cherry")
        assert resolved.aliases["apple"] == ("malus",)
        assert len(resolved.revision_ids) == 1
        assert resolved.prompt_version_ids["apple"]
        assert resolved.prompt_source_revision_ids["apple"] == resolved.revision_ids

        french = await repo.upsert_bundled(
            slug="francais",
            name="Français",
            description="Mots français",
            language="fr",
            prompts=[
                BundledPromptDefinition(str(generate_uuid()), "éléphant"),
                BundledPromptDefinition(str(generate_uuid()), "vélo"),
            ],
            version=1,
        )
        async with factory() as session:
            async with session.begin():
                session.add(
                    PromptListLocalization(
                        prompt_list_id=UUID(french.id),
                        locale="en",
                        name="French",
                        description="French words",
                    )
                )
        french_lists = await repo.list_all(language="fr", locale="en")
        assert [(entry.slug, entry.name, entry.language) for entry in french_lists] == [
            ("francais", "French", "fr")
        ]
        with pytest.raises(PromptListSelectionError, match="same language"):
            await repo.resolve_selection(["standard", "francais"])
        with pytest.raises(PromptListSelectionError, match="not found"):
            await repo.resolve_selection(["missing"])

        # 5. Record one finished game's offers and picks
        apple_id = resolved.prompt_version_ids["apple"]
        banana_id = resolved.prompt_version_ids["banana"]
        await repo.record_prompt_usage(
            resolved.revision_ids,
            PromptUsage(
                offers={
                    apple_id: 1,
                    banana_id: 1,
                    str(generate_uuid()): 1,
                },
                picks={
                    apple_id: PromptPickTotals(
                        picks=1, correct_guesses=3, total_guessers=4
                    )
                },
            ),
        )

        stats = await repo.get_prompt_stats("standard")
        apple_stat = next(s for s in stats if s.text == "apple")
        assert apple_stat.offer_count == 1
        assert apple_stat.pick_count == 1
        assert apple_stat.correct_guess_count == 3
        assert apple_stat.total_guesser_count == 4
        assert apple_stat.pick_rate == 1.0
        assert apple_stat.correct_guess_ratio == 0.75

        banana_stat = next(s for s in stats if s.text == "banana")
        assert banana_stat.offer_count == 1
        assert banana_stat.pick_count == 0
        assert banana_stat.pick_rate == 0.0

        # 7. Version upgrade maintains stats
        date_concept = str(generate_uuid())
        first_revision_ids = resolved.revision_ids
        upgraded = await repo.upsert_bundled(
            slug="standard",
            name="Standard List v2",
            description="Updated words",
            language="en",
            prompts=[
                BundledPromptDefinition(
                    apple_concept,
                    "apple tree",
                    prompt_version=2,
                    aliases=("apple", "malus"),
                    tags=("fruit",),
                ),
                BundledPromptDefinition(date_concept, "date"),
            ],
            version=2,
        )
        assert upgraded.version == 2
        assert upgraded.prompt_count == 2

        new_stats = await repo.get_prompt_stats("standard")
        assert len(new_stats) == 2
        apple_stat_v2 = next(s for s in new_stats if s.text == "apple tree")
        assert apple_stat_v2.pick_count == 1  # preserved stats
        resolved_v2 = await repo.resolve_selection(["standard"])
        assert resolved_v2.revision_ids != first_revision_ids
        assert resolved_v2.aliases["apple tree"] == ("apple", "malus")
        assert (
            resolved_v2.prompt_version_ids["apple tree"]
            != resolved.prompt_version_ids["apple"]
        )
        async with factory() as session:
            revisions = (
                await session.execute(
                    select(PromptListRevision).where(
                        PromptListRevision.prompt_list_id == UUID(wl.id)
                    )
                )
            ).scalars().all()
            versions = (
                await session.execute(
                    select(PromptVersion).where(
                        PromptVersion.concept_id == UUID(apple_concept)
                    )
                )
            ).scalars().all()
        assert {revision.version for revision in revisions} == {1, 2}
        assert {entry.canonical_answer for entry in versions} == {"apple", "apple tree"}

        with pytest.raises(PromptSeedConflictError, match="changed in place"):
            await repo.upsert_bundled(
                slug="standard",
                name="Contradictory",
                description="",
                language="en",
                prompts=[BundledPromptDefinition(apple_concept, "apple tree", 2)],
                version=2,
            )
    finally:
        await engine.dispose()


async def test_save_game_persists_the_analytics_columns():
    """These are written for later analysis and are not read back by any view,
    so the write itself is what has to be checked."""
    factory, engine = await create_test_db()
    try:
        user_repo = SqlAlchemyUserRepository(factory)
        history_repo = SqlAlchemyGameHistoryRepository(factory)
        drawer = await user_repo.create_anonymous("Drawer")
        guesser = await user_repo.create_anonymous("Guesser")

        now = datetime.now(timezone.utc)
        turn_id = str(generate_uuid())
        game_id = await history_repo.save_game(
            GameRecordInput(
                room_name="Analytics Room",
                scoring_mode="default",
                hint_mode="purchase",
                drawing_seconds=90,
                total_rounds=1,
                player_count=2,
                started_at=now,
                finished_at=now,
            ),
            [
                GameParticipantInput(
                    user_id=drawer.id, final_score=350, final_rank=1, turns_played=2
                ),
                GameParticipantInput(
                    user_id=guesser.id, final_score=200, final_rank=2, turns_played=1
                ),
            ],
            [
                TurnRecordInput(
                    id=turn_id,
                    round_number=1,
                    turn_number=1,
                    drawer_user_id=drawer.id,
                    prompt="guitar",
                    duration_seconds=30.0,
                    guesser_count=4,
                    prompt_auto_picked=True,
                    stroke_count=23,
                    end_reason="all_guessed",
                    wrong_guess_count=7,
                    near_miss_count=3,
                )
            ],
            [
                TurnGuessInput(
                    turn_id=turn_id,
                    user_id=guesser.id,
                    points_awarded=200,
                    guess_time_seconds=12.5,
                    hints_used=2,
                    points_spent_on_hints=36,
                    wrong_guesses_before=5,
                )
            ],
        )

        async with factory() as session:
            round_row = (
                await session.execute(
                    select(TurnRecord).where(TurnRecord.game_id == UUID(game_id))
                )
            ).scalar_one()
            assert round_row.guesser_count == 4
            assert round_row.prompt_auto_picked is True
            assert round_row.stroke_count == 23
            assert round_row.end_reason == "all_guessed"
            assert round_row.wrong_guess_count == 7
            assert round_row.near_miss_count == 3

            guess_row = (
                await session.execute(
                    select(TurnGuess).where(TurnGuess.turn_id == round_row.id)
                )
            ).scalar_one()
            assert guess_row.hints_used == 2
            assert guess_row.points_spent_on_hints == 36
            assert guess_row.wrong_guesses_before == 5

            played = {
                row.user_id: row.turns_played
                for row in (
                    await session.execute(
                        select(GameParticipant).where(
                            GameParticipant.game_id == UUID(game_id)
                        )
                    )
                ).scalars()
            }
            assert played == {UUID(drawer.id): 2, UUID(guesser.id): 1}
    finally:
        await engine.dispose()


async def _seed_two_lists(repo):
    apple = str(generate_uuid())
    await repo.upsert_bundled(
        slug="alpha",
        name="Alpha",
        description="",
        language="en",
        prompts=[
            BundledPromptDefinition(apple, "apple"),
            BundledPromptDefinition(str(generate_uuid()), "banana"),
        ],
        version=1,
    )
    await repo.upsert_bundled(
        slug="beta",
        name="Beta",
        description="",
        language="en",
        prompts=[
            BundledPromptDefinition(apple, "apple"),
            BundledPromptDefinition(str(generate_uuid()), "castle"),
        ],
        version=1,
    )


def _stat(stats, text):
    return next(entry for entry in stats if entry.text == text)


async def test_prompt_usage_reaches_every_named_list_in_one_call():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await _seed_two_lists(repo)
        selection = await repo.resolve_selection(["alpha", "beta"])
        apple_id = selection.prompt_version_ids["apple"]
        banana_id = selection.prompt_version_ids["banana"]
        castle_id = selection.prompt_version_ids["castle"]

        await repo.record_prompt_usage(
            selection.revision_ids,
            PromptUsage(
                offers={apple_id: 3, banana_id: 1, castle_id: 1},
                picks={
                    apple_id: PromptPickTotals(
                        picks=2, correct_guesses=5, total_guessers=8
                    )
                },
            ),
        )

        for slug in ("alpha", "beta"):
            stats = await repo.get_prompt_stats(slug)
            apple = _stat(stats, "apple")
            # A prompt offered three times over a game moves by three, not one.
            assert apple.offer_count == 3
            assert apple.pick_count == 2
            assert apple.correct_guess_count == 5
            assert apple.total_guesser_count == 8

        # Words are only touched in the lists that actually contain them.
        assert _stat(await repo.get_prompt_stats("alpha"), "banana").offer_count == 1
        assert _stat(await repo.get_prompt_stats("beta"), "castle").offer_count == 1
    finally:
        await engine.dispose()


async def test_prompt_usage_is_idempotent_windowable_and_segmentable():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await _seed_two_lists(repo)
        selection = await repo.resolve_selection(["alpha"])
        apple_id = selection.prompt_version_ids["apple"]
        occurred_at = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
        usage = PromptUsage(
            offers={apple_id: 1},
            picks={
                apple_id: PromptPickTotals(
                    picks=1, correct_guesses=2, total_guessers=3
                )
            },
            batch_id=str(generate_uuid()),
            occurred_at=occurred_at,
            scoring_mode="pressure",
            hint_mode="wheel",
        )

        await repo.record_prompt_usage(selection.revision_ids, usage)
        await repo.record_prompt_usage(selection.revision_ids, usage)

        async with factory() as session:
            facts = list(
                (
                    await session.scalars(
                        select(PromptUsageFact).where(
                            PromptUsageFact.batch_id == UUID(usage.batch_id)
                        )
                    )
                ).all()
            )
        assert len(facts) == 1
        assert facts[0].scoring_mode == "pressure"
        assert facts[0].hint_mode == "wheel"

        included = await repo.get_prompt_stats(
            "alpha",
            from_time=occurred_at - timedelta(seconds=1),
            to_time=occurred_at + timedelta(seconds=1),
            scoring_mode="pressure",
            hint_mode="wheel",
        )
        assert _stat(included, "apple").pick_count == 1
        excluded = await repo.get_prompt_stats(
            "alpha", from_time=occurred_at + timedelta(seconds=1)
        )
        assert _stat(excluded, "apple").pick_count == 0
        wrong_mode = await repo.get_prompt_stats("alpha", scoring_mode="default")
        assert _stat(wrong_mode, "apple").pick_count == 0
    finally:
        await engine.dispose()


async def test_a_revision_that_no_longer_exists_does_not_cost_the_others():
    """A pinned revision disappearing beside a valid one is not fatal."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await _seed_two_lists(repo)
        alpha = await repo.resolve_selection(["alpha"])
        apple_id = alpha.prompt_version_ids["apple"]
        missing_revision_id = str(generate_uuid())

        await repo.record_prompt_usage(
            [*alpha.revision_ids, missing_revision_id],
            PromptUsage(
                offers={apple_id: 1},
                picks={
                    apple_id: PromptPickTotals(
                        picks=1, correct_guesses=1, total_guessers=2
                    )
                },
            ),
        )

        assert _stat(await repo.get_prompt_stats("alpha"), "apple").pick_count == 1
        # A call naming only missing revisions is a no-op rather than an error.
        await repo.record_prompt_usage(
            [missing_revision_id], PromptUsage(offers={apple_id: 1}, picks={})
        )
        assert _stat(await repo.get_prompt_stats("alpha"), "apple").offer_count == 1
    finally:
        await engine.dispose()


async def test_recording_nothing_touches_no_counters():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await _seed_two_lists(repo)
        alpha = await repo.resolve_selection(["alpha"])
        apple_id = alpha.prompt_version_ids["apple"]

        await repo.record_prompt_usage([], PromptUsage(offers={apple_id: 1}, picks={}))
        await repo.record_prompt_usage(alpha.revision_ids, PromptUsage(offers={}, picks={}))

        assert _stat(await repo.get_prompt_stats("alpha"), "apple").offer_count == 0
    finally:
        await engine.dispose()


def _skch_bytes(name: str = "representative") -> bytes:
    """A real canvas frame from the cross-language golden fixtures."""

    fixtures = json.loads(
        (Path(__file__).parents[2] / "fixtures" / "canvas_protocol_v1.json").read_text()
    )
    entry = next(item for item in fixtures["histories"] if item["name"] == name)
    return bytes.fromhex(entry["binary"])


async def _save_game_with_drawings(history_repo, user_repo, drawings_for):
    """Persist a one-turn game, letting the caller decide the drawing rows."""

    drawer = await user_repo.create_anonymous("Drawer")
    guesser = await user_repo.create_anonymous("Guesser")
    now = datetime.now(timezone.utc)
    turn_id = str(generate_uuid())
    game_id = await history_repo.save_game(
        GameRecordInput(
            room_name="Studio",
            scoring_mode="default",
            hint_mode="purchase",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=now,
            finished_at=now,
        ),
        [
            GameParticipantInput(
                user_id=drawer.id, final_score=300, final_rank=1, turns_played=1
            ),
            GameParticipantInput(
                user_id=guesser.id, final_score=100, final_rank=2, turns_played=0
            ),
        ],
        [
            TurnRecordInput(
                id=turn_id,
                round_number=1,
                turn_number=1,
                drawer_user_id=drawer.id,
                prompt="guitar",
                duration_seconds=30.0,
            )
        ],
        [],
        None,
        drawings_for(turn_id),
    )
    return game_id, turn_id, drawer, guesser


async def test_a_drawing_is_stored_verbatim_beside_its_turn():
    factory, engine = await create_test_db()
    try:
        user_repo = SqlAlchemyUserRepository(factory)
        history_repo = SqlAlchemyGameHistoryRepository(factory)
        blob = _skch_bytes()

        game_id, turn_id, _, _ = await _save_game_with_drawings(
            history_repo,
            user_repo,
            lambda tid: [TurnDrawingInput(turn_id=tid, payload=blob)],
        )

        async with factory() as session:
            row = await session.get(TurnDrawing, UUID(turn_id))
            assert row is not None
            assert row.payload == blob, "the stored bytes must be the canvas's bytes"
            assert row.status == "ready"
            assert row.format_magic == "SKCH"
            assert row.format_version == 1
            assert row.byte_size == len(blob)
            assert row.checksum_sha256 == hashlib.sha256(blob).hexdigest()
            assert row.game_id == UUID(game_id)
            assert row.unavailable_reason is None
    finally:
        await engine.dispose()


async def test_a_drawing_the_recap_dropped_is_stored_as_unavailable():
    factory, engine = await create_test_db()
    try:
        user_repo = SqlAlchemyUserRepository(factory)
        history_repo = SqlAlchemyGameHistoryRepository(factory)

        _, turn_id, _, _ = await _save_game_with_drawings(
            history_repo,
            user_repo,
            lambda tid: [
                TurnDrawingInput(
                    turn_id=tid, payload=None, unavailable_reason="recap_budget"
                )
            ],
        )

        async with factory() as session:
            row = await session.get(TurnDrawing, UUID(turn_id))
            assert row.status == "unavailable"
            assert row.payload is None
            assert row.unavailable_reason == "recap_budget"
    finally:
        await engine.dispose()


async def test_a_drawing_for_an_unknown_turn_is_refused_loudly():
    """Silent data loss is the failure this guard exists to prevent."""

    factory, engine = await create_test_db()
    try:
        user_repo = SqlAlchemyUserRepository(factory)
        history_repo = SqlAlchemyGameHistoryRepository(factory)
        stray = str(generate_uuid())

        with pytest.raises(ValueError, match="unknown turn_id"):
            await _save_game_with_drawings(
                history_repo,
                user_repo,
                lambda _tid: [
                    TurnDrawingInput(turn_id=stray, payload=_skch_bytes("empty"))
                ],
            )
    finally:
        await engine.dispose()


async def test_erasing_a_drawing_cannot_leave_its_bytes_behind():
    """The constraint, not the calling code, is what guarantees erasure."""

    factory, engine = await create_test_db()
    try:
        user_repo = SqlAlchemyUserRepository(factory)
        history_repo = SqlAlchemyGameHistoryRepository(factory)
        blob = _skch_bytes()
        _, turn_id, _, _ = await _save_game_with_drawings(
            history_repo,
            user_repo,
            lambda tid: [TurnDrawingInput(turn_id=tid, payload=blob)],
        )

        with pytest.raises(IntegrityError):
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        update(TurnDrawing)
                        .where(TurnDrawing.turn_id == UUID(turn_id))
                        .values(status="deleted")
                    )
    finally:
        await engine.dispose()

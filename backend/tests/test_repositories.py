"""Unit tests for repository implementations."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sqlalchemy import delete, select

from app.db.models import (
    Base,
    GameParticipant,
    Prompt,
    PromptList,
    TurnGuess,
    TurnRecord,
    PromptListLocalization,
    PromptListRevision,
    PromptVersion,
    generate_uuid,
)
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    BundledPromptDefinition,
    GameParticipantInput,
    GameRecordInput,
    InvalidProfileDataError,
    TurnGuessInput,
    TurnRecordInput,
    UsernameTakenError,
    PromptPickTotals,
    PromptListSelectionError,
    PromptSeedConflictError,
    PromptUsage,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyPromptListRepository,
)

pytestmark = pytest.mark.asyncio


async def create_test_db():
    external_url = os.environ.get("TEST_DATABASE_URL")
    if external_url:
        engine = create_async_engine(external_url, echo=False)
        # The external database is migrated before this suite starts. Keep the
        # schema intact so repositories exercise Alembic's output, while
        # isolating tests by removing application rows in dependency order.
        async with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())
        factory = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        return factory, engine

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return factory, engine


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

        await user_repo.update_profile(u1.id, display_name="RenamedLater")

        # Check user games list with pagination clamping
        u1_games = await history_repo.get_user_games(u1.id, limit=999999, offset=-5)
        assert len(u1_games) == 1
        assert u1_games[0].id == game_id
        assert len(u1_games[0].participants) == 2
        assert u1_games[0].participants[0].user_id == u1.id
        assert u1_games[0].participants[0].seat_id
        assert u1_games[0].participants[0].display_name == "Player1"

        # Check game detail for participant (authorized)
        detail = await history_repo.get_game_detail(game_id, requesting_user_id=u1.id)
        assert detail is not None
        assert detail.summary.id == game_id
        assert len(detail.turns) == 1
        assert detail.turns[0].prompt == "guitar"
        assert detail.turns[0].drawer_display_name == "Player1"
        assert len(detail.turns[0].guesses) == 1
        assert detail.turns[0].guesses[0].user_id == u2.id
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
                        offer_count=0,
                        pick_count=0,
                        correct_guess_count=0,
                        total_guesser_count=0,
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

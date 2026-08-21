"""Unit tests for repository implementations."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sqlalchemy import select

from app.db.models import (
    Base,
    GameParticipant,
    TurnGuess,
    TurnRecord,
)
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    GameParticipantInput,
    GameRecordInput,
    InvalidProfileDataError,
    TurnGuessInput,
    TurnRecordInput,
    UsernameTakenError,
    WordPickTotals,
    WordUsage,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyPromptListRepository,
)

pytestmark = pytest.mark.asyncio


async def create_test_db():
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

        # 7. Get by username (case-insensitive) returns UserData without password_hash
        by_name = await repo.get_by_username("BOB123")
        assert by_name is not None
        assert by_name.id == anon.id
        assert not hasattr(by_name, "password_hash")

        # 8. Update profile with valid and invalid avatar URLs
        updated = await repo.update_profile(anon.id, name_color="#00ff00", avatar_url="https://example.com/avatar.png")
        assert updated is not None
        assert updated.name_color == "#00ff00"
        assert updated.avatar_url == "https://example.com/avatar.png"

        # Disallow javascript: schemes or XSS characters in avatar_url
        with pytest.raises(InvalidProfileDataError):
            await repo.update_profile(anon.id, avatar_url="javascript:alert(1)")

        with pytest.raises(InvalidProfileDataError):
            await repo.update_profile(anon.id, avatar_url='https://example.com/"onerror="alert(1)')

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
        rounds = [
            TurnRecordInput(
                round_number=1,
                turn_number=1,
                drawer_user_id=u1.id,
                prompt="guitar",
                duration_seconds=30.0,
            )
        ]
        guesses = [
            TurnGuessInput(
                turn_index=0,
                user_id=u2.id,
                points_awarded=200,
                guess_time_seconds=10.0,
            )
        ]

        game_id = await history_repo.save_game(game_input, participants, rounds, guesses)
        assert game_id is not None

        # Invalid guess turn_index fails loudly
        invalid_guesses = [
            TurnGuessInput(
                turn_index=99,
                user_id=u2.id,
                points_awarded=100,
                guess_time_seconds=5.0,
            )
        ]
        with pytest.raises(ValueError, match="out of bounds"):
            await history_repo.save_game(game_input, participants, rounds, invalid_guesses)

        # Check user games list with pagination clamping
        u1_games = await history_repo.get_user_games(u1.id, limit=999999, offset=-5)
        assert len(u1_games) == 1
        assert u1_games[0].id == game_id
        assert len(u1_games[0].participants) == 2
        assert u1_games[0].participants[0].user_id == u1.id

        # Check game detail for participant (authorized)
        detail = await history_repo.get_game_detail(game_id, requesting_user_id=u1.id)
        assert detail is not None
        assert detail.summary.id == game_id
        assert len(detail.turns) == 1
        assert detail.turns[0].prompt == "guitar"
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
        wl = await repo.upsert_bundled(
            slug="standard",
            name="Standard List",
            description="Standard curated words",
            language="en",
            prompts=["apple", "banana", "cherry", "apple"],  # includes duplicate
            version=1,
        )
        assert wl.slug == "standard"
        assert wl.prompt_count == 3

        # 2. List all
        all_lists = await repo.list_all()
        assert len(all_lists) == 1
        assert all_lists[0].slug == "standard"

        # 3. Get words
        words = await repo.get_words(wl.id)
        assert words == ["apple", "banana", "cherry"]

        # 4. Get by slugs
        slug_words = await repo.get_prompts_by_slugs(["standard"])
        assert slug_words == ["apple", "banana", "cherry"]

        # 5. Record one finished game's offers and picks
        await repo.record_word_usage(
            ["standard"],
            WordUsage(
                offers={"apple": 1, "banana": 1, "dragon": 1},
                picks={
                    "apple": WordPickTotals(
                        picks=1, correct_guesses=3, total_guessers=4
                    )
                },
            ),
        )

        stats = await repo.get_word_stats("standard")
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
        upgraded = await repo.upsert_bundled(
            slug="standard",
            name="Standard List v2",
            description="Updated words",
            language="en",
            prompts=["apple", "date"],  # banana removed, date added
            version=2,
        )
        assert upgraded.version == 2
        assert upgraded.prompt_count == 2

        new_stats = await repo.get_word_stats("standard")
        assert len(new_stats) == 2
        apple_stat_v2 = next(s for s in new_stats if s.text == "apple")
        assert apple_stat_v2.pick_count == 1  # preserved stats
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
                    turn_index=0,
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
                    select(TurnRecord).where(TurnRecord.game_id == game_id)
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
                        select(GameParticipant).where(GameParticipant.game_id == game_id)
                    )
                ).scalars()
            }
            assert played == {drawer.id: 2, guesser.id: 1}
    finally:
        await engine.dispose()


async def _seed_two_lists(repo):
    await repo.upsert_bundled(
        slug="alpha",
        name="Alpha",
        description="",
        language="en",
        prompts=["apple", "banana"],
        version=1,
    )
    await repo.upsert_bundled(
        slug="beta",
        name="Beta",
        description="",
        language="en",
        prompts=["apple", "castle"],
        version=1,
    )


def _stat(stats, text):
    return next(entry for entry in stats if entry.text == text)


async def test_prompt_usage_reaches_every_named_list_in_one_call():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await _seed_two_lists(repo)

        await repo.record_word_usage(
            ["alpha", "beta"],
            WordUsage(
                offers={"apple": 3, "banana": 1, "castle": 1},
                picks={
                    "apple": WordPickTotals(
                        picks=2, correct_guesses=5, total_guessers=8
                    )
                },
            ),
        )

        for slug in ("alpha", "beta"):
            stats = await repo.get_word_stats(slug)
            apple = _stat(stats, "apple")
            # A prompt offered three times over a game moves by three, not one.
            assert apple.offer_count == 3
            assert apple.pick_count == 2
            assert apple.correct_guess_count == 5
            assert apple.total_guesser_count == 8

        # Words are only touched in the lists that actually contain them.
        assert _stat(await repo.get_word_stats("alpha"), "banana").offer_count == 1
        assert _stat(await repo.get_word_stats("beta"), "castle").offer_count == 1
    finally:
        await engine.dispose()


async def test_a_slug_that_no_longer_exists_does_not_cost_the_others():
    """A room outlives the lists it was created with; a deleted one is not fatal."""
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await _seed_two_lists(repo)

        await repo.record_word_usage(
            ["alpha", "gone-missing"],
            WordUsage(
                offers={"apple": 1},
                picks={
                    "apple": WordPickTotals(
                        picks=1, correct_guesses=1, total_guessers=2
                    )
                },
            ),
        )

        assert _stat(await repo.get_word_stats("alpha"), "apple").pick_count == 1
        # And a call naming only missing lists is a no-op rather than an error.
        await repo.record_word_usage(["gone-missing"], WordUsage(offers={"apple": 1}, picks={}))
        assert _stat(await repo.get_word_stats("alpha"), "apple").offer_count == 1
    finally:
        await engine.dispose()


async def test_recording_nothing_touches_no_counters():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await _seed_two_lists(repo)

        await repo.record_word_usage([], WordUsage(offers={"apple": 1}, picks={}))
        await repo.record_word_usage(["alpha"], WordUsage(offers={}, picks={}))

        assert _stat(await repo.get_word_stats("alpha"), "apple").offer_count == 0
    finally:
        await engine.dispose()

"""Unit tests for word list seeding, REST API, selection, and usage metrics."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.seed import seed_prompt_lists
from app.repositories.interfaces import WordPickTotals, WordUsage
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository
from app.rooms import RoomManager

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


async def test_seed_bundled_prompt_lists():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        seeded = await seed_prompt_lists(repo)
        assert len(seeded) >= 2

        slugs = {wl.slug for wl in seeded}
        assert "english_standard" in slugs
        assert "english_extended" in slugs

        std_words = await repo.get_prompts_by_slugs(["english_standard"])
        assert len(std_words) > 200
        assert "airplane" in std_words
        assert "guitar" in std_words

        ext_words = await repo.get_prompts_by_slugs(["english_extended"])
        assert len(ext_words) > 400
        assert "accordion" in ext_words

        combined_words = await repo.get_prompts_by_slugs(["english_standard", "english_extended"])
        assert len(combined_words) >= len(std_words)
    finally:
        await engine.dispose()


async def test_prompt_usage_tracking_metrics():
    factory, engine = await create_test_db()
    try:
        repo = SqlAlchemyPromptListRepository(factory)
        await seed_prompt_lists(repo)

        # One game: "apple", "banana" and "robot" offered, "robot" drawn and
        # guessed by 2 of 3 possible guessers.
        await repo.record_word_usage(
            ["english_standard"],
            WordUsage(
                offers={"apple": 1, "banana": 1, "robot": 1},
                picks={
                    "robot": WordPickTotals(
                        picks=1, correct_guesses=2, total_guessers=3
                    )
                },
            ),
        )

        word_stats_list = await repo.get_word_stats("english_standard")
        stats = next((w for w in word_stats_list if w.text == "robot"), None)
        assert stats is not None
        assert stats.offer_count == 1
        assert stats.pick_count == 1
        assert stats.correct_guess_count == 2
        assert stats.total_guesser_count == 3
        assert stats.pick_rate == 1.0
        assert stats.correct_guess_ratio == round(2 / 3, 4)

        # Banana was offered but not picked
        banana_stats = next((w for w in word_stats_list if w.text == "banana"), None)
        assert banana_stats is not None
        assert banana_stats.offer_count == 1
        assert banana_stats.pick_count == 0
        assert banana_stats.correct_guess_count == 0
        assert banana_stats.total_guesser_count == 0
        assert banana_stats.pick_rate == 0.0
        assert banana_stats.correct_guess_ratio == 0.0
    finally:
        await engine.dispose()


async def test_room_effective_word_pool_with_curated_and_custom_words():
    rm = RoomManager()
    room = rm.create_room(
        name="Test Room",
        prompt_list_slugs=["english_standard"],
        curated_prompts=["apple", "banana", "cherry"],
        custom_prompts=["dragon", "APPLE"],
        custom_prompts_only=False,
    )
    pool = room.effective_word_pool()
    assert pool is not None
    # Custom words take priority, case-insensitively deduplicating
    assert pool[0] == "dragon"
    assert pool[1] == "APPLE"
    assert "banana" in pool
    assert "cherry" in pool
    assert pool.count("apple") + pool.count("APPLE") == 1

    # Custom words only
    room.custom_prompts_only = True
    pool_custom = room.effective_word_pool()
    assert pool_custom == ["dragon", "APPLE"]

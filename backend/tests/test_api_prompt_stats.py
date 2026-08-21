"""The prompt statistics endpoint: what it ranks, and what it refuses to rank."""
from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.prompt_lists import (
    MIN_RATED_GUESSERS,
    create_prompt_list_router,
    stats_limiter,
)
from app.db.models import Base
from app.repositories.interfaces import PromptPickTotals, PromptUsage
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    stats_limiter.reset()

    prompts = SqlAlchemyPromptListRepository(session_factory)
    app = FastAPI()
    app.include_router(create_prompt_list_router(prompts))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, prompts
    await engine.dispose()


async def seed(prompts, *texts: str) -> None:
    await prompts.upsert_bundled(
        slug="standard",
        name="Standard",
        description="",
        language="en",
        prompts=list(texts),
        version=1,
    )


async def play(prompts, text: str, *, correct: int, guessers: int) -> None:
    """Record one turn's worth of usage for a prompt."""
    await prompts.record_prompt_usage(
        ["standard"],
        PromptUsage(
            offers={text: 1},
            picks={
                text: PromptPickTotals(
                    picks=1, correct_guesses=correct, total_guessers=guessers
                )
            },
        ),
    )


async def test_an_unknown_list_is_not_found(env):
    http, _ = env
    assert (await http.get("/api/prompt-lists/nope/prompt-stats")).status_code == 404


async def test_a_prompt_below_the_sample_floor_is_counted_but_not_ranked(env):
    http, prompts = env
    await seed(prompts, "apple", "tree")
    await play(prompts, "apple", correct=0, guessers=MIN_RATED_GUESSERS)
    await play(prompts, "tree", correct=0, guessers=MIN_RATED_GUESSERS - 1)

    body = (await http.get("/api/prompt-lists/standard/prompt-stats")).json()

    assert [p["text"] for p in body["prompts"]] == ["apple"]
    assert body["ratedCount"] == 1
    # "tree" was played but not enough; the never-played prompt is unrated too.
    assert body["unratedCount"] == 1
    assert body["minRatedGuessers"] == MIN_RATED_GUESSERS


async def test_a_never_offered_prompt_does_not_rank_as_hardest(env):
    """Its ratio is 0.0 for want of data, not because nobody could guess it."""
    http, prompts = env
    await seed(prompts, "apple", "never-played")
    await play(prompts, "apple", correct=1, guessers=MIN_RATED_GUESSERS)

    body = (await http.get("/api/prompt-lists/standard/prompt-stats")).json()

    assert [p["text"] for p in body["prompts"]] == ["apple"]
    assert body["unratedCount"] == 1


async def test_hardest_first_by_default_and_easiest_reverses_it(env):
    http, prompts = env
    await seed(prompts, "easy", "hard")
    await play(prompts, "easy", correct=5, guessers=MIN_RATED_GUESSERS)
    await play(prompts, "hard", correct=1, guessers=MIN_RATED_GUESSERS)

    hardest = (await http.get("/api/prompt-lists/standard/prompt-stats")).json()
    assert [p["text"] for p in hardest["prompts"]] == ["hard", "easy"]

    easiest = (
        await http.get("/api/prompt-lists/standard/prompt-stats?sort=easiest")
    ).json()
    assert [p["text"] for p in easiest["prompts"]] == ["easy", "hard"]


async def test_most_picked_ranks_on_how_often_an_offer_was_taken(env):
    http, prompts = env
    await seed(prompts, "popular", "ignored")
    await play(prompts, "popular", correct=3, guessers=MIN_RATED_GUESSERS)
    # Offered twice as often and picked once: a lower rate, same pick count.
    await prompts.record_prompt_usage(
        ["standard"],
        PromptUsage(
            offers={"ignored": 3},
            picks={
                "ignored": PromptPickTotals(
                    picks=1, correct_guesses=3, total_guessers=MIN_RATED_GUESSERS
                )
            },
        ),
    )

    body = (
        await http.get("/api/prompt-lists/standard/prompt-stats?sort=most-picked")
    ).json()

    assert [p["text"] for p in body["prompts"]] == ["popular", "ignored"]
    assert body["prompts"][0]["pickRate"] > body["prompts"][1]["pickRate"]


async def test_the_limit_bounds_the_page_and_is_itself_bounded(env):
    http, prompts = env
    texts = [f"prompt-{index}" for index in range(6)]
    await seed(prompts, *texts)
    for text in texts:
        await play(prompts, text, correct=1, guessers=MIN_RATED_GUESSERS)

    body = (await http.get("/api/prompt-lists/standard/prompt-stats?limit=2")).json()
    assert len(body["prompts"]) == 2
    # The count reports the whole rated set, not the page.
    assert body["ratedCount"] == 6

    assert (
        await http.get("/api/prompt-lists/standard/prompt-stats?limit=0")
    ).status_code == 422
    assert (
        await http.get("/api/prompt-lists/standard/prompt-stats?limit=9999")
    ).status_code == 422


async def test_an_unknown_sort_is_rejected(env):
    http, prompts = env
    await seed(prompts, "apple")
    response = await http.get("/api/prompt-lists/standard/prompt-stats?sort=sideways")
    assert response.status_code == 422


async def test_the_list_index_still_answers(env):
    http, prompts = env
    await seed(prompts, "apple", "tree")
    body = (await http.get("/api/prompt-lists")).json()
    assert [entry["slug"] for entry in body] == ["standard"]
    assert body[0]["promptCount"] == 2

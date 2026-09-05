"""The prompt statistics endpoint: what it ranks, and what it refuses to rank."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.prompt_lists import (
    MIN_RATED_GUESSERS,
    create_prompt_list_router,
    stats_limiter,
)
from app.db.models import generate_uuid
from app.repositories.interfaces import (
    BundledPromptDefinition,
    PromptPickTotals,
    PromptUsage,
)
from app.repositories.sqlalchemy import SqlAlchemyPromptListRepository

from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def env():
    session_factory, engine = await create_test_db()
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
        prompts=[
            BundledPromptDefinition(str(generate_uuid()), text)
            for text in texts
        ],
        version=1,
    )


async def test_prompt_list_catalogue_filters_on_valid_content_language(env):
    http, prompts = env
    await seed(prompts, "apple")
    await prompts.upsert_bundled(
        slug="francais",
        name="Français",
        description="Mots français",
        language="fr",
        prompts=[BundledPromptDefinition(str(generate_uuid()), "éléphant")],
        version=1,
    )

    response = await http.get("/api/prompt-lists?language=fr")
    assert response.status_code == 200
    assert [(item["slug"], item["language"]) for item in response.json()] == [
        ("francais", "fr")
    ]
    assert (await http.get("/api/prompt-lists?language=zh")).status_code == 422


async def play(
    prompts,
    text: str,
    *,
    correct: int,
    guessers: int,
    occurred_at: datetime | None = None,
    scoring_mode: str = "default",
    hint_mode: str = "none",
) -> None:
    """Record one turn's worth of usage for a prompt."""
    selection = await prompts.resolve_selection(["standard"])
    prompt_version_id = selection.prompt_version_ids[text]
    await prompts.record_prompt_usage(
        selection.revision_ids,
        PromptUsage(
            offers={prompt_version_id: 1},
            picks={
                prompt_version_id: PromptPickTotals(
                    picks=1, correct_guesses=correct, total_guessers=guessers
                )
            },
            **({"occurred_at": occurred_at} if occurred_at else {}),
            scoring_mode=scoring_mode,
            hint_mode=hint_mode,
        ),
    )


async def test_an_unknown_list_is_not_found(env):
    http, _ = env
    assert (await http.get("/api/prompt-lists/nope/prompt-stats")).status_code == 404


async def test_a_prompt_below_the_sample_floor_is_listed_but_flagged(env):
    """It is still a prompt in the list; it just has no measured difficulty."""
    http, prompts = env
    await seed(prompts, "apple", "tree")
    await play(prompts, "apple", correct=0, guessers=MIN_RATED_GUESSERS)
    await play(prompts, "tree", correct=0, guessers=MIN_RATED_GUESSERS - 1)

    body = (await http.get("/api/prompt-lists/standard/prompt-stats")).json()

    assert {p["text"]: p["isRated"] for p in body["prompts"]} == {
        "apple": True,
        "tree": False,
    }
    assert body["ratedCount"] == 1
    assert body["unratedCount"] == 1
    assert body["minRatedGuessers"] == MIN_RATED_GUESSERS


async def test_a_never_offered_prompt_never_outranks_a_measured_one(env):
    """Its ratio is 0.0 for want of data, not because nobody could guess it."""
    http, prompts = env
    await seed(prompts, "apple", "never-played")
    await play(prompts, "apple", correct=1, guessers=MIN_RATED_GUESSERS)

    body = (await http.get("/api/prompt-lists/standard/prompt-stats")).json()

    # Sorted hardest first, and "apple" was guessed once in five - yet the
    # prompt nobody has ever drawn must not be called the harder of the two.
    assert [p["text"] for p in body["prompts"]] == ["apple", "never-played"]
    assert body["unratedCount"] == 1


async def test_unrated_prompts_follow_the_ranked_ones_in_every_sort(env):
    http, prompts = env
    await seed(prompts, "zebra", "apple", "unplayed-one", "unplayed-two")
    await play(prompts, "zebra", correct=1, guessers=MIN_RATED_GUESSERS)
    await play(prompts, "apple", correct=4, guessers=MIN_RATED_GUESSERS)

    for sort in ("hardest", "easiest", "most-picked"):
        body = (
            await http.get(f"/api/prompt-lists/standard/prompt-stats?sort={sort}")
        ).json()
        flags = [p["isRated"] for p in body["prompts"]]
        assert flags == sorted(flags, reverse=True), (
            f"{sort} interleaved unrated prompts with ranked ones: "
            f"{[p['text'] for p in body['prompts']]}"
        )
        # And the unrated tail is alphabetical, not arbitrary.
        unrated = [p["text"] for p in body["prompts"] if not p["isRated"]]
        assert unrated == sorted(unrated)


async def test_the_whole_list_comes_back_by_default(env):
    """The page shows every prompt, so the endpoint must not quietly page it."""
    http, prompts = env
    texts = [f"prompt-{index:03d}" for index in range(150)]
    await seed(prompts, *texts)

    body = (await http.get("/api/prompt-lists/standard/prompt-stats")).json()

    assert len(body["prompts"]) == 150
    assert body["unratedCount"] == 150


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
    selection = await prompts.resolve_selection(["standard"])
    ignored_id = selection.prompt_version_ids["ignored"]
    await prompts.record_prompt_usage(
        selection.revision_ids,
        PromptUsage(
            offers={ignored_id: 3},
            picks={
                ignored_id: PromptPickTotals(
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


async def test_stats_can_be_windowed_and_segmented_by_game_rules(env):
    http, prompts = env
    await seed(prompts, "apple")
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    recent = datetime(2026, 8, 1, tzinfo=timezone.utc)
    await play(
        prompts,
        "apple",
        correct=0,
        guessers=5,
        occurred_at=old,
        scoring_mode="default",
        hint_mode="none",
    )
    await play(
        prompts,
        "apple",
        correct=4,
        guessers=5,
        occurred_at=recent,
        scoring_mode="pressure",
        hint_mode="wheel",
    )

    response = await http.get(
        "/api/prompt-lists/standard/prompt-stats",
        params={
            "from": (recent - timedelta(days=1)).isoformat(),
            "to": (recent + timedelta(days=1)).isoformat(),
            "scoringMode": "pressure",
            "hintMode": "wheel",
        },
    )
    assert response.status_code == 200
    prompt = response.json()["prompts"][0]
    assert prompt["pickCount"] == 1
    assert prompt["correctGuessCount"] == 4
    assert prompt["totalGuesserCount"] == 5

    assert (
        await http.get(
            "/api/prompt-lists/standard/prompt-stats",
            params={"scoringMode": "invented"},
        )
    ).status_code == 422
    assert (
        await http.get(
            "/api/prompt-lists/standard/prompt-stats",
            params={"from": recent.isoformat(), "to": old.isoformat()},
        )
    ).status_code == 422


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

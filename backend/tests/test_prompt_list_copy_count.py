"""How many copies of a published list exist (R-LIST-20).

Derived from rows, the way a star count is, and never kept as a number: every
copy's first revision already records the revision it was taken from
(`forked_from_revision_id`, R-LIST-17), so the count is a question asked of
facts that are there anyway. What it counts is the copies that **still exist** -
a copy its owner deletes stops counting at once, as a removed star does - and
only **direct** copies: a copy of a copy counts toward the list it was taken
from, not toward that list's own source.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_refusal_handler
from app.api.prompt_lists import (
    community_limiter,
    create_prompt_list_router,
    preview_limiter,
    publish_limiter,
)
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.db.models import PromptList
from app.repositories.interfaces import PromptListEntryInput
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from tests.dbfixtures import create_test_db

PUBLISHED_AT = datetime(2026, 9, 1, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    prompts = SqlAlchemyPromptListRepository(factory)
    await prompts.seed_list_tags()
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_prompt_list_router(prompts, users, factory))
    for limiter in (publish_limiter, community_limiter, preview_limiter):
        limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, users, prompts, factory
    await engine.dispose()


async def account(users, name: str):
    guest = await users.create_anonymous(name)
    return await users.claim_account(guest.id, name, "test-hash")


async def sign_in(http, factory, user_id: str) -> None:
    issued = await create_session(factory, user_id=user_id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)


async def publish(factory, prompt_list_id: str) -> None:
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(prompt_list_id))
            row.visibility = "public"
            row.published_at = PUBLISHED_AT


async def a_published_list(prompts, factory, owner_id: str, name: str = "Source"):
    created = await prompts.create_owned(
        owner_id,
        name=name,
        description="Worth copying",
        language="en",
        prompts=(PromptListEntryInput(answer="otter"), PromptListEntryInput(answer="badger")),
        tags=("animals",),
    )
    await publish(factory, created.id)
    return created


async def copy_as(http, factory, user_id: str, prompt_list_id: str) -> str:
    await sign_in(http, factory, user_id)
    response = await http.post(f"/api/prompt-lists/{prompt_list_id}/fork")
    assert response.status_code == 201
    return response.json()["id"]


async def counts(http, factory, owner_id: str, prompt_list_id: str) -> dict[str, int]:
    """The count, read from all three places it is served."""
    listing = (await http.get("/api/prompt-lists/community")).json()["lists"]
    detail = (await http.get(f"/api/prompt-lists/community/{prompt_list_id}")).json()
    await sign_in(http, factory, owner_id)
    owned = (await http.get("/api/prompt-lists/mine")).json()
    owned_rows = owned["promptLists"] if isinstance(owned, dict) else owned
    return {
        "listing": next(row["copyCount"] for row in listing if row["id"] == prompt_list_id),
        "detail": detail["copyCount"],
        "owned": next(row["copyCount"] for row in owned_rows if row["id"] == prompt_list_id),
    }


async def test_the_count_is_the_copies_that_exist_wherever_the_list_is_read(env):
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    for name in ("Bo", "Cass"):
        reader = await account(users, name)
        await copy_as(http, factory, reader.id, source.id)

    assert await counts(http, factory, author.id, source.id) == {
        "listing": 2,
        "detail": 2,
        "owned": 2,
    }


async def test_a_copy_its_owner_deletes_stops_counting(env):
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    keeper = await account(users, "Keeper")
    deleter = await account(users, "Deleter")
    await copy_as(http, factory, keeper.id, source.id)
    doomed = await copy_as(http, factory, deleter.id, source.id)

    assert await prompts.delete_owned(deleter.id, doomed)

    assert (await counts(http, factory, author.id, source.id))["detail"] == 1


async def test_a_copy_of_a_copy_counts_toward_what_it_was_copied_from(env):
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    middle = await account(users, "Middle")
    copy_id = await copy_as(http, factory, middle.id, source.id)
    await publish(factory, copy_id)
    last = await account(users, "Last")
    await copy_as(http, factory, last.id, copy_id)

    assert (await counts(http, factory, author.id, source.id))["detail"] == 1
    assert (await counts(http, factory, middle.id, copy_id))["detail"] == 1


async def test_a_copy_still_counts_after_its_source_is_edited(env):
    # Provenance names the revision a copy was taken from, so an edit that
    # moves the source to a new revision must not lose the copies of the old.
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    reader = await account(users, "Reader")
    await copy_as(http, factory, reader.id, source.id)

    await prompts.update_owned(
        author.id,
        source.id,
        expected_version=source.version,
        name="Source, revised",
        description="Worth copying",
        prompts=(PromptListEntryInput(answer="otter"), PromptListEntryInput(answer="weasel")),
        tags=("animals",),
    )

    assert (await counts(http, factory, author.id, source.id))["detail"] == 1


async def test_a_list_nobody_copied_says_zero_rather_than_nothing(env):
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)

    assert await counts(http, factory, author.id, source.id) == {
        "listing": 0,
        "detail": 0,
        "owned": 0,
    }

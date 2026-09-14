"""Starring a published list: what it counts, and what it never says.

Two rules do most of the work here. A star is a **fact** rather than a counter
(R-LIST-16), so the count is derived from the rows every time and a double
star, a retry, or a departing account cannot leave a number wrong. And only a
**published** list can be starred, which is not a restriction so much as the
removal of a problem: a star row is durable, so one on an Unlisted list would
be lasting evidence that its owner holds that list's bearer share code -
exactly what R-LIST-03 keeps out of payloads and logs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.errors import install_refusal_handler
from app.api.prompt_lists import create_prompt_list_router, star_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.db.models import PromptList, PromptListStar, User
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
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_prompt_list_router(prompts, users, factory))
    star_limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, users, prompts, factory
    await engine.dispose()


async def verified(users, factory, name: str):
    guest = await users.create_anonymous(name)
    account = await users.claim_account(guest.id, name, "test-hash")
    async with factory() as session:
        async with session.begin():
            row = await session.get(User, UUID(account.id))
            row.email = f"{name.lower()}@example.test"
            row.email_verified_at = PUBLISHED_AT
    return account


async def sign_in(http, factory, user_id: str) -> None:
    issued = await create_session(factory, user_id=user_id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)


async def a_list(prompts, factory, owner_id: str, *, visibility="public"):
    created = await prompts.create_owned(
        owner_id,
        name="Starrable",
        description="",
        language="en",
        visibility="private" if visibility == "public" else visibility,
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    if visibility == "public":
        async with factory() as session:
            async with session.begin():
                row = await session.get(PromptList, UUID(created.id))
                row.visibility = "public"
                row.published_at = PUBLISHED_AT
    return created


async def test_starring_is_idempotent_in_both_directions(env):
    """The composite primary key is the idempotency; no guard needed."""
    http, users, prompts, factory = env
    owner = await verified(users, factory, "Owner")
    reader = await verified(users, factory, "Reader")
    published = await a_list(prompts, factory, owner.id)
    await sign_in(http, factory, reader.id)

    first = await http.put(f"/api/prompt-lists/{published.id}/star")
    second = await http.put(f"/api/prompt-lists/{published.id}/star")

    assert first.json() == {"starCount": 1, "starredByMe": True}
    assert second.json() == {"starCount": 1, "starredByMe": True}
    async with factory() as session:
        assert await session.scalar(
            select(func.count()).select_from(PromptListStar)
        ) == 1

    away = await http.delete(f"/api/prompt-lists/{published.id}/star")
    again = await http.delete(f"/api/prompt-lists/{published.id}/star")

    assert away.json() == {"starCount": 0, "starredByMe": False}
    assert again.json() == {"starCount": 0, "starredByMe": False}


async def test_only_a_published_list_can_be_starred(env):
    """The narrowing that keeps a star from disclosing a share code."""
    http, users, prompts, factory = env
    owner = await verified(users, factory, "Owner")
    reader = await verified(users, factory, "Reader")
    private = await a_list(prompts, factory, owner.id, visibility="private")
    unlisted = await a_list(prompts, factory, owner.id, visibility="unlisted")
    await sign_in(http, factory, reader.id)

    assert (await http.put(f"/api/prompt-lists/{private.id}/star")).status_code == 404
    assert (
        await http.put(f"/api/prompt-lists/{unlisted.id}/star")
    ).status_code == 404
    async with factory() as session:
        assert await session.scalar(
            select(func.count()).select_from(PromptListStar)
        ) == 0


async def test_a_hidden_or_retired_list_cannot_be_starred(env):
    http, users, prompts, factory = env
    owner = await verified(users, factory, "Owner")
    reader = await verified(users, factory, "Reader")
    hidden = await a_list(prompts, factory, owner.id)
    retired = await a_list(prompts, factory, owner.id)
    async with factory() as session:
        async with session.begin():
            (await session.get(PromptList, UUID(hidden.id))).moderation_state = "hidden"
            (await session.get(PromptList, UUID(retired.id))).deleted_at = PUBLISHED_AT
    await sign_in(http, factory, reader.id)

    assert (await http.put(f"/api/prompt-lists/{hidden.id}/star")).status_code == 404
    assert (await http.put(f"/api/prompt-lists/{retired.id}/star")).status_code == 404


async def test_an_unverified_account_cannot_star(env):
    """A star is a public number on somebody else's list, so the account
    giving it has to cost something (R-LIST-12)."""
    http, users, prompts, factory = env
    owner = await verified(users, factory, "Owner")
    published = await a_list(prompts, factory, owner.id)
    guest = await users.create_anonymous("Unverified")
    unverified = await users.claim_account(guest.id, "Unverified", "test-hash")
    await sign_in(http, factory, unverified.id)

    response = await http.put(f"/api/prompt-lists/{published.id}/star")

    assert response.status_code == 403
    # The same gate as publishing, saying what it is guarding this time.
    assert response.json()["errorCode"] == "email_verification_required"
    assert response.json()["params"] == {"action": "star"}


async def test_the_owner_sees_the_count_and_never_who_gave_it(env):
    """R-LIST-16's disclosure rule, from the owner's own listing."""
    http, users, prompts, factory = env
    owner = await verified(users, factory, "Owner")
    published = await a_list(prompts, factory, owner.id)
    for index in range(3):
        fan = await verified(users, factory, f"Fan{index}")
        async with factory() as session:
            async with session.begin():
                session.add(
                    PromptListStar(
                        user_id=UUID(fan.id), prompt_list_id=UUID(published.id)
                    )
                )
    await sign_in(http, factory, owner.id)

    listing = await http.get("/api/prompt-lists/mine")
    detail = await http.get(f"/api/prompt-lists/mine/{published.id}")

    assert listing.json()[0]["starCount"] == 3
    assert detail.json()["starCount"] == 3
    for body in (listing.text, detail.text):
        assert "Fan0" not in body and "Fan1" not in body


async def test_stars_survive_unpublishing_and_are_found_again(env):
    """They are rows, not a counter: the list stops being reachable and the
    count is where it was left."""
    http, users, prompts, factory = env
    owner = await verified(users, factory, "Owner")
    reader = await verified(users, factory, "Reader")
    published = await a_list(prompts, factory, owner.id)
    await sign_in(http, factory, reader.id)
    await http.put(f"/api/prompt-lists/{published.id}/star")

    await sign_in(http, factory, owner.id)
    await http.post(f"/api/prompt-lists/mine/{published.id}/unpublish")
    while_private = await http.get(f"/api/prompt-lists/mine/{published.id}")
    await http.post(f"/api/prompt-lists/mine/{published.id}/publish")
    once_more = await http.get(f"/api/prompt-lists/mine/{published.id}")

    assert while_private.json()["starCount"] == 1
    assert once_more.json()["starCount"] == 1


async def test_a_star_on_an_unpublished_list_cannot_be_given(env):
    """The count survives, but nobody can add to it while it is out."""
    http, users, prompts, factory = env
    owner = await verified(users, factory, "Owner")
    reader = await verified(users, factory, "Reader")
    published = await a_list(prompts, factory, owner.id)
    await sign_in(http, factory, owner.id)
    await http.post(f"/api/prompt-lists/mine/{published.id}/unpublish")
    await sign_in(http, factory, reader.id)

    assert (await http.put(f"/api/prompt-lists/{published.id}/star")).status_code == 404

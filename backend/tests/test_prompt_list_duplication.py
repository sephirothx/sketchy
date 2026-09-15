"""Duplicating one's own list: its contents again, and none of its history.

A duplicate is the author's own content twice, so it records no lineage, counts
toward no copy and credits nobody (R-LIST-17). What it must not do is carry
what a moderator decided *out* of the list: the owner's editor shows hidden
prompts and hidden lists to their owner, and a duplicate built from that would
give their text new, active identities - a takedown undone by a button.
"""
from __future__ import annotations

from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.errors import install_refusal_handler
from app.api.prompt_lists import create_prompt_list_router, publish_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.db.models import PromptList, PromptListRevision, PromptVersion
from app.repositories.interfaces import PromptListEntryInput
from app.repositories.sqlalchemy import (
    MAX_OWNED_PROMPT_LISTS,
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db


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
    publish_limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, users, prompts, factory
    await engine.dispose()


async def signed_in_owner(http, users, factory, name: str = "Owner"):
    guest = await users.create_anonymous(name)
    account = await users.claim_account(guest.id, name, "test-hash")
    issued = await create_session(factory, user_id=account.id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)
    return account


async def a_list(prompts, owner_id: str):
    return await prompts.create_owned(
        owner_id,
        name="Kitchen things",
        description="Everything in a kitchen",
        language="en",
        prompts=(
            PromptListEntryInput(answer="colander", aliases=("strainer",)),
            PromptListEntryInput(answer="whisk"),
        ),
        tags=("animals",),
    )


async def duplicate(http, list_id: str, name: str = "Kitchen things (duplicate)"):
    return await http.post(f"/api/prompt-lists/mine/{list_id}/duplicate", json={"name": name})


async def test_a_duplicate_has_the_contents_and_none_of_the_history(env):
    http, users, prompts, factory = env
    owner = await signed_in_owner(http, users, factory)
    source = await a_list(prompts, owner.id)

    response = await duplicate(http, source.id)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Kitchen things (duplicate)"
    assert body["description"] == "Everything in a kitchen"
    assert body["visibility"] == "private"
    assert [(entry["prompt"], entry["aliases"]) for entry in body["prompts"]] == [
        ("colander", ["strainer"]),
        ("whisk", []),
    ]
    assert body["tags"] == ["animals"]
    assert body["copiedFrom"] is None and body["forkedFromRevisionId"] is None
    # Its own prompt identities, not the source's.
    assert {entry["conceptId"] for entry in body["prompts"]}.isdisjoint(
        {entry.concept_id for entry in source.prompts}
    )
    async with factory() as session:
        row = await session.get(PromptList, UUID(body["id"]))
        revision = await session.scalar(
            select(PromptListRevision).where(PromptListRevision.prompt_list_id == row.id)
        )
    assert row.is_copy is False
    assert revision.forked_from_revision_id is None


async def test_a_hidden_prompt_is_left_out_rather_than_given_a_new_identity(env):
    """The laundering path: hide a prompt, duplicate, get it back as active."""
    http, users, prompts, factory = env
    owner = await signed_in_owner(http, users, factory)
    source = await a_list(prompts, owner.id)
    async with factory() as session:
        async with session.begin():
            version = await session.get(PromptVersion, UUID(source.prompts[0].prompt_version_id))
            version.moderation_state = "hidden"

    response = await duplicate(http, source.id)

    assert response.status_code == 201
    assert [entry["prompt"] for entry in response.json()["prompts"]] == ["whisk"]


async def test_a_list_under_moderation_or_a_copy_is_not_duplicated(env):
    http, users, prompts, factory = env
    owner = await signed_in_owner(http, users, factory)
    for state in ("hidden", "under_review"):
        source = await a_list(prompts, owner.id)
        async with factory() as session:
            async with session.begin():
                (await session.get(PromptList, UUID(source.id))).moderation_state = state
        response = await duplicate(http, source.id)
        assert response.status_code == 422, state
        assert response.json()["errorCode"] == "cannot_duplicate_prompt_list"
        assert response.json()["params"] == {"reason": "moderation"}

    copy = await a_list(prompts, owner.id)
    async with factory() as session:
        async with session.begin():
            (await session.get(PromptList, UUID(copy.id))).is_copy = True
    response = await duplicate(http, copy.id)
    assert response.status_code == 422
    assert response.json()["params"] == {"reason": "copy"}

    async with factory() as session:
        owned = await session.scalar(
            select(func.count(PromptList.id)).where(PromptList.owner_user_id == UUID(owner.id))
        )
    assert owned == 3, "nothing was written"


async def test_only_the_owner_duplicates_and_the_allowance_holds(env):
    http, users, prompts, factory = env
    author = await signed_in_owner(http, users, factory, "Author")
    theirs = await a_list(prompts, author.id)
    await signed_in_owner(http, users, factory, "Stranger")
    assert (await duplicate(http, theirs.id)).status_code == 404

    owner = await signed_in_owner(http, users, factory, "Collector")
    source = await a_list(prompts, owner.id)
    for index in range(MAX_OWNED_PROMPT_LISTS - 1):
        await prompts.create_owned(
            owner.id, name=f"List {index}", description="", language="en",
            prompts=(PromptListEntryInput(answer=f"answer {index}"),),
        )
    response = await duplicate(http, source.id)
    assert response.status_code == 422
    assert response.json()["errorCode"] == "prompt_list_allowance_reached"

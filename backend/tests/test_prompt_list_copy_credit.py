"""A copy credits the list it was copied from (R-LIST-21).

The credit reads the original as it is **now** - its current name and its
owner's current display name - because a revision does not carry a name and an
original may be renamed after it was copied. What changes with the original's
state is only whether it links: a published original is linked, one that was
unpublished or hidden is named without a link, and one its author deleted is
not named at all.

Deleted is the case the schema has to carry on its own. When an author deletes
a list, its copies deliberately forget where they came from (R-LIST-17): the
reclaim sweep clears `forked_from_revision_id`, and a copy then looks exactly
like a list nobody copied. `prompt_lists.is_copy` is what still knows it was
one - that it was copied, never what from.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from app.services.prompt_reclaim import reclaim_retired_prompt_lists
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


async def set_list(factory, prompt_list_id: str, **columns) -> None:
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(prompt_list_id))
            for column, value in columns.items():
                setattr(row, column, value)


async def a_published_list(prompts, factory, owner_id: str, name: str = "Creatures of the deep"):
    created = await prompts.create_owned(
        owner_id,
        name=name,
        description="",
        language="en",
        visibility="private",
        prompts=(PromptListEntryInput(answer="octopus"), PromptListEntryInput(answer="narwhal")),
    )
    await set_list(factory, created.id, visibility="public", published_at=PUBLISHED_AT)
    return created


async def copy_as(http, factory, user_id: str, prompt_list_id: str) -> str:
    await sign_in(http, factory, user_id)
    response = await http.post(f"/api/prompt-lists/{prompt_list_id}/fork")
    assert response.status_code == 201
    return response.json()["id"]


async def credit_seen_by_owner(http, factory, owner_id: str, prompt_list_id: str):
    await sign_in(http, factory, owner_id)
    return (await http.get(f"/api/prompt-lists/mine/{prompt_list_id}")).json()["copiedFrom"]


async def test_a_copy_of_a_published_list_credits_and_links_it(env):
    http, users, prompts, factory = env
    ada = await account(users, "Ada")
    source = await a_published_list(prompts, factory, ada.id)
    bo = await account(users, "Bo")
    copy_id = await copy_as(http, factory, bo.id, source.id)

    assert await credit_seen_by_owner(http, factory, bo.id, copy_id) == {
        "status": "published",
        "listId": source.id,
        "name": "Creatures of the deep",
        "ownerDisplayName": "Ada",
    }
    owned = (await http.get("/api/prompt-lists/mine")).json()
    rows = owned["promptLists"] if isinstance(owned, dict) else owned
    assert next(row for row in rows if row["id"] == copy_id)["copiedFrom"]["status"] == "published"


async def test_a_published_copy_carries_its_credit_into_the_catalogue(env):
    http, users, prompts, factory = env
    ada = await account(users, "Ada")
    source = await a_published_list(prompts, factory, ada.id)
    bo = await account(users, "Bo")
    copy_id = await copy_as(http, factory, bo.id, source.id)
    await set_list(factory, copy_id, visibility="public", published_at=PUBLISHED_AT)

    detail = (await http.get(f"/api/prompt-lists/community/{copy_id}")).json()

    assert detail["copiedFrom"]["name"] == "Creatures of the deep"
    assert detail["copiedFrom"]["ownerDisplayName"] == "Ada"
    original = (await http.get(f"/api/prompt-lists/community/{source.id}")).json()
    assert original["copiedFrom"] is None, "an original credits nobody"


async def test_an_unpublished_or_hidden_original_is_still_named_but_not_linked(env):
    http, users, prompts, factory = env
    ada = await account(users, "Ada")
    withdrawn = await a_published_list(prompts, factory, ada.id, "Withdrawn one")
    hidden = await a_published_list(prompts, factory, ada.id, "Hidden one")
    bo = await account(users, "Bo")
    withdrawn_copy = await copy_as(http, factory, bo.id, withdrawn.id)
    hidden_copy = await copy_as(http, factory, bo.id, hidden.id)

    await prompts.set_owned_publication(ada.id, withdrawn.id, published=False)
    await set_list(factory, hidden.id, moderation_state="hidden")

    for copy_id, name in ((withdrawn_copy, "Withdrawn one"), (hidden_copy, "Hidden one")):
        assert await credit_seen_by_owner(http, factory, bo.id, copy_id) == {
            "status": "withdrawn",
            "listId": None,
            "name": name,
            "ownerDisplayName": "Ada",
        }


async def test_a_deleted_original_is_credited_without_its_name_even_after_the_sweep(env):
    http, users, prompts, factory = env
    ada = await account(users, "Ada")
    source = await a_published_list(prompts, factory, ada.id)
    bo = await account(users, "Bo")
    copy_id = await copy_as(http, factory, bo.id, source.id)

    assert await prompts.delete_owned(ada.id, source.id)
    deleted = {"status": "deleted", "listId": None, "name": None, "ownerDisplayName": None}
    assert await credit_seen_by_owner(http, factory, bo.id, copy_id) == deleted

    # The sweep clears the only pointer back to the original. The copy still
    # knows it was a copy; it no longer knows what of, which is the point.
    await reclaim_retired_prompt_lists(
        factory, now=datetime.now(timezone.utc) + timedelta(days=2)
    )
    assert await credit_seen_by_owner(http, factory, bo.id, copy_id) == deleted


async def test_the_credit_follows_a_renamed_original(env):
    http, users, prompts, factory = env
    ada = await account(users, "Ada")
    source = await a_published_list(prompts, factory, ada.id)
    bo = await account(users, "Bo")
    copy_id = await copy_as(http, factory, bo.id, source.id)

    await set_list(factory, source.id, name="Deep sea, revised")

    assert (await credit_seen_by_owner(http, factory, bo.id, copy_id))["name"] == "Deep sea, revised"


async def test_a_copy_of_a_copy_credits_the_list_it_was_taken_from(env):
    http, users, prompts, factory = env
    ada = await account(users, "Ada")
    source = await a_published_list(prompts, factory, ada.id)
    bo = await account(users, "Bo")
    middle = await copy_as(http, factory, bo.id, source.id)
    await set_list(factory, middle, visibility="public", published_at=PUBLISHED_AT, name="Bo's deep")
    cass = await account(users, "Cass")
    last = await copy_as(http, factory, cass.id, middle)

    credit = await credit_seen_by_owner(http, factory, cass.id, last)
    assert (credit["name"], credit["ownerDisplayName"]) == ("Bo's deep", "Bo")


async def test_saving_a_copy_does_not_take_its_credit_away(env):
    # Where a list came from does not change when it is edited, so no save
    # can drop the credit - there is no field for it to drop.
    http, users, prompts, factory = env
    ada = await account(users, "Ada")
    source = await a_published_list(prompts, factory, ada.id)
    bo = await account(users, "Bo")
    copy_id = await copy_as(http, factory, bo.id, source.id)
    copy = await prompts.get_owned(bo.id, copy_id)

    await prompts.update_owned(
        bo.id,
        copy_id,
        expected_version=copy.version,
        name="Completely rewritten",
        description="Nothing like the original",
        visibility="private",
        prompts=(PromptListEntryInput(answer="lighthouse"),),
    )

    assert (await credit_seen_by_owner(http, factory, bo.id, copy_id))["status"] == "published"


async def test_a_list_that_is_not_a_copy_credits_nobody(env):
    http, users, prompts, factory = env
    ada = await account(users, "Ada")
    source = await a_published_list(prompts, factory, ada.id)

    assert await credit_seen_by_owner(http, factory, ada.id, source.id) is None

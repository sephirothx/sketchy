"""Copying a published list into one of your own (R-LIST-17).

`prompt_list_revisions.forked_from_revision_id` has existed since #318 with no
writer anywhere in application code — lineage modelled and never recorded.
This is what records it.

The lineage names a **revision** rather than a list, and that is the whole
reason it survives being useful: both sides go on being edited, so a pointer at
the list would stop meaning anything after the first edit on either.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.errors import install_refusal_handler
from app.api.prompt_lists import create_prompt_list_router, publish_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.db.models import (
    PromptList,
    PromptListRevision,
    PromptVersion,
    generate_uuid,
)
from app.repositories.interfaces import (
    BundledPromptDefinition,
    PromptListEntryInput,
)
from app.services.prompt_reclaim import reclaim_retired_prompt_lists
from app.repositories.sqlalchemy import (
    MAX_OWNED_PROMPT_LISTS,
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
    publish_limiter.reset()
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


async def a_published_list(prompts, factory, owner_id: str, **kwargs):
    created = await prompts.create_owned(
        owner_id,
        name=kwargs.get("name", "Source"),
        description="Worth copying",
        language="en",
        visibility="private",
        prompts=kwargs.get(
            "prompts",
            (
                PromptListEntryInput(answer="otter", aliases=("river otter",)),
                PromptListEntryInput(answer="badger"),
            ),
        ),
        tags=kwargs.get("tags", ("animals", "nature")),
    )
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(created.id))
            row.visibility = "public"
            row.published_at = PUBLISHED_AT
    return created


async def test_a_fork_is_private_and_names_the_revision_it_came_from(env):
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    forker = await account(users, "Forker")
    await sign_in(http, factory, forker.id)

    response = await http.post(f"/api/prompt-lists/{source.id}/fork")

    assert response.status_code == 201
    body = response.json()
    assert body["visibility"] == "private", "publishing a fork is its own act"
    assert body["name"] == "Source"
    assert [entry["prompt"] for entry in body["prompts"]] == ["otter", "badger"]
    assert body["prompts"][0]["aliases"] == ["river otter"]
    assert body["tags"] == ["animals", "nature"]

    async with factory() as session:
        origin = await session.scalar(
            select(PromptListRevision).where(
                PromptListRevision.prompt_list_id == UUID(source.id)
            )
        )
        forked = await session.scalar(
            select(PromptListRevision).where(
                PromptListRevision.prompt_list_id == UUID(body["id"])
            )
        )
    assert forked.forked_from_revision_id == origin.id
    assert body["forkedFromRevisionId"] == str(origin.id)


async def test_a_fork_is_independent_content_from_the_moment_it_exists(env):
    """Hiding the source afterwards does not reach into the copy."""
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    forker = await account(users, "Forker")
    await sign_in(http, factory, forker.id)
    forked = (await http.post(f"/api/prompt-lists/{source.id}/fork")).json()

    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(source.id))
            row.moderation_state = "hidden"

    still_there = await http.get(f"/api/prompt-lists/mine/{forked['id']}")

    assert still_there.status_code == 200
    assert still_there.json()["moderationState"] == "active"
    # The lineage may now point at a revision nothing serves. That is correct:
    # revisions are immutable, and the pointer records where the copy came
    # from rather than promising it is still reachable.
    assert still_there.json()["forkedFromRevisionId"] is not None


async def test_a_fork_gets_its_own_prompt_versions_not_the_source_s(env):
    """Otherwise editing one list would edit the other's pinned content."""
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    forker = await account(users, "Forker")
    await sign_in(http, factory, forker.id)
    forked = (await http.post(f"/api/prompt-lists/{source.id}/fork")).json()

    source_detail = await prompts.get_owned(author.id, source.id)
    assert {entry.prompt_version_id for entry in source_detail.prompts}.isdisjoint(
        {entry["promptVersionId"] for entry in forked["prompts"]}
    )
    async with factory() as session:
        # New concepts too: the fork is not a second reference to the same
        # prompt identity, which would make one owner's edit rewrite what the
        # other's list means.
        assert await session.scalar(
            select(func.count()).select_from(PromptVersion)
        ) == 4


async def test_only_a_published_list_can_be_forked(env):
    http, users, prompts, factory = env
    author = await account(users, "Author")
    private = await prompts.create_owned(
        author.id,
        name="Private",
        description="",
        language="en",
        visibility="private",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    hidden = await a_published_list(prompts, factory, author.id, name="Hidden")
    async with factory() as session:
        async with session.begin():
            (await session.get(PromptList, UUID(hidden.id))).moderation_state = "hidden"
    forker = await account(users, "Forker")
    await sign_in(http, factory, forker.id)

    assert (await http.post(f"/api/prompt-lists/{private.id}/fork")).status_code == 404
    assert (await http.post(f"/api/prompt-lists/{hidden.id}/fork")).status_code == 404


async def test_the_cap_refuses_visibly_and_writes_nothing(env):
    """R-LIST-04's allowance, failing the way R-LIST-08 asks it to."""
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    forker = await account(users, "Forker")
    for index in range(MAX_OWNED_PROMPT_LISTS):
        await prompts.create_owned(
            forker.id,
            name=f"Mine {index}",
            description="",
            language="en",
            visibility="private",
            prompts=(PromptListEntryInput(answer=f"thing {index}"),),
        )
    await sign_in(http, factory, forker.id)

    response = await http.post(f"/api/prompt-lists/{source.id}/fork")

    assert response.status_code == 422
    assert response.json()["errorCode"] == "prompt_list_allowance_reached"
    assert response.json()["params"] == {"max": MAX_OWNED_PROMPT_LISTS}
    async with factory() as session:
        owned = await session.scalar(
            select(func.count(PromptList.id)).where(
                PromptList.owner_user_id == UUID(forker.id)
            )
        )
    assert owned == MAX_OWNED_PROMPT_LISTS, "nothing was written"


async def test_a_hidden_prompt_is_not_copied_into_the_fork(env):
    """A moderator took it out of play; a copy must not put it back, under a
    new owner who never saw the decision."""
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    detail = await prompts.get_owned(author.id, source.id)
    async with factory() as session:
        async with session.begin():
            version = await session.get(
                PromptVersion, UUID(detail.prompts[0].prompt_version_id)
            )
            version.moderation_state = "hidden"
    forker = await account(users, "Forker")
    await sign_in(http, factory, forker.id)

    forked = await http.post(f"/api/prompt-lists/{source.id}/fork")

    assert [entry["prompt"] for entry in forked.json()["prompts"]] == ["badger"]


async def test_a_guest_cannot_fork(env):
    """A fork is a saved list, and saving one needs an account (R-LIST-06)."""
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    guest = await users.create_anonymous("Guest")
    await sign_in(http, factory, guest.id)

    response = await http.post(f"/api/prompt-lists/{source.id}/fork")

    assert response.status_code == 403


async def test_provenance_survives_the_fork_being_edited(env):
    """It is the list's origin, so it cannot live on the current revision.

    `forked_from_revision_id` is a fact about one revision - where *that*
    revision was derived from - and only the revision a fork starts life as
    was derived from anywhere else. Reading the current one answered correctly
    until the fork's owner made their first edit, and null from then on.
    """
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    forker = await account(users, "Forker")
    await sign_in(http, factory, forker.id)
    forked = (await http.post(f"/api/prompt-lists/{source.id}/fork")).json()
    origin = forked["forkedFromRevisionId"]
    assert origin is not None

    edited = await http.put(
        f"/api/prompt-lists/mine/{forked['id']}",
        json={
            "expectedVersion": forked["version"],
            "name": "Mine now",
            "prompts": [
                {"conceptId": entry["conceptId"], "prompt": entry["prompt"]}
                for entry in forked["prompts"]
            ]
            + [{"prompt": "heron"}],
        },
    )

    assert edited.status_code == 200
    assert edited.json()["version"] > forked["version"]
    assert edited.json()["forkedFromRevisionId"] == origin
    reopened = await http.get(f"/api/prompt-lists/mine/{forked['id']}")
    assert reopened.json()["forkedFromRevisionId"] == origin


async def test_an_official_bundled_list_cannot_be_forked(env):
    """Bundled lists are public and active, so a public-active-present check
    let them through - and the extended one holds 592 prompts, well past the
    500 an owned list may contain."""
    http, users, prompts, factory = env
    forker = await account(users, "Forker")
    await prompts.upsert_bundled(
        slug="official",
        name="Official",
        description="",
        language="en",
        prompts=[
            BundledPromptDefinition(
                concept_id=str(generate_uuid()), answer="otter"
            )
        ],
        version=1,
    )
    async with factory() as session:
        bundled_id = await session.scalar(
            select(PromptList.id).where(PromptList.slug == "official")
        )
    await sign_in(http, factory, forker.id)

    response = await http.post(f"/api/prompt-lists/{bundled_id}/fork")

    assert response.status_code == 404
    async with factory() as session:
        owned = await session.scalar(
            select(func.count(PromptList.id)).where(
                PromptList.owner_user_id == UUID(forker.id)
            )
        )
    assert owned == 0, "a refused fork spends no list slot"


async def test_reclaiming_a_deleted_source_forgets_where_the_fork_came_from(env):
    """And that is retention working, not provenance being lost.

    A fork reference is deliberately **not** a pin. Pins exist so a finished
    game's provenance survives its content's author tidying up (R-PRIV-05);
    a fork is not a finished game, it is a live list somebody else owns and
    edits. Treating it as a pin would mean an author who deletes their list
    can never actually remove it once a stranger has copied it — the sweep
    would keep the revision alive for as long as the copy exists, which is
    indefinitely.

    So the foreign key's `SET NULL` is the answer rather than a leak: the fork
    keeps every prompt it copied and forgets only the pointer. This test is
    here because that is a decision, and a decision nobody wrote down looks
    exactly like a bug the next time somebody reads the column.
    """
    http, users, prompts, factory = env
    author = await account(users, "Author")
    source = await a_published_list(prompts, factory, author.id)
    forker = await account(users, "Forker")
    await sign_in(http, factory, forker.id)
    forked = (await http.post(f"/api/prompt-lists/{source.id}/fork")).json()
    assert forked["forkedFromRevisionId"] is not None

    assert await prompts.delete_owned(author.id, source.id)
    await reclaim_retired_prompt_lists(
        factory, now=datetime.now(timezone.utc) + timedelta(days=2)
    )

    kept = await http.get(f"/api/prompt-lists/mine/{forked['id']}")
    assert kept.status_code == 200
    assert [entry["prompt"] for entry in kept.json()["prompts"]] == [
        "otter",
        "badger",
    ], "the copy keeps every prompt it copied"
    assert kept.json()["forkedFromRevisionId"] is None, (
        "only the pointer goes, and it goes because the author asked for the "
        "list to go"
    )

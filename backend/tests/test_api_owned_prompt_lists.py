"""The registered-owner REST workflow for persistent prompt lists."""
from __future__ import annotations

from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.errors import install_refusal_handler
from app.api.prompt_lists import create_prompt_list_router, share_limiter
from app.db.models import PromptList, PromptListRevision, PromptListRevisionTag
from app.prompt_content import LIST_TAG_VOCABULARY, MAX_LIST_TAGS
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db

LIST_TAG_SLUGS_IN_ORDER = tuple(slug for slug, _ in LIST_TAG_VOCABULARY)


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    prompts = SqlAlchemyPromptListRepository(factory)
    app = FastAPI()
    # Built the way `main.py` builds the real one. Without the handler a
    # `Refusal` renders as a bare `{"detail": ...}`, and a test cannot see the
    # code a client branches on - which is the contract since #760.
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_prompt_list_router(prompts, users))
    share_limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, users, factory
    await engine.dispose()


async def sign_in(http, factory, user_id: str) -> None:
    issued = await create_session(factory, user_id=user_id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)


async def test_guests_cannot_persist_quick_prompts(env):
    http, users, factory = env
    guest = await users.create_anonymous("Guest")
    await sign_in(http, factory, guest.id)

    response = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Nope", "prompts": [{"prompt": "apple"}]},
    )

    assert response.status_code == 403
    assert "Create an account" in response.json()["detail"]


async def test_owner_can_create_revise_reuse_and_share_a_list(env):
    http, users, factory = env
    account = await users.create_anonymous("Owner")
    account = await users.claim_account(account.id, "Owner", "test-hash")
    await sign_in(http, factory, account.id)

    created_response = await http.post(
        "/api/prompt-lists/mine",
        json={
            "name": "Animals",
            "language": "en",
            "visibility": "private",
            "prompts": [{"prompt": "red panda"}, {"prompt": "otter"}],
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["version"] == 1
    assert created["promptCount"] == 2
    assert created["shareCode"] is None
    assert (
        await http.get(f"/api/prompt-lists/{created['slug']}/prompt-stats")
    ).status_code == 404

    mine = (await http.get("/api/prompt-lists/mine")).json()
    assert [(item["name"], item["promptCount"]) for item in mine] == [
        ("Animals", 2)
    ]
    detail = (
        await http.get(f"/api/prompt-lists/mine/{created['id']}")
    ).json()
    panda = detail["prompts"][0]

    updated_response = await http.put(
        f"/api/prompt-lists/mine/{created['id']}",
        json={
            "expectedVersion": 1,
            "name": "Animals",
            "description": "Shared with friends",
            "visibility": "unlisted",
            "prompts": [
                {
                    "conceptId": panda["conceptId"],
                    "prompt": "giant panda",
                    "aliases": ["panda"],
                },
                {"prompt": "capybara"},
            ],
        },
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()
    assert updated["version"] == 2
    assert updated["shareCode"]

    stale = await http.put(
        f"/api/prompt-lists/mine/{created['id']}",
        json={
            "expectedVersion": 1,
            "name": "Stale",
            "visibility": "private",
            "prompts": [{"prompt": "apple"}],
        },
    )
    assert stale.status_code == 409

    http.cookies.clear()
    shared = await http.post(
        "/api/prompt-lists/shared", json={"code": updated["shareCode"]}
    )
    assert shared.status_code == 200
    assert shared.json()["slug"] == created["slug"]
    assert [prompt["prompt"] for prompt in shared.json()["prompts"]] == [
        "giant panda",
        "capybara",
    ]
    assert all("promptVersionId" in prompt for prompt in shared.json()["prompts"])
    assert "shareCode" not in shared.json()
    assert (await http.get("/api/prompt-lists")).json() == []


async def test_the_tag_vocabulary_is_served_rather_than_guessed(env):
    """A client offering a tag a save then refuses is the failure to avoid."""
    http, _, _ = env

    response = await http.get("/api/prompt-tags")

    assert response.status_code == 200
    body = response.json()
    assert body["maxPerList"] == MAX_LIST_TAGS
    slugs = [tag["slug"] for tag in body["tags"]]
    assert slugs == list(LIST_TAG_SLUGS_IN_ORDER)
    assert all(tag["name"] for tag in body["tags"])


async def test_owner_tags_their_list_and_the_tags_ride_the_revision(env):
    """Tags live on the revision, so setting them is an edit (R-LIST-05).

    A game pins a revision, and a discovery filter that found a list by its
    tags has to keep agreeing with the content that revision holds - which it
    cannot do if the tags hang off the mutable list row instead.
    """
    http, users, factory = env
    account = await users.create_anonymous("Tagger")
    account = await users.claim_account(account.id, "Tagger", "test-hash")
    await sign_in(http, factory, account.id)

    created = await http.post(
        "/api/prompt-lists/mine",
        json={
            "name": "Zoo",
            "prompts": [{"prompt": "otter"}],
            "tags": ["nature", "animals"],
        },
    )
    assert created.status_code == 201
    # Vocabulary order, not the order they were sent, so two lists carrying
    # the same tags present them the same way.
    assert created.json()["tags"] == ["animals", "nature"]
    assert created.json()["version"] == 1

    list_id = created.json()["id"]
    retagged = await http.put(
        f"/api/prompt-lists/mine/{list_id}",
        json={
            "expectedVersion": 1,
            "name": "Zoo",
            "prompts": [{"conceptId": created.json()["prompts"][0]["conceptId"],
                         "prompt": "otter"}],
            "tags": ["animals"],
        },
    )
    assert retagged.status_code == 200
    assert retagged.json()["tags"] == ["animals"]
    # A tag change alone is a change of content and earns its own revision,
    # exactly as a name or visibility change does.
    assert retagged.json()["version"] == 2

    unchanged = await http.put(
        f"/api/prompt-lists/mine/{list_id}",
        json={
            "expectedVersion": 2,
            "name": "Zoo",
            "prompts": [{"conceptId": created.json()["prompts"][0]["conceptId"],
                         "prompt": "otter"}],
            "tags": ["animals"],
        },
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["version"] == 2, "an exact restatement writes nothing"

    async with factory() as session:
        revisions = (
            await session.scalars(
                select(PromptListRevision)
                .where(PromptListRevision.prompt_list_id == UUID(list_id))
                .options(
                    selectinload(PromptListRevision.revision_tags).selectinload(
                        PromptListRevisionTag.tag
                    )
                )
                .order_by(PromptListRevision.version)
            )
        ).all()
    held = {
        revision.version: sorted(link.tag.slug for link in revision.revision_tags)
        for revision in revisions
    }
    # Revision one keeps what it was tagged with. The edit did not reach back.
    assert held == {1: ["animals", "nature"], 2: ["animals"]}


async def test_an_unknown_tag_is_named_rather_than_dropped(env):
    """R-LIST-01's rule: a save that silently discards part of what was sent
    is worse than one that refuses."""
    http, users, factory = env
    account = await users.create_anonymous("Inventor")
    account = await users.claim_account(account.id, "Inventor", "test-hash")
    await sign_in(http, factory, account.id)

    response = await http.post(
        "/api/prompt-lists/mine",
        json={
            "name": "Invented",
            "prompts": [{"prompt": "otter"}],
            "tags": ["animals", "not-a-real-tag"],
        },
    )

    assert response.status_code == 422
    assert response.json()["errorCode"] == "unknown_prompt_tag"
    assert response.json()["params"] == {"tag": "not-a-real-tag"}

    async with factory() as session:
        assert await session.scalar(select(func.count(PromptList.id))) == 0, (
            "a refused save writes no list at all"
        )


async def test_more_tags_than_a_list_may_carry_are_refused(env):
    http, users, factory = env
    account = await users.create_anonymous("Maximalist")
    account = await users.claim_account(account.id, "Maximalist", "test-hash")
    await sign_in(http, factory, account.id)

    response = await http.post(
        "/api/prompt-lists/mine",
        json={
            "name": "Everything",
            "prompts": [{"prompt": "otter"}],
            "tags": [slug for slug, _ in LIST_TAG_VOCABULARY][: MAX_LIST_TAGS + 1],
        },
    )

    assert response.status_code == 422

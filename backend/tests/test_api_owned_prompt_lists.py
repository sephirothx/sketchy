"""The registered-owner REST workflow for persistent prompt lists."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.errors import install_refusal_handler
from app.api.prompt_lists import create_prompt_list_router, share_limiter
from app.services.publication_policy import PUBLICATION_REVIEW_KEY
from app.db.models import (
    AuditEvent,
    PromptList,
    PromptListRevision,
    PromptListRevisionTag,
    User,
    UserWarning,
    generate_uuid,
)
from app.services import config_store
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
    app.include_router(create_prompt_list_router(prompts, users, factory))
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


async def verified(users, factory, name: str):
    """A registered account that has confirmed its address (R-LIST-12)."""
    account = await users.create_anonymous(name)
    account = await users.claim_account(account.id, name, "test-hash")
    async with factory() as session:
        async with session.begin():
            row = await session.get(User, UUID(account.id))
            row.email = f"{name.lower()}@example.test"
            row.email_verified_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return account


async def test_publishing_is_an_act_with_its_own_moment(env):
    """R-LIST-11: the list is public because somebody published it."""
    http, users, factory = env
    account = await verified(users, factory, "Publisher")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Shareable", "prompts": [{"prompt": "otter"}]},
    )
    list_id = created.json()["id"]
    assert created.json()["visibility"] == "private"

    published = await http.post(f"/api/prompt-lists/mine/{list_id}/publish")

    assert published.status_code == 200
    assert published.json()["visibility"] == "public"
    async with factory() as session:
        row = await session.get(PromptList, UUID(list_id))
        assert row.published_at is not None
        event = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "prompt_list.published")
        )
    assert event is not None and str(event.target_id) == list_id

    withdrawn = await http.post(f"/api/prompt-lists/mine/{list_id}/unpublish")

    assert withdrawn.status_code == 200
    assert withdrawn.json()["visibility"] == "private"
    async with factory() as session:
        row = await session.get(PromptList, UUID(list_id))
        assert row.published_at is None, "a later publish is a new act"


async def test_an_unverified_account_cannot_publish(env):
    """The gate is on the account, because the content is judged afterwards."""
    http, users, factory = env
    account = await users.create_anonymous("Unverified")
    account = await users.claim_account(account.id, "Unverified", "test-hash")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Eager", "prompts": [{"prompt": "otter"}]},
    )

    response = await http.post(
        f"/api/prompt-lists/mine/{created.json()['id']}/publish"
    )

    assert response.status_code == 403
    assert response.json()["errorCode"] == "email_verification_required"
    assert response.json()["params"] == {"action": "publish"}
    async with factory() as session:
        row = await session.get(PromptList, UUID(created.json()["id"]))
    assert row.visibility == "private", "a refused publish changes nothing"


async def test_an_unread_warning_holds_publishing_back(env):
    http, users, factory = env
    account = await verified(users, factory, "Warned")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Warned list", "prompts": [{"prompt": "otter"}]},
    )
    async with factory() as session:
        async with session.begin():
            session.add(
                UserWarning(
                    id=generate_uuid(),
                    user_id=UUID(account.id),
                    reason="Please read the rules.",
                )
            )

    response = await http.post(
        f"/api/prompt-lists/mine/{created.json()['id']}/publish"
    )

    assert response.status_code == 403
    assert response.json()["errorCode"] == "warning_unread"
    assert response.json()["params"] == {"action": "publish"}


async def test_the_operator_switch_sends_a_new_publication_to_review(env):
    """R-LIST-13's lever: pre-approval without a release."""
    http, users, factory = env
    account = await verified(users, factory, "Reviewed")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Queued", "prompts": [{"prompt": "otter"}]},
    )
    async with factory() as session:
        async with session.begin():
            await config_store.put(session, PUBLICATION_REVIEW_KEY, "1")

    published = await http.post(
        f"/api/prompt-lists/mine/{created.json()['id']}/publish"
    )

    assert published.status_code == 200
    assert published.json()["visibility"] == "public"
    assert published.json()["moderationState"] == "under_review"


async def test_a_hidden_list_cannot_be_published_by_its_owner(env):
    """A takedown has to survive the owner's own hand."""
    http, users, factory = env
    account = await verified(users, factory, "Hidden")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Taken down", "prompts": [{"prompt": "otter"}]},
    )
    list_id = created.json()["id"]
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(list_id))
            row.moderation_state = "hidden"

    response = await http.post(f"/api/prompt-lists/mine/{list_id}/publish")

    assert response.status_code == 422
    assert response.json()["errorCode"] == "prompt_list_hidden"
    async with factory() as session:
        row = await session.get(PromptList, UUID(list_id))
    assert row.visibility == "private"


async def test_publishing_revokes_the_share_code_it_no_longer_needs(env):
    """A published list is reached by identity, so the bearer capability it
    was carrying has nothing left to authorize (R-LIST-03)."""
    http, users, factory = env
    account = await verified(users, factory, "Sharer")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={
            "name": "Was unlisted",
            "visibility": "unlisted",
            "prompts": [{"prompt": "otter"}],
        },
    )
    assert created.json()["shareCode"]

    published = await http.post(
        f"/api/prompt-lists/mine/{created.json()['id']}/publish"
    )

    assert published.json()["shareCode"] is None


async def test_unpublishing_is_not_a_moderator_s_finding(env):
    """Leaving the catalogue does not clear what a moderator decided.

    Unpublishing is the owner's act and moderation is somebody else's, so a
    list that was taken down and then withdrawn by its owner stays hidden -
    otherwise unpublishing would be a way to launder a takedown, and
    re-publishing would put the content back.
    """
    http, users, factory = env
    account = await verified(users, factory, "Withdrawer")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Withdrawn", "prompts": [{"prompt": "otter"}]},
    )
    list_id = created.json()["id"]
    await http.post(f"/api/prompt-lists/mine/{list_id}/publish")
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(list_id))
            row.moderation_state = "hidden"

    withdrawn = await http.post(f"/api/prompt-lists/mine/{list_id}/unpublish")

    assert withdrawn.status_code == 200
    assert withdrawn.json()["moderationState"] == "hidden"
    again = await http.post(f"/api/prompt-lists/mine/{list_id}/publish")
    assert again.status_code == 422


async def test_editing_a_published_list_leaves_it_published(env):
    """A save carries content, never publication (R-LIST-11).

    Before this, a published list could not be edited at all: the owner's
    editor would send back the `visibility` it was given, and `public` is not
    a value the save endpoint accepts. Silently accepting `private` instead
    would have been worse - fixing a typo would have taken the list out of the
    catalogue.
    """
    http, users, factory = env
    account = await verified(users, factory, "Editor")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Typo", "prompts": [{"prompt": "otter"}]},
    )
    list_id = created.json()["id"]
    published = await http.post(f"/api/prompt-lists/mine/{list_id}/publish")
    version = published.json()["version"]

    edited = await http.put(
        f"/api/prompt-lists/mine/{list_id}",
        json={
            "expectedVersion": version,
            "name": "Typo fixed",
            "visibility": "private",
            "prompts": [
                {
                    "conceptId": created.json()["prompts"][0]["conceptId"],
                    "prompt": "otter",
                }
            ],
        },
    )

    assert edited.status_code == 200
    assert edited.json()["name"] == "Typo fixed"
    assert edited.json()["visibility"] == "public", (
        "an edit cannot take a list out of the catalogue"
    )
    async with factory() as session:
        row = await session.get(PromptList, UUID(list_id))
    assert row.published_at is not None
    assert row.share_code is None


async def test_the_list_of_my_lists_carries_their_tags(env):
    """The collection endpoint dropped them while the detail route kept them.

    Two paths build an owned list: one loads the current revision and the
    other counts prompts. Tags were wired into the first only, so a list read
    back through `/mine` had `tags: []` however it had been saved.
    """
    http, users, factory = env
    account = await users.create_anonymous("Collector")
    account = await users.claim_account(account.id, "Collector", "test-hash")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={
            "name": "Tagged",
            "prompts": [{"prompt": "otter"}],
            "tags": ["animals", "nature"],
        },
    )
    assert created.json()["tags"] == ["animals", "nature"]

    listing = await http.get("/api/prompt-lists/mine")

    [row] = listing.json()
    assert row["tags"] == ["animals", "nature"]


async def test_publication_and_its_ledger_entry_commit_together(env):
    """A published list with nothing to say who published it is the failure.

    The mutation used to commit, and a second transaction wrote the ledger;
    anything failing between the two left exactly that.
    """
    http, users, factory = env
    account = await verified(users, factory, "Ledger")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Audited", "prompts": [{"prompt": "otter"}]},
    )
    list_id = created.json()["id"]

    await http.post(f"/api/prompt-lists/mine/{list_id}/publish")
    await http.post(f"/api/prompt-lists/mine/{list_id}/unpublish")

    async with factory() as session:
        events = (
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.target_id == list_id)
                .order_by(AuditEvent.created_at)
            )
        ).all()
    assert [event.event_type for event in events] == [
        "prompt_list.published",
        "prompt_list.unpublished",
    ]
    assert all(event.actor_user_id == UUID(account.id) for event in events)


async def test_a_refused_publish_writes_no_ledger_entry(env):
    """The ledger records what happened, not what was attempted."""
    http, users, factory = env
    account = await verified(users, factory, "Refused")
    await sign_in(http, factory, account.id)
    created = await http.post(
        "/api/prompt-lists/mine",
        json={"name": "Hidden", "prompts": [{"prompt": "otter"}]},
    )
    list_id = created.json()["id"]
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(list_id))
            row.moderation_state = "hidden"

    assert (
        await http.post(f"/api/prompt-lists/mine/{list_id}/publish")
    ).status_code == 422

    async with factory() as session:
        assert await session.scalar(
            select(func.count(AuditEvent.id)).where(AuditEvent.target_id == list_id)
        ) == 0

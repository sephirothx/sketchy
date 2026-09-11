"""The community catalogue: what is in it, in what order, and what is not.

The three conditions deciding membership - public, active, not retired - are
the interesting part. They are one predicate rather than three filters spread
across the reads, so a takedown drops a list out of the catalogue without a
second code path having to agree (R-LIST-13, R-LIST-14).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest_asyncio
from sqlalchemy import select
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_refusal_handler
from app.api.prompt_lists import community_limiter, create_prompt_list_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.db.models import (
    PromptList,
    PromptListStar,
    PromptVersion,
    generate_uuid,
)
from app.repositories.interfaces import (
    BundledPromptDefinition,
    PromptListEntryInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db

PUBLISHED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


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
    community_limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, users, prompts, factory
    await engine.dispose()


async def account(users, name: str):
    guest = await users.create_anonymous(name)
    return await users.claim_account(guest.id, name, "test-hash")


async def published(
    prompts,
    factory,
    owner_id: str,
    name: str,
    *,
    tags: tuple[str, ...] = (),
    language: str = "en",
    at: datetime = PUBLISHED_AT,
    stars: int = 0,
    users=None,
    entries: tuple[PromptListEntryInput, ...] = (PromptListEntryInput(answer="otter"),),
):
    """A list in the catalogue, with its stars already given."""
    created = await prompts.create_owned(
        owner_id,
        name=name,
        description="",
        language=language,
        visibility="private",
        prompts=entries,
        tags=tags,
    )
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(created.id))
            row.visibility = "public"
            row.published_at = at
            for index in range(stars):
                fan = await users.create_anonymous(f"{name} fan {index}")
                session.add(
                    PromptListStar(
                        user_id=UUID(fan.id), prompt_list_id=UUID(created.id)
                    )
                )
    return created


async def test_only_published_active_present_lists_are_in_the_catalogue(env):
    http, users, prompts, factory = env
    owner = await account(users, "Owner")
    await published(prompts, factory, owner.id, "Visible", users=users)
    hidden = await published(prompts, factory, owner.id, "Hidden", users=users)
    retired = await published(prompts, factory, owner.id, "Retired", users=users)
    reviewing = await published(prompts, factory, owner.id, "Waiting", users=users)
    await prompts.create_owned(
        owner.id,
        name="Never published",
        description="",
        language="en",
        visibility="private",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    async with factory() as session:
        async with session.begin():
            (await session.get(PromptList, UUID(hidden.id))).moderation_state = "hidden"
            (
                await session.get(PromptList, UUID(reviewing.id))
            ).moderation_state = "under_review"
            (await session.get(PromptList, UUID(retired.id))).deleted_at = PUBLISHED_AT

    response = await http.get("/api/prompt-lists/community")

    assert response.status_code == 200
    assert [row["name"] for row in response.json()["lists"]] == ["Visible"]


async def test_the_official_catalogue_never_carries_a_community_list(env):
    """R-LIST-09 survives #398 because the two are different routes."""
    http, users, prompts, factory = env
    owner = await account(users, "Owner")
    await published(prompts, factory, owner.id, "Community", users=users)

    official = await http.get("/api/prompt-lists")

    assert official.status_code == 200
    assert official.json() == []


async def test_stars_order_the_catalogue_and_recency_breaks_the_tie(env):
    http, users, prompts, factory = env
    owner = await account(users, "Owner")
    await published(prompts, factory, owner.id, "Popular", stars=3, users=users)
    await published(prompts, factory, owner.id, "Quiet", stars=0, users=users)
    await published(
        prompts,
        factory,
        owner.id,
        "Newer but quiet",
        stars=0,
        at=PUBLISHED_AT + timedelta(days=1),
        users=users,
    )

    by_stars = await http.get("/api/prompt-lists/community")
    by_date = await http.get("/api/prompt-lists/community?sort=newest")

    assert [row["name"] for row in by_stars.json()["lists"]] == [
        "Popular",
        "Newer but quiet",
        "Quiet",
    ]
    assert [row["starCount"] for row in by_stars.json()["lists"]] == [3, 0, 0]
    # Ids are UUIDv7, so the last tiebreak is creation order, newest first -
    # deterministic, which is what a cursor needs it to be.
    assert [row["name"] for row in by_date.json()["lists"]] == [
        "Newer but quiet",
        "Quiet",
        "Popular",
    ]


async def test_a_tag_filter_wants_every_tag_not_any_of_them(env):
    http, users, prompts, factory = env
    owner = await account(users, "Owner")
    await published(
        prompts, factory, owner.id, "Both", tags=("animals", "nature"), users=users
    )
    await published(prompts, factory, owner.id, "One", tags=("animals",), users=users)

    both = await http.get("/api/prompt-lists/community?tag=animals&tag=nature")
    one = await http.get("/api/prompt-lists/community?tag=animals")

    assert [row["name"] for row in both.json()["lists"]] == ["Both"]
    assert sorted(row["name"] for row in one.json()["lists"]) == ["Both", "One"]
    assert both.json()["lists"][0]["tags"] == ["animals", "nature"]


async def test_an_unknown_tag_filter_is_refused_rather_than_ignored(env):
    """Ignoring it would answer a different question than the one asked."""
    http, *_ = env

    response = await http.get("/api/prompt-lists/community?tag=not-a-real-tag")

    assert response.status_code == 422
    assert response.json()["errorCode"] == "unknown_prompt_tag"
    assert response.json()["params"] == {"tag": "not-a-real-tag"}


async def test_a_language_filter_narrows_the_catalogue(env):
    http, users, prompts, factory = env
    owner = await account(users, "Owner")
    await published(prompts, factory, owner.id, "English", users=users)
    await published(prompts, factory, owner.id, "Deutsch", language="de", users=users)

    response = await http.get("/api/prompt-lists/community?language=de")

    assert [row["name"] for row in response.json()["lists"]] == ["Deutsch"]


async def test_paging_walks_the_catalogue_without_repeating_or_skipping(env):
    http, users, prompts, factory = env
    owner = await account(users, "Owner")
    for index in range(5):
        await published(
            prompts,
            factory,
            owner.id,
            f"List {index}",
            at=PUBLISHED_AT + timedelta(minutes=index),
            users=users,
        )

    seen: list[str] = []
    cursor = None
    for _ in range(5):
        query = "/api/prompt-lists/community?sort=newest&limit=2"
        if cursor:
            query += f"&cursor={cursor}"
        page = (await http.get(query)).json()
        seen.extend(row["name"] for row in page["lists"])
        cursor = page["nextCursor"]
        if cursor is None:
            break

    assert cursor is None
    assert seen == [f"List {index}" for index in (4, 3, 2, 1, 0)]
    assert len(seen) == len(set(seen))


async def test_the_catalogue_says_whether_this_caller_starred_a_list(env):
    """Null for a signed-out caller: a different answer from `no`."""
    http, users, prompts, factory = env
    owner = await account(users, "Owner")
    reader = await account(users, "Reader")
    starred = await published(prompts, factory, owner.id, "Starred", users=users)
    await published(prompts, factory, owner.id, "Unstarred", users=users)
    async with factory() as session:
        async with session.begin():
            session.add(
                PromptListStar(
                    user_id=UUID(reader.id), prompt_list_id=UUID(starred.id)
                )
            )

    anonymous = await http.get("/api/prompt-lists/community")
    assert {row["starredByMe"] for row in anonymous.json()["lists"]} == {None}

    issued = await create_session(factory, user_id=reader.id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)
    signed_in = await http.get("/api/prompt-lists/community")

    assert {
        row["name"]: row["starredByMe"] for row in signed_in.json()["lists"]
    } == {"Starred": True, "Unstarred": False}


async def test_a_catalogue_row_names_its_owner_and_no_account_id(env):
    """Attribution is a name. A stable third-party id in a public listing is
    a join key for anybody who collects the pages."""
    http, users, prompts, factory = env
    owner = await account(users, "Cartographer")
    await published(prompts, factory, owner.id, "Attributed", users=users)

    response = await http.get("/api/prompt-lists/community")

    [row] = response.json()["lists"]
    assert row["ownerDisplayName"] == "Cartographer"
    assert owner.id not in response.text


async def test_a_guest_reads_as_nobody_rather_than_as_unstarred(env):
    """`false` is the registered answer, and a guest cannot star at all.

    A guest holds a session and a user id like anyone else, so passing that id
    through answered "you have not starred this" to somebody who cannot — and
    a client reading it would offer a control that answers 403.
    """
    http, users, prompts, factory = env
    owner = await account(users, "Owner")
    await published(prompts, factory, owner.id, "Findable", users=users)
    guest = await users.create_anonymous("Guest")
    issued = await create_session(factory, user_id=guest.id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)

    response = await http.get("/api/prompt-lists/community")

    assert [row["starredByMe"] for row in response.json()["lists"]] == [None]


async def test_an_official_bundled_list_never_reaches_the_catalogue(env):
    """The three-clause predicate matched them; the fourth is what excludes."""
    http, users, prompts, factory = env
    await prompts.upsert_bundled(
        slug="official",
        name="Official",
        description="",
        language="en",
        prompts=[
            BundledPromptDefinition(concept_id=str(generate_uuid()), answer="otter")
        ],
        version=1,
    )

    response = await http.get("/api/prompt-lists/community")

    assert response.json()["lists"] == []


async def test_a_published_list_can_be_read_whole(env):
    """R-LIST-19: choosing from a name and a count is choosing blind."""
    http, users, prompts, factory = env
    owner = await account(users, "Cartographer")
    created = await published(
        prompts,
        factory,
        owner.id,
        "Seaside",
        tags=("nature", "places"),
        users=users,
        entries=(
            PromptListEntryInput(answer="lighthouse"),
            PromptListEntryInput(answer="harbour"),
        ),
    )

    response = await http.get(f"/api/prompt-lists/community/{created.id}")

    assert response.status_code == 200
    body = response.json()
    assert [entry["prompt"] for entry in body["prompts"]] == ["lighthouse", "harbour"]
    # Version ids, so one exact prompt can be reported (R-LIST-13); no
    # concept ids or aliases, which are matching machinery.
    assert all(entry["promptVersionId"] for entry in body["prompts"])
    assert body["name"] == "Seaside"
    assert body["ownerDisplayName"] == "Cartographer"
    assert body["tags"] == ["nature", "places"]
    # Text only: a public listing is not the place to hand out identifiers.
    assert "conceptId" not in response.text and "aliases" not in response.text


async def test_the_preview_leaves_out_a_prompt_a_moderator_hid(env):
    """A hidden version is out of play, so it is not part of what this list
    would draw - and showing it would put it back in front of people."""
    http, users, prompts, factory = env
    owner = await account(users, "Author")
    created = await published(
        prompts,
        factory,
        owner.id,
        "Mixed",
        users=users,
        entries=(
            PromptListEntryInput(answer="otter"),
            PromptListEntryInput(answer="something unpleasant"),
        ),
    )
    async with factory() as session:
        async with session.begin():
            version = await session.get(
                PromptVersion, UUID(created.prompts[1].prompt_version_id)
            )
            version.moderation_state = "hidden"

    body = (await http.get(f"/api/prompt-lists/community/{created.id}")).json()

    assert [entry["prompt"] for entry in body["prompts"]] == ["otter"]


async def test_the_preview_opens_only_what_the_listing_shows(env):
    """One predicate for both, so a takedown closes both doors at once."""
    http, users, prompts, factory = env
    owner = await account(users, "Author")
    hidden = await published(prompts, factory, owner.id, "Hidden", users=users)
    retired = await published(prompts, factory, owner.id, "Retired", users=users)
    private = await prompts.create_owned(
        owner.id,
        name="Private",
        description="",
        language="en",
        visibility="private",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    await prompts.upsert_bundled(
        slug="official",
        name="Official",
        description="",
        language="en",
        prompts=[
            BundledPromptDefinition(concept_id=str(generate_uuid()), answer="otter")
        ],
        version=1,
    )
    async with factory() as session:
        async with session.begin():
            (await session.get(PromptList, UUID(hidden.id))).moderation_state = "hidden"
            (await session.get(PromptList, UUID(retired.id))).deleted_at = PUBLISHED_AT
            bundled_id = await session.scalar(
                select(PromptList.id).where(PromptList.slug == "official")
            )

    for list_id in (hidden.id, retired.id, private.id, str(bundled_id)):
        response = await http.get(f"/api/prompt-lists/community/{list_id}")
        assert response.status_code == 404, list_id
        assert response.json()["errorCode"] == "prompt_list_not_found"


async def test_a_signed_out_reader_can_open_one(env):
    http, users, prompts, factory = env
    owner = await account(users, "Author")
    created = await published(prompts, factory, owner.id, "Open", users=users)

    body = (await http.get(f"/api/prompt-lists/community/{created.id}")).json()

    assert [entry["prompt"] for entry in body["prompts"]] == ["otter"]
    assert body["starredByMe"] is None


async def test_the_starred_filter_is_this_account_s_shortlist(env):
    """What the room picker's Starred group reads."""
    http, users, prompts, factory = env
    owner = await account(users, "Author")
    reader = await account(users, "Reader")
    kept = await published(prompts, factory, owner.id, "Kept", users=users)
    await published(prompts, factory, owner.id, "Ignored", users=users)
    async with factory() as session:
        async with session.begin():
            session.add(
                PromptListStar(user_id=UUID(reader.id), prompt_list_id=UUID(kept.id))
            )
    issued = await create_session(factory, user_id=reader.id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)

    everything = await http.get("/api/prompt-lists/community")
    shortlist = await http.get("/api/prompt-lists/community?starred=true")

    assert sorted(row["name"] for row in everything.json()["lists"]) == [
        "Ignored",
        "Kept",
    ]
    assert [row["name"] for row in shortlist.json()["lists"]] == ["Kept"]
    assert shortlist.json()["lists"][0]["starredByMe"] is True


async def test_the_starred_filter_needs_an_account(env):
    """Nobody's shortlist is not everybody's stars."""
    http, users, prompts, factory = env
    owner = await account(users, "Author")
    await published(prompts, factory, owner.id, "Findable", users=users)

    signed_out = await http.get("/api/prompt-lists/community?starred=true")
    assert signed_out.status_code == 403
    assert signed_out.json()["errorCode"] == "account_required"
    assert signed_out.json()["params"] == {"action": "stars"}

    guest = await users.create_anonymous("Guest")
    issued = await create_session(factory, user_id=guest.id, device_label="Test")
    http.cookies.set(COOKIE_NAME, issued.token)
    assert (
        await http.get("/api/prompt-lists/community?starred=true")
    ).status_code == 403

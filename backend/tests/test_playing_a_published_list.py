"""A published list is playable by anyone, on the one predicate (R-LIST-15).

Before #744 a room could admit a list on three grounds - bundled, owned, or
unlisted with its share code - and `public` was none of them. Discovery without
this issue would have been a shop window: browse, star, fork, and then have to
own a copy before anybody could play it, spending R-LIST-04's allowance of 25
on lists nobody wanted to keep.

The tests below care as much about *where* the check lives as what it says.
`resolve_selection` (opening a room) and `authorize_selection` (Start, R-LIST-07)
share one predicate, so an unpublish or a takedown between the two refuses the
room visibly rather than quietly shrinking the pool it draws from.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
import pytest_asyncio

from app.db.models import PromptList
from app.repositories.interfaces import (
    PromptListEntryInput,
    PromptListSelectionError,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db

PUBLISHED_AT = datetime(2026, 9, 1, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    yield (
        SqlAlchemyPromptListRepository(factory),
        SqlAlchemyUserRepository(factory),
        factory,
    )
    await engine.dispose()


async def a_published_list(prompts, users, factory, name: str = "Published"):
    guest = await users.create_anonymous("Author")
    author = await users.claim_account(guest.id, "Author", "test-hash")
    created = await prompts.create_owned(
        author.id,
        name=name,
        description="",
        language="en",
        visibility="private",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(created.id))
            row.visibility = "public"
            row.published_at = PUBLISHED_AT
    return created


async def test_a_stranger_can_open_a_room_on_somebody_else_s_published_list(env):
    prompts, users, factory = env
    published = await a_published_list(prompts, users, factory)
    stranger = await users.create_anonymous("Stranger")

    resolved = await prompts.resolve_selection(
        [published.slug], requesting_user_id=stranger.id
    )

    assert list(resolved.prompts) == ["otter"]
    assert resolved.language == "en"


async def test_a_signed_out_caller_can_too(env):
    """Publishing is the owner saying so; no capability stands in front of it."""
    prompts, users, factory = env
    published = await a_published_list(prompts, users, factory)

    resolved = await prompts.resolve_selection([published.slug])

    assert list(resolved.prompts) == ["otter"]


async def test_start_re_authorizes_and_pins_the_revision_it_finds(env):
    prompts, users, factory = env
    published = await a_published_list(prompts, users, factory)
    stranger = await users.create_anonymous("Host")

    pinned = await prompts.authorize_selection(
        [published.slug], requesting_user_id=stranger.id
    )

    assert len(pinned.revision_ids) == 1


async def test_unpublishing_between_the_picker_and_start_refuses_the_room(env):
    """R-LIST-07's re-authorization covers the new ground like the others.

    The room must fail visibly (R-LIST-06a), never open on the built-in list
    while the host is looking at the list they chose.
    """
    prompts, users, factory = env
    published = await a_published_list(prompts, users, factory)
    host = await users.create_anonymous("Host")
    await prompts.resolve_selection([published.slug], requesting_user_id=host.id)

    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(published.id))
            row.visibility = "private"
            row.published_at = None

    with pytest.raises(PromptListSelectionError) as refusal:
        await prompts.authorize_selection(
            [published.slug], requesting_user_id=host.id
        )
    assert published.slug in str(refusal.value)


async def test_a_takedown_between_the_picker_and_start_refuses_the_room(env):
    prompts, users, factory = env
    published = await a_published_list(prompts, users, factory)
    host = await users.create_anonymous("Host")
    await prompts.resolve_selection([published.slug], requesting_user_id=host.id)

    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(published.id))
            row.moderation_state = "hidden"

    with pytest.raises(PromptListSelectionError):
        await prompts.authorize_selection(
            [published.slug], requesting_user_id=host.id
        )


async def test_retiring_a_published_list_takes_it_out_of_play_too(env):
    prompts, users, factory = env
    published = await a_published_list(prompts, users, factory)
    host = await users.create_anonymous("Host")

    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(published.id))
            row.deleted_at = PUBLISHED_AT

    with pytest.raises(PromptListSelectionError):
        await prompts.resolve_selection(
            [published.slug], requesting_user_id=host.id
        )


async def test_the_three_older_refusals_still_refuse(env):
    """The fourth ground is an addition, not a loosening."""
    prompts, users, factory = env
    guest = await users.create_anonymous("Author")
    author = await users.claim_account(guest.id, "Author", "test-hash")
    private = await prompts.create_owned(
        author.id,
        name="Private",
        description="",
        language="en",
        visibility="private",
        prompts=(PromptListEntryInput(answer="otter"),),
    )
    unlisted = await prompts.create_owned(
        author.id,
        name="Unlisted",
        description="",
        language="en",
        visibility="unlisted",
        prompts=(PromptListEntryInput(answer="badger"),),
    )
    stranger = await users.create_anonymous("Stranger")

    with pytest.raises(PromptListSelectionError):
        await prompts.resolve_selection(
            [private.slug], requesting_user_id=stranger.id
        )
    with pytest.raises(PromptListSelectionError):
        await prompts.resolve_selection(
            [unlisted.slug], requesting_user_id=stranger.id
        )
    # And with the code, the unlisted one still resolves.
    resolved = await prompts.resolve_selection(
        [unlisted.slug],
        requesting_user_id=stranger.id,
        share_codes=[unlisted.share_code],
    )
    assert list(resolved.prompts) == ["badger"]


async def test_a_list_under_review_is_not_playable_even_though_it_is_public(env):
    """The operator switch's waiting room is a waiting room (R-LIST-13)."""
    prompts, users, factory = env
    published = await a_published_list(prompts, users, factory)
    stranger = await users.create_anonymous("Stranger")
    async with factory() as session:
        async with session.begin():
            row = await session.get(PromptList, UUID(published.id))
            row.moderation_state = "under_review"

    with pytest.raises(PromptListSelectionError):
        await prompts.resolve_selection(
            [published.slug], requesting_user_id=stranger.id
        )

"""Publishing makes an edition; saving changes only the working copy (#1360).

Before editions, every save of a published list reached the catalogue and
every room at once, so nothing could be approved as it stood and a reader's
page could change under them. A published list now has a live edition - an
immutable snapshot of the working copy - and at most one pending edition
waiting for review. Strangers read, play and copy the live edition; the owner
edits, and plays, the working copy; Publish update replaces the live edition.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.db.models import PromptListEdition, PromptVersion
from app.repositories.interfaces import PromptListEntryInput, PromptListsChangedError
from app.repositories.sqlalchemy import (
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from tests.dbfixtures import create_test_db


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    yield (
        SqlAlchemyPromptListRepository(factory),
        SqlAlchemyUserRepository(factory),
        factory,
    )
    await engine.dispose()


async def account(users, name: str):
    guest = await users.create_anonymous(name)
    return await users.claim_account(guest.id, name, "test-hash")


async def published(prompts, owner_id: str, *answers: str, name: str = "Seaside"):
    created = await prompts.create_owned(
        owner_id,
        name=name,
        description="",
        language="en",
        prompts=tuple(PromptListEntryInput(answer=answer) for answer in answers),
    )
    return await prompts.set_owned_publication(owner_id, created.id, published=True)


async def saved(prompts, owner_id: str, current, *answers: str, name: str | None = None):
    return await prompts.update_owned(
        owner_id,
        current.id,
        expected_version=current.version,
        name=name or current.name,
        description=current.description,
        prompts=tuple(PromptListEntryInput(answer=answer) for answer in answers),
    )


async def edition_count(factory, list_id: str) -> int:
    async with factory() as session:
        return await session.scalar(
            select(func.count(PromptListEdition.id)).where(
                PromptListEdition.prompt_list_id == UUID(list_id)
            )
        )


async def test_a_save_reaches_no_reader_until_it_is_published(env):
    prompts, users, factory = env
    owner = await account(users, "Owner")
    first = await published(prompts, owner.id, "gull", "lighthouse")
    assert first.live_edition.number == 1 and not first.unpublished_changes

    edited = await saved(prompts, owner.id, first, "gull", "crab", name="Seaside, revised")

    assert edited.unpublished_changes is True
    page = await prompts.get_community(first.id)
    assert page.name == "Seaside"
    assert sorted(entry.answer for entry in page.prompts) == ["gull", "lighthouse"]

    updated = await prompts.set_owned_publication(owner.id, first.id, published=True)

    assert updated.live_edition.number == 2 and not updated.unpublished_changes
    page = await prompts.get_community(first.id)
    assert page.name == "Seaside, revised"
    assert sorted(entry.answer for entry in page.prompts) == ["crab", "gull"]
    assert await edition_count(factory, first.id) == 1, "the edition it replaced is gone"


async def test_publishing_what_is_already_live_makes_no_edition(env):
    prompts, users, factory = env
    owner = await account(users, "Owner")
    first = await published(prompts, owner.id, "gull")

    again = await prompts.set_owned_publication(owner.id, first.id, published=True)

    assert again.live_edition.number == 1
    assert await edition_count(factory, first.id) == 1


async def test_a_stranger_plays_the_live_edition_and_the_owner_the_working_copy(env):
    prompts, users, _ = env
    owner = await account(users, "Owner")
    stranger = await account(users, "Stranger")
    first = await published(prompts, owner.id, "gull")
    await saved(prompts, owner.id, first, "crab")

    async def drawn_for(user_id):
        pinned = await prompts.authorize_selection([first.slug], requesting_user_id=user_id)
        sample = await prompts.sample_prompts(
            list(pinned.list_ids),
            limit=5,
            expected_versions=pinned.list_versions,
            edition_ids=pinned.edition_ids,
        )
        return [prompt.answer for prompt in sample.prompts]

    assert await drawn_for(stranger.id) == ["gull"]
    assert await drawn_for(owner.id) == ["crab"]


async def test_a_draw_from_an_edition_replaced_since_the_check_is_refused(env):
    """Publish update deletes the edition it replaces: a room that checked
    the old one is told to check again rather than drawing nothing."""
    prompts, users, _ = env
    owner = await account(users, "Owner")
    stranger = await account(users, "Stranger")
    first = await published(prompts, owner.id, "gull")
    pinned = await prompts.authorize_selection([first.slug], requesting_user_id=stranger.id)
    await saved(prompts, owner.id, first, "crab")
    await prompts.set_owned_publication(owner.id, first.id, published=True)

    with pytest.raises(PromptListsChangedError):
        await prompts.sample_prompts(
            list(pinned.list_ids), limit=5, edition_ids=pinned.edition_ids
        )

    again = await prompts.authorize_selection([first.slug], requesting_user_id=stranger.id)
    sample = await prompts.sample_prompts(
        list(again.list_ids), limit=5, edition_ids=again.edition_ids
    )
    assert [prompt.answer for prompt in sample.prompts] == ["crab"]


async def test_a_copy_takes_the_live_edition_not_unpublished_changes(env):
    prompts, users, _ = env
    owner = await account(users, "Owner")
    reader = await account(users, "Reader")
    first = await published(prompts, owner.id, "gull")
    await saved(prompts, owner.id, first, "crab", name="Unpublished name")

    copy = await prompts.fork_published(reader.id, first.id)

    assert [entry.answer for entry in copy.prompts] == ["gull"]
    assert copy.name == "Seaside"


async def test_unpublishing_drops_a_pending_edition_and_keeps_the_live_one(env):
    prompts, users, factory = env
    owner = await account(users, "Owner")
    first = await published(prompts, owner.id, "gull")
    await saved(prompts, owner.id, first, "crab")
    held = await prompts.set_owned_publication(
        owner.id, first.id, published=True, under_review=True
    )
    assert held.live_edition.number == 1 and held.pending_edition.number == 2

    withdrawn = await prompts.set_owned_publication(owner.id, first.id, published=False)

    assert withdrawn.visibility == "private"
    assert withdrawn.pending_edition is None
    assert withdrawn.live_edition.number == 1
    assert await prompts.get_community(first.id) is None


async def test_a_word_only_the_live_edition_holds_is_kept_past_the_grace(env):
    """The unlisted sweep collects a wording nothing names. A live edition
    names the word a save took out of the working copy, so it stays - and
    stays reportable - for as long as readers can see it."""
    from app.services.prompt_reclaim import reclaim_unlisted_versions

    prompts, users, factory = env
    owner = await account(users, "Owner")
    first = await published(prompts, owner.id, "gull")
    gull = first.prompts[0].prompt_version_id
    await saved(prompts, owner.id, first, "crab")

    await reclaim_unlisted_versions(
        factory, now=datetime.now(timezone.utc) + timedelta(days=2)
    )

    async with factory() as session:
        kept = await session.get(PromptVersion, UUID(gull))
    assert kept is not None
    assert (kept.unlisted_at, kept.unlisted_from_list_id) == (None, None)


# --- #1386 review


async def test_deleting_a_published_list_takes_its_editions_at_once(env):
    """Left for the list's reclaim, an edition named its versions, so the
    unlisted sweep unstamped them and nothing stamped them again when the
    edition finally went: the text outlived the list."""
    from app.services.prompt_reclaim import (
        reclaim_retired_prompt_lists,
        reclaim_unlisted_versions,
    )

    prompts, users, factory = env
    owner = await account(users, "Owner")
    first = await published(prompts, owner.id, "gull")
    gull = UUID(first.prompts[0].prompt_version_id)
    assert await prompts.delete_owned(owner.id, first.id)
    assert await edition_count(factory, first.id) == 0
    later = datetime.now(timezone.utc) + timedelta(days=2)

    # The unlisted sweep first, as when the list's reclaim is deferred.
    await reclaim_unlisted_versions(factory, now=later)
    await reclaim_retired_prompt_lists(factory, now=later)

    async with factory() as session:
        assert await session.get(PromptVersion, gull) is None


async def test_erasure_leaves_no_edition_holding_the_authored_name(env):
    from app.services.prompt_reclaim import retire_owned_lists

    prompts, users, factory = env
    owner = await account(users, "Owner")
    await published(prompts, owner.id, "gull", name="Authored name")
    async with factory() as session:
        async with session.begin():
            await retire_owned_lists(session, [UUID(owner.id)], now=datetime.now(timezone.utc))

    async with factory() as session:
        assert (await session.scalars(select(PromptListEdition.name))).all() == []


async def test_republishing_a_withdrawn_list_under_review_shows_nothing_unreviewed(env):
    """The withdrawn live edition would be back the moment the list turned
    public, unreviewed, beside the edition waiting for a moderator."""
    prompts, users, _ = env
    owner = await account(users, "Owner")
    first = await published(prompts, owner.id, "gull")
    withdrawn = await prompts.set_owned_publication(owner.id, first.id, published=False)
    await saved(prompts, owner.id, withdrawn, "crab")

    held = await prompts.set_owned_publication(
        owner.id, first.id, published=True, under_review=True
    )

    assert held.live_edition is None and held.pending_edition is not None
    assert await prompts.get_community(first.id) is None


async def test_edits_made_while_an_edition_waits_are_unpublished_changes(env):
    prompts, users, _ = env
    owner = await account(users, "Owner")
    created = await prompts.create_owned(
        owner.id, name="Seaside", description="", language="en",
        prompts=(PromptListEntryInput(answer="gull"),),
    )
    held = await prompts.set_owned_publication(
        owner.id, created.id, published=True, under_review=True
    )
    assert not held.unpublished_changes

    edited = await saved(prompts, owner.id, held, "crab")

    assert edited.unpublished_changes

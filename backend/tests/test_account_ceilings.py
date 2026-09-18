"""Per-account ceilings hold under concurrency (#898).

Every one of these limits is count-then-insert: owned prompt lists on create,
fork and duplicate; a friends list, pending requests sent and received. Two
requests landing together at one below the cap both count "one below" and
both write, unless something serialises the pair. The owning account's row,
locked `FOR UPDATE` before the count, is that something.

Each test holds the first writer just after its count, long enough for the
second to reach the same point if nothing stops it. With the lock, the second
is still waiting for the row when the first commits, counts the cap, and is
refused; without it, both counts say "one below" and the cap is exceeded by
one. Row locks are only real on PostgreSQL; SQLite has one writer.
"""
from __future__ import annotations

import asyncio
import os
from uuid import UUID

import pytest
from sqlalchemy import func, select

import app.repositories.sqlalchemy as repository
from app.db.models import Friendship, PromptList
from app.domain_values import FriendshipState
from app.repositories.interfaces import PromptListEntryInput
from app.repositories.sqlalchemy import (
    MAX_OWNED_PROMPT_LISTS,
    PromptListMutationError,
    SqlAlchemyPromptListRepository,
    SqlAlchemyUserRepository,
)
from app.services.friends import (
    MAX_FRIENDS_PER_ACCOUNT,
    MAX_PENDING_SENT,
    FriendService,
    FriendshipRefused,
)

from tests.dbfixtures import create_test_db
from tests.test_friends import _fill, make_account

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="row locks are only real on PostgreSQL"
)

# How long the first writer waits after its count for the second to arrive.
# The second arrives within milliseconds unless the lock holds it back.
RENDEZVOUS_SECONDS = 1.0


def held_after(real):
    """Wrap a count so the first caller waits for a second one to count too."""
    arrived: list[int] = []
    second = asyncio.Event()

    async def paused(*args, **kwargs):
        result = await real(*args, **kwargs)
        arrived.append(1)
        if len(arrived) == 1:
            try:
                await asyncio.wait_for(second.wait(), RENDEZVOUS_SECONDS)
            except TimeoutError:
                pass
        else:
            second.set()
        return result

    return paused


async def settle(*calls):
    return await asyncio.gather(*calls, return_exceptions=True)


# --- prompt lists -----------------------------------------------------------


async def _owner_with(prompts, users, lists: int) -> str:
    guest = await users.create_anonymous("Owner")
    owner = await users.claim_account(guest.id, "Owner", "test-hash")
    for index in range(lists):
        await prompts.create_owned(
            owner.id,
            name=f"Mine {index}",
            description="",
            language="en",
            prompts=(PromptListEntryInput(answer=f"thing {index}"),),
        )
    return owner.id


async def _owned(factory, owner_id: str) -> int:
    async with factory() as session:
        return await session.scalar(
            select(func.count(PromptList.id)).where(
                PromptList.owner_user_id == UUID(owner_id), PromptList.deleted_at.is_(None)
            )
        )


def _create(prompts, owner_id: str, name: str):
    return prompts.create_owned(
        owner_id,
        name=name,
        description="",
        language="en",
        prompts=(PromptListEntryInput(answer=name.lower()),),
    )


async def test_two_creates_at_one_below_the_allowance_leave_exactly_the_allowance(monkeypatch):
    factory, engine = await create_test_db()
    try:
        users, prompts = SqlAlchemyUserRepository(factory), SqlAlchemyPromptListRepository(factory)
        owner = await _owner_with(prompts, users, MAX_OWNED_PROMPT_LISTS - 1)
        monkeypatch.setattr(repository, "_owned_list_count", held_after(repository._owned_list_count))

        results = await settle(_create(prompts, owner, "Left"), _create(prompts, owner, "Right"))

        assert sum(isinstance(result, PromptListMutationError) for result in results) == 1, results
        assert await _owned(factory, owner) == MAX_OWNED_PROMPT_LISTS
    finally:
        await engine.dispose()


async def test_two_forks_at_one_below_the_allowance_leave_exactly_the_allowance(monkeypatch):
    from tests.test_prompt_list_forking import a_published_list

    factory, engine = await create_test_db()
    try:
        users, prompts = SqlAlchemyUserRepository(factory), SqlAlchemyPromptListRepository(factory)
        author_guest = await users.create_anonymous("Author")
        author = await users.claim_account(author_guest.id, "Author", "test-hash")
        first = await a_published_list(prompts, factory, author.id, name="First")
        second = await a_published_list(prompts, factory, author.id, name="Second")
        forker = await _owner_with(prompts, users, MAX_OWNED_PROMPT_LISTS - 1)
        monkeypatch.setattr(repository, "_owned_list_count", held_after(repository._owned_list_count))

        results = await settle(
            prompts.fork_published(forker, first.id), prompts.fork_published(forker, second.id)
        )

        assert sum(isinstance(result, PromptListMutationError) for result in results) == 1, results
        assert await _owned(factory, forker) == MAX_OWNED_PROMPT_LISTS
    finally:
        await engine.dispose()


# --- friendships ------------------------------------------------------------


async def _count(factory, *, status: str, requested_by=None) -> int:
    async with factory() as session:
        statement = select(func.count()).select_from(Friendship).where(Friendship.status == status)
        if requested_by is not None:
            statement = statement.where(Friendship.requested_by_id == requested_by)
        return await session.scalar(statement)


async def test_two_requests_at_one_below_the_pending_cap_leave_exactly_the_cap(monkeypatch):
    factory, engine = await create_test_db()
    try:
        asker = await make_account(factory, "Asker")
        await _fill(factory, asker, MAX_PENDING_SENT - 1, FriendshipState.PENDING.value)
        left = await make_account(factory, "Left")
        right = await make_account(factory, "Right")
        friends = FriendService(factory)
        monkeypatch.setattr(
            friends, "_raise_if_too_many_pending", held_after(friends._raise_if_too_many_pending)
        )

        results = await settle(friends.request(asker, left), friends.request(asker, right))

        assert sum(isinstance(result, FriendshipRefused) for result in results) == 1, results
        assert await _count(factory, status="pending", requested_by=asker) == MAX_PENDING_SENT
    finally:
        await engine.dispose()


async def test_two_accepts_at_one_below_the_friends_cap_leave_exactly_the_cap(monkeypatch):
    factory, engine = await create_test_db()
    try:
        owner = await make_account(factory, "Owner")
        await _fill(factory, owner, MAX_FRIENDS_PER_ACCOUNT - 1, FriendshipState.ACCEPTED.value)
        friends = FriendService(factory)
        askers = [await make_account(factory, name) for name in ("Left", "Right")]
        for asker in askers:
            await friends.request(asker, owner)
        monkeypatch.setattr(
            friends, "_raise_if_either_list_is_full", held_after(friends._raise_if_either_list_is_full)
        )

        results = await settle(*(friends.accept(owner, asker) for asker in askers))

        assert sum(isinstance(result, FriendshipRefused) for result in results) == 1, results
        async with factory() as session:
            accepted = await session.scalar(
                select(func.count())
                .select_from(Friendship)
                .where(
                    Friendship.status == FriendshipState.ACCEPTED.value,
                    (Friendship.user_low_id == owner) | (Friendship.user_high_id == owner),
                )
            )
        assert accepted == MAX_FRIENDS_PER_ACCOUNT
    finally:
        await engine.dispose()

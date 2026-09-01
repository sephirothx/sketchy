"""Friendship rules: the crossing request, the decline, and the silences.

Most of what matters here is what a caller is *not* told. A request into a
block, a request to somebody who already refused, and a request to an id that
was never an account all answer the same way - because anything else makes
this endpoint a way to learn who blocked you, or which ids are real.
"""
from __future__ import annotations

import pytest

from app.db.models import Friendship, User, UserBlock, generate_uuid
from app.domain_values import AccountState, FriendshipState
from app.services.friends import (
    MAX_FRIENDS_PER_ACCOUNT,
    MAX_PENDING_SENT,
    FriendService,
    FriendshipOutcome,
    FriendshipRefused,
    friendship_key,
)
from tests.dbfixtures import create_test_db

pytestmark = pytest.mark.asyncio


async def make_account(factory, name, *, guest=False, deleted=False):
    user_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(
                User(
                    id=user_id,
                    display_name=name,
                    username=None if guest else name.lower(),
                    password_hash=None if guest else "hash",
                    state=(
                        AccountState.DELETED.value
                        if deleted
                        else AccountState.ANONYMOUS.value
                        if guest
                        else AccountState.REGISTERED.value
                    ),
                )
            )
    return user_id


async def row_for(factory, a, b):
    low, high = friendship_key(a, b)
    async with factory() as session:
        return await session.get(Friendship, (low, high))


async def block(factory, blocker, blocked):
    async with factory() as session:
        async with session.begin():
            session.add(UserBlock(blocker_user_id=blocker, blocked_user_id=blocked))


# --- the key --------------------------------------------------------------


async def test_the_key_is_the_same_pair_whichever_way_round_it_is_asked():
    a, b = generate_uuid(), generate_uuid()
    assert friendship_key(a, b) == friendship_key(b, a)
    low, high = friendship_key(a, b)
    assert low < high
    with pytest.raises(ValueError):
        friendship_key(a, a)


# --- requesting -----------------------------------------------------------


async def test_a_request_creates_one_pending_row():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")

        assert await service.request(ada, bob) == FriendshipOutcome.CREATED
        row = await row_for(factory, ada, bob)
        assert row.status == FriendshipState.PENDING.value
        assert row.requested_by_id == ada
        # Asking twice is not two requests, and not an error either.
        assert await service.request(ada, bob) == FriendshipOutcome.UNCHANGED
    finally:
        await engine.dispose()


async def test_a_crossing_request_is_how_you_say_yes():
    """The case #529's 'mutual?' question was really about.

    B asking A while A's request is still pending cannot create a second row -
    the canonical key forbids it - so the only sensible reading is agreement,
    and that is what it does.
    """
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")

        await service.request(ada, bob)
        assert await service.request(bob, ada) == FriendshipOutcome.ACCEPTED

        row = await row_for(factory, ada, bob)
        assert row.status == FriendshipState.ACCEPTED.value
        assert row.responded_at is not None
        assert await service.are_friends(ada, bob)
        assert await service.are_friends(bob, ada)
    finally:
        await engine.dispose()


async def test_a_request_to_a_guest_or_a_stranger_is_quietly_dropped():
    """Silent, so the endpoint cannot be used to find out which ids are real."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        guest = await make_account(factory, "Guesty", guest=True)
        gone = await make_account(factory, "Gone", deleted=True)

        assert await service.request(ada, guest) == FriendshipOutcome.IGNORED
        assert await service.request(ada, gone) == FriendshipOutcome.IGNORED
        assert await service.request(ada, generate_uuid()) == FriendshipOutcome.IGNORED
        assert await service.request(ada, ada) == FriendshipOutcome.IGNORED
        assert await row_for(factory, ada, guest) is None
    finally:
        await engine.dispose()


async def test_a_block_stops_a_request_without_saying_so():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        await block(factory, bob, ada)

        # Answered exactly as a delivered request is, in both directions: a
        # block must not be discoverable by trying to friend somebody.
        assert await service.request(ada, bob) == FriendshipOutcome.IGNORED
        assert await service.request(bob, ada) == FriendshipOutcome.IGNORED
        assert await row_for(factory, ada, bob) is None
    finally:
        await engine.dispose()


# --- declining ------------------------------------------------------------


async def test_a_decline_is_durable_and_cannot_be_re_sent_into():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")

        await service.request(ada, bob)
        assert await service.remove(bob, ada) == FriendshipOutcome.IGNORED
        row = await row_for(factory, ada, bob)
        assert row.status == FriendshipState.DECLINED.value

        # Ada asking again changes nothing, and is not told that it changed
        # nothing: "they said no" is not a message she is owed.
        assert await service.request(ada, bob) == FriendshipOutcome.IGNORED
        row = await row_for(factory, ada, bob)
        assert row.status == FriendshipState.DECLINED.value
    finally:
        await engine.dispose()


async def test_the_person_who_declined_may_still_ask_later():
    """Saying no is not a commitment."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")

        await service.request(ada, bob)
        await service.remove(bob, ada)

        assert await service.request(bob, ada) == FriendshipOutcome.CREATED
        row = await row_for(factory, ada, bob)
        assert row.status == FriendshipState.PENDING.value
        assert row.requested_by_id == bob
        assert row.responded_at is None
    finally:
        await engine.dispose()


async def test_cancelling_and_unfriending_delete_rather_than_refuse():
    """Neither is a refusal, so neither may suppress a future request."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")

        # Cancelling your own pending request.
        await service.request(ada, bob)
        await service.remove(ada, bob)
        assert await row_for(factory, ada, bob) is None

        # Unfriending after it was accepted.
        await service.request(ada, bob)
        await service.accept(bob, ada)
        assert await service.are_friends(ada, bob)
        await service.remove(ada, bob)
        assert await row_for(factory, ada, bob) is None
        assert not await service.are_friends(ada, bob)

        # And Bob can ask afresh, because nothing said no.
        assert await service.request(bob, ada) == FriendshipOutcome.CREATED
    finally:
        await engine.dispose()


async def test_removing_somebody_elses_refusal_is_not_this_callers_to_do():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        await service.request(ada, bob)
        await service.remove(bob, ada)

        assert await service.remove(ada, bob) == FriendshipOutcome.UNCHANGED
        row = await row_for(factory, ada, bob)
        assert row is not None and row.status == FriendshipState.DECLINED.value
    finally:
        await engine.dispose()


# --- accepting ------------------------------------------------------------


async def test_you_cannot_accept_your_own_request():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        await service.request(ada, bob)

        assert await service.accept(ada, bob) == FriendshipOutcome.UNCHANGED
        assert not await service.are_friends(ada, bob)
    finally:
        await engine.dispose()


async def test_a_block_placed_after_the_request_still_wins():
    """Or it is a block that did not hold."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        await service.request(ada, bob)
        await block(factory, bob, ada)

        assert await service.accept(bob, ada) == FriendshipOutcome.IGNORED
        assert not await service.are_friends(ada, bob)
        row = await row_for(factory, ada, bob)
        assert row.status == FriendshipState.DECLINED.value
    finally:
        await engine.dispose()


async def test_blocking_removes_an_existing_friendship_in_the_same_transaction():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        await service.request(ada, bob)
        await service.accept(bob, ada)

        async with factory() as session:
            async with session.begin():
                session.add(UserBlock(blocker_user_id=bob, blocked_user_id=ada))
                await service.forget_pair(session, bob, ada)

        assert await row_for(factory, ada, bob) is None
        assert not await service.are_friends(ada, bob)
    finally:
        await engine.dispose()


# --- ceilings -------------------------------------------------------------


async def _fill(factory, owner, count, status):
    async with factory() as session:
        async with session.begin():
            for index in range(count):
                other = generate_uuid()
                session.add(
                    User(
                        id=other,
                        display_name=f"Other{index}",
                        username=f"other{index}",
                        password_hash="hash",
                        state=AccountState.REGISTERED.value,
                    )
                )
                low, high = friendship_key(owner, other)
                session.add(
                    Friendship(
                        user_low_id=low,
                        user_high_id=high,
                        requested_by_id=owner,
                        status=status,
                    )
                )


async def test_a_full_friends_list_refuses_with_something_to_do_about_it():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        await _fill(
            factory, ada, MAX_FRIENDS_PER_ACCOUNT, FriendshipState.ACCEPTED.value
        )

        newcomer = await make_account(factory, "Newcomer")
        with pytest.raises(FriendshipRefused, match="full"):
            await service.request(ada, newcomer)
    finally:
        await engine.dispose()


async def test_too_many_unanswered_requests_stops_a_sweep_of_the_online_list():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        await _fill(factory, ada, MAX_PENDING_SENT, FriendshipState.PENDING.value)

        newcomer = await make_account(factory, "Newcomer")
        with pytest.raises(FriendshipRefused, match="waiting for an"):
            await service.request(ada, newcomer)
    finally:
        await engine.dispose()


# --- listing --------------------------------------------------------------


async def test_the_listing_separates_friends_from_each_direction_of_request():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        friend = await make_account(factory, "Friend")
        asked = await make_account(factory, "Asked")
        asker = await make_account(factory, "Asker")
        refused = await make_account(factory, "Refused")

        await service.request(ada, friend)
        await service.accept(friend, ada)
        await service.request(ada, asked)
        await service.request(asker, ada)
        await service.request(refused, ada)
        await service.remove(ada, refused)

        listing = await service.listing(ada)
        assert [u.display_name for _, u in listing["friends"]] == ["Friend"]
        assert [u.display_name for _, u in listing["outgoing"]] == ["Asked"]
        assert [u.display_name for _, u in listing["incoming"]] == ["Asker"]
        # A refusal is not something either side has to keep looking at.
        names = {u.display_name for rows in listing.values() for _, u in rows}
        assert "Refused" not in names

        assert await service.accepted_ids(ada) == {friend}
    finally:
        await engine.dispose()

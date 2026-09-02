"""Friendship rules: the crossing request, the decline, and the silences.

Most of what matters here is what a caller is *not* told. A request into a
block, a request to somebody who already refused, and a request to an id that
was never an account all answer the same way - because anything else makes
this endpoint a way to learn who blocked you, or which ids are real.
"""
from __future__ import annotations

import pytest

from sqlalchemy.exc import IntegrityError

from app.db.models import Friendship, User, UserBlock, generate_uuid
from app.domain_values import AccountState, FriendshipState
from app.services.friends import (
    MAX_FRIENDS_PER_ACCOUNT,
    MAX_PENDING_RECEIVED,
    MAX_PENDING_SENT,
    FriendService,
    FriendshipOutcome,
    FriendshipRefused,
    FriendshipThrottled,
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
    """Or it is a block that did not hold.

    Reached only by inserting the block behind the router, which deletes the
    friendship as it writes one - so an accept after a real block finds no row
    at all. The branch is kept for the second way to block somebody will add,
    which is why its announcement is pinned here too.
    """
    factory, engine = await create_test_db()
    told: list[str] = []

    async def announce(user_id: str) -> None:
        told.append(user_id)

    try:
        service = FriendService(factory, announce=announce)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        await service.request(ada, bob)
        await block(factory, bob, ada)
        told.clear()

        assert await service.accept(bob, ada) == FriendshipOutcome.IGNORED
        assert not await service.are_friends(ada, bob)
        row = await row_for(factory, ada, bob)
        assert row.status == FriendshipState.DECLINED.value
        # The row moved, so both lists did. What Ada sees is her outgoing
        # request going away, which is what an ordinary decline looks like -
        # so this says nothing a decline does not say already.
        assert sorted(told) == sorted([str(ada), str(bob)])
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


# --- the identity merge ---------------------------------------------------


async def _add_row(factory, a, b, requested_by, status):
    low, high = friendship_key(a, b)
    async with factory() as session:
        async with session.begin():
            session.add(
                Friendship(
                    user_low_id=low,
                    user_high_id=high,
                    requested_by_id=requested_by,
                    status=status,
                )
            )


async def _merge(factory, source, target):
    from app.repositories.sqlalchemy import SqlAlchemyUserRepository

    await SqlAlchemyUserRepository(factory).merge_guest_into_account(
        str(source), str(target)
    )


async def test_a_merge_moves_a_friendship_onto_the_account():
    """Registered-only makes this unreachable today; the merge is written anyway.

    The rule is a product decision that could be revisited, and this merge is
    genuinely harder than the block merge beside it: the pair is *ordered*, so
    a remap can move an id from one column to the other and the row has to be
    rebuilt rather than reassigned.
    """
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        guest = await make_account(factory, "Guesty", guest=True)
        account = await make_account(factory, "Ada")
        friend = await make_account(factory, "Friend")
        await _add_row(
            factory, guest, friend, guest, FriendshipState.ACCEPTED.value
        )

        await _merge(factory, guest, account)

        assert await service.are_friends(account, friend)
        assert await row_for(factory, guest, friend) is None
        row = await row_for(factory, account, friend)
        # The requester moved too, or the members CHECK would have fired.
        assert row.requested_by_id == account
    finally:
        await engine.dispose()


async def test_a_merge_does_not_make_somebody_their_own_friend():
    factory, engine = await create_test_db()
    try:
        guest = await make_account(factory, "Guesty", guest=True)
        account = await make_account(factory, "Ada")
        await _add_row(
            factory, guest, account, guest, FriendshipState.ACCEPTED.value
        )

        await _merge(factory, guest, account)

        assert await row_for(factory, guest, account) is None
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "guest_status,account_status,expected",
    [
        (FriendshipState.ACCEPTED.value, FriendshipState.PENDING.value, "accepted"),
        (FriendshipState.PENDING.value, FriendshipState.ACCEPTED.value, "accepted"),
        (FriendshipState.DECLINED.value, FriendshipState.ACCEPTED.value, "accepted"),
        (FriendshipState.ACCEPTED.value, FriendshipState.DECLINED.value, "accepted"),
    ],
)
async def test_a_merge_keeps_the_stronger_of_two_statuses(
    guest_status, account_status, expected
):
    """An accepted friendship is a decision both people made.

    A merge is not a reason to quietly undo it, whichever of the two identities
    happened to hold it.
    """
    factory, engine = await create_test_db()
    try:
        guest = await make_account(factory, "Guesty", guest=True)
        account = await make_account(factory, "Ada")
        friend = await make_account(factory, "Friend")
        await _add_row(factory, guest, friend, guest, guest_status)
        await _add_row(factory, account, friend, account, account_status)

        await _merge(factory, guest, account)

        row = await row_for(factory, account, friend)
        assert row is not None and row.status == expected
        assert await row_for(factory, guest, friend) is None
    finally:
        await engine.dispose()


async def test_a_merge_collapses_two_crossing_requests_into_a_friendship():
    """Or the account is left holding two pendings that can never resolve."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        guest = await make_account(factory, "Guesty", guest=True)
        account = await make_account(factory, "Ada")
        friend = await make_account(factory, "Friend")
        # The guest asked them; they asked the account.
        await _add_row(factory, guest, friend, guest, FriendshipState.PENDING.value)
        await _add_row(
            factory, account, friend, friend, FriendshipState.PENDING.value
        )

        await _merge(factory, guest, account)

        assert await service.are_friends(account, friend)
    finally:
        await engine.dispose()


# --- races ----------------------------------------------------------------


async def test_a_request_that_loses_the_insert_race_reads_again():
    """Two people asking each other at once both find no row and both write one.

    The pair is the primary key, so the database refuses the second. Re-reading
    is all it takes: the row that won is the pending request this call should
    have been answering, which is the crossing-request case.

    Driven by raising the collision rather than by racing two coroutines - the
    in-memory fixture serves both sessions from one connection, so a real
    conflict there rolls back the winner too and models nothing that happens
    on PostgreSQL.
    """
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        # Bob's request is the one that won the insert.
        await service.request(bob, ada)

        attempts = []
        real = service._request_once

        async def once(requester_id, target_id):
            attempts.append(1)
            if len(attempts) == 1:
                raise IntegrityError("INSERT", {}, Exception("duplicate key"))
            return await real(requester_id, target_id)

        service._request_once = once
        outcome = await service.request(ada, bob)

        assert len(attempts) == 2, "the collision was not retried"
        assert outcome == FriendshipOutcome.ACCEPTED
        assert await service.are_friends(ada, bob)
    finally:
        await engine.dispose()


async def test_a_collision_that_keeps_happening_is_not_swallowed():
    """One retry, not a loop: a conflict that survives it is a real fault."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")

        async def always(requester_id, target_id):
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        service._request_once = always
        with pytest.raises(IntegrityError):
            await service.request(ada, bob)
    finally:
        await engine.dispose()


async def test_removing_says_whether_anything_actually_went():
    """So a caller can tell a real removal from a no-op it should stay quiet about."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")

        # Nothing there at all.
        assert await service.remove(ada, bob) == FriendshipOutcome.UNCHANGED

        # Cancelling your own request, and ending a friendship.
        await service.request(ada, bob)
        assert await service.remove(ada, bob) == FriendshipOutcome.REMOVED
        await service.request(ada, bob)
        await service.accept(bob, ada)
        assert await service.remove(bob, ada) == FriendshipOutcome.REMOVED

        # Declining leaves the refusal behind, which is its own answer.
        await service.request(ada, bob)
        assert await service.remove(bob, ada) == FriendshipOutcome.IGNORED
    finally:
        await engine.dispose()


async def test_forgetting_a_pair_reports_whether_it_revoked_anything():
    """A block of a stranger must not be a way to ask whether they were a friend."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        stranger = await make_account(factory, "Stranger")
        await service.request(ada, bob)
        await service.accept(bob, ada)

        # Who to tell, which is nobody when nothing was revoked.
        async with factory() as session:
            async with session.begin():
                told = await service.forget_pair(session, ada, bob)
        assert sorted(told) == sorted([str(ada), str(bob)])
        async with factory() as session:
            async with session.begin():
                assert await service.forget_pair(session, ada, stranger) == ()
    finally:
        await engine.dispose()


async def test_re_asking_along_a_refusal_is_still_a_request():
    """Somebody who has declined a lot of people has a row per refusal.

    Each one can be rewritten into a request they sent, so if the rewrite
    skipped the ceilings it would be an uncounted way to send as many as they
    have refused.
    """
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        decliner = await make_account(factory, "Decliner")

        # Fill the outgoing allowance with ordinary pending requests.
        await _fill(factory, decliner, MAX_PENDING_SENT, FriendshipState.PENDING.value)

        # And hold one refusal: somebody asked, and was told no.
        asker = await make_account(factory, "Asker")
        await service.request(asker, decliner)
        await service.remove(decliner, asker)
        assert (await row_for(factory, asker, decliner)).status == (
            FriendshipState.DECLINED.value
        )

        with pytest.raises(FriendshipRefused, match="waiting for an"):
            await service.request(decliner, asker)

        # And the refusal is left as it was, rather than half-rewritten.
        assert (await row_for(factory, asker, decliner)).status == (
            FriendshipState.DECLINED.value
        )
    finally:
        await engine.dispose()


async def test_re_asking_along_a_refusal_respects_a_full_friends_list():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        decliner = await make_account(factory, "Decliner")
        asker = await make_account(factory, "Asker")
        await service.request(asker, decliner)
        await service.remove(decliner, asker)
        await _fill(
            factory, decliner, MAX_FRIENDS_PER_ACCOUNT, FriendshipState.ACCEPTED.value
        )

        with pytest.raises(FriendshipRefused, match="full"):
            await service.request(decliner, asker)
    finally:
        await engine.dispose()


# --- the hourly ceiling ---------------------------------------------------


class CountingLimiter:
    """Stands in for the persistent bucket, so both entry points can be checked."""

    def __init__(self, limit: int):
        self.limit = limit
        self.spent: dict[str, int] = {}

    async def check(self, key: str) -> bool:
        if self.spent.get(key, 0) >= self.limit:
            return False
        self.spent[key] = self.spent.get(key, 0) + 1
        return True

    async def refund(self, key: str) -> None:
        self.spent[key] = max(0, self.spent.get(key, 0) - 1)


async def test_the_hourly_ceiling_lives_with_the_service_not_a_router():
    """So every way of sending a request answers to it.

    It used to be the REST router's, which left the in-room command with only
    the generic per-socket command budget - a documented hourly ceiling that
    one of the two entry points did not have.
    """
    factory, engine = await create_test_db()
    try:
        limiter = CountingLimiter(2)
        service = FriendService(factory, request_limiter=limiter)
        ada = await make_account(factory, "Ada")
        others = [await make_account(factory, f"Other{i}") for i in range(3)]

        assert await service.request(ada, others[0]) == FriendshipOutcome.CREATED
        assert await service.request(ada, others[1]) == FriendshipOutcome.CREATED
        with pytest.raises(FriendshipThrottled):
            await service.request(ada, others[2])
        assert await row_for(factory, ada, others[2]) is None
    finally:
        await engine.dispose()


async def test_a_request_that_wrote_nothing_is_given_back():
    """R-RATE-05's rule, and now it applies to both entry points at once."""
    factory, engine = await create_test_db()
    try:
        limiter = CountingLimiter(2)
        service = FriendService(factory, request_limiter=limiter)
        ada = await make_account(factory, "Ada")
        guest = await make_account(factory, "Guesty", guest=True)
        bob = await make_account(factory, "Bob")

        # A request that goes nowhere, several times over.
        for _ in range(5):
            assert await service.request(ada, guest) == FriendshipOutcome.IGNORED
        assert limiter.spent[str(ada)] == 0

        # Asking the same person twice spends one, not two.
        await service.request(ada, bob)
        await service.request(ada, bob)
        assert limiter.spent[str(ada)] == 1
    finally:
        await engine.dispose()


async def test_a_refused_ceiling_gives_the_allowance_back_too():
    factory, engine = await create_test_db()
    try:
        limiter = CountingLimiter(10)
        service = FriendService(factory, request_limiter=limiter)
        ada = await make_account(factory, "Ada")
        await _fill(factory, ada, MAX_PENDING_SENT, FriendshipState.PENDING.value)
        newcomer = await make_account(factory, "Newcomer")

        with pytest.raises(FriendshipRefused):
            await service.request(ada, newcomer)
        assert limiter.spent[str(ada)] == 0
    finally:
        await engine.dispose()


# --- one place decides who is told ----------------------------------------


async def test_every_write_announces_itself_and_no_no_op_does():
    """The contract the routers and handlers now rely on rather than repeat.

    Six rounds of review found the same shape of bug: one entry point telling
    the other account their lists had moved, and another not. It is decided
    here now, beside the write, so a third way in cannot be given a weaker
    rule than the first two.
    """
    factory, engine = await create_test_db()
    told: list[str] = []

    async def announce(user_id: str) -> None:
        told.append(user_id)

    try:
        service = FriendService(factory, announce=announce)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        guest = await make_account(factory, "Guesty", guest=True)

        # Everyone whose list moved, which always includes the account that
        # did it: the event is delivered per account, and a player with a
        # second lobby open has no other way to hear about their own write.
        await service.request(ada, bob)
        assert sorted(told) == sorted([str(ada), str(bob)])

        told.clear()
        await service.accept(bob, ada)
        assert str(ada) in told, "the person who asked was not told"
        assert str(bob) in told, "the account that accepted was not told"

        told.clear()
        await service.remove(ada, bob)
        assert sorted(told) == sorted([str(ada), str(bob)]), "unfriending said nothing"

        # A refusal is a change to the asker's list too.
        told.clear()
        await service.request(bob, ada)
        told.clear()
        await service.remove(ada, bob)
        assert sorted(told) == sorted([str(ada), str(bob)])

        # And nothing that wrote nothing says anything - to anybody, the
        # caller included. A request quietly dropped must not become
        # detectable by the asker's own other tabs waking up.
        told.clear()
        await service.request(ada, guest)
        await service.remove(ada, guest)
        await service.accept(ada, guest)
        assert told == []
    finally:
        await engine.dispose()


async def test_one_unreachable_recipient_does_not_silence_the_rest():
    """Best effort has to be per recipient, or it is best effort for the first.

    Deleting an account tells everybody who lost a row, which is the batch
    where this shows. The deletion route used to loop with its own `try` per
    id; collapsing that into one call took the isolation with it until this
    put it back where the announcement lives.
    """
    factory, engine = await create_test_db()
    told: list[str] = []

    async def announce(user_id: str) -> None:
        told.append(user_id)
        if len(told) == 1:
            raise RuntimeError("that socket has gone")

    try:
        service = FriendService(factory, announce=announce)
        await service.announce_to(["one", "two", "three"])
        assert told == ["one", "two", "three"]
    finally:
        await engine.dispose()


async def test_a_write_stands_even_when_nobody_can_be_told():
    """The row is committed by the time any of this runs.

    A notification that cannot be delivered is not a reason to report the
    write as failed - which is what an exception escaping here would do, with
    the friendship already in the database.
    """
    factory, engine = await create_test_db()

    async def announce(user_id: str) -> None:
        raise RuntimeError("the channel is gone")

    try:
        service = FriendService(factory, announce=announce)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")

        assert await service.request(ada, bob) == FriendshipOutcome.CREATED
        assert await service.accept(bob, ada) == FriendshipOutcome.ACCEPTED
        assert await service.are_friends(ada, bob)
        assert await service.remove(ada, bob) == FriendshipOutcome.REMOVED
    finally:
        await engine.dispose()


# --- the refusals nothing else reaches ------------------------------------


async def test_announcing_skips_an_empty_id_rather_than_emitting_one():
    factory, engine = await create_test_db()
    told: list[str] = []

    async def announce(user_id: str) -> None:
        told.append(user_id)

    try:
        service = FriendService(factory, announce=announce)
        await service.announce_to(["real", "", None])
        assert told == ["real"]
        # And a service with nowhere to announce is not an error.
        await FriendService(factory).announce_to(["real"])
    finally:
        await engine.dispose()


async def test_are_friends_answers_no_for_a_question_that_is_not_one():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        assert await service.are_friends(None, ada) is False
        assert await service.are_friends(ada, None) is False
        assert await service.are_friends(ada, ada) is False
    finally:
        await engine.dispose()


async def test_the_pair_block_check_is_answerable_on_its_own():
    """The join and invite paths ask it without a transaction of their own."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        assert await service.is_blocked_pair(ada, bob) is False
        await block(factory, bob, ada)
        assert await service.is_blocked_pair(ada, bob) is True
    finally:
        await engine.dispose()


async def test_a_request_to_somebody_whose_list_is_full_says_so_without_numbers():
    """How full somebody else's list is, is their fact rather than the caller's."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        popular = await make_account(factory, "Popular")
        await _fill(
            factory, popular, MAX_FRIENDS_PER_ACCOUNT, FriendshipState.ACCEPTED.value
        )
        # Their request is waiting, so Ada asking back is an acceptance - which
        # is where the other person's ceiling is read. Written directly: they
        # could not have sent it through `request`, because their own list
        # being full is refused first, and that is a different refusal.
        await _add_row(factory, popular, ada, popular, FriendshipState.PENDING.value)

        with pytest.raises(FriendshipRefused) as refused:
            await service.request(ada, popular)
        assert str(MAX_FRIENDS_PER_ACCOUNT) not in str(refused.value)
    finally:
        await engine.dispose()


async def test_a_crowded_inbox_is_refused_without_describing_it():
    """Naming the recipient's inbox would disclose a third party's state."""
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        popular = await make_account(factory, "Popular")
        # Requests *to* them, from many different accounts.
        async with factory() as session:
            async with session.begin():
                for index in range(MAX_PENDING_RECEIVED):
                    other = generate_uuid()
                    session.add(
                        User(
                            id=other,
                            display_name=f"Asker{index}",
                            username=f"asker{index}",
                            password_hash="hash",
                            state=AccountState.REGISTERED.value,
                        )
                    )
                    low, high = friendship_key(popular, other)
                    session.add(
                        Friendship(
                            user_low_id=low,
                            user_high_id=high,
                            requested_by_id=other,
                            status=FriendshipState.PENDING.value,
                        )
                    )

        with pytest.raises(FriendshipRefused, match="could not be sent"):
            await service.request(ada, popular)
    finally:
        await engine.dispose()


async def test_asking_somebody_you_are_already_friends_with_changes_nothing():
    factory, engine = await create_test_db()
    try:
        service = FriendService(factory)
        ada = await make_account(factory, "Ada")
        bob = await make_account(factory, "Bob")
        await service.request(ada, bob)
        await service.accept(bob, ada)

        assert await service.request(ada, bob) == FriendshipOutcome.UNCHANGED
        assert await service.request(bob, ada) == FriendshipOutcome.UNCHANGED
    finally:
        await engine.dispose()

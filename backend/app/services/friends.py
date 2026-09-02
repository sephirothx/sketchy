"""Friendships: one row per pair, and the rules for getting one.

The table stores a pair in a canonical order (see `Friendship`), so every read
and write has to agree on which of two accounts is `low`. That decision lives
here, in `friendship_key`, and nowhere else - a site that inlines it and gets
it wrong writes a row the CHECK rejects, which is the failure worth having.

The interesting rules are not the storage, though. They are what a request
does when there is already a row, and what it refuses to tell the caller:

* **A crossing request is an acceptance.** If they asked first, asking back is
  how you say yes. The canonical key means the second request cannot create a
  second row, so this falls out of the schema rather than out of a query
  somebody remembered to write.
* **A block is not a probe.** A request into a block answers exactly what a
  delivered one answers. So does a request to somebody who declined, and one
  to an account that does not exist. Anything else turns this endpoint into a
  way to learn who has blocked you, or which ids are real.
* **A decline is durable, and asymmetric.** The row stays as `declined` so the
  sender cannot simply ask again for ever; "you are doing that too quickly" is
  the wrong sentence for "this person said no". But the person who declined may
  still ask in their own right later, which rewrites the row - saying no is not
  a commitment. Unfriending, by contrast, deletes: it is not a refusal, and
  must not suppress a future request.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import logging
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Friendship, IdentityAlias, User, UserBlock
from app.domain_values import AccountState, FriendshipState

logger = logging.getLogger("sketchy.friends")

# Ceilings, in the style the room ones are written in: configurable defaults
# with a refusal that says which one was reached and what to do about it.
MAX_FRIENDS_PER_ACCOUNT = 200
# Enough that nobody honest meets it; low enough that a scripted sweep of the
# online list does.
MAX_PENDING_SENT = 50
# Deliberately high, and its refusal deliberately vague - see `request`.
MAX_PENDING_RECEIVED = 200


class FriendshipOutcome(StrEnum):
    """What a request or a response actually did."""

    CREATED = "created"
    ACCEPTED = "accepted"
    #: A row was deleted - a request cancelled, or a friendship ended.
    REMOVED = "removed"
    #: Nothing to do - already friends, or already asked.
    UNCHANGED = "unchanged"
    #: Deliberately nothing, and deliberately not said out loud.
    IGNORED = "ignored"


class FriendshipRefused(Exception):
    """A ceiling was reached. The message is for the person who hit it."""


class FriendshipThrottled(FriendshipRefused):
    """Too many requests in too short a time, rather than too many at once."""


def friendship_key(a: UUID, b: UUID) -> tuple[UUID, UUID]:
    """The pair in the order the table stores it.

    The single place the canonical ordering is decided. `Friendship` has a
    CHECK that says the same thing, so a caller that builds a pair by hand and
    gets it backwards is rejected by the database rather than quietly writing
    the same relationship twice.
    """
    if a == b:
        raise ValueError("a friendship needs two different accounts")
    return (a, b) if a < b else (b, a)


def other_of(row: Friendship, user_id: UUID) -> UUID:
    """The half of the pair that is not this account."""
    return row.user_high_id if row.user_low_id == user_id else row.user_low_id


async def resolve_account(session: AsyncSession, user_id: UUID) -> User | None:
    """The account behind an id, following a merge and refusing a tombstone."""
    user = await session.get(User, user_id)
    if user is not None and user.state == AccountState.MERGED.value:
        canonical = await session.scalar(
            select(IdentityAlias.target_user_id).where(
                IdentityAlias.source_user_id == user.id
            )
        )
        user = await session.get(User, canonical) if canonical else None
    if user is None or user.state == AccountState.DELETED.value:
        return None
    return user


async def pair_is_blocked(session: AsyncSession, a: UUID, b: UUID) -> bool:
    """Whether either of these two has blocked the other.

    Uncached on purpose. `BlockService` answers a different question - who has
    muted this sender - on the chat path, where a query per line would be felt;
    this runs when somebody presses a button. Caching it would mean one more
    thing to invalidate for no gain, so if you are here to add an LRU: don't.

    A block is directional (R-BLOCK-01) but its effect on a friendship is
    symmetric. A one-way block leaving a one-way friendship is nonsense in a
    model where a friendship is mutual.
    """
    found = await session.scalar(
        select(UserBlock.blocker_user_id)
        .where(
            or_(
                (UserBlock.blocker_user_id == a) & (UserBlock.blocked_user_id == b),
                (UserBlock.blocker_user_id == b) & (UserBlock.blocked_user_id == a),
            )
        )
        .limit(1)
    )
    return found is not None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FriendService:
    """Reads and writes friendships, and the rules around them.

    Takes an `async_sessionmaker` rather than a repository, the way the other
    inherently relational services do: every operation here is a small number
    of statements against two tables, and the interesting part is which
    statement, not which entity.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        request_limiter=None,
    ) -> None:
        self._session_factory = session_factory
        # Held here rather than by a router, so every way of sending a request
        # answers to it. It used to live in the REST router alone, which meant
        # the in-room command had only the generic per-socket command budget -
        # a documented hourly ceiling that one of the two entry points did not
        # have. A rule that lives beside one caller is a rule the next caller
        # does not get.
        self._request_limiter = request_limiter

    # --- reads ------------------------------------------------------------

    async def get(self, a: UUID, b: UUID) -> Friendship | None:
        low, high = friendship_key(a, b)
        async with self._session_factory() as session:
            return await session.get(Friendship, (low, high))

    async def are_friends(self, a: UUID | None, b: UUID | None) -> bool:
        """Whether these two have an accepted friendship. One key lookup."""
        if not a or not b or a == b:
            return False
        row = await self.get(a, b)
        return row is not None and row.status == FriendshipState.ACCEPTED.value

    async def is_blocked_pair(self, a: UUID, b: UUID) -> bool:
        async with self._session_factory() as session:
            return await pair_is_blocked(session, a, b)

    async def accepted_ids(self, user_id: UUID) -> set[UUID]:
        """Every account this one is friends with.

        Bounded by `MAX_FRIENDS_PER_ACCOUNT`, which is what makes it safe to
        ask for on the lobby's presence path.
        """
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(Friendship).where(
                        Friendship.status == FriendshipState.ACCEPTED.value,
                        or_(
                            Friendship.user_low_id == user_id,
                            Friendship.user_high_id == user_id,
                        ),
                    )
                )
            ).all()
        return {other_of(row, user_id) for row in rows}

    async def listing(self, user_id: UUID) -> dict[str, list[tuple[Friendship, User]]]:
        """This account's friends, and the requests waiting at either end."""
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Friendship).where(
                        Friendship.status != FriendshipState.DECLINED.value,
                        or_(
                            Friendship.user_low_id == user_id,
                            Friendship.user_high_id == user_id,
                        ),
                    )
                )
            ).scalars().all()
            others = {other_of(row, user_id) for row in rows}
            people = {
                user.id: user
                for user in (
                    await session.scalars(select(User).where(User.id.in_(others)))
                ).all()
            } if others else {}

        friends: list[tuple[Friendship, User]] = []
        incoming: list[tuple[Friendship, User]] = []
        outgoing: list[tuple[Friendship, User]] = []
        for row in rows:
            person = people.get(other_of(row, user_id))
            if person is None:
                continue
            if row.status == FriendshipState.ACCEPTED.value:
                friends.append((row, person))
            elif row.requested_by_id == user_id:
                outgoing.append((row, person))
            else:
                incoming.append((row, person))
        return {"friends": friends, "incoming": incoming, "outgoing": outgoing}

    # --- writes -----------------------------------------------------------

    async def request(self, requester_id: UUID, target_id: UUID) -> FriendshipOutcome:
        """Ask to be friends, or answer a request that was already waiting.

        Retried once on a primary-key collision. Two people asking each other
        at the same moment both find no row and both insert one; the pair is
        the key, so the loser is rejected by the database rather than writing a
        second row. Re-reading is all it takes - the row that won is now the
        `pending` request this call should have been answering, which is the
        crossing-request case, and the second attempt handles it. The block
        router retries the same way for the same reason.
        """
        if self._request_limiter is not None and not await self._request_limiter.check(
            str(requester_id)
        ):
            raise FriendshipThrottled(
                "You have sent a lot of friend requests recently. "
                "Try again later."
            )
        try:
            try:
                outcome = await self._request_once(requester_id, target_id)
            except IntegrityError:
                outcome = await self._request_once(requester_id, target_id)
        except FriendshipRefused:
            await self._refund_request(requester_id)
            raise
        if outcome in (FriendshipOutcome.IGNORED, FriendshipOutcome.UNCHANGED):
            # Nothing was written, so nothing was spent (R-RATE-05's rule).
            await self._refund_request(requester_id)
        return outcome

    async def _refund_request(self, requester_id: UUID) -> None:
        if self._request_limiter is not None:
            await self._request_limiter.refund(str(requester_id))

    async def _request_once(
        self, requester_id: UUID, target_id: UUID
    ) -> FriendshipOutcome:
        """One attempt at `request`. See there for what any of this means.

        Answers the same way whether the request landed or was quietly dropped.
        A caller cannot tell a block from a decline from an id that was never
        an account, which is the point: the alternative is an endpoint that
        reports who has blocked you and which ids are real.

        `FriendshipRefused` is the exception, and only for a ceiling the caller
        themselves hit - their own list being full is their own fact, and one
        they can act on.
        """
        if requester_id == target_id:
            return FriendshipOutcome.IGNORED
        low, high = friendship_key(requester_id, target_id)
        async with self._session_factory() as session:
            async with session.begin():
                target = await resolve_account(session, target_id)
                # A guest has no durable identity to be friends with: the row
                # would outlive the account, which is purged after a month of
                # not playing. Silent rather than explanatory, for the same
                # reason a block is.
                if target is None or target.is_anonymous:
                    return FriendshipOutcome.IGNORED
                if target.id != target_id:
                    # The id named an alias; re-key onto the account it became.
                    low, high = friendship_key(requester_id, target.id)
                if await pair_is_blocked(session, requester_id, target.id):
                    return FriendshipOutcome.IGNORED

                row = await session.get(Friendship, (low, high))
                if row is not None:
                    if row.status == FriendshipState.ACCEPTED.value:
                        return FriendshipOutcome.UNCHANGED
                    if row.status == FriendshipState.PENDING.value:
                        if row.requested_by_id == requester_id:
                            return FriendshipOutcome.UNCHANGED
                        # They asked first, so asking back is how you say yes.
                        await self._raise_if_either_list_is_full(
                            session, requester_id, target.id
                        )
                        row.status = FriendshipState.ACCEPTED.value
                        row.responded_at = _now()
                        return FriendshipOutcome.ACCEPTED
                    # Declined. If this caller is the one who was refused, the
                    # refusal stands and they are told nothing. If they are the
                    # one who refused, they may ask in their own right.
                    if row.requested_by_id == requester_id:
                        return FriendshipOutcome.IGNORED
                    # Held to the same ceilings as a request that writes a new
                    # row. Rewriting a refusal is still sending a request, and
                    # somebody who has declined a lot of people would otherwise
                    # have a row per refusal to send an uncounted one along.
                    await self._raise_if_full(session, requester_id)
                    await self._raise_if_too_many_pending(
                        session, requester_id, target.id
                    )
                    row.status = FriendshipState.PENDING.value
                    row.requested_by_id = requester_id
                    row.responded_at = None
                    return FriendshipOutcome.CREATED

                await self._raise_if_full(session, requester_id)
                await self._raise_if_too_many_pending(session, requester_id, target.id)
                # Same two checks as the declined-row rewrite above: every path
                # that leaves a pending request behind answers to them.
                session.add(
                    Friendship(
                        user_low_id=low,
                        user_high_id=high,
                        requested_by_id=requester_id,
                        status=FriendshipState.PENDING.value,
                    )
                )
                return FriendshipOutcome.CREATED

    async def accept(self, user_id: UUID, other_id: UUID) -> FriendshipOutcome:
        """Answer a request that is waiting on this account."""
        low, high = friendship_key(user_id, other_id)
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(Friendship, (low, high))
                if row is None or row.status != FriendshipState.PENDING.value:
                    return FriendshipOutcome.UNCHANGED
                if row.requested_by_id == user_id:
                    # Their own outgoing request. Accepting it yourself would
                    # be a friendship one party never agreed to.
                    return FriendshipOutcome.UNCHANGED
                # Re-checked here, not just at the request: a block placed in
                # between has to win, or it is a block that did not hold.
                if await pair_is_blocked(session, user_id, other_id):
                    row.status = FriendshipState.DECLINED.value
                    row.responded_at = _now()
                    return FriendshipOutcome.IGNORED
                await self._raise_if_either_list_is_full(session, user_id, other_id)
                row.status = FriendshipState.ACCEPTED.value
                row.responded_at = _now()
                return FriendshipOutcome.ACCEPTED

    async def remove(self, user_id: UUID, other_id: UUID) -> FriendshipOutcome:
        """Decline, cancel, or unfriend - whichever this row is asking for.

        One endpoint, because from the caller's side they are one gesture: make
        this not a thing. What differs is what is left behind. Declining
        somebody else's request keeps the row as a refusal, so it cannot simply
        be re-sent. Cancelling your own request, or ending a friendship, deletes
        it: neither is a refusal, and neither should stop them asking later.
        """
        low, high = friendship_key(user_id, other_id)
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.get(Friendship, (low, high))
                if row is None:
                    return FriendshipOutcome.UNCHANGED
                if (
                    row.status == FriendshipState.PENDING.value
                    and row.requested_by_id != user_id
                ):
                    row.status = FriendshipState.DECLINED.value
                    row.responded_at = _now()
                    return FriendshipOutcome.IGNORED
                if row.status == FriendshipState.DECLINED.value:
                    # Somebody else's refusal is not this caller's to clear.
                    return FriendshipOutcome.UNCHANGED
                await session.delete(row)
                return FriendshipOutcome.REMOVED

    async def forget_pair(self, session: AsyncSession, a: UUID, b: UUID) -> bool:
        """Remove any friendship between two accounts, in the caller's session.

        Called from the block router - a surviving friendship is a capability the
        blocker has just tried to revoke, and it has to go in the same
        transaction as the block itself. Deleted rather than tombstoned: the
        block is now the durable record, and unblocking must not silently
        restore a friendship neither party re-agreed to.
        """
        low, high = friendship_key(a, b)
        result = await session.execute(
            delete(Friendship).where(
                Friendship.user_low_id == low, Friendship.user_high_id == high
            )
        )
        # Whether anything was actually revoked. The caller uses it to decide
        # whether to tell the other account their lists moved - saying so when
        # there was no friendship would turn a block into a way to ask whether
        # one existed.
        return bool(result.rowcount)

    # --- ceilings ---------------------------------------------------------

    async def _count_accepted(self, session: AsyncSession, user_id: UUID) -> int:
        return await session.scalar(
            select(func.count())
            .select_from(Friendship)
            .where(
                Friendship.status == FriendshipState.ACCEPTED.value,
                or_(
                    Friendship.user_low_id == user_id,
                    Friendship.user_high_id == user_id,
                ),
            )
        ) or 0

    async def _raise_if_full(self, session: AsyncSession, user_id: UUID) -> None:
        if await self._count_accepted(session, user_id) >= MAX_FRIENDS_PER_ACCOUNT:
            raise FriendshipRefused(
                f"Your friends list is full ({MAX_FRIENDS_PER_ACCOUNT}). "
                "Remove someone to add another."
            )

    async def _raise_if_either_list_is_full(
        self, session: AsyncSession, user_id: UUID, other_id: UUID
    ) -> None:
        await self._raise_if_full(session, user_id)
        if await self._count_accepted(session, other_id) >= MAX_FRIENDS_PER_ACCOUNT:
            # Their ceiling, said without their numbers: how full somebody
            # else's list is is their fact, not the caller's.
            raise FriendshipRefused(
                "That player cannot take any more friends right now."
            )

    async def _raise_if_too_many_pending(
        self, session: AsyncSession, requester_id: UUID, target_id: UUID
    ) -> None:
        sent = await session.scalar(
            select(func.count())
            .select_from(Friendship)
            .where(
                Friendship.status == FriendshipState.PENDING.value,
                Friendship.requested_by_id == requester_id,
            )
        ) or 0
        if sent >= MAX_PENDING_SENT:
            raise FriendshipRefused(
                f"You have {MAX_PENDING_SENT} friend requests waiting for an "
                "answer. Wait for some of them before sending more."
            )
        received = await session.scalar(
            select(func.count())
            .select_from(Friendship)
            .where(
                Friendship.status == FriendshipState.PENDING.value,
                Friendship.requested_by_id != target_id,
                or_(
                    Friendship.user_low_id == target_id,
                    Friendship.user_high_id == target_id,
                ),
            )
        ) or 0
        if received >= MAX_PENDING_RECEIVED:
            # Generic on purpose. Naming the recipient's inbox state would
            # disclose a fact about somebody who is not in this conversation.
            raise FriendshipRefused(
                "That request could not be sent right now. Try again later."
            )

"""Which of an account's friends are online, told to that account alone (#873, #878).

The lobby's presence list is public, ordered for everyone the same way and cut
at `PRESENCE_LIST_LIMIT` so its snapshot stays inside the deflate window. A
friend is not somebody the public list should have to reach: with more than a
hundred accounts online, one whose name sorted past the cap could not be
invited and never showed as online (#878). And a waiting room subscribed to the
whole lobby channel - every seat, guests included, every lobby chat line - to
read the handful of rows it needed for its invite list (#873).

So friends are answered per account, from memory, apart from the list:

- `friends_online` hands a socket its account's online friends and what they
  are doing (`lobby` or `playing`) - uncapped, and nothing else.
- Every presence tick, an account whose status moved (came online, started or
  stopped playing, went away) is told to each of its online friends as
  `friend_presence`, on `user:{id}` - the per-account room the friends
  surface already listens on.

**Status is the public list's, not more.** `lobby` or `playing` is exactly
what `lobby_presence_changed` says about any account, and never which room
(R-ROOM-07): a friend learns nothing a stranger in the lobby could not.

**Friend sets are cached while an account is online** and dropped when it goes
or when `friends_changed` says its lists moved, so the tick reads the database
only for an account whose status changed and whose friends it has not loaded -
a connect, in practice. `MAX_FRIENDS_PER_ACCOUNT` bounds each set. A guest has
none and is never looked up.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.rooms import RoomManager
from app.services.presence import (
    STATUS_LOBBY,
    STATUS_PLAYING,
    PresenceIdentityCache,
    PresenceRegistry,
    seated_accounts,
)

logger = logging.getLogger("sketchy.friend_presence")

FriendsOf = Callable[[UUID], Awaitable[set[UUID]]]


class FriendsUnavailable(Exception):
    """An account's friend list could not be read just now."""

# How many friend lists one tick may read. A connect costs one, but a restart
# or a burst of arrivals would otherwise be one tick reading a list for every
# account at once, on the loop every room shares. The rest wait a tick each:
# a friend shown online a second or two late is not worth that.
READS_PER_TICK = 25


class FriendPresence:
    def __init__(
        self,
        sio,
        registry: PresenceRegistry,
        identities: PresenceIdentityCache,
        room_manager: RoomManager,
        friends_of: FriendsOf | None,
    ) -> None:
        self._sio = sio
        self._registry = registry
        self._identities = identities
        self._room_manager = room_manager
        self._friends_of = friends_of
        self._friends: dict[str, frozenset[str]] = {}
        # What each online account was last said to be, by the tick.
        self._told: dict[str, str] = {}

    def statuses(self) -> dict[str, str]:
        """Every online account's status, uncapped."""
        seated = seated_accounts(self._room_manager)
        return {
            user_id: STATUS_PLAYING if user_id in seated else STATUS_LOBBY
            for user_id in self._registry.online_user_ids()
        }

    def forget(self, user_id: str | None) -> None:
        """This account's friend lists moved: read them again next time."""
        if user_id:
            self._friends.pop(user_id, None)

    def _needs_read(self, user_id: str) -> bool:
        if user_id in self._friends or self._friends_of is None:
            return False
        identity = self._identities.cached([user_id]).get(user_id)
        return identity is None or not identity.is_anonymous

    async def friends_of(self, user_id: str) -> frozenset[str]:
        """This account's friends; raises `FriendsUnavailable` when unreadable.

        A failed read is not an empty list: answered as one, a client would
        erase friends it had right, and the tick would count a change as told
        that nobody heard. It is not cached, so the next ask reads again."""
        cached = self._friends.get(user_id)
        if cached is not None:
            return cached
        if not self._needs_read(user_id):
            return frozenset()
        try:
            account = UUID(user_id)
        except ValueError:
            # Remembered, or it would be "unread" and spend a read every tick.
            self._friends[user_id] = frozenset()
            return frozenset()
        try:
            friends = frozenset(str(friend) for friend in await self._friends_of(account))
        except Exception as error:
            logger.exception("Could not read the friends of %s", user_id)
            raise FriendsUnavailable(user_id) from error
        self._friends[user_id] = friends
        return friends

    async def online_friends(self, user_id: str) -> list[list[str]]:
        """`[[userId, status], …]` for this account's friends who are online.

        Answered from what the tick last **told**, not from live state. Every
        `friend_presence` already sent is part of that state, and every one
        still to come moves on from it - so a client can replace its map with
        this answer whenever it lands and apply later pushes on top, with no
        sequence number to compare. A live answer could be newer than a push
        the tick had decided but not yet sent, and that push would then roll
        the client back. The price is that a friend who arrived in the last
        second shows up by push a moment later instead."""
        friends = await self.friends_of(user_id)
        told = self._told
        return [[friend, told[friend]] for friend in sorted(friends) if friend in told]

    async def flush(self) -> int:
        """Tell each online friend of every account whose status moved.
        Returns how many messages went out.

        Two passes. The first reads the friend lists the movers need - the
        only awaits on the database, bounded by `READS_PER_TICK`. The second
        takes the statuses afresh and decides every message without awaiting,
        so what is told is the state as of one instant after the reads. An
        account whose list is not in hand - over the budget, or unreadable -
        keeps its last told status, so the next tick sees it moved again and
        nothing is marked told that nobody heard."""
        reads = 0
        for user_id in self._moved(self.statuses()):
            if not self._needs_read(user_id):
                continue
            if reads >= READS_PER_TICK:
                break
            reads += 1
            try:
                await self.friends_of(user_id)
            except FriendsUnavailable:
                pass

        current = self.statuses()
        told = dict(current)
        messages: list[tuple[list, str]] = []
        for user_id, status in self._moved(current).items():
            if self._needs_read(user_id):
                if user_id in self._told:
                    told[user_id] = self._told[user_id]
                else:
                    told.pop(user_id, None)
                continue
            for friend in self._friends.get(user_id, frozenset()):
                if friend in current:
                    messages.append(([user_id, status], f"user:{friend}"))
        self._told = told
        # Only accounts still online keep a cached set: memory is bounded by
        # the socket ceiling, and a returning account is read fresh.
        for gone in [user_id for user_id in self._friends if user_id not in current]:
            del self._friends[gone]
        for payload, room in messages:
            await self._sio.emit("friend_presence", payload, room=room)
        return len(messages)

    def _moved(self, current: dict[str, str]) -> dict[str, str | None]:
        return {
            user_id: current.get(user_id)
            for user_id in current.keys() | self._told.keys()
            if current.get(user_id) != self._told.get(user_id)
        }

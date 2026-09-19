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
        cached = self._friends.get(user_id)
        if cached is not None:
            return cached
        identity = self._identities.cached([user_id]).get(user_id)
        if self._friends_of is None or (identity is not None and identity.is_anonymous):
            return frozenset()
        try:
            account = UUID(user_id)
        except ValueError:
            return frozenset()
        try:
            friends = frozenset(str(friend) for friend in await self._friends_of(account))
        except Exception:
            # Not cached: the next change reads it again. Presence is best
            # effort, and one account's unreadable friends must not stop the
            # tick for everyone else.
            logger.exception("Could not read the friends of %s", user_id)
            return frozenset()
        self._friends[user_id] = friends
        return friends

    async def online_friends(self, user_id: str) -> list[list[str]]:
        """`[[userId, status], …]` for this account's friends who are online."""
        statuses = self.statuses()
        return [
            [friend, statuses[friend]]
            for friend in sorted(await self.friends_of(user_id))
            if friend in statuses
        ]

    async def flush(self) -> int:
        """Tell each online friend of every account whose status moved.
        Returns how many messages went out."""
        current = self.statuses()
        moved = {
            user_id: current.get(user_id)
            for user_id in current.keys() | self._told.keys()
            if current.get(user_id) != self._told.get(user_id)
        }
        sent = 0
        reads = 0
        told = dict(current)
        for user_id, status in moved.items():
            if self._needs_read(user_id):
                if reads >= READS_PER_TICK:
                    # Left as last told, so the next tick sees it moved again.
                    if user_id in self._told:
                        told[user_id] = self._told[user_id]
                    else:
                        told.pop(user_id, None)
                    continue
                reads += 1
            for friend in await self.friends_of(user_id):
                if friend in current:
                    await self._sio.emit(
                        "friend_presence", [user_id, status], room=f"user:{friend}"
                    )
                    sent += 1
        self._told = told
        # Only accounts still online keep a cached set: memory is bounded by
        # the socket ceiling, and a returning account is read fresh.
        for gone in [user_id for user_id in self._friends if user_id not in current]:
            del self._friends[gone]
        return sent

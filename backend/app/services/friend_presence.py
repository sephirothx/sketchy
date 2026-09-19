"""Which of an account's friends are online, answered to that account alone (#873, #878).

The lobby's presence list is public, ordered for everyone the same way and cut
at `PRESENCE_LIST_LIMIT` so its snapshot stays inside the deflate window. A
friend is not somebody the public list should have to reach: with more than a
hundred accounts online, one whose name sorted past the cap could not be
invited and never showed as online (#878). And a waiting room subscribed to the
whole lobby channel - every seat, guests included, every lobby chat line - to
read the handful of rows it needed for its invite list (#873).

So `friends_online` hands a socket its account's online friends and what they
are doing (`lobby` or `playing`) - uncapped, live, and nothing else.

**Asked for, not pushed.** A client showing friends asks on arrival, on
`friends_changed`, and every few seconds while that surface is on screen
(R-PRESENCE-06). A push stream on the presence tick was built first and
dropped: merging it with the answer took a record of what had been told, a
read budget per tick and ordering rules, all to buy freshness nothing here
needs - an invitation is checked by the server when it is sent, so a stale row
costs one refused invite.

**Status is the public list's, not more.** `lobby` or `playing` is exactly
what `lobby_presence_changed` says about any account, and never which room
(R-ROOM-07): a friend learns nothing a stranger in the lobby could not.

**Friend sets are cached while an account is online**, so polling reads the
database once per connection rather than once per ask. An entry is dropped
when the account's last socket closes, and when `friends_changed` says its
lists moved. `MAX_FRIENDS_PER_ACCOUNT` bounds each set.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.rooms import RoomManager
from app.services.presence import (
    STATUS_LOBBY,
    STATUS_PLAYING,
    PresenceRegistry,
    seated_accounts,
)

FriendsOf = Callable[[UUID], Awaitable[set[UUID]]]


class FriendPresence:
    def __init__(
        self,
        registry: PresenceRegistry,
        room_manager: RoomManager,
        friends_of: FriendsOf | None,
    ) -> None:
        self._registry = registry
        self._room_manager = room_manager
        self._friends_of = friends_of
        self._friends: dict[str, frozenset[str]] = {}
        # The read each account's cache may be filled from: the latest one
        # started since the last `forget`. Only reads in flight are here.
        self._reading: dict[str, object] = {}

    def forget(self, user_id: str | None) -> None:
        """Read this account's friends again next time it asks: its lists
        moved, or its last socket closed."""
        if user_id:
            self._friends.pop(user_id, None)
            # A read already in flight started before whatever this forgets,
            # so its answer may be the old one: it must not refill the cache.
            self._reading.pop(user_id, None)

    async def _friends_of_account(self, user_id: str) -> frozenset[str]:
        cached = self._friends.get(user_id)
        if cached is not None:
            return cached
        if self._friends_of is None:
            return frozenset()
        try:
            account = UUID(user_id)
        except ValueError:
            return frozenset()
        token = object()
        self._reading[user_id] = token
        try:
            # A failed read raises to the caller rather than reading as nobody:
            # answered empty, a client would erase friends it had right.
            friends = frozenset(str(friend) for friend in await self._friends_of(account))
        finally:
            owns_cache = self._reading.get(user_id) is token
            if owns_cache:
                del self._reading[user_id]
        # Cached only by the latest read begun since the last `forget` - one
        # that began before a friendship changed would restore the old set -
        # and only while the account is still online, since its last socket
        # closing is what would otherwise drop the entry.
        if owns_cache and self._registry.is_online(user_id):
            self._friends[user_id] = friends
        return friends

    async def online_friends(self, user_id: str) -> list[list[str]]:
        """`[[userId, status], …]` for this account's friends who are online."""
        friends = await self._friends_of_account(user_id)
        seated = seated_accounts(self._room_manager)
        return [
            [friend, STATUS_PLAYING if friend in seated else STATUS_LOBBY]
            for friend in sorted(friends)
            if self._registry.is_online(friend)
        ]

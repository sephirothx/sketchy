"""Who is connected, and whether they are seated.

Until now `connected` only ever meant something *inside* a room: `Player.sid`
and `Player.connected` describe a seat, and a visitor idling in the lobby held
a live socket nothing tracked. The lobby's online list needs the other
question answered - which accounts can be reached right now - and #529's
friend requests need it too, because a request delivered to `user:{id}` with
nobody there goes nowhere.

Three pieces, deliberately separated by what can go wrong with each:

* `PresenceRegistry` - pure, synchronous, no I/O. Who is online.
* `PresenceIdentityCache` - the name and colour to show, read through a
  bounded LRU rather than stored, because identity changes through five paths
  and only one of them touches a socket.
* `LobbyBroadcaster` - the fixed tick that turns changes into at most one
  delta per second on the `lobby` channel.

Process-owned and never durable, like every other live-state owner (see the
state ownership table in `docs/architecture.md`). Nothing here survives a
restart, and nothing here is a source of truth about seats: status is derived
from `RoomManager` on every snapshot rather than cached beside it.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
import logging
import os

from app.repositories.interfaces import UserRepository
from app.services.lobby_rooms import (
    EMPTY_ROOMS,
    RoomsDelta,
    RoomsSnapshot,
    build_rooms_snapshot,
    diff_rooms,
)
from app.rooms import RoomManager

logger = logging.getLogger("sketchy.presence")

# The Socket.IO room every lobby that asked for presence is in. Named for the
# defined term in GLOSSARY.md: the lobby is one place, and it is not inside a
# room.
LOBBY_CHANNEL = "lobby"

STATUS_LOBBY = "lobby"
STATUS_PLAYING = "playing"

# 400 connected seats is the validation target in `docs/requirements.md`; 400
# rows is not a user interface. The list is capped and the true total ships
# beside it, so a cap is never mistaken for a quiet server.
DEFAULT_LIST_LIMIT = 100
# A fixed tick, not a trailing debounce: a trailing debounce under continuous
# churn never fires at all, while a tick has a bounded worst case of one
# broadcast per interval however much is moving. It also absorbs the flicker
# of a mobile transport bounce for free, which is a presentation concern and
# belongs here rather than in the registry.
DEFAULT_BROADCAST_INTERVAL_MS = 1000
# Long enough that an ordinary cold read succeeds, short enough that a stalled
# one is not felt. A miss omits the row rather than showing a blank name.
IDENTITY_TIMEOUT_SECONDS = 2
# How many identities one tick may read. The handshake warms the ordinary
# case, so this is only ever repairing what was invalidated or evicted - but
# a cold cache with a full server behind it would otherwise be one tick
# issuing hundreds of reads at once. Spread over ticks instead: a row missing
# for an extra second is not worth a thundering herd.
WARM_PER_TICK = 25
# Every account that can hold a socket must fit, or the cache thrashes (see
# `PresenceIdentityCache`). The default sits above `DEFAULT_SOCKETS`; where the
# socket ceiling is raised, the cache is built from it instead.
DEFAULT_MAX_CACHED_IDENTITIES = 1024


def _ceiling(values: Mapping[str, str], name: str, default: int) -> int:
    """Read a ceiling from the environment, falling back to the default."""
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s is not a number; using %d", name, default)
        return default
    if value <= 0:
        logger.warning("%s must be positive; using %d", name, default)
        return default
    return value


@dataclass(frozen=True, slots=True)
class PresenceIdentity:
    """The part of an account a presence row shows."""

    user_id: str
    display_name: str
    name_color: str | None
    is_anonymous: bool


@dataclass(frozen=True, slots=True)
class PresenceEntry:
    """One online account, as the lobby sees them."""

    user_id: str
    display_name: str
    name_color: str | None
    is_anonymous: bool
    status: str

    def payload(self) -> dict:
        """The wire shape.

        Carries the account id, because a friend request needs a stable
        target and there is no seat to resolve for somebody idling in the
        lobby. It carries no room id, code, name, or state richer than
        lobby-or-game: `Room.to_public_roster` refuses to make the lobby a
        directory of who is playing where, and naming the room would also
        disclose that a private one exists.
        """
        return {
            "userId": self.user_id,
            "displayName": self.display_name,
            "nameColor": self.name_color,
            "isAnonymous": self.is_anonymous,
            "status": self.status,
        }


def sort_key(entry: PresenceEntry) -> tuple[bool, str, str]:
    """The one order both ends agree on.

    Deterministic, so the same state always yields the same list and a diff
    against the last one means something. Registered before guests matches
    R-ACCT-05 - a name is either a claimed account or an unclaimed guest - and
    puts the accounts a friend request can actually reach at the top. The id
    breaks ties, so two players sharing a display name still have a total
    order rather than one that depends on dictionary iteration.

    Explicitly not recency: a list sorted by when people arrived reorders
    under the reader's cursor on every tick.

    #529 puts friends above everyone else, which is a term in front of this
    one rather than a change to it - the rest of the order still decides
    among friends, and among everybody else.

    The client re-sorts by the same rule after applying a delta
    (`frontend/src/lib/lobbyPresence.ts`), and `fixtures/lobby_presence_v1.json`
    pins that the two agree. They provably can: `NAME_PATTERN` restricts a
    display name to `[a-zA-Z0-9_-]`, so Python's `lower` and JavaScript's
    `toLowerCase` are the same function here, and comparing by code point and
    by UTF-16 code unit are the same comparison. `casefold` is deliberately
    not used - it has no ASCII-range difference from `lower`, and reaching
    for it would imply an agreement across the wire that only holds by
    accident of the charset.
    """
    return (entry.is_anonymous, entry.display_name.lower(), entry.user_id)


@dataclass(frozen=True, slots=True)
class PresenceSnapshot:
    """The capped, ordered list at one revision."""

    revision: int
    entries: tuple[PresenceEntry, ...]
    online_count: int

    def payload(self) -> dict:
        return {
            "revision": self.revision,
            "players": [entry.payload() for entry in self.entries],
            "onlineCount": self.online_count,
        }


@dataclass(frozen=True, slots=True)
class PresenceDelta:
    """What changed between two snapshots, over the capped list.

    Computed over the *capped* entries rather than the whole online set, so
    that what the client is told matches what it was sent: an account pushed
    out of the list by the cap leaves, as far as this channel is concerned,
    and re-joins when it fits again.
    """

    revision: int
    joined: tuple[PresenceEntry, ...]
    left: tuple[str, ...]
    changed: tuple[PresenceEntry, ...]
    online_count: int

    @property
    def is_empty(self) -> bool:
        return not (self.joined or self.left or self.changed)

    def payload(self) -> dict:
        return {
            "revision": self.revision,
            "joined": [entry.payload() for entry in self.joined],
            "left": list(self.left),
            "changed": [entry.payload() for entry in self.changed],
            "onlineCount": self.online_count,
        }


def diff_snapshots(before: PresenceSnapshot, after: PresenceSnapshot) -> PresenceDelta:
    """What a client holding `before` must apply to arrive at `after`."""
    previous = {entry.user_id: entry for entry in before.entries}
    current = {entry.user_id: entry for entry in after.entries}
    joined = tuple(
        entry for user_id, entry in current.items() if user_id not in previous
    )
    left = tuple(user_id for user_id in previous if user_id not in current)
    changed = tuple(
        entry
        for user_id, entry in current.items()
        if user_id in previous and previous[user_id] != entry
    )
    return PresenceDelta(
        revision=after.revision,
        joined=joined,
        left=left,
        changed=changed,
        online_count=after.online_count,
    )


class PresenceRegistry:
    """Which accounts hold at least one open socket.

    Keyed by account rather than by socket, so several tabs of one player are
    one entry in the list by construction rather than by a de-duplicating
    pass somebody has to remember to write.

    A connection with no account is not in here at all. There is no key to
    file it under - `_sids_by_user` is keyed by account and an anonymous
    socket has none - so a crawler, a link preview and an uptime check are
    invisible by the absence of a key rather than by a filter a later
    refactor could drop. That matters because R-ACCT-02 makes `user_id=None`
    the *ordinary* first visit, not a rarity: choosing a name is what
    provisions a guest.
    """

    def __init__(self) -> None:
        self._sids_by_user: dict[str, set[str]] = {}
        self._user_by_sid: dict[str, str] = {}

    def note_socket_opened(self, sid: str, user_id: str | None) -> bool:
        """Record a socket. True when that account was not online before.

        Sets rather than counts, for the reason `RoomCapacityService` gives
        for its own socket ledger: a count is only ever as right as the last
        event that moved it, and one missed or repeated notification drifts it
        for the life of the process. A set cannot drift, and it makes both
        notifications idempotent.
        """
        if not sid or not user_id:
            return False
        existing = self._user_by_sid.get(sid)
        if existing is not None and existing != user_id:
            # A sid is only ever handed out once, so this is a bug rather than
            # a race - but leaving the old account holding a socket that has
            # moved on is the leak this class exists to prevent.
            self._drop(sid, existing)
        self._user_by_sid[sid] = user_id
        sids = self._sids_by_user.setdefault(user_id, set())
        was_offline = not sids
        sids.add(sid)
        return was_offline

    def note_socket_closed(self, sid: str) -> bool:
        """Forget a socket. True when that was the account's last one."""
        if not sid:
            return False
        user_id = self._user_by_sid.get(sid)
        if user_id is None:
            return False
        return self._drop(sid, user_id)

    def _drop(self, sid: str, user_id: str) -> bool:
        self._user_by_sid.pop(sid, None)
        sids = self._sids_by_user.get(user_id)
        if sids is None:
            return False
        sids.discard(sid)
        if sids:
            return False
        del self._sids_by_user[user_id]
        return True

    def rekey(self, source_user_id: str, target_user_id: str) -> None:
        """Move every socket of a merged guest onto the account it became.

        A guest logging in becomes an alias of an account (R-ACCT-04), and the
        sockets they already had open still resolved the guest at their
        handshake - the server reads the cookie once. Left alone they would
        sit in the registry as a second person: an entry that inflates the
        total, cannot be shown once the alias resolves, and only clears when
        that tab is closed.

        Moved rather than closed on purpose. Closing them is what a deletion
        or a ban does, because those end the account - but a merge does not,
        and closing here would drop a player out of a game they are in on
        another tab because they signed in on this one. The seat is
        deliberately left alone (historical seats keep their identity) and
        revocation applies on the next connection (R-AUTH-04). What moves is
        only who presence says the socket belongs to, which is precisely what
        an alias means.

        A set union, so the account being online already is the ordinary case
        rather than a collision.
        """
        if source_user_id == target_user_id:
            return
        sids = self._sids_by_user.pop(source_user_id, set())
        if not sids:
            return
        for sid in sids:
            self._user_by_sid[sid] = target_user_id
        self._sids_by_user.setdefault(target_user_id, set()).update(sids)

    def is_online(self, user_id: str | None) -> bool:
        return bool(user_id) and user_id in self._sids_by_user

    def user_for_sid(self, sid: str) -> str | None:
        """The account behind one socket; None for a socket with no account.

        What a lobby chat line consults when its author is blocked: the
        channel is a list of sockets, and a block is between accounts.
        """
        return self._user_by_sid.get(sid)

    def online_user_ids(self) -> list[str]:
        return list(self._sids_by_user)

    @property
    def online_accounts(self) -> int:
        return len(self._sids_by_user)

    def tracked_sockets(self) -> int:
        """Sockets this registry believes are open.

        Never larger than the socket ledger's, which is the invariant the
        lifecycle tests assert after every way in and out.
        """
        return len(self._user_by_sid)


def seated_accounts(room_manager: RoomManager) -> set[str]:
    """Every account holding a live seat, in one pass over the rooms.

    Inverted deliberately. `seats_for_sid` answers the same question per
    socket and walks every room to do it, which is a few hundred comparisons
    on one disconnect but the square of that if a snapshot asked it once per
    online account. One pass builds the whole answer: at the product ceiling
    that is 50 rooms of 24 seats, once per broadcast, not once per viewer.

    Derived from the rooms themselves on every call rather than cached beside
    them. A cache fed from the `GameFlowService` seat transitions would be
    wrong on the first day: `player.sid` is also assigned by the seat
    confirmation in `handlers/rooms.py`, which those transitions never see.
    """
    return {
        player.user_id
        for room in list(room_manager.rooms.values())
        for player in list(room.players.values())
        if player.user_id
    }


def build_snapshot(
    registry: PresenceRegistry,
    room_manager: RoomManager,
    identities: Mapping[str, PresenceIdentity],
    *,
    revision: int,
    limit: int = DEFAULT_LIST_LIMIT,
) -> PresenceSnapshot:
    """The ordered, capped list of who is online.

    An account whose identity is not resolved is *omitted* rather than shown
    with a blank name: presence is a convenience, and a missing row is a
    better failure than a wrong one. It still counts towards the total, which
    is the number of accounts online rather than the number the list could
    render.
    """
    online = registry.online_user_ids()
    seated = seated_accounts(room_manager)
    entries = [
        PresenceEntry(
            user_id=user_id,
            display_name=identity.display_name,
            name_color=identity.name_color,
            is_anonymous=identity.is_anonymous,
            status=STATUS_PLAYING if user_id in seated else STATUS_LOBBY,
        )
        for user_id in online
        if (identity := identities.get(user_id)) is not None
    ]
    entries.sort(key=sort_key)
    return PresenceSnapshot(
        revision=revision,
        entries=tuple(entries[:limit]),
        online_count=len(online),
    )


EMPTY_SNAPSHOT = PresenceSnapshot(revision=0, entries=(), online_count=0)


class PresenceIdentityCache:
    """The name and colour behind an account id, without a query per row.

    The same shape `BlockService` uses, for the same reason and with the same
    failure rule. Warmed at the handshake, where waiting is already expected,
    so a snapshot is ordinarily built entirely from hits.

    Identity is read through here rather than stored in the registry because
    the registry is written once, at the handshake, while a display name or
    colour changes through five paths - `set_display_name`, `set_name_color`,
    the in-room colour change in `update_player_settings`,
    the `rename_player` command, and a guest merge - three of which never
    touch a socket. Five invalidation sites for a cache is routine; five
    writers into a live registry is the drift this module is shaped to avoid -
    and the tick's repair is what makes a missed one recoverable rather than
    permanent.
    """

    def __init__(
        self,
        user_repo: UserRepository | None,
        *,
        max_cached: int = DEFAULT_MAX_CACHED_IDENTITIES,
    ) -> None:
        self._user_repo = user_repo
        # Never smaller than the number of accounts that can be online at
        # once. A cache below that ceiling cannot hold the list it exists to
        # answer: every tick would evict rows it is about to be asked for and
        # read back rows it just evicted, and the lobby would flicker for ever
        # while the database took the cost. `BlockService` has no equivalent
        # floor because a miss there is answered by a read on the spot; here a
        # miss means the row is simply absent until a later tick.
        self._max_cached = max(1, max_cached)
        self._identities: OrderedDict[str, PresenceIdentity] = OrderedDict()

    def cached(self, user_ids: list[str]) -> dict[str, PresenceIdentity]:
        """Whatever is known now, without waiting for anything.

        The snapshot builder asks this rather than reading through, so
        building a payload never awaits a database. What makes that safe is
        `missing` below: the tick repairs what this could not answer, so an
        account absent here is absent for a tick rather than for good.
        """
        found = {}
        for user_id in user_ids:
            identity = self._identities.get(user_id)
            if identity is not None:
                self._identities.move_to_end(user_id)
                found[user_id] = identity
        return found

    def missing(self, user_ids: list[str]) -> list[str]:
        """Which of these accounts this cache cannot currently answer for."""
        return [user_id for user_id in user_ids if user_id not in self._identities]

    async def warm(self, user_id: str | None) -> None:
        """Read an account's identity ahead of the first snapshot needing it.

        Called from the handshake, which is already the place a visitor waits.
        A read that does not come back in time leaves the account out of the
        list until something warms it again - never a blank row.
        """
        if not user_id or self._user_repo is None:
            return
        if user_id in self._identities:
            self._identities.move_to_end(user_id)
            return
        try:
            user = await asyncio.wait_for(
                self._user_repo.get_by_id(user_id), timeout=IDENTITY_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Timed out reading presence identity after %ss; leaving %s out of the list",
                IDENTITY_TIMEOUT_SECONDS,
                user_id,
            )
            return
        except Exception:
            logger.exception("Failed to read presence identity; leaving it out")
            return
        if user is None:
            return
        # Stored under the key that was *asked for*, not the one the record
        # came back with. `get_by_id` resolves an identity alias, so a merged
        # guest's id reads back as the account it was merged into - and a
        # cache keyed by the answer would never satisfy the question. The tick
        # would ask again every second, for as long as that socket stayed
        # open, and never stop.
        self.remember(
            PresenceIdentity(
                user_id=user.id,
                display_name=user.display_name,
                name_color=user.name_color,
                is_anonymous=user.is_anonymous,
            ),
            key=user_id,
        )

    def remember(
        self, identity: PresenceIdentity, *, key: str | None = None
    ) -> None:
        """Cache an identity under the key presence will look it up by.

        `key` differs from `identity.user_id` only for an alias: a merged
        guest is asked about under the id its socket handshook with, and
        answers with the account it became.
        """
        cache_key = key or identity.user_id
        self._identities[cache_key] = identity
        self._identities.move_to_end(cache_key)
        while len(self._identities) > self._max_cached:
            self._identities.popitem(last=False)

    def invalidate(self, user_id: str | None) -> None:
        """Forget one account, so the next warm reads it again.

        Called from every path that writes a display name or colour. A merged
        or deleted account is invalidated the same way: the row goes, and
        nothing re-warms an account with no sockets.
        """
        if user_id:
            self._identities.pop(user_id, None)

    def clear(self) -> None:
        self._identities.clear()

    @property
    def capacity(self) -> int:
        return self._max_cached

    def cached_accounts(self) -> int:
        return len(self._identities)


class LobbyBroadcaster:
    """One tick, two feeds, and a delta only where something moved.

    Presence and the public room list both ride the channel the lobby opens,
    as separate events with separate revisions. Separate because they move
    independently: a room filling up should not re-send who is online, and
    somebody signing in should not re-send the rooms.

    Deliberately has no `mark_dirty`. Every tick rebuilds the snapshot and
    diffs it against the last one broadcast, so a change is picked up wherever
    it happened - a handshake, a disconnect, or a seat taken deep inside
    `GameFlowService` - without a mutation site having to remember to say so.
    A missed mark would be a row that stays wrong until something unrelated
    moved, which is the worst kind of staleness: intermittent and unreported.

    The cost of that choice is one pass over the rooms and one sort per tick
    whether or not anything changed. At the product ceiling that is 50 rooms
    of 24 seats and a sort of at most a few hundred entries, once a second,
    against a saving of one more invariant nobody can break.
    """

    def __init__(
        self,
        sio,
        registry: PresenceRegistry,
        identities: PresenceIdentityCache,
        room_manager: RoomManager,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        values = os.environ if environ is None else environ
        self._sio = sio
        self._registry = registry
        self._identities = identities
        self._room_manager = room_manager
        self.list_limit = _ceiling(values, "PRESENCE_LIST_LIMIT", DEFAULT_LIST_LIMIT)
        self.interval_ms = _ceiling(
            values, "PRESENCE_BROADCAST_INTERVAL_MS", DEFAULT_BROADCAST_INTERVAL_MS
        )
        self._revision = 0
        self._last = EMPTY_SNAPSHOT
        self._rooms_revision = 0
        self._last_rooms = EMPTY_ROOMS

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def rooms_revision(self) -> int:
        return self._rooms_revision

    def _build(self, revision: int) -> PresenceSnapshot:
        online = self._registry.online_user_ids()
        return build_snapshot(
            self._registry,
            self._room_manager,
            self._identities.cached(online),
            revision=revision,
            limit=self.list_limit,
        )

    def snapshot_for_watcher(self) -> PresenceSnapshot:
        """The baseline a socket joining the channel is handed.

        Built fresh rather than handing over the last broadcast, so a new
        watcher sees the current list immediately instead of whatever was
        true up to a tick ago - and stamped with the revision already
        broadcast rather than a new one, so it stays in the same sequence as
        everybody else.

        Safe because the delta stream is idempotent: `joined` and `changed`
        are upserts and `left` is a delete, so a row this snapshot already
        carried being announced again, or one it had already dropped being
        dropped again, changes nothing. That is what lets a watcher be given
        a fresher view than the channel without falling out of step with it.
        """
        return self._build(self._revision)

    def rooms_for_watcher(self) -> RoomsSnapshot:
        """The room list a socket joining the channel is handed.

        Fresh, and stamped with the revision already broadcast - the same
        bargain the presence snapshot strikes, and safe for the same reason:
        `opened` and `changed` are upserts and `closed` is a delete, so a room
        this snapshot already carried being announced again changes nothing.
        """
        return build_rooms_snapshot(self._room_manager, revision=self._rooms_revision)

    async def _flush_rooms(self) -> RoomsDelta | None:
        """Broadcast what moved in the room list, if anything did."""
        candidate = build_rooms_snapshot(
            self._room_manager, revision=self._rooms_revision + 1
        )
        delta = diff_rooms(self._last_rooms, candidate)
        if delta.is_empty:
            return None
        # Emitted before the revision is consumed. `run` swallows a failed
        # tick so that one bad broadcast does not stop every later one, which
        # means a raise here must leave the feed exactly where it was: state
        # written first would mark this revision delivered and diff the next
        # tick against a list nobody was sent, so the change would never go
        # out again and watchers would sit on the old list until some
        # unrelated room moved. Re-sending instead is free - a client ignores
        # a revision it already holds, and every entry is an upsert or a
        # delete.
        await self._sio.emit(
            "lobby_rooms_changed", delta.payload(), room=LOBBY_CHANNEL
        )
        self._last_rooms = candidate
        self._rooms_revision = candidate.revision
        return delta

    async def _repair_identities(self) -> None:
        """Read back the identities the cache can no longer answer for.

        The handshake warms an account once, and every writer of a display
        name or colour invalidates it - but **nothing re-handshakes after a
        write**: a rename, a colour change and a guest claim all keep the same
        account id, and `authStore` only shakes hands again when the id
        changes. Without this, `invalidate` would be permanent for as long as
        the player stayed connected - their row would drop out of the list,
        be broadcast as a `left` for a socket that never closed, and never
        come back.

        Doing it here rather than at each call site is the point. There are
        four writers today, and the same state is reached with nobody writing
        at all: a busy server evicts an online account from a bounded cache
        just by warming others after it. A repair living at the writers would
        be one more invariant every future writer has to know about, and would
        still not cover eviction. The tick already rebuilds everything else
        from truth; this is that idea applied to the one part of a row that is
        not held in memory.
        """
        absent = self._identities.missing(self._registry.online_user_ids())
        if not absent:
            return
        await asyncio.gather(
            *(self._identities.warm(user_id) for user_id in absent[:WARM_PER_TICK])
        )

    async def flush(self) -> PresenceDelta | None:
        """Broadcast what changed since the last tick, on either feed."""
        await self._flush_rooms()
        await self._repair_identities()
        candidate = self._build(self._revision + 1)
        delta = diff_snapshots(self._last, candidate)
        # The count moves on its own: an account beyond the cap connecting
        # changes nothing in the list but does change the "showing 100 of
        # 412" the panel renders, and a client told nothing would keep
        # rendering the old number for as long as the list stayed still.
        if delta.is_empty and candidate.online_count == self._last.online_count:
            return None
        # Emitted before the revision is consumed, for the reason
        # `_flush_rooms` gives at length: a swallowed failure must not leave a
        # revision spent on a broadcast nobody received.
        await self._sio.emit(
            "lobby_presence_changed", delta.payload(), room=LOBBY_CHANNEL
        )
        self._last = candidate
        self._revision = candidate.revision
        return delta

    async def run(self, *, health=None) -> None:
        """Tick for ever, swallowing everything but cancellation.

        Sleeps first: a process that has just started has nothing to say, and
        an empty broadcast into an empty channel is a wasted first impression
        of the loop's health.
        """
        interval = self.interval_ms / 1000
        while True:
            await asyncio.sleep(interval)
            try:
                await self.flush()
                if health is not None:
                    health.record_success()
            except asyncio.CancelledError:
                raise
            except Exception:
                # One bad tick must not stop every later one. Counted rather
                # than only logged, so a broadcast failing every time is
                # visible from outside rather than as a lobby that quietly
                # stopped updating.
                if health is not None:
                    health.record_failure()
                logger.exception("presence broadcast failed")


def start_presence_loop(
    broadcaster: LobbyBroadcaster, *, health=None
) -> asyncio.Task[None]:
    return asyncio.create_task(broadcaster.run(health=health))


async def stop_presence_loop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

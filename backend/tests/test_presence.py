"""Who is online, and the one order both ends of the channel agree on.

The registry is the ledger a leak would show up in: an account left behind
after its last socket closed is a row that says somebody is reachable when
nobody is, and in PR2 a friend request delivered to a channel with nobody in
it. So the balance cases get the same attention `RoomCapacityService`'s socket
ledger gets, and the lifecycle half of them lives in
`tests/handlers/test_lobby_presence.py`, where the real handshake runs.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.rooms import RoomManager
from app.services.presence import (
    EMPTY_SNAPSHOT,
    STATUS_LOBBY,
    STATUS_PLAYING,
    PresenceBroadcaster,
    PresenceEntry,
    PresenceIdentity,
    PresenceIdentityCache,
    PresenceRegistry,
    build_snapshot,
    diff_snapshots,
    seated_accounts,
    sort_key,
)

FIXTURE = json.loads(
    (Path(__file__).resolve().parent.parent.parent / "fixtures" / "lobby_presence_v1.json").read_text(
        encoding="utf-8"
    )
)


def identity(user_id: str, name: str, *, guest: bool = False) -> PresenceIdentity:
    return PresenceIdentity(
        user_id=user_id,
        display_name=name,
        name_color=None if guest else "#4f9",
        is_anonymous=guest,
    )


def identities(*pairs: tuple[str, str]) -> dict[str, PresenceIdentity]:
    return {user_id: identity(user_id, name) for user_id, name in pairs}


# --- the registry ---------------------------------------------------------


def test_a_socket_with_no_account_is_not_recorded_at_all():
    """R-ACCT-02 makes this the ordinary first visit, not a rarity.

    Choosing a name is what provisions a guest, so a visitor who has not yet
    chosen one - and every crawler, link preview and uptime check - holds a
    socket with no account. They are absent because there is no key to file
    them under, which is what stops a later refactor dropping the filter.
    """
    registry = PresenceRegistry()
    assert registry.note_socket_opened("sid-anon", None) is False
    assert registry.online_accounts == 0
    assert registry.tracked_sockets() == 0
    assert registry.online_user_ids() == []


def test_two_tabs_of_one_account_are_one_entry():
    registry = PresenceRegistry()
    assert registry.note_socket_opened("sid-a", "user-1") is True
    # Not the first socket, so not a transition anything needs to hear about.
    assert registry.note_socket_opened("sid-b", "user-1") is False
    assert registry.online_accounts == 1
    assert registry.tracked_sockets() == 2

    # Closing one tab leaves the account online through the other.
    assert registry.note_socket_closed("sid-a") is False
    assert registry.is_online("user-1")
    assert registry.note_socket_closed("sid-b") is True
    assert not registry.is_online("user-1")
    assert registry.tracked_sockets() == 0


def test_both_notifications_are_idempotent():
    """A set, not a count, so a repeated close cannot drift it downwards."""
    registry = PresenceRegistry()
    registry.note_socket_opened("sid-a", "user-1")
    registry.note_socket_opened("sid-a", "user-1")
    assert registry.tracked_sockets() == 1
    assert registry.note_socket_closed("sid-a") is True
    assert registry.note_socket_closed("sid-a") is False
    assert registry.note_socket_closed("never-opened") is False
    assert registry.note_socket_closed("") is False
    assert registry.note_socket_opened("", "user-1") is False
    assert registry.online_accounts == 0


def test_a_sid_reused_for_another_account_leaves_nothing_behind():
    """A bug rather than a race, but not one that may leak a socket."""
    registry = PresenceRegistry()
    registry.note_socket_opened("sid-a", "user-1")
    registry.note_socket_opened("sid-a", "user-2")
    assert registry.is_online("user-2")
    assert not registry.is_online("user-1")
    assert registry.tracked_sockets() == 1


# --- the snapshot ---------------------------------------------------------


def test_the_sort_matches_the_cross_language_fixture():
    """The comparator the client re-sorts with after applying a delta.

    Pinned by a shared fixture rather than by two independent test suites,
    so a comparator changed on one side alone fails on the other.
    """
    entries = [
        PresenceEntry(
            user_id=row["userId"],
            display_name=row["displayName"],
            name_color=row["nameColor"],
            is_anonymous=row["isAnonymous"],
            status=row["status"],
        )
        for row in FIXTURE["entries"]
    ]
    ordered = [entry.user_id for entry in sorted(entries, key=sort_key)]
    assert ordered == FIXTURE["sortedUserIds"]


def test_a_seated_account_reads_playing_and_everyone_else_reads_lobby():
    registry = PresenceRegistry()
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    room_manager.add_player(room, "Ada", user_id="user-seated", is_anonymous=False)
    registry.note_socket_opened("sid-a", "user-seated")
    registry.note_socket_opened("sid-b", "user-idle")

    snapshot = build_snapshot(
        registry,
        room_manager,
        identities(("user-seated", "Ada"), ("user-idle", "Bob")),
        revision=1,
    )
    by_id = {entry.user_id: entry.status for entry in snapshot.entries}
    assert by_id == {"user-seated": STATUS_PLAYING, "user-idle": STATUS_LOBBY}


def test_seated_accounts_ignores_a_seat_with_no_account():
    """A cookieless visitor still plays (R-HIST-10); they are just not an account."""
    room_manager = RoomManager()
    room = room_manager.create_room(name="Room", is_public=True)
    room_manager.add_player(room, "Nobody", user_id=None)
    room_manager.add_player(room, "Ada", user_id="user-1", is_anonymous=False)
    assert seated_accounts(room_manager) == {"user-1"}


def test_the_list_is_capped_while_the_count_stays_true():
    """A cap must never be mistakable for a quiet server."""
    registry = PresenceRegistry()
    known = {}
    for index in range(250):
        user_id = f"user-{index:03d}"
        registry.note_socket_opened(f"sid-{index}", user_id)
        known[user_id] = identity(user_id, f"player{index:03d}")

    snapshot = build_snapshot(
        registry, RoomManager(), known, revision=7, limit=100
    )
    assert len(snapshot.entries) == 100
    assert snapshot.online_count == 250
    assert snapshot.revision == 7
    assert snapshot.payload()["onlineCount"] == 250


def test_an_account_with_no_resolved_identity_is_omitted_but_still_counted():
    """A missing row is a better failure than a wrong name."""
    registry = PresenceRegistry()
    registry.note_socket_opened("sid-a", "user-known")
    registry.note_socket_opened("sid-b", "user-unwarmed")

    snapshot = build_snapshot(
        registry, RoomManager(), identities(("user-known", "Ada")), revision=1
    )
    assert [entry.user_id for entry in snapshot.entries] == ["user-known"]
    assert snapshot.online_count == 2


def test_the_payload_carries_no_room_identifier():
    """R-ROOM-07's neighbour: presence says lobby-or-game and nothing richer.

    `Room.to_public_roster` refuses to make the lobby a directory of who is
    playing where, and naming the room would additionally disclose that a
    private one exists.
    """
    registry = PresenceRegistry()
    room_manager = RoomManager()
    room = room_manager.create_room(name="Secret Room", is_public=False)
    room_manager.add_player(room, "Ada", user_id="user-1", is_anonymous=False)
    registry.note_socket_opened("sid-a", "user-1")

    payload = build_snapshot(
        registry, room_manager, identities(("user-1", "Ada")), revision=1
    ).payload()
    flat = json.dumps(payload)
    assert room.id not in flat
    assert room.code not in flat
    assert room.name not in flat
    assert set(payload["players"][0]) == {
        "userId",
        "displayName",
        "nameColor",
        "isAnonymous",
        "status",
    }


# --- the delta ------------------------------------------------------------


def snapshot_of(registry, room_manager, known, revision, limit=100):
    return build_snapshot(
        registry, room_manager, known, revision=revision, limit=limit
    )


def test_a_delta_names_exactly_what_moved():
    registry = PresenceRegistry()
    room_manager = RoomManager()
    known = identities(("user-a", "Ada"), ("user-b", "Bob"))
    registry.note_socket_opened("sid-a", "user-a")
    before = snapshot_of(registry, room_manager, known, 1)

    registry.note_socket_opened("sid-b", "user-b")
    room = room_manager.create_room(name="Room", is_public=True)
    room_manager.add_player(room, "Ada", user_id="user-a", is_anonymous=False)
    after = snapshot_of(registry, room_manager, known, 2)

    delta = diff_snapshots(before, after)
    assert delta.revision == 2
    assert [entry.user_id for entry in delta.joined] == ["user-b"]
    assert delta.left == ()
    assert [entry.user_id for entry in delta.changed] == ["user-a"]
    assert delta.changed[0].status == STATUS_PLAYING


def test_an_unchanged_snapshot_produces_an_empty_delta():
    registry = PresenceRegistry()
    known = identities(("user-a", "Ada"))
    registry.note_socket_opened("sid-a", "user-a")
    first = snapshot_of(registry, RoomManager(), known, 1)
    second = snapshot_of(registry, RoomManager(), known, 2)
    assert diff_snapshots(first, second).is_empty


def apply_delta(entries, delta):
    """The client's half of the contract, in Python.

    Deliberately written the way `lobbyPresence.ts` is: a map keyed by
    account, upserts for joined and changed, deletes for left, then a re-sort
    with the shared comparator.
    """
    by_id = {entry.user_id: entry for entry in entries}
    for entry in delta.joined:
        by_id[entry.user_id] = entry
    for entry in delta.changed:
        by_id[entry.user_id] = entry
    for user_id in delta.left:
        by_id.pop(user_id, None)
    return tuple(sorted(by_id.values(), key=sort_key))


def test_a_sequence_of_deltas_and_a_full_snapshot_agree():
    """The contract #493 asked for, and the reason deltas are safe here.

    A client that applies every delta in order must hold exactly what a
    snapshot would have given it. Checked across joins, a status change, a
    leave, and an eviction by the cap - that last one being the case easiest
    to get wrong, because an account pushed out of the list has left as far
    as this channel is concerned even though it is still online.
    """
    registry = PresenceRegistry()
    room_manager = RoomManager()
    known = {}
    broadcast = EMPTY_SNAPSHOT
    held = EMPTY_SNAPSHOT.entries

    def tick():
        nonlocal broadcast, held
        current = snapshot_of(
            registry, room_manager, known, broadcast.revision + 1, limit=3
        )
        held = apply_delta(held, diff_snapshots(broadcast, current))
        broadcast = current
        assert held == current.entries

    for index, name in enumerate(["ada", "bob", "cleo", "dan"]):
        user_id = f"user-{name}"
        known[user_id] = identity(user_id, name)
        registry.note_socket_opened(f"sid-{index}", user_id)
        tick()

    # A status change, which is a `changed` rather than a join.
    room = room_manager.create_room(name="Room", is_public=True)
    room_manager.add_player(room, "ada", user_id="user-ada", is_anonymous=False)
    tick()

    # A leave, which lets the account the cap had hidden back into the list.
    registry.note_socket_closed("sid-0")
    tick()

    registry.note_socket_closed("sid-1")
    registry.note_socket_closed("sid-2")
    tick()

    assert {entry.user_id for entry in held} == {"user-dan"}


# --- the identity cache ---------------------------------------------------


class StubUserRepo:
    def __init__(self, users, *, hang=False):
        self._users = users
        self._hang = hang
        self.reads = 0

    async def get_by_id(self, user_id):
        self.reads += 1
        if self._hang:
            await asyncio.sleep(3600)
        return self._users.get(user_id)


class StubUser:
    def __init__(self, user_id, name, *, guest=False):
        self.id = user_id
        self.display_name = name
        self.name_color = None if guest else "#4f9"
        self.is_anonymous = guest


@pytest.mark.asyncio
async def test_warming_reads_once_and_then_answers_from_memory():
    repo = StubUserRepo({"user-1": StubUser("user-1", "Ada")})
    cache = PresenceIdentityCache(repo)
    await cache.warm("user-1")
    await cache.warm("user-1")
    assert repo.reads == 1
    assert cache.cached(["user-1"])["user-1"].display_name == "Ada"


@pytest.mark.asyncio
async def test_invalidation_makes_the_next_warm_read_again():
    """The four writers of a display name all come through here."""
    repo = StubUserRepo({"user-1": StubUser("user-1", "Ada")})
    cache = PresenceIdentityCache(repo)
    await cache.warm("user-1")
    cache.invalidate("user-1")
    assert cache.cached(["user-1"]) == {}
    repo._users["user-1"] = StubUser("user-1", "Adalovelace")
    await cache.warm("user-1")
    assert cache.cached(["user-1"])["user-1"].display_name == "Adalovelace"


@pytest.mark.asyncio
async def test_a_read_that_never_answers_leaves_the_row_out(monkeypatch):
    """Never a blank name, and never a snapshot that waits on a database."""
    monkeypatch.setattr("app.services.presence.IDENTITY_TIMEOUT_SECONDS", 0.01)
    cache = PresenceIdentityCache(StubUserRepo({}, hang=True))
    await cache.warm("user-1")
    assert cache.cached(["user-1"]) == {}


@pytest.mark.asyncio
async def test_the_cache_is_bounded():
    users = {f"user-{i}": StubUser(f"user-{i}", f"p{i}") for i in range(10)}
    cache = PresenceIdentityCache(StubUserRepo(users), max_cached=4)
    for user_id in users:
        await cache.warm(user_id)
    assert cache.cached_accounts() == 4


# --- the broadcaster ------------------------------------------------------


class RecordingSio:
    def __init__(self):
        self.emitted = []

    async def emit(self, event, payload=None, room=None, **_):
        self.emitted.append((event, payload, room))


def broadcaster_for(registry, room_manager, cache):
    return PresenceBroadcaster(
        RecordingSio(), registry, cache, room_manager, environ={}
    )


@pytest.mark.asyncio
async def test_a_tick_with_nothing_to_say_emits_nothing_and_holds_the_revision():
    registry = PresenceRegistry()
    cache = PresenceIdentityCache(None)
    caster = broadcaster_for(registry, RoomManager(), cache)
    assert await caster.flush() is None
    assert caster.revision == 0
    assert caster._sio.emitted == []


@pytest.mark.asyncio
async def test_a_change_is_broadcast_once_with_the_next_revision():
    registry = PresenceRegistry()
    cache = PresenceIdentityCache(None)
    cache.remember(identity("user-1", "Ada"))
    caster = broadcaster_for(registry, RoomManager(), cache)
    registry.note_socket_opened("sid-a", "user-1")

    delta = await caster.flush()
    assert delta is not None and caster.revision == 1
    event, payload, room = caster._sio.emitted[0]
    assert event == "lobby_presence_changed"
    assert room == "lobby"
    assert [row["userId"] for row in payload["joined"]] == ["user-1"]
    # Nothing moved since, so the next tick is silent.
    assert await caster.flush() is None
    assert len(caster._sio.emitted) == 1


@pytest.mark.asyncio
async def test_the_count_moving_alone_is_still_worth_broadcasting():
    """An account beyond the cap changes 'showing 100 of 412' and nothing else."""
    registry = PresenceRegistry()
    cache = PresenceIdentityCache(None)
    for index in range(3):
        cache.remember(identity(f"user-{index}", f"player{index}"))
        registry.note_socket_opened(f"sid-{index}", f"user-{index}")
    caster = PresenceBroadcaster(
        RecordingSio(),
        registry,
        cache,
        RoomManager(),
        environ={"PRESENCE_LIST_LIMIT": "2"},
    )
    await caster.flush()
    before = len(caster._sio.emitted)

    # A fourth account, past the cap: the list is identical, the total is not.
    cache.remember(identity("user-9", "zzz"))
    registry.note_socket_opened("sid-9", "user-9")
    delta = await caster.flush()
    assert delta is not None and delta.is_empty
    assert delta.online_count == 4
    assert len(caster._sio.emitted) == before + 1


@pytest.mark.asyncio
async def test_a_new_watcher_is_handed_the_revision_already_broadcast():
    """So its first delta is the next one in the same sequence, not a gap."""
    registry = PresenceRegistry()
    cache = PresenceIdentityCache(None)
    cache.remember(identity("user-1", "Ada"))
    registry.note_socket_opened("sid-a", "user-1")
    caster = broadcaster_for(registry, RoomManager(), cache)
    await caster.flush()

    # Somebody arrives between ticks: the watcher sees them immediately, but
    # is still stamped with the revision the channel is on.
    cache.remember(identity("user-2", "Bob"))
    registry.note_socket_opened("sid-b", "user-2")
    snapshot = caster.snapshot_for_watcher()
    assert snapshot.revision == caster.revision == 1
    assert {entry.user_id for entry in snapshot.entries} == {"user-1", "user-2"}

    # And the delta that follows is idempotent against what it already had.
    delta = await caster.flush()
    assert delta.revision == 2
    assert apply_delta(snapshot.entries, delta) == caster._last.entries


@pytest.mark.asyncio
async def test_the_loop_records_a_healthy_tick_and_survives_a_broken_one():
    """A fourth supervised loop, so `/api/health` has to be able to tell.

    Swallowing everything but cancellation is what stops one bad tick ending
    the lobby's updates for the life of the process - and is also what makes a
    loop failing every single time indistinguishable from a working one, from
    outside. The counters are that distinction.
    """
    from app.services.readiness import LoopHealth
    from app.services.presence import start_presence_loop, stop_presence_loop

    registry = PresenceRegistry()
    cache = PresenceIdentityCache(None)
    caster = PresenceBroadcaster(
        RecordingSio(),
        registry,
        cache,
        RoomManager(),
        environ={"PRESENCE_BROADCAST_INTERVAL_MS": "1"},
    )
    health = LoopHealth("presence_broadcast")
    task = start_presence_loop(caster, health=health)
    for _ in range(200):
        await asyncio.sleep(0)
        if health.last_success is not None:
            break
    assert health.last_success is not None, "a quiet tick never reported success"

    async def explode():
        raise RuntimeError("the channel is gone")

    caster.flush = explode
    for _ in range(400):
        await asyncio.sleep(0)
        if health.total_failures:
            break
    assert health.total_failures, "a broken tick was invisible from outside"

    await stop_presence_loop(task)
    assert task.cancelled() or task.done()
    # Stopping something that was never started is not an error: the lifespan
    # runs this in a `finally` that also covers a startup which never got here.
    await stop_presence_loop(None)


def test_a_ceiling_that_is_not_a_positive_number_falls_back(caplog):
    """Configurable, but never into a value that would break the feature."""
    from app.services.presence import (
        DEFAULT_BROADCAST_INTERVAL_MS,
        DEFAULT_LIST_LIMIT,
    )

    caster = PresenceBroadcaster(
        RecordingSio(),
        PresenceRegistry(),
        PresenceIdentityCache(None),
        RoomManager(),
        environ={
            "PRESENCE_LIST_LIMIT": "not a number",
            "PRESENCE_BROADCAST_INTERVAL_MS": "-5",
        },
    )
    assert caster.list_limit == DEFAULT_LIST_LIMIT
    assert caster.interval_ms == DEFAULT_BROADCAST_INTERVAL_MS

    blank = PresenceBroadcaster(
        RecordingSio(),
        PresenceRegistry(),
        PresenceIdentityCache(None),
        RoomManager(),
        environ={"PRESENCE_LIST_LIMIT": "   "},
    )
    assert blank.list_limit == DEFAULT_LIST_LIMIT


@pytest.mark.asyncio
async def test_a_repository_that_raises_leaves_the_row_out():
    class BrokenRepo:
        async def get_by_id(self, user_id):
            raise RuntimeError("the database is down")

    cache = PresenceIdentityCache(BrokenRepo())
    await cache.warm("user-1")
    assert cache.cached(["user-1"]) == {}


@pytest.mark.asyncio
async def test_an_account_that_no_longer_exists_is_not_remembered():
    cache = PresenceIdentityCache(StubUserRepo({}))
    await cache.warm("user-gone")
    assert cache.cached_accounts() == 0


@pytest.mark.asyncio
async def test_a_merge_clears_every_cached_identity():
    """Aliases move names between accounts, so none of them is trustworthy."""
    cache = PresenceIdentityCache(StubUserRepo({}))
    cache.remember(identity("user-1", "Ada"))
    cache.remember(identity("user-2", "Bob"))
    cache.clear()
    assert cache.cached_accounts() == 0


@pytest.mark.asyncio
async def test_warming_without_a_repository_is_a_no_op():
    """The handler stack is built without a database in most of the suite."""
    cache = PresenceIdentityCache(None)
    await cache.warm("user-1")
    await cache.warm(None)
    assert cache.cached_accounts() == 0

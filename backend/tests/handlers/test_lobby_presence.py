"""Presence across the socket lifecycle, and the lobby channel it feeds.

The registry is a ledger, so the cases that matter are the ways *out*: a
handshake refused before the disconnect handler ever runs, a socket this
server closed from inside a seat transition, and the ordinary drop. Each one
that fails to balance leaves an account listed as reachable when nothing is
listening on it - and in #529 a friend request delivered into that silence.

The invariant every case ends on is the same one the socket ledger holds:
presence never tracks more sockets than are open.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio
from socketio.exceptions import ConnectionRefusedError

from app.handlers import register_all_handlers as register_handlers
from app.protocol import PROTOCOL_VERSION
from app.rooms import RoomManager
from app.services.presence import LOBBY_CHANNEL, STATUS_PLAYING
from tests.handlers.helpers import SessionStore


def build_stack(room_manager: RoomManager, **kwargs):
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, **kwargs)
    sessions = SessionStore()
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return ctx, sio, sessions


class StubResolution:
    def __init__(self, user_id=None, banned_user_id=None):
        self.session = None if user_id is None else _StubSession(user_id)
        self.banned_user_id = banned_user_id


class _StubSession:
    def __init__(self, user_id):
        self.user_id = user_id


def account_cookies(monkeypatch, mapping, *, banned=()):
    """Make the handshake resolve a cookie to an account, without a database."""

    async def resolve(_factory, token, **_kwargs):
        if token in banned:
            return StubResolution(banned_user_id=mapping.get(token))
        return StubResolution(user_id=mapping.get(token))

    monkeypatch.setattr("app.handlers.connection.resolve_session_status", resolve)


def environ_for(token: str) -> dict:
    return {"HTTP_COOKIE": f"sketchy_session={token}"}


async def connect_as(ctx, sio, sid, token):
    ctx.session_factory = lambda: None
    return await sio.handlers["/"]["connect"](
        sid, environ_for(token), {"protocol": PROTOCOL_VERSION}
    )


def assert_balanced(ctx):
    """Presence may never claim more sockets than the process holds open."""
    assert ctx.presence.tracked_sockets() <= ctx.room_capacity.open_sockets


@pytest.mark.asyncio
async def test_a_handshake_registers_the_account_and_a_disconnect_releases_it(
    monkeypatch,
):
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})

    await connect_as(ctx, sio, "sid-a", "tok-ada")
    assert ctx.presence.is_online("user-ada")
    assert_balanced(ctx)

    await sio.handlers["/"]["disconnect"]("sid-a")
    assert not ctx.presence.is_online("user-ada")
    assert ctx.presence.tracked_sockets() == 0


@pytest.mark.asyncio
async def test_a_visitor_who_has_not_chosen_a_name_is_not_in_the_list(monkeypatch):
    """R-ACCT-02: a socket alone never makes an account, so this is ordinary."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {})

    await connect_as(ctx, sio, "sid-anon", "tok-none")
    assert ctx.presence.online_accounts == 0
    assert_balanced(ctx)


@pytest.mark.asyncio
async def test_a_socket_refused_for_capacity_leaves_nothing_behind(monkeypatch):
    """It is told and then closed, and never reaches the disconnect handler."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    ctx.room_capacity.sockets = 0

    await connect_as(ctx, sio, "sid-a", "tok-ada")

    assert ctx.presence.online_accounts == 0
    assert ctx.room_capacity.open_sockets == 0
    assert_balanced(ctx)


@pytest.mark.asyncio
async def test_a_suspended_account_is_refused_and_never_appears_online(monkeypatch):
    """`ConnectionRefusedError` is answered with CONNECT_ERROR, not a disconnect."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-banned": "user-banned"}, banned={"tok-banned"})

    with pytest.raises(ConnectionRefusedError):
        await connect_as(ctx, sio, "sid-banned", "tok-banned")

    assert ctx.presence.online_accounts == 0
    assert ctx.room_capacity.open_sockets == 0
    assert_balanced(ctx)


@pytest.mark.asyncio
async def test_a_handshake_that_explodes_leaves_nothing_behind(monkeypatch):
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)

    async def explode(*_args, **_kwargs):
        raise RuntimeError("the session store is down")

    monkeypatch.setattr("app.handlers.connection.resolve_session_status", explode)

    with pytest.raises(RuntimeError):
        await connect_as(ctx, sio, "doomed", "tok-ada")

    assert ctx.presence.online_accounts == 0
    assert_balanced(ctx)


@pytest.mark.asyncio
async def test_a_handshake_that_fails_after_registering_still_balances(monkeypatch):
    """The `finally` earns its place here, and nowhere else.

    Every refusal the handshake performs on purpose - the socket ceiling, a
    suspension, a session store that will not answer - happens *before* the
    account is registered, so none of them can prove this. What can is a
    failure in the tail: the account is on the books by then, and the socket
    is torn down by Socket.IO answering CONNECT_ERROR rather than by the
    disconnect handler, so without the `finally` the account stays listed as
    online for the life of the process with nothing listening on it.
    """
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})

    async def emit(event, *args, **kwargs):
        if event == "client_config":
            raise RuntimeError("the socket went away mid-handshake")

    sio.emit = AsyncMock(side_effect=emit)

    with pytest.raises(RuntimeError):
        await connect_as(ctx, sio, "sid-a", "tok-ada")

    assert ctx.presence.online_accounts == 0
    assert ctx.room_capacity.open_sockets == 0
    assert_balanced(ctx)


@pytest.mark.asyncio
async def test_a_socket_this_server_closes_still_drains(monkeypatch):
    """The `is_closing` branch returns early; the drain sits above it.

    This is the tab a reconnect superseded: Socket.IO runs its disconnect
    handler inline from inside the transition that closed it, so it never
    queues at the seating gate - and a drain placed below that branch would
    only ever run for connections that dropped on their own.
    """
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    await connect_as(ctx, sio, "sid-a", "tok-ada")

    with ctx.closing("sid-a"):
        await sio.handlers["/"]["disconnect"]("sid-a")

    assert not ctx.presence.is_online("user-ada")
    assert ctx.presence.tracked_sockets() == 0


@pytest.mark.asyncio
async def test_two_tabs_of_one_account_survive_one_of_them_closing(monkeypatch):
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})

    await connect_as(ctx, sio, "sid-a", "tok-ada")
    await connect_as(ctx, sio, "sid-b", "tok-ada")
    assert ctx.presence.online_accounts == 1

    await sio.handlers["/"]["disconnect"]("sid-a")
    assert ctx.presence.is_online("user-ada")
    await sio.handlers["/"]["disconnect"]("sid-b")
    assert not ctx.presence.is_online("user-ada")


@pytest.mark.asyncio
async def test_a_mid_game_drop_leaves_the_seat_but_not_the_presence(monkeypatch):
    """The R-CONN-01 grace protects a seat, not a claim to be reachable.

    The player keeps their place in the turn order for thirty seconds. They
    are not online for any of them: nothing is listening on that socket, and
    a list that said otherwise would be wrong about the one thing it is for.
    """
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    room = room_manager.create_room(name="Studio", is_public=True)
    player = room_manager.add_player(
        room, "Ada", user_id="user-ada", is_anonymous=False
    )
    player.sid = "sid-a"
    await connect_as(ctx, sio, "sid-a", "tok-ada")

    await sio.handlers["/"]["disconnect"]("sid-a")

    assert not ctx.presence.is_online("user-ada")
    assert room.players[player.id] is player, "the seat was evicted, not graced"
    assert player.connected is False
    await ctx.timers.close()


# --- the channel ----------------------------------------------------------


@pytest.mark.asyncio
async def test_watching_the_lobby_answers_with_a_baseline_to_apply_to(monkeypatch):
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada", "tok-bob": "user-bob"})
    ctx.presence_identities.remember(
        _identity("user-ada", "Ada")
    )
    ctx.presence_identities.remember(_identity("user-bob", "Bob"))
    await connect_as(ctx, sio, "sid-a", "tok-ada")
    await connect_as(ctx, sio, "sid-b", "tok-bob")

    answer = await sio.handlers["/"]["watch_lobby"]("sid-a", None)

    assert answer["ok"] is True
    assert answer["revision"] == 0
    assert answer["onlineCount"] == 2
    assert [row["displayName"] for row in answer["players"]] == ["Ada", "Bob"]
    sio.enter_room.assert_awaited_with("sid-a", LOBBY_CHANNEL)


@pytest.mark.asyncio
async def test_one_acknowledgement_carries_both_baselines(monkeypatch):
    """One subscription, two feeds, and no window between them.

    Two acknowledgements would leave a moment in which this socket is on the
    channel receiving room deltas against a list it has not been given - the
    exact gap `watch_lobby` answering with the snapshot exists to close, now
    that there are two things to be given.
    """
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    ctx.presence_identities.remember(_identity("user-ada", "Ada"))
    await connect_as(ctx, sio, "sid-a", "tok-ada")
    public = room_manager.create_room(name="Open", is_public=True)
    room_manager.create_room(name="Hidden", is_public=False)

    answer = await sio.handlers["/"]["watch_lobby"]("sid-a", None)

    assert answer["ok"] is True
    # Named separately from the presence revision, because they move
    # separately - a room filling up must not look like presence news.
    assert answer["roomsRevision"] == 0
    assert [room["id"] for room in answer["rooms"]] == [public.id]
    assert "revision" in answer and "players" in answer


@pytest.mark.asyncio
async def test_the_acknowledged_room_list_never_carries_a_private_room(monkeypatch):
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    await connect_as(ctx, sio, "sid-a", "tok-ada")
    hidden = room_manager.create_room(name="Hidden", is_public=False)

    answer = await sio.handlers["/"]["watch_lobby"]("sid-a", None)
    assert answer["rooms"] == []
    assert hidden.code not in repr(answer)


@pytest.mark.asyncio
async def test_a_room_change_reaches_the_channel_and_nowhere_else(monkeypatch):
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    await connect_as(ctx, sio, "sid-a", "tok-ada")
    await sio.handlers["/"]["watch_lobby"]("sid-a", None)

    room = room_manager.create_room(name="Open", is_public=True)
    await ctx.presence_broadcaster.flush()

    frames = [
        call for call in sio.emit.await_args_list
        if call.args and call.args[0] == "lobby_rooms_changed"
    ]
    assert len(frames) == 1
    assert frames[0].kwargs["room"] == LOBBY_CHANNEL
    assert [entry["id"] for entry in frames[0].args[1]["opened"]] == [room.id]


@pytest.mark.asyncio
async def test_leaving_the_lobby_leaves_the_channel(monkeypatch):
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    await connect_as(ctx, sio, "sid-a", "tok-ada")

    assert (await sio.handlers["/"]["unwatch_lobby"]("sid-a", None))["ok"] is True
    sio.leave_room.assert_awaited_with("sid-a", LOBBY_CHANNEL)


@pytest.mark.asyncio
async def test_a_change_is_broadcast_to_the_channel_and_nowhere_else(monkeypatch):
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    ctx.presence_identities.remember(_identity("user-ada", "Ada"))
    await connect_as(ctx, sio, "sid-a", "tok-ada")
    sio.emit.reset_mock()

    await ctx.presence_broadcaster.flush()

    broadcasts = [
        call for call in sio.emit.await_args_list
        if call.args and call.args[0] == "lobby_presence_changed"
    ]
    assert len(broadcasts) == 1
    assert broadcasts[0].kwargs["room"] == LOBBY_CHANNEL
    assert [row["userId"] for row in broadcasts[0].args[1]["joined"]] == ["user-ada"]


@pytest.mark.asyncio
async def test_a_seated_account_reads_playing_and_a_second_tab_does_not_change_it(
    monkeypatch,
):
    """Seats are matched by socket (R-ROOM-08); presence is keyed by account."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    ctx.presence_identities.remember(_identity("user-ada", "Ada"))
    room = room_manager.create_room(name="Studio", is_public=True)
    seat = room_manager.add_player(room, "Ada", user_id="user-ada", is_anonymous=False)
    seat.sid = "sid-a"
    await connect_as(ctx, sio, "sid-a", "tok-ada")
    await connect_as(ctx, sio, "sid-b", "tok-ada")

    answer = await sio.handlers["/"]["watch_lobby"]("sid-b", None)

    assert answer["onlineCount"] == 1
    assert [row["status"] for row in answer["players"]] == [STATUS_PLAYING]


@pytest.mark.asyncio
async def test_no_presence_payload_names_the_room_anybody_is_in(monkeypatch):
    """A private room must not become discoverable by watching the lobby."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    ctx.presence_identities.remember(_identity("user-ada", "Ada"))
    room = room_manager.create_room(name="Hidden Studio", is_public=False)
    room_manager.add_player(room, "Ada", user_id="user-ada", is_anonymous=False)
    await connect_as(ctx, sio, "sid-a", "tok-ada")
    sio.emit.reset_mock()

    answer = await sio.handlers["/"]["watch_lobby"]("sid-a", None)
    await ctx.presence_broadcaster.flush()

    timeline = json.dumps(
        [answer]
        + [
            [call.args[0], call.args[1] if len(call.args) > 1 else None]
            for call in sio.emit.await_args_list
        ]
    )
    assert room.id not in timeline
    assert room.code not in timeline
    assert room.name not in timeline


@pytest.mark.asyncio
async def test_watching_the_lobby_answers_to_a_budget():
    """`ctx.on` is the only way in, so this is really a check that it was used."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    budget = ctx.command_budgets.for_command("watch_lobby")

    refusals = []
    for _ in range(budget.limit + 5):
        answer = await sio.handlers["/"]["watch_lobby"]("sid-flood", None)
        if not answer.get("ok"):
            refusals.append(answer)

    assert refusals, "an unbounded command reached the registry"


def _identity(user_id, name):
    from app.services.presence import PresenceIdentity

    return PresenceIdentity(
        user_id=user_id, display_name=name, name_color="#4f9", is_anonymous=False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["watch_lobby", "unwatch_lobby"])
async def test_a_payload_where_none_belongs_is_refused(command):
    """Neither command takes arguments, and unknown fields are never ignored."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)

    answer = await sio.handlers["/"][command]("sid-a", {"roomId": "sneaky"})

    assert answer["ok"] is False
    sio.enter_room.assert_not_awaited()
    sio.leave_room.assert_not_awaited()
    assert ctx is not None


@pytest.mark.asyncio
async def test_a_merged_guest_is_one_person_in_the_list(monkeypatch):
    """Signing in must not leave the guest behind as a second online player."""
    from app.services.presence import PresenceIdentity

    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-guest": "guest", "tok-account": "account"})
    ctx.presence_identities.remember(
        PresenceIdentity(
            user_id="guest",
            display_name="Guest",
            name_color=None,
            is_anonymous=True,
        )
    )
    ctx.presence_identities.remember(_identity("account", "Ada"))

    # Two tabs as a guest, then a sign-in on a third as the account.
    await connect_as(ctx, sio, "guest-tab-1", "tok-guest")
    await connect_as(ctx, sio, "guest-tab-2", "tok-guest")
    await connect_as(ctx, sio, "account-tab", "tok-account")
    assert ctx.presence.online_accounts == 2

    ctx.presence.rekey("guest", "account")

    answer = await sio.handlers["/"]["watch_lobby"]("account-tab", None)
    assert answer["onlineCount"] == 1
    assert [row["displayName"] for row in answer["players"]] == ["Ada"]
    # And the sockets are still open: a merge is not a ban.
    assert ctx.room_capacity.open_sockets == 3
    assert_balanced(ctx)


@pytest.mark.asyncio
async def test_an_in_room_colour_change_reaches_the_lobby(monkeypatch):
    """The fifth writer of an account's identity, and the easiest to miss.

    A registered player changing colour mid-room writes it to their account,
    which is what the lobby's list shows. The cache is warmed at the handshake
    and nothing re-handshakes for a colour change, so without invalidating it
    the lobby keeps the old one - and the tick's repair does not help, because
    a stale entry is a hit rather than a miss.
    """
    from app.services.presence import PresenceIdentity

    room_manager = RoomManager()
    ctx, sio, sessions = build_stack(room_manager)
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})
    ctx.presence_identities.remember(
        PresenceIdentity(
            user_id="user-ada",
            display_name="Ada",
            name_color="#111111",
            is_anonymous=False,
        )
    )
    ctx.user_repo = SimpleNamespace(update_profile=AsyncMock())
    room = room_manager.create_room(name="Studio", is_public=True)
    seat = room_manager.add_player(
        room, "Ada", user_id="user-ada", is_anonymous=False
    )
    seat.sid = "sid-a"
    await connect_as(ctx, sio, "sid-a", "tok-ada")
    await sessions.save("sid-a", {"room_id": room.id, "player_id": seat.id})

    await sio.handlers["/"]["update_player_settings"](
        "sid-a", {"nameColor": "#4f9a2b"}
    )

    ctx.user_repo.update_profile.assert_awaited()
    assert ctx.presence_identities.cached(["user-ada"]) == {}


@pytest.mark.asyncio
async def test_a_handshake_warms_who_has_muted_the_account(monkeypatch):
    """A lobby line has no seat to warm the block filter at, so the handshake
    is where a sender's entry is read - and only for a socket with an
    account, since a visitor without one has nobody's list to be on."""
    room_manager = RoomManager()
    ctx, sio, _ = build_stack(room_manager)
    ctx.block_service = SimpleNamespace(warm=AsyncMock(), blockers_of=AsyncMock())
    account_cookies(monkeypatch, {"tok-ada": "user-ada"})

    await connect_as(ctx, sio, "sid-a", "tok-ada")
    ctx.block_service.warm.assert_awaited_once_with("user-ada")

    await connect_as(ctx, sio, "sid-anon", "tok-none")
    ctx.block_service.warm.assert_awaited_once()

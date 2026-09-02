"""Lobby chat: said once, heard by every open lobby, minus whoever muted the author.

A line is an event on the lobby channel rather than a feed of it, so the cases
that matter are the ones a feed would have answered differently: it goes out
the moment it is said, an arrival is handed the recent lines in the same
acknowledgement as the other baselines, and a block narrows one line's
recipients without anybody resyncing over the gap.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import socketio

from app.handlers import register_all_handlers as register_handlers
from app.handlers.lobby import (
    EMPTY_LINE,
    IDENTITY_UNAVAILABLE,
    NAME_REQUIRED,
    NOT_WATCHING,
)
from app.rooms import RoomManager
from app.services.lobby_chat import LOBBY_CHAT_BACKLOG
from app.services.presence import LOBBY_CHANNEL, PresenceIdentity
from tests.handlers.helpers import SessionStore
from tests.handlers.test_lobby_presence import account_cookies, connect_as


class FakeManager:
    """Just enough of Socket.IO's room bookkeeping for a channel to have members."""

    def __init__(self) -> None:
        self._rooms: dict[str, list[str]] = {}

    async def enter(self, sid, room, namespace=None) -> None:
        members = self._rooms.setdefault(room, [])
        if sid not in members:
            members.append(sid)

    async def leave(self, sid, room, namespace=None) -> None:
        members = self._rooms.get(room, [])
        if sid in members:
            members.remove(sid)

    def get_participants(self, namespace, room):
        assert namespace == "/"
        for sid in list(self._rooms.get(room, [])):
            yield sid, f"eio-{sid}"

    def get_rooms(self, sid, namespace):
        assert namespace == "/"
        return [room for room, members in self._rooms.items() if sid in members]


def build_stack(**kwargs):
    room_manager = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    ctx = register_handlers(sio, room_manager, **kwargs)
    sessions = SessionStore(accounts=False)
    manager = FakeManager()
    sio.manager = manager
    sio.get_session = AsyncMock(side_effect=sessions.get)
    sio.save_session = AsyncMock(side_effect=sessions.save)
    sio.enter_room = AsyncMock(side_effect=manager.enter)
    sio.leave_room = AsyncMock(side_effect=manager.leave)
    sio.disconnect = AsyncMock()
    sio.emit = AsyncMock()
    return ctx, sio, room_manager


def identity(user_id, name, *, anonymous=False):
    return PresenceIdentity(
        user_id=user_id,
        display_name=name,
        name_color=None if anonymous else "#4f9",
        is_anonymous=anonymous,
    )


ACCOUNTS = {"tok-a": "user-ada", "tok-b": "user-bob", "tok-c": "user-carol"}
NAMES = {"user-ada": "Ada", "user-bob": "Bob", "user-carol": "Carol"}


async def arrive(ctx, sio, sid, token, *, watch=True):
    """Connect as one account and, usually, open the lobby."""
    await connect_as(ctx, sio, sid, token)
    if not watch:
        return None
    answer = await sio.handlers["/"]["watch_lobby"](sid, None)
    assert answer["ok"] is True
    return answer


def lobby_stack(monkeypatch, **kwargs):
    ctx, sio, room_manager = build_stack(**kwargs)
    account_cookies(monkeypatch, ACCOUNTS)
    for user_id, name in NAMES.items():
        ctx.presence_identities.remember(identity(user_id, name))
    return ctx, sio, room_manager


async def say(sio, sid, text):
    return await sio.handlers["/"]["send_lobby_chat"](sid, {"text": text})


def chat_emits(sio):
    return [
        call
        for call in sio.emit.await_args_list
        if call.args and call.args[0] == "lobby_chat_message"
    ]


@pytest.mark.asyncio
async def test_a_line_reaches_the_channel_and_nowhere_else(monkeypatch):
    ctx, sio, _ = lobby_stack(monkeypatch)
    await arrive(ctx, sio, "sid-a", "tok-a")
    await arrive(ctx, sio, "sid-b", "tok-b")
    sio.emit.reset_mock()

    assert await say(sio, "sid-a", "  hello  ") == {"ok": True}

    sio.emit.assert_awaited_once()
    call = sio.emit.await_args
    assert call.args[0] == "lobby_chat_message"
    assert call.kwargs == {"room": LOBBY_CHANNEL}
    payload = call.args[1]
    assert payload == {
        "seq": 1,
        "userId": "user-ada",
        "displayName": "Ada",
        "nameColor": "#4f9",
        "isAnonymous": False,
        "text": "hello",
        "sentAt": payload["sentAt"],
    }
    assert payload["sentAt"].endswith("+00:00")


@pytest.mark.asyncio
async def test_the_acknowledgement_hands_an_arrival_the_recent_lines(monkeypatch):
    """The third baseline on the one acknowledgement: nothing to place a line
    against otherwise, and the number of the last line said so the client can
    tell a line that beat the answer from one it already holds."""
    ctx, sio, _ = lobby_stack(monkeypatch)
    first = await arrive(ctx, sio, "sid-a", "tok-a")
    assert first["chat"] == [] and first["chatSeq"] == 0

    await say(sio, "sid-a", "one")
    await say(sio, "sid-a", "two")

    later = await arrive(ctx, sio, "sid-b", "tok-b")
    assert [line["text"] for line in later["chat"]] == ["one", "two"]
    assert [line["seq"] for line in later["chat"]] == [1, 2]
    assert later["chatSeq"] == 2
    # The other two baselines are still there, untouched.
    assert {"revision", "players", "onlineCount", "rooms", "roomsRevision"} <= set(later)


@pytest.mark.asyncio
async def test_the_backlog_handed_over_is_bounded(monkeypatch):
    ctx, sio, _ = lobby_stack(monkeypatch)
    await arrive(ctx, sio, "sid-a", "tok-a")
    from datetime import datetime, timezone

    for index in range(LOBBY_CHAT_BACKLOG + 10):
        ctx.lobby_chat.append(
            user_id="user-ada",
            display_name="Ada",
            name_color="#4f9",
            is_anonymous=False,
            text=f"line {index}",
            sent_at=datetime.now(timezone.utc),
        )

    answer = await arrive(ctx, sio, "sid-b", "tok-b")
    assert len(answer["chat"]) == LOBBY_CHAT_BACKLOG
    assert answer["chat"][0]["seq"] == 11
    assert answer["chatSeq"] == LOBBY_CHAT_BACKLOG + 10


@pytest.mark.asyncio
async def test_a_visitor_without_a_name_may_read_but_not_speak(monkeypatch):
    ctx, sio, _ = build_stack()
    account_cookies(monkeypatch, {})
    answer = await arrive(ctx, sio, "sid-x", "tok-none")
    assert answer["chat"] == []
    sio.emit.reset_mock()

    assert await say(sio, "sid-x", "hello") == {"ok": False, "error": NAME_REQUIRED}
    assert chat_emits(sio) == []
    assert ctx.lobby_chat.last_seq == 0


@pytest.mark.asyncio
async def test_a_socket_not_watching_the_lobby_cannot_speak_into_it(monkeypatch):
    ctx, sio, _ = lobby_stack(monkeypatch)
    await arrive(ctx, sio, "sid-a", "tok-a", watch=False)
    sio.emit.reset_mock()

    assert await say(sio, "sid-a", "hello") == {"ok": False, "error": NOT_WATCHING}
    assert chat_emits(sio) == []

    await sio.handlers["/"]["watch_lobby"]("sid-a", None)
    await sio.handlers["/"]["unwatch_lobby"]("sid-a", None)
    assert await say(sio, "sid-a", "hello") == {"ok": False, "error": NOT_WATCHING}
    assert ctx.lobby_chat.last_seq == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "   ", "x" * 501])
async def test_an_empty_or_oversized_line_is_refused_before_it_is_numbered(
    monkeypatch, text
):
    ctx, sio, _ = lobby_stack(monkeypatch)
    await arrive(ctx, sio, "sid-a", "tok-a")
    sio.emit.reset_mock()

    answer = await say(sio, "sid-a", text)
    assert answer["ok"] is False
    if text.strip() == "":
        assert answer["error"] == EMPTY_LINE
    assert chat_emits(sio) == []
    assert ctx.lobby_chat.last_seq == 0


def muted(pairs: dict[str, set[str]]):
    """A block service where `pairs` maps a sender to who muted them."""

    async def blockers_of(user_id):
        return frozenset(pairs.get(user_id, set()))

    return SimpleNamespace(blockers_of=AsyncMock(side_effect=blockers_of), warm=AsyncMock())


@pytest.mark.asyncio
async def test_a_muted_author_is_heard_by_everyone_but_the_one_who_muted_them(
    monkeypatch,
):
    """R-BLOCK-02, in the lobby: the recipient list narrows for that one line,
    the sender still sees their own, and a socket with no account - which has
    no block list - always receives."""
    ctx, sio, _ = lobby_stack(monkeypatch)
    ctx.block_service = muted({"user-ada": {"user-bob"}})
    account_cookies(monkeypatch, {**ACCOUNTS, "tok-none": None})
    for sid, token in (
        ("sid-a", "tok-a"),
        ("sid-b", "tok-b"),
        ("sid-c", "tok-c"),
        ("sid-anon", "tok-none"),
    ):
        await arrive(ctx, sio, sid, token)
    sio.emit.reset_mock()

    assert await say(sio, "sid-a", "hello") == {"ok": True}

    [call] = chat_emits(sio)
    assert "room" not in call.kwargs
    assert set(call.kwargs["to"]) == {"sid-a", "sid-c", "sid-anon"}

    # And the other way round is an ordinary broadcast: nobody muted Bob.
    sio.emit.reset_mock()
    await say(sio, "sid-b", "hi")
    [call] = chat_emits(sio)
    assert call.kwargs == {"room": LOBBY_CHANNEL}


@pytest.mark.asyncio
async def test_the_backlog_is_filtered_for_the_one_who_muted_its_author(monkeypatch):
    ctx, sio, _ = lobby_stack(monkeypatch)
    ctx.block_service = muted({"user-ada": {"user-bob"}})
    await arrive(ctx, sio, "sid-a", "tok-a")
    await say(sio, "sid-a", "hello")

    for_bob = await arrive(ctx, sio, "sid-b", "tok-b")
    for_carol = await arrive(ctx, sio, "sid-c", "tok-c")
    assert for_bob["chat"] == []
    assert [line["text"] for line in for_carol["chat"]] == ["hello"]
    # The number of the last line said is the same for both: what Bob was
    # not shown is still a line that was said, and his client must not treat
    # the next one as older than it is.
    assert for_bob["chatSeq"] == for_carol["chatSeq"] == 1


@pytest.mark.asyncio
async def test_a_block_lookup_that_answers_nobody_delivers_unfiltered(monkeypatch):
    """`BlockService` answers an empty set when the read fails inside its
    bound (R-BLOCK-06); the lobby must take that as a broadcast, not as a
    reason to hold the line or to look again."""
    ctx, sio, _ = lobby_stack(monkeypatch)
    ctx.block_service = muted({})
    await arrive(ctx, sio, "sid-a", "tok-a")
    await arrive(ctx, sio, "sid-b", "tok-b")
    sio.emit.reset_mock()

    await say(sio, "sid-a", "hello")
    [call] = chat_emits(sio)
    assert call.kwargs == {"room": LOBBY_CHANNEL}

    answer = await arrive(ctx, sio, "sid-c", "tok-c")
    assert [line["text"] for line in answer["chat"]] == ["hello"]
    ctx.block_service.blockers_of.assert_any_await("user-ada")


@pytest.mark.asyncio
async def test_a_name_the_cache_has_lost_is_read_once_before_the_line_goes(
    monkeypatch,
):
    ctx, sio, _ = lobby_stack(monkeypatch)
    await arrive(ctx, sio, "sid-a", "tok-a")
    ctx.presence_identities.invalidate("user-ada")

    async def warm(user_id):
        ctx.presence_identities.remember(identity(user_id, "Ada"))

    ctx.presence_identities.warm = AsyncMock(side_effect=warm)
    sio.emit.reset_mock()

    assert await say(sio, "sid-a", "hello") == {"ok": True}
    ctx.presence_identities.warm.assert_awaited_once_with("user-ada")
    [call] = chat_emits(sio)
    assert call.args[1]["displayName"] == "Ada"


@pytest.mark.asyncio
async def test_a_line_with_no_name_to_sign_it_is_refused(monkeypatch):
    ctx, sio, _ = lobby_stack(monkeypatch)
    await arrive(ctx, sio, "sid-a", "tok-a")
    ctx.presence_identities.invalidate("user-ada")
    ctx.presence_identities.warm = AsyncMock()
    sio.emit.reset_mock()

    assert await say(sio, "sid-a", "hello") == {
        "ok": False,
        "error": IDENTITY_UNAVAILABLE,
    }
    assert chat_emits(sio) == []
    assert ctx.lobby_chat.last_seq == 0


@pytest.mark.asyncio
async def test_a_retained_line_carries_its_identifier_and_an_unretained_one_does_not(
    monkeypatch,
):
    ctx, sio, _ = lobby_stack(monkeypatch)
    ctx.message_retention = SimpleNamespace(
        record_lobby=AsyncMock(return_value="0192-abc")
    )
    await arrive(ctx, sio, "sid-a", "tok-a")
    sio.emit.reset_mock()

    await say(sio, "sid-a", "hello")
    [call] = chat_emits(sio)
    assert call.args[1]["retainedMessageId"] == "0192-abc"
    recorded = ctx.message_retention.record_lobby.await_args.kwargs
    assert recorded["user_id"] == "user-ada"
    assert recorded["display_name"] == "Ada"
    assert recorded["text"] == "hello"
    assert recorded["sent_at"].isoformat() == call.args[1]["sentAt"]

    ctx.message_retention.record_lobby.return_value = None
    sio.emit.reset_mock()
    await say(sio, "sid-a", "again")
    [call] = chat_emits(sio)
    assert "retainedMessageId" not in call.args[1]

    answer = await arrive(ctx, sio, "sid-b", "tok-b")
    assert [line.get("retainedMessageId") for line in answer["chat"]] == [
        "0192-abc",
        None,
    ]


@pytest.mark.asyncio
async def test_no_lobby_chat_payload_names_the_room_anybody_is_in(monkeypatch):
    ctx, sio, room_manager = lobby_stack(monkeypatch)
    room = room_manager.create_room(name="Hidden Studio", is_public=False)
    room_manager.add_player(room, "Ada", user_id="user-ada", is_anonymous=False)
    await arrive(ctx, sio, "sid-a", "tok-a")
    sio.emit.reset_mock()

    await say(sio, "sid-a", "hello from a private room")
    answer = await arrive(ctx, sio, "sid-b", "tok-b")

    timeline = json.dumps(
        [answer["chat"]] + [call.args[1] for call in chat_emits(sio)]
    )
    assert room.id not in timeline
    assert room.code not in timeline
    assert room.name not in timeline


@pytest.mark.asyncio
async def test_speaking_answers_to_its_own_budget(monkeypatch):
    """A lobby line reaches every open lobby, so it is not a `conversation`
    line: tightening one must never tighten guessing."""
    ctx, sio, _ = lobby_stack(monkeypatch)
    await arrive(ctx, sio, "sid-a", "tok-a")
    budget = ctx.command_budgets.for_command("send_lobby_chat")
    assert budget != ctx.command_budgets.for_command("send_chat")

    for index in range(budget.limit):
        assert (await say(sio, "sid-a", f"line {index}"))["ok"] is True
    refused = await say(sio, "sid-a", "one more")
    assert refused["ok"] is False and "too quickly" in refused["error"]
    assert ctx.lobby_chat.last_seq == budget.limit

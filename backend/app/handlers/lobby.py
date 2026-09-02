"""Socket.IO handlers for the lobby: its online player list, and its chat.

Membership of the lobby channel is asked for by the client rather than
derived from whether it holds a seat. Two reasons, and both matter:

* Watching a list is not a seat transition, so putting it under the seating
  gate would queue every lobby view behind whatever is currently seating -
  the same "work that is not part of making the seat" that was moved out from
  under the gate once already.
* Seats are matched by socket, never by account (R-ROOM-08), so a player
  seated in one tab may perfectly well have the lobby open in another. Seat
  state is the wrong question to ask.

A socket that never asks is never in the channel, which is what bounds the
fan-out to the lobbies actually open. Nothing has to leave it on the way out:
Socket.IO drops a closed socket from its rooms itself, as it does for the
per-account `user:{id}` room.

Chat rides the same channel but is not a third feed of the broadcaster's. The
two feeds describe state - who is online, which rooms are open - rebuilt on a
tick, diffed, and numbered so a client can resync across a gap. A chat line is
an event with nothing to rebuild it from, a tick is latency a conversation
feels, and a gap in it is expected: a line is deliberately not delivered to
somebody who blocked its author. So a line goes out from here the moment it is
accepted, and the acknowledgement hands an arrival the last few, the way it
hands over the other two baselines - there must be no window in which a socket
is in the channel receiving lines it cannot place.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import partial

from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    TextPayload,
    parse_empty_payload,
    parse_payload,
)
from app.services.presence import LOBBY_CHANNEL, PresenceIdentity

NAME_REQUIRED = "Choose a name to chat."
NOT_WATCHING = "Open the lobby to chat."
EMPTY_LINE = "Message cannot be empty"
IDENTITY_UNAVAILABLE = "Try again in a moment."


async def _user_of(ctx: HandlerContext, sid) -> str | None:
    session = await ctx.sio.get_session(sid)
    return session.get("user_id") if session else None


async def _hidden_authors_for(
    ctx: HandlerContext, watcher: str | None, authors: set[str]
) -> set[str]:
    """Which of these authors the watcher has blocked.

    One bounded lookup per author, together rather than in turn. A lookup
    that does not answer says "nobody", so that author's lines are shown
    rather than withheld - the same ranking of failures as room chat
    (R-BLOCK-06): a block is a presentation filter, and a line silently
    missing is a failure nobody can see.
    """
    if watcher is None or ctx.block_service is None or not authors:
        return set()
    ordered = sorted(authors)
    blockers = await asyncio.gather(
        *(ctx.block_service.blockers_of(author) for author in ordered)
    )
    return {
        author
        for author, who in zip(ordered, blockers, strict=True)
        if watcher in who
    }


async def watch_lobby(ctx: HandlerContext, sid, data=None):
    """Join the lobby channel, answering with every baseline to apply to.

    Presence and the public room list, each with its own revision, and the
    recent chat with the number of the last line said. The channel is what a
    lobby opens instead of polling `GET /api/rooms` every four seconds
    (#462); the endpoint stays for operators and for the tests that pin its
    shape, and nothing in the app asks it any more.
    """
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    await ctx.sio.enter_room(sid, LOBBY_CHANNEL)
    feed = ctx.presence_broadcaster
    rooms = feed.rooms_for_watcher()
    # A line said between joining the channel and reading the backlog is in
    # both the backlog and a delta that beat this answer; the client's
    # sequence numbers make that a duplicate it ignores, not a line it shows
    # twice. Nothing here depends on the order of the two.
    hidden = await _hidden_authors_for(
        ctx, await _user_of(ctx, sid), ctx.lobby_chat.authors()
    )
    return {
        "ok": True,
        **feed.snapshot_for_watcher().payload(),
        # The room list rides the same acknowledgement rather than a first
        # delta, for the reason presence does: there must be no window in
        # which the socket is in the channel and receiving changes against a
        # list it has not been given. Its own revision, because the two feeds
        # move independently.
        "rooms": rooms.payload()["rooms"],
        "roomsRevision": rooms.revision,
        "chat": [
            line.payload()
            for line in ctx.lobby_chat.backlog_for(hidden_authors=hidden)
        ],
        "chatSeq": ctx.lobby_chat.last_seq,
    }


async def unwatch_lobby(ctx: HandlerContext, sid, data=None):
    """Leave the channel - the lobby was navigated away from, not closed."""
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    await ctx.sio.leave_room(sid, LOBBY_CHANNEL)
    return {"ok": True}


async def _identity_of(ctx: HandlerContext, user_id: str) -> PresenceIdentity | None:
    """The name and colour a line is signed with, from the cache the tick keeps.

    Warmed at the handshake and repaired by the tick, so a miss is an
    eviction or a read that failed; one bounded read here is cheaper than
    refusing a line for a cache's housekeeping. Still missing after that is
    a refusal, because a line with no name is worse than no line.
    """
    cached = ctx.presence_identities.cached([user_id])
    if user_id not in cached:
        await ctx.presence_identities.warm(user_id)
        cached = ctx.presence_identities.cached([user_id])
    return cached.get(user_id)


async def _emit_lobby_chat(ctx: HandlerContext, line, *, sender_user_id: str) -> None:
    """One broadcast, or a recipient list when somebody has muted the author.

    The same shape as room chat's `_emit_player_chat`: a block narrows who is
    sent this one line and nothing else. A socket with no account has no
    block list and always receives; the sender is never in their own
    blockers, so they always see their line.
    """
    blockers = (
        await ctx.block_service.blockers_of(sender_user_id)
        if ctx.block_service is not None
        else frozenset()
    )
    payload = line.payload()
    if not blockers:
        await ctx.sio.emit("lobby_chat_message", payload, room=LOBBY_CHANNEL)
        return
    recipients = [
        member
        for member, _ in ctx.sio.manager.get_participants("/", LOBBY_CHANNEL)
        if (ctx.presence.user_for_sid(member) or "") not in blockers
    ]
    if recipients:
        await ctx.sio.emit("lobby_chat_message", payload, to=recipients)


async def send_lobby_chat(ctx: HandlerContext, sid, data):
    """Say one line to every lobby that is open.

    Every refusal comes before the line is numbered or kept, so a refused
    line never spends a sequence number and never shows up in a backlog.
    Anyone with an account may speak - a guest included, the same boundary
    as the online list - and only from a socket that is watching, since a
    line to a lobby the sender cannot see is a line they cannot be answered
    in.
    """
    try:
        payload = parse_payload(TextPayload, data)
    except PayloadError as error:
        return error.acknowledgement()
    text = payload.text.strip()
    if not text:
        return {"ok": False, "error": EMPTY_LINE}
    user_id = await _user_of(ctx, sid)
    if not user_id:
        return {"ok": False, "error": NAME_REQUIRED}
    if LOBBY_CHANNEL not in ctx.sio.rooms(sid):
        return {"ok": False, "error": NOT_WATCHING}
    identity = await _identity_of(ctx, user_id)
    if identity is None:
        return {"ok": False, "error": IDENTITY_UNAVAILABLE}
    # One instant for the wire and for the retained row, so the time a
    # watcher sees beside the line is the time a moderator sees on it.
    sent_at = datetime.now(timezone.utc)
    retained_id = (
        await ctx.message_retention.record_lobby(
            user_id=user_id,
            display_name=identity.display_name,
            name_color=identity.name_color,
            is_anonymous=identity.is_anonymous,
            text=text,
            sent_at=sent_at,
        )
        if ctx.message_retention is not None
        else None
    )
    line = ctx.lobby_chat.append(
        user_id=user_id,
        display_name=identity.display_name,
        name_color=identity.name_color,
        is_anonymous=identity.is_anonymous,
        text=text,
        sent_at=sent_at,
        retained_message_id=retained_id,
    )
    await _emit_lobby_chat(ctx, line, sender_user_id=user_id)
    return {"ok": True}


def register(ctx: HandlerContext) -> None:
    ctx.on("watch_lobby", handler=partial(watch_lobby, ctx))
    ctx.on("unwatch_lobby", handler=partial(unwatch_lobby, ctx))
    ctx.on("send_lobby_chat", handler=partial(send_lobby_chat, ctx))

"""Socket.IO handlers for the lobby's online player list.

Membership of the presence channel is asked for by the client rather than
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
"""
from __future__ import annotations

from functools import partial

from app.handlers.context import HandlerContext
from app.handlers.payloads import PayloadError, parse_empty_payload
from app.services.presence import LOBBY_CHANNEL


async def watch_lobby(ctx: HandlerContext, sid, data=None):
    """Join the presence channel, answering with the baseline to apply to.

    The snapshot rides in the acknowledgement rather than in a follow-up
    event, so there is no window in which the socket is in the channel and
    receiving deltas against a list it does not have yet.
    """
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    await ctx.sio.enter_room(sid, LOBBY_CHANNEL)
    return {"ok": True, **ctx.presence_broadcaster.snapshot_for_watcher().payload()}


async def unwatch_lobby(ctx: HandlerContext, sid, data=None):
    """Leave the channel - the lobby was navigated away from, not closed."""
    try:
        parse_empty_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    await ctx.sio.leave_room(sid, LOBBY_CHANNEL)
    return {"ok": True}


def register(ctx: HandlerContext) -> None:
    ctx.on("watch_lobby", handler=partial(watch_lobby, ctx))
    ctx.on("unwatch_lobby", handler=partial(unwatch_lobby, ctx))

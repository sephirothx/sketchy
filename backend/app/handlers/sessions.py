"""Socket session resolution shared by handler domains.

About sockets and rooms, not authentication - account identity lives in
``app/auth``. The two were easy to confuse while both were called ``auth``.
"""
from __future__ import annotations

from app.handlers.context import HandlerContext
from app.rooms import Player, Room


async def existing_player_for_sid(
    ctx: HandlerContext, sid: str, room_id: str
) -> Player | None:
    """Return the live player already bound to this socket in ``room_id``."""
    session = await ctx.sio.get_session(sid)
    if not session or session.get("room_id") != room_id:
        return None
    room = ctx.room_manager.get_room(room_id)
    if not room:
        return None
    player = room.players.get(session.get("player_id"))
    return player if player and player.sid == sid and player.connected else None


async def require_current_player(
    ctx: HandlerContext, sid: str
) -> tuple[Room, Player] | None:
    """Resolve a member while rejecting disconnected or superseded sockets."""
    session = await ctx.sio.get_session(sid) if sid else None
    room = ctx.room_manager.get_room(session.get("room_id")) if session else None
    player = room.players.get(session.get("player_id")) if room and session else None
    if not room or not player or not player.connected or player.sid != sid:
        return None
    return room, player

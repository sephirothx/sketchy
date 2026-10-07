"""Decide whether a room seat may share a drawing to the Gallery (#1430).

The reactions' arrangement (`drawing_reactions.py`): no sockets, no database,
no timers - only the rules, against a `Room` built by hand. The handler does
the I/O around them, and the repository applies the same rules a second time
for a finished game, against rows instead of a room.

A share is somebody who was there putting a drawing in front of everybody
else, so the rules protect three things: that the drawing is one the sharer
can see and that is worth showing (kept, and not blank), that a private room's
drawings leave it only by their maker's hand (R-SHARE-02), and that the
drawer's taking one back out holds against everybody else (R-SHARE-04).
"""
from __future__ import annotations

from app.game import Game, Phase
from app.rooms import DrawingRecapEntry, Player, Room
from app.services.drawing_reactions import (
    NOT_RECORDED,
    STILL_SAVING,
    _same_account,
    recap_entry_for,
)

# The refusals are player-facing copy; the handler returns them as-is.
NOT_VISIBLE = "That drawing can no longer be shared from here."
NOT_SHAREABLE = "That drawing can't be shared."
PRIVATE_ROOM = "Only the artist can share a drawing from a private room."
WITHDRAWN = "The artist took this drawing out of the Gallery."
NOT_ACCEPTED = "That drawing could not be shared. Try again in a moment."

__all__ = [
    "NOT_ACCEPTED",
    "NOT_RECORDED",
    "NOT_SHAREABLE",
    "NOT_VISIBLE",
    "PRIVATE_ROOM",
    "STILL_SAVING",
    "WITHDRAWN",
    "drawer_is_watching",
    "is_drawer",
    "live_share_refusal",
    "recap_share_refusal",
    "share_broadcast",
]


def is_drawer(room: Room, entry: DrawingRecapEntry, player: Player) -> bool:
    """Whether this seat drew the entry - by token, or by account for a drawer
    who left and came back on a new seat."""
    return _same_account(room, entry.drawer_id, player)


def _rules_refusal(
    room: Room, entry: DrawingRecapEntry, player: Player, shared: bool
) -> str | None:
    """What every share, live or from the recap, has to hold."""
    if not shared:
        # Taking back is always one's own to do: the drawer's whole drawing,
        # anyone else's own share.
        return None
    if not entry.is_available or entry.action_count <= 0:
        # Not kept, so there is nothing to show; or blank (R-SHARE-03).
        return NOT_SHAREABLE
    if is_drawer(room, entry, player):
        return None
    if not room.is_public:
        return PRIVATE_ROOM
    if entry.turn_id in room.drawing_share_withdrawn:
        return WITHDRAWN
    return None


def live_share_refusal(
    room: Room, game: Game, player: Player, turn_id: str, shared: bool
) -> str | None:
    """Why a share of `turn_id` in a live game is refused, or None if allowed.

    Only from the current turn's results: before them the drawing is not
    finished, and after them the recap will offer it again once the game
    ends. Its entry is the room's own record of the drawing, written as the
    turn ended.
    """
    if turn_id != game.current_turn_id or game.phase != Phase.TURN_RESULTS:
        return NOT_VISIBLE
    entry = recap_entry_for(room, turn_id)
    if entry is None:
        return NOT_VISIBLE
    return _rules_refusal(room, entry, player, shared)


def recap_share_refusal(
    room: Room, player: Player, entry: DrawingRecapEntry, shared: bool
) -> str | None:
    """Why a share from the recap is refused before any write is tried. The
    recap outlives the game, so the share lands on the game's row, which has
    to exist first - the recap reaction's rule."""
    refusal = _rules_refusal(room, entry, player, shared)
    if refusal:
        return refusal
    if room.last_game_history == "pending":
        return STILL_SAVING
    if room.last_game_history != "recorded" or room.last_game_id is None:
        return NOT_RECORDED
    return None


def drawer_is_watching(room: Room, entry: DrawingRecapEntry) -> bool:
    """Whether the drawer is in the room to see a share happen, in which case
    they are not sent a notice about it as well (R-SHARE-09)."""
    drawer = room.players.get(entry.drawer_id)
    if drawer is not None and drawer.connected:
        return True
    departed = room.departed_seats.get(entry.drawer_id)
    account = drawer.user_id if drawer is not None else (
        departed.user_id if departed is not None else None
    )
    if account is None:
        return False
    return any(
        player.connected and player.user_id == account
        for player in room.players.values()
    )


def share_broadcast(room: Room, player: Player, turn_id: str, shared: bool) -> dict:
    """The room-wide `drawing_shared` payload: who acted and the drawing's
    share state after it - seat tokens and presentation only, no account id
    (R-ROOM-07)."""
    return {
        "turnId": turn_id,
        "playerId": player.id,
        "nickname": player.nickname,
        "nameColor": player.name_color,
        "isAnonymous": player.is_anonymous,
        "shared": shared,
        **room.drawing_share_state(turn_id),
    }

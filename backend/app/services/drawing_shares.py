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
PRIVATE_ROOM = "Only its drawer can share a drawing from a private room."
WITHDRAWN = "Its drawer took this drawing out of the Gallery."
NOT_ACCEPTED = "That drawing could not be shared. Try again in a moment."

__all__ = [
    "NOT_ACCEPTED",
    "NOT_RECORDED",
    "NOT_SHAREABLE",
    "NOT_VISIBLE",
    "PRIVATE_ROOM",
    "STILL_SAVING",
    "WITHDRAWN",
    "apply_recorded_shares",
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
    room: Room, entry: DrawingRecapEntry, player: Player, shared: bool, *, public: bool
) -> str | None:
    """What every share, live or from the recap, has to hold. `public` is the
    game's visibility: the room's while it is being played, and the one the
    game was recorded with once it is over."""
    if not shared:
        # Taking back is always one's own to do: the drawer's whole drawing,
        # anyone else's own share.
        return None
    if not entry.is_available or entry.action_count <= 0:
        # Not kept, so there is nothing to show; or blank (R-SHARE-03).
        return NOT_SHAREABLE
    if is_drawer(room, entry, player):
        return None
    if not public:
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
    return _rules_refusal(room, entry, player, shared, public=room.is_public)


def recap_share_refusal(
    room: Room, player: Player, entry: DrawingRecapEntry, shared: bool
) -> str | None:
    """Why a share from the recap is refused before any write is tried. The
    recap outlives the game, so the share lands on the game's row, which has
    to exist first - the recap reaction's rule."""
    refusal = _rules_refusal(room, entry, player, shared, public=room.last_game_public)
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
    recorded = room.last_game_seats.get(entry.drawer_id)
    account = (
        drawer.user_id
        if drawer is not None
        else departed.user_id
        if departed is not None
        else recorded.user_id
        if recorded is not None
        else None
    )
    if account is None:
        return False
    return any(
        player.connected and player.user_id == account
        for player in room.players.values()
    )


def share_broadcast(room: Room, turn_id: str) -> dict:
    """The room-wide `drawing_shared` payload: the drawing's share state as it
    now stands - seat tokens only, no account id (R-ROOM-07). It names no
    actor: a change can come from outside the room (history, a pin, the
    Gallery), and what every seat needs is the state, not who moved it."""
    return {"turnId": turn_id, **room.drawing_share_state(turn_id)}


def apply_recorded_shares(room: Room, result) -> None:
    """Put a finished game's committed share state for one drawing in the
    room, its seats named by their tokens (`Room.tokens_for_seats`)."""
    room.replace_drawing_shares(
        result.turn_id, room.tokens_for_seats(result.shares), withdrawn=result.withdrawn
    )

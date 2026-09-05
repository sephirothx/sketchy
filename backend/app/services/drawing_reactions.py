"""Decide whether, and to which drawing, a room seat may react (#520).

Kept apart from the handler for the same reason `game_highlights.py` is kept
apart from `GameFlowService`: no sockets, no database, no timers - only the
rules, so they can be tested against a `Room` built by hand and read in one
place. The handler does the I/O around them; the repository applies the same
rules a second time for a finished game, against rows instead of a room.

A reaction is a fact about a drawing, so the two things the rules protect are
that the drawing is one the reactor can actually see, and that nobody reacts to
their own. Everything else - who is a guest, who is a spectator - is the
handler's authorization step, answered before any of this runs.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from app.game import Game, Phase
from app.rooms import DrawingRecapEntry, Player, Room

# The refusals are player-facing copy; the handler returns them as-is.
NOT_VISIBLE = "That drawing can no longer be reacted to."
OWN_DRAWING = "You can't react to your own drawing."
STILL_SAVING = "That game is still being saved. Try again in a moment."
NOT_RECORDED = "That game was not recorded, so reactions can't be saved."
NOT_ACCEPTED = "That drawing can't be reacted to."


def reaction_tally(reactions: Mapping[str, str]) -> dict[str, int]:
    """Per-emoji counts, in first-seen order, from a token -> code mapping."""
    return dict(Counter(reactions.values()))


def _same_account(room: Room, token: str, player: Player) -> bool:
    """Whether a seat token belongs to this player's account.

    A drawer who left and rejoined holds a new token, and their old one is in
    `departed_seats`; comparing tokens alone would let them react to their own
    drawing from the new seat.
    """
    if token == player.id:
        return True
    if player.user_id is None:
        return False
    other = room.players.get(token)
    if other is not None:
        return other.user_id == player.user_id
    departed = room.departed_seats.get(token)
    return departed is not None and departed.user_id == player.user_id


def live_reaction_refusal(room: Room, game: Game, player: Player, turn_id: str) -> str | None:
    """Why a reaction to `turn_id` in a live game is refused, or None if allowed.

    Only the current turn's drawing is on anyone's screen, and only while it is
    being drawn or its results are up: during `choosing_prompt` the id already
    names the next turn and nothing has been drawn. An earlier turn of this
    game is refused too - it is no longer visible, and the recap will offer it
    again once the game ends.
    """
    if turn_id != game.current_turn_id or game.phase not in (
        Phase.DRAWING,
        Phase.TURN_RESULTS,
    ):
        return NOT_VISIBLE
    if game.current_drawer is not None and _same_account(
        room, game.current_drawer, player
    ):
        return OWN_DRAWING
    return None


def recap_entry_for(room: Room, turn_id: str) -> DrawingRecapEntry | None:
    """The last game's recap entry for a turn, if the room still holds one."""
    for entry in room.last_game_drawings:
        if entry.turn_id == turn_id:
            return entry
    return None


def recap_reaction_refusal(room: Room, player: Player, entry: DrawingRecapEntry) -> str | None:
    """Why a reaction to a recap drawing is refused before any write is tried.

    The recap outlives the game, so the reaction has to land on the game's row.
    `Room.last_game_history` says whether that row exists yet: while the write
    is in the air the honest answer is "try again", and when there was never
    going to be a row there is nothing to write to.
    """
    if _same_account(room, entry.drawer_id, player):
        return OWN_DRAWING
    if room.last_game_history == "pending":
        return STILL_SAVING
    if room.last_game_history != "recorded" or room.last_game_id is None:
        return NOT_RECORDED
    return None


def reaction_broadcast(room: Room, player: Player, turn_id: str, emoji: str | None) -> dict:
    """The room-wide `drawing_reaction` payload: seat token and presentation only.

    Carries the reactor's name because the room shows who reacted, and the
    full tally so a client that missed an earlier event still converges. No
    account id, like every other room payload (R-ROOM-07).
    """
    return {
        "turnId": turn_id,
        "playerId": player.id,
        "nickname": player.nickname,
        "nameColor": player.name_color,
        "isAnonymous": player.is_anonymous,
        "emoji": emoji,
        "tally": reaction_tally(room.drawing_reactions.get(turn_id, {})),
    }

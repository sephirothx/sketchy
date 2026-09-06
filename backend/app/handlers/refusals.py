"""One shape for every refused acknowledgement, and the codes that name them.

A refusal used to be `{"ok": false, "error": "<sentence>"}` plus, on a handful of
paths, a boolean nobody else set - `roomFull`, `codeRetired`, `serverPaused`. The
client had two ways to find out *why* it was refused: read the boolean if that
path had one, or compare the sentence. `useCanvasProtocol` really did compare
"Drawing actions are out of sequence", so a copy edit could change recovery
behaviour, and the booleans were mutually ambiguous - a response could carry
none, or in principle two. #565 replaced both with one discriminator:

    {"ok": false, "errorCode": "canvas_out_of_sequence", "error": "…", "field"?: …}

`errorCode` rather than `code`, because `code` already means the invite code in a
successful room-entry acknowledgement. The prose stays, for people; the code is for
programs, and `frontend/src/types.ts` mirrors this enum member for member - a test
in `tests/test_wire_contract.py` fails when the two drift, and another fails on any
`"ok": False` literal that carries no code. `retryAfterMs` is set where the server
knows when trying again could work (a command budget, a vote cooldown).

Three acknowledgements are deliberately *not* refusals in this shape, and are
documented as exceptions in docs/wire-protocol.md §2: `guess` answers with a bare
receipt, `session_ping` with a compact tuple, and a throttled `draw` answers
nothing at all.
"""
from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Every reason the server refuses a command. Add, never rename."""

    # Payloads and arguments
    INVALID_PAYLOAD = "invalid_payload"
    INVALID_NICKNAME = "invalid_nickname"
    INVALID_NAME_COLOR = "invalid_name_color"
    INVALID_HINT = "invalid_hint"
    INVALID_LETTER = "invalid_letter"
    INVALID_PROMPT_LISTS = "invalid_prompt_lists"
    INVALID_CUSTOM_PROMPTS = "invalid_custom_prompts"
    MAX_PLAYERS_BELOW_SEATED = "max_players_below_seated"
    EMPTY_MESSAGE = "empty_message"

    # Rate and capacity
    TOO_FAST = "too_fast"
    SEAT_CHANGING_TOO_FAST = "seat_changing_too_fast"
    JOINING_TOO_FAST = "joining_too_fast"
    ROOM_QUOTA = "room_quota"
    ROOM_FULL = "room_full"  # player slots taken; spectating still open
    SPECTATORS_FULL = "spectators_full"
    PLAYER_SLOTS_FULL = "player_slots_full"  # a spectator asked for a seat

    # Server and account state
    SERVER_DRAINING = "server_draining"
    SERVER_PAUSED = "server_paused"
    DATABASE_BUSY = "database_busy"
    ACCOUNT_ENDED = "account_ended"
    ACCOUNT_REQUIRED = "account_required"
    IDENTITY_UNAVAILABLE = "identity_unavailable"

    # Rooms
    NOT_IN_ROOM = "not_in_room"
    ROOM_NOT_FOUND = "room_not_found"
    ROOM_ENDED = "room_ended"  # the code was valid but its room has ended
    COULD_NOT_CREATE_ROOM = "could_not_create_room"
    NO_SESSION_TO_RESUME = "no_session_to_resume"
    HOST_ONLY = "host_only"
    PLAYERS_ONLY = "players_only"
    WAITING_ROOM_ONLY = "waiting_room_only"
    ALREADY_A_PLAYER = "already_a_player"
    REGISTERED_NAME_FIXED = "registered_name_fixed"
    NAME_TAKEN_BY_ACCOUNT = "name_taken_by_account"
    GUESTS_CANNOT_CHOOSE_COLOR = "guests_cannot_choose_color"
    SUGGESTION_INACTIVE = "suggestion_inactive"
    DRAWING_NOT_FOUND = "drawing_not_found"
    DRAWING_NOT_KEPT = "drawing_not_kept"

    # Games and turns
    NOT_IN_GAME = "not_in_game"
    GAME_IN_PROGRESS = "game_in_progress"
    GAME_STARTING = "game_starting"
    NEED_TWO_PLAYERS = "need_two_players"
    ROOM_NOT_STARTABLE = "room_not_startable"
    PROMPT_NOT_READY = "prompt_not_ready"
    PROMPT_UNAVAILABLE = "prompt_unavailable"
    HINTS_DISABLED = "hints_disabled"
    HINT_SPEND_LIMIT = "hint_spend_limit"
    HINT_UNAVAILABLE = "hint_unavailable"

    # Canvas
    DRAWER_ONLY = "drawer_only"
    CANVAS_STALE_GENERATION = "canvas_stale_generation"
    CANVAS_SEQUENCE_COMMITTED = "canvas_sequence_committed"
    CANVAS_OUT_OF_SEQUENCE = "canvas_out_of_sequence"
    CANVAS_OUT_OF_SYNC = "canvas_out_of_sync"
    NOTHING_TO_UNDO = "nothing_to_undo"

    # Votes and restarts
    SPECTATORS_CANNOT_VOTE = "spectators_cannot_vote"
    SPECTATORS_CANNOT_BE_TARGETS = "spectators_cannot_be_targets"
    INVALID_VOTE_TARGET = "invalid_vote_target"
    NOT_ELIGIBLE = "not_eligible"
    RESTART_VOTE_ACTIVE = "restart_vote_active"
    RESTART_VOTE_COOLDOWN = "restart_vote_cooldown"
    NO_RESTART_VOTE = "no_restart_vote"
    RESTART_VOTE_CLOSED = "restart_vote_closed"

    # Reactions
    SPECTATORS_CANNOT_REACT = "spectators_cannot_react"
    GUESTS_CANNOT_REACT = "guests_cannot_react"
    REACTION_NOT_VISIBLE = "reaction_not_visible"
    OWN_DRAWING = "own_drawing"
    GAME_STILL_SAVING = "game_still_saving"
    GAME_NOT_RECORDED = "game_not_recorded"
    REACTION_NOT_ACCEPTED = "reaction_not_accepted"

    # Friends
    FRIENDS_UNAVAILABLE = "friends_unavailable"
    FRIEND_REFUSED = "friend_refused"
    FRIEND_NOT_IN_GAME = "friend_not_in_game"
    FRIEND_IN_SEVERAL_GAMES = "friend_in_several_games"
    NOT_FRIENDS = "not_friends"
    FRIENDS_ONLY_UNINVITED = "friends_only_uninvited"
    INVITE_EXPIRED = "invite_expired"

    # Moderation
    REPORTING_UNAVAILABLE = "reporting_unavailable"
    NO_SUCH_PLAYER = "no_such_player"
    CANNOT_REPORT = "cannot_report"
    ALREADY_REPORTED = "already_reported"

    # Lobby chat
    NAME_REQUIRED = "name_required"
    NOT_WATCHING_LOBBY = "not_watching_lobby"


def refuse(
    code: ErrorCode,
    error: str,
    *,
    field: str | None = None,
    retry_after_ms: int | None = None,
    **extra: object,
) -> dict[str, object]:
    """The refused acknowledgement, in the one shape the client reads."""
    response: dict[str, object] = {"ok": False, "errorCode": code, "error": error}
    if field:
        response["field"] = field
    if retry_after_ms is not None:
        response["retryAfterMs"] = retry_after_ms
    response.update(extra)
    return response

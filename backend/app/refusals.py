"""Every reason the server refuses something, named once for both surfaces.

A refusal reaches a player over the socket or over REST, and until #760 the two
disagreed about what a refusal *was*. The socket had already been fixed: #565
replaced prose-matching and a scatter of booleans with one discriminator, so an
acknowledgement refuses as `{"ok": false, "errorCode": ..., "error": ...}` and
the client branches on the code. REST had nothing. `HTTPException(detail="Sign
in first.")` was the whole contract, and 237 of them across `app/api` and
`app/auth` meant the only thing a client could do with a refusal was print the
server's English at the player.

That is what makes the vocabulary live here rather than under `app/handlers`.
It is a vocabulary, not a transport detail: `app/api` and `app/handlers` are
siblings, and a code both of them raise cannot belong to one of them.
`refuse()` - the socket acknowledgement shape - stays in
`app/handlers/refusals.py`; `Refusal` - the HTTP one - lives in
`app/api/errors.py`; both name their reason from here.

**Add, never rename.** A code is a wire value a client branches on, and
`frontend/src/types.ts` mirrors this enum member for member, with
`tests/test_wire_contract.py` failing on any drift. The prose that used to be
the contract is now a courtesy: the server still sends a sentence, for a log
and for a bug report, and no client renders it (R-I18N-01).
"""
from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Every reason the server refuses a command or a request."""

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

    # Versioning: the socket was told to upgrade and has not reloaded yet.
    PROTOCOL_MISMATCH = "protocol_mismatch"

    # ---------------------------------------------------------------- REST --
    # Everything below is reached over HTTP rather than the socket. The split
    # is where the refusal happens, not what it means: `account_required` and
    # the rate-limit codes above are raised by both.

    # Sessions and accounts
    SIGN_IN_REQUIRED = "sign_in_required"  # no session at all, not "no account"
    CREDENTIALS_INCORRECT = "credentials_incorrect"  # login; which one is not said
    PASSWORD_INCORRECT = "password_incorrect"  # re-authentication, name already known
    ACCOUNT_SUSPENDED = "account_suspended"
    ALREADY_SIGNED_IN = "already_signed_in"
    USERNAME_TAKEN = "username_taken"
    INVALID_USERNAME = "invalid_username"
    WEAK_PASSWORD = "weak_password"
    PASSWORD_CHANGE_FAILED = "password_change_failed"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_REPLACED = "session_replaced"
    GUEST_PROGRESS_UNLINKED = "guest_progress_unlinked"
    NOT_TAKING_VISITORS = "not_taking_visitors"  # admission, not a rate limit
    ACCOUNT_DELETE_REFUSED = "account_delete_refused"
    PASSWORD_REQUIRED_TO_DELETE = "password_required_to_delete"

    # Second factor and passkeys
    SECOND_FACTOR_REQUIRED = "second_factor_required"
    SECOND_FACTOR_PASSKEY_ONLY = "second_factor_passkey_only"
    SECOND_FACTOR_NOT_ENROLLED = "second_factor_not_enrolled"
    SECOND_FACTOR_NOT_SET_UP = "second_factor_not_set_up"
    SECOND_FACTOR_CODE_WRONG = "second_factor_code_wrong"
    SECOND_FACTOR_THROTTLED = "second_factor_throttled"
    STEP_UP_REQUIRED = "step_up_required"
    PASSKEY_SIGN_IN_REQUIRED = "passkey_sign_in_required"
    PASSKEY_NOT_REGISTERED = "passkey_not_registered"
    PASSKEY_NOT_FOUND = "passkey_not_found"
    PASSKEY_REFUSED = "passkey_refused"
    LAST_FACTOR = "last_factor"  # removing this one would leave no second factor
    SECOND_FACTOR_REQUIRED_FOR_ROLE = "second_factor_required_for_role"
    SECOND_FACTOR_NOT_PROVED = "second_factor_not_proved"

    # Email, verification and recovery
    INVALID_EMAIL = "invalid_email"
    EMAIL_IN_USE = "email_in_use"
    EMAIL_CHANGE_REFUSED = "email_change_refused"
    VERIFICATION_LINK_INVALID = "verification_link_invalid"
    # Publishing and starring need a confirmed address (R-LIST-12); carries `action`.
    EMAIL_VERIFICATION_REQUIRED = "email_verification_required"
    RESET_LINK_INVALID = "reset_link_invalid"

    # Account data export
    EXPORT_NOT_FOUND = "export_not_found"
    EXPORT_EXPIRED = "export_expired"
    EXPORT_NOT_READY = "export_not_ready"
    EXPORT_UNREADABLE = "export_unreadable"
    EXPORT_NOT_YET_ALLOWED = "export_not_yet_allowed"
    EXPORT_REFUSED = "export_refused"

    # Rate limits reached over HTTP
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    TOO_MANY_REQUESTS = "too_many_requests"
    TOO_MANY_REPORTS = "too_many_reports"
    TOO_MANY_BUG_REPORTS = "too_many_bug_reports"
    TOO_MANY_PICTURES = "too_many_pictures"

    # Pictures
    UNSUPPORTED_PICTURE_TYPE = "unsupported_picture_type"
    PICTURE_NOT_FOUND = "picture_not_found"
    PICTURE_REFUSED = "picture_refused"

    # Bug reports
    SCREENSHOT_UNREADABLE = "screenshot_unreadable"
    SCREENSHOT_TOO_LARGE = "screenshot_too_large"
    SCREENSHOT_UNSUPPORTED_TYPE = "screenshot_unsupported_type"
    BUG_REPORT_CONTEXT_TOO_LARGE = "bug_report_context_too_large"

    # Friends, over HTTP rather than in a room
    FRIENDS_THROTTLED = "friends_throttled"
    THAT_IS_YOU = "that_is_you"

    # Profiles and history
    NO_SUCH_GAME = "no_such_game"
    NO_SUCH_DRAWING = "no_such_drawing"
    DRAWING_UNREADABLE = "drawing_unreadable"

    # Prompt lists
    PROMPT_LIST_NOT_FOUND = "prompt_list_not_found"
    SHARED_PROMPT_LIST_NOT_FOUND = "shared_prompt_list_not_found"
    PROMPT_LIST_CONFLICT = "prompt_list_conflict"
    PROMPT_LIST_INVALID = "prompt_list_invalid"
    PROMPT_LIST_FORBIDDEN = "prompt_list_forbidden"
    # A tag the curated vocabulary does not hold (R-LIST-18); carries `tag`.
    UNKNOWN_PROMPT_TAG = "unknown_prompt_tag"
    # A list a moderator hid cannot be put back in front of people by its owner.
    PROMPT_LIST_HIDDEN = "prompt_list_hidden"
    UNKNOWN_SORT = "unknown_sort"
    TIMEZONE_REQUIRED = "timezone_required"
    RANGE_REVERSED = "range_reversed"

    # Room presets
    ROOM_PRESET_NOT_FOUND = "room_preset_not_found"
    ROOM_PRESET_CONFLICT = "room_preset_conflict"
    ROOM_PRESET_UNAVAILABLE = "room_preset_unavailable"
    ROOM_PRESET_FORBIDDEN = "room_preset_forbidden"

    # Blocks
    CANNOT_BLOCK_YOURSELF = "cannot_block_yourself"
    BLOCK_LIST_FULL = "block_list_full"

    # Settings
    SETTING_REFUSED = "setting_refused"

    # Role notices
    NO_SUCH_NOTICE = "no_such_notice"

    # Reporting, from the reporter's side. The moderator's side of the queue
    # is staff-only and keeps its English prose (R-I18N-01).
    CANNOT_REPORT_YOURSELF = "cannot_report_yourself"
    CANNOT_REPORT_OWN_PROMPT_LIST = "cannot_report_own_prompt_list"
    NO_REPORTABLE_PROMPT_LIST = "no_reportable_prompt_list"
    PROMPT_NOT_IN_LIST = "prompt_not_in_list"
    NO_PICTURE_TO_REPORT = "no_picture_to_report"
    NO_SUCH_GAME_CONTEXT = "no_such_game_context"
    NO_SUCH_TURN_CONTEXT = "no_such_turn_context"
    TURN_NOT_IN_GAME = "turn_not_in_game"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    EVIDENCE_MIXED_SCOPES = "evidence_mixed_scopes"
    EVIDENCE_SEVERAL_ROOMS = "evidence_several_rooms"
    EVIDENCE_NOT_THEIRS = "evidence_not_theirs"
    EVIDENCE_NOT_RECEIVED = "evidence_not_received"
    EVIDENCE_NOT_IN_GAME = "evidence_not_in_game"
    EVIDENCE_NOT_IN_TURN = "evidence_not_in_turn"
    NO_SUCH_WARNING = "no_such_warning"
    # An unacknowledged warning holds publishing and starring back; carries `action`.
    WARNING_UNREAD = "warning_unread"
    NO_DRAWING = "no_drawing"

"""What the room says about itself, as facts rather than as English sentences.

A room-authored announcement (`R-BLOCK-03`'s term) is one event reaching every
seat at once: *somebody joined*, *a vote passed*, *the restart was cancelled*.
It used to be a sentence built on the server and broadcast, which works
exactly as long as everybody in the room reads the same language.

It is the one surface where the rest of R-I18N-01 does not simply transfer.
Everywhere else the recipient is one reader; here one event reaches a room
whose players need not share a language, and the transcript they are all
looking at has to say the same thing to each of them. Rendering per recipient
is the wrong fix twice over: it puts a translation catalogue on the server,
and it sends N different payloads for one event, so the shared transcript is
no longer shared.

So an announcement travels as a code and typed parameters, and each client
renders it locally. Two players in one room, set to different languages, read
the same fact in their own.

**Parameters are values, never fragments** (R-I18N-02). That is why
`RESTART_CANCELLED` carries `reason: "server_update"` rather than the clause
`"a server update is in progress"` it used to interpolate: the clause is
English, and in most languages it cannot simply be dropped after *because*.

Codes are **added, never renamed** - a client branches on them, and
`frontend/src/lib/announcements.ts` mirrors this enum member for member with
`tests/test_wire_contract.py` failing on any drift.
"""
from __future__ import annotations

from enum import StrEnum


class Announcement(StrEnum):
    """Every line the room itself can say."""

    # Seats
    NICKNAME_CHANGED = "nickname_changed"  # previous, nickname
    JOINED_AS_PLAYER = "joined_as_player"  # nickname
    KICKED_BY_VOTE = "kicked_by_vote"  # nickname
    MARKED_AFK_BY_VOTE = "marked_afk_by_vote"  # nickname

    # Restart votes
    RESTART_VOTE_STARTED = "restart_vote_started"  # nickname
    RESTART_VOTE_PASSED = "restart_vote_passed"  # seconds
    RESTART_VOTE_REJECTED = "restart_vote_rejected"
    RESTART_VOTE_EXPIRED = "restart_vote_expired"
    RESTART_VOTE_ABANDONED = "restart_vote_abandoned"  # too few players left
    RESTART_CANCELLED = "restart_cancelled"  # reason
    GAME_RESTARTED_BY_VOTE = "game_restarted_by_vote"

    # Hints and near misses, said to one player rather than to the room
    HINT_LETTER_FOUND = "hint_letter_found"  # letter, cost, count
    HINT_LETTER_MISSING = "hint_letter_missing"  # letter, cost
    GUESS_VERY_CLOSE = "guess_very_close"  # text
    GUESS_SOME_WORDS_CORRECT = "guess_some_words_correct"


class RestartCancelReason(StrEnum):
    """Why an approved restart never happened.

    Enumerated rather than interpolated, because *"the restart was cancelled
    because {reason}"* only works in a language that builds the clause the way
    English does. Each client writes the whole sentence.
    """

    SERVER_UPDATE = "server_update"
    TOO_FEW_PLAYERS = "too_few_players"
    PROMPT_LISTS_UNAVAILABLE = "prompt_lists_unavailable"
    EVERYBODY_LEFT = "everybody_left"

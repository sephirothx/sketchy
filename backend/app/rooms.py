"""In-memory Player/Room domain model and RoomManager."""
from __future__ import annotations

import asyncio
import random
import re
import secrets
import string
import time
import uuid
from uuid import UUID
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Literal, Optional

from app.drawing_rules import (
    DEFAULT_ALLOWED_TOOLS,
    DEFAULT_COLOR_MODE,
)
from app.game import Game
from app.identifiers import generate_uuid7
from app.domain_values import GamePromptSourceMode, RuntimeEventType
from app.services.runtime_metrics import metrics
from app.prompt_content import prompt_match_key

DEFAULT_ROOM_DRAWING_SECONDS = 90
DEFAULT_ROOM_HINT_MODE = "checkpoints"
DRAWING_TIME_OPTIONS = (15, 30, 60, 90, 120, 180, 240, 300)
MAX_PLAYERS_MIN = 2
MAX_PLAYERS_MAX = 16


# How many recent guess ids a seat remembers per connection. The client retries
# a guess once, about two seconds after sending it, so only the handful of
# guesses typed inside that window can ever be retried - and the bound is what
# keeps a client that invents ids from growing this without limit.
GUESS_DEDUP_WINDOW = 16

# How much drawing a room keeps for the recap, across the whole game.
#
# Every turn's canvas is held until a new game starts, so this is the one thing
# in a room that grows with the length of a game: sixteen players over ten
# rounds is a hundred and sixty turns. Real drawings run about 10 KB, so a
# full-length game of them keeps everything with room to spare - the budget
# only ever binds on a client sending deliberately enormous histories, where
# turning the later ones away is the right outcome.
MAX_RECAP_CANVAS_BYTES = 8 * 1024 * 1024


def resolve_hint_mode(
    hint_mode: str, scoring_mode: str, hide_masked_prompt: bool
) -> str:
    """Force hints off where the rest of the settings leave nothing to hint at.

    A hidden prompt has no blanks to reveal, and a paid hint costs points a
    room that is not scoring cannot charge.
    """
    if hide_masked_prompt or (
        scoring_mode == "none" and hint_mode in {"purchase", "wheel"}
    ):
        return "none"
    return hint_mode


def majority_of(population: int) -> int:
    """Votes needed to carry a strict majority of `population`."""
    return (population // 2) + 1


def nearest_drawing_seconds(value: int) -> int:
    """Snap a drawing-time request onto the allowed preset list."""
    return min(DRAWING_TIME_OPTIONS, key=lambda option: (abs(option - value), option))


# The twelve colours a registered player may wear on their name. The same list
# lives in the client as NAME_COLOR_PALETTE (frontend/src/store/settingsStore.ts);
# the swatches there are the only interface that can choose one, and the rule
# below is what stops a modified client choosing anything else (#571).
#
# Every entry clears NAME_COLOR_MIN_CONTRAST against both NAME_COLOR_SURFACES -
# tests/test_name_color.py proves it - so the palette and the rule cannot
# disagree. Hues are spread so no two neighbours read as the same colour, and
# the set deliberately includes light ones (yellow, sky, pink) that only clear
# a low floor on the white panel: readable, not AA, is the bar.
NAME_COLORS: tuple[str, ...] = (
    "#e11d48",  # red
    "#f97316",  # orange
    "#eab308",  # yellow
    "#84cc16",  # lime
    "#16a34a",  # green
    "#0d9488",  # teal
    "#38bdf8",  # sky
    "#2563eb",  # blue
    "#6366f1",  # indigo
    "#a855f7",  # purple
    "#d946ef",  # magenta
    "#f472b6",  # pink
)
NAME_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

# Where a name is read: the player-list panel, which is `--card` in
# frontend/src/styles/theme.css, once per theme. Mirrored rather than imported
# because the server has no stylesheet to read; tests/test_name_color.py fails
# the moment the CSS token moves without this following it.
NAME_COLOR_SURFACES: tuple[str, ...] = ("#ffffff", "#1e293b")
# Deliberately below WCAG's 3:1 for large text: the floor exists to refuse a
# colour that *vanishes* on one of the panels - white on the light theme,
# slate on the dark - not to enforce a reading grade on a short bold label.
# 3:1 on both a white and a slate panel would leave no yellow, sky or pink at
# all; every palette entry clears this on both.
NAME_COLOR_MIN_CONTRAST = 1.8

# Guests render in grey italics everywhere, so a color would be meaningless
# and would also make an unclaimed name look like a registered one.
ANONYMOUS_NAME_COLOR = "#888888"


def _relative_luminance(hex_color: str) -> float:
    """WCAG 2.x relative luminance of a `#rrggbb` colour."""
    channels = []
    for offset in (1, 3, 5):
        value = int(hex_color[offset : offset + 2], 16) / 255
        channels.append(
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two `#rrggbb` colours, 1.0 to 21.0."""
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def name_color_is_readable(hex_color: str) -> bool:
    """Whether a name in this colour clears the floor on every surface it sits on."""
    return all(
        contrast_ratio(hex_color, surface) >= NAME_COLOR_MIN_CONTRAST
        for surface in NAME_COLOR_SURFACES
    )


def normalize_name_color(value: object) -> str | None:
    """The colour a name may be drawn in, lower-cased, or None.

    Shape is not enough (#571): a well-formed `#rrggbb` can still be white on
    the light theme or near-black on the dark one, and the swatches in
    Settings are a client-side courtesy that a modified client or the
    `update_player_settings` socket path does not have to observe. So the
    server holds the rule the palette was drawn to: readable on both panels.

    A value that fails is returned as None, and every caller treats None as
    "no colour" - the seat rolls one from the palette instead. That is also
    what heals a colour stored before this rule existed: it is not refused
    after the fact, it simply is not kept.
    """
    if not isinstance(value, str) or not NAME_COLOR_PATTERN.fullmatch(value):
        return None
    color = value.lower()
    return color if name_color_is_readable(color) else None


def generate_random_name_color() -> str:
    return random.choice(NAME_COLORS)

ROOM_NAME_ADJECTIVES: tuple[str, ...] = (
    "The Sketchy",
    "Picasso's",
    "The Frantic",
    "The Chaotic",
    "The Scribbly",
    "The Abstract",
    "The Messy",
    "The Crayola",
    "Bob Ross's",
    "The Wobbly",
    "The Furious",
    "The Unfinished",
    "The Finger-Painted",
    "The Accidental",
    "The Over-Drawn",
    "The Pixelated",
    "The Ear-Resistible",
    "The Wild",
    "The Melting",
    "The Glorious",
    "Leonardo's",
    "Van Gogh's",
)

ROOM_NAME_NOUNS: tuple[str, ...] = (
    "Panic Room",
    "Catastrophe",
    "Disaster Zone",
    "Sanctuary",
    "Society",
    "Asylum",
    "Speakeasy",
    "Workshop",
    "Canvas",
    "Gallery",
    "Lab",
    "Guild",
    "Haven",
    "Corner",
    "Studio",
    "Art Class",
    "Accident",
    "Rejects",
    "Caper",
)


def generate_random_room_name() -> str:
    adj = random.choice(ROOM_NAME_ADJECTIVES)
    noun = random.choice(ROOM_NAME_NOUNS)
    return f"{adj} {noun}"



def _metrics_user_id(user_id: object) -> UUID | None:
    """Only a real account id is worth recording; a guest token is not one."""
    if not isinstance(user_id, str) or not user_id:
        return None
    try:
        return UUID(user_id)
    except ValueError:
        return None


class RoomFullError(Exception):
    pass


@dataclass
class Player:
    id: str
    nickname: str
    # The account this seat belongs to. None when the client had no session
    # cookie (cookies blocked, embedded webview): such a player still plays
    # normally and receives a factual history seat, but cannot reconnect.
    user_id: str | None = None
    is_anonymous: bool = True
    name_color: str = field(default_factory=generate_random_name_color)
    sid: Optional[str] = None
    score: int = 0
    connected: bool = True
    is_host: bool = False
    is_spectator: bool = False
    is_afk: bool = False
    # Private accessibility input used only to compute an unattributed,
    # host-only room suggestion. Deliberately absent from every presenter.
    colorblind_safe_colors: bool = False
    kick_votes: set[str] = field(default_factory=set)
    afk_votes: set[str] = field(default_factory=set)
    # Guess ids already handled on the current connection. A guess is emitted
    # volatile, so the client retries once with the same id when the server
    # never acknowledges; without this the retry of a guess that did arrive
    # would be echoed to the room twice and counted twice in the turn stats.
    _guess_window_sid: Optional[str] = None
    _guess_ids_seen: deque[int] = field(
        default_factory=lambda: deque(maxlen=GUESS_DEDUP_WINDOW)
    )

    def accept_guess_id(self, sid: str, guess_id: Optional[int]) -> bool:
        """Whether this guess is new to `sid`, remembering it if so.

        Ids are monotonic within one connection and meaningless across
        connections, so a new sid starts a fresh window rather than judging a
        reconnected client's counter against the old one. A client that sends
        no id forgoes deduplication and is always accepted - a retry it never
        makes cannot be confused for one.
        """
        if guess_id is None:
            return True
        if self._guess_window_sid != sid:
            self._guess_window_sid = sid
            self._guess_ids_seen.clear()
        if guess_id in self._guess_ids_seen:
            return False
        self._guess_ids_seen.append(guess_id)
        return True


@dataclass(slots=True)
class RestartVote:
    proposer_id: str
    proposer_nickname: str
    eligible_voter_ids: tuple[str, ...]
    votes: dict[str, bool]
    expires_at: float
    status: Literal["voting", "approved"] = "voting"
    restart_at: float | None = None

    @property
    def required_votes(self) -> int:
        return majority_of(len(self.eligible_voter_ids))

    def payload(self) -> dict:
        return {
            "status": self.status,
            "proposerId": self.proposer_id,
            "proposerNickname": self.proposer_nickname,
            "eligibleVoterIds": list(self.eligible_voter_ids),
            "yesVoterIds": [
                player_id for player_id, vote in self.votes.items() if vote
            ],
            "noVoterIds": [
                player_id for player_id, vote in self.votes.items() if not vote
            ],
            "castVotes": [
                {"playerId": player_id, "vote": vote}
                for player_id, vote in self.votes.items()
            ],
            "requiredVotes": self.required_votes,
            "expiresAt": round(self.expires_at * 1000),
            "restartAt": (
                round(self.restart_at * 1000)
                if self.restart_at is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class DepartedSeat:
    """What a player leaves behind when their seat is removed.

    A player who drew in round 1 and quit is gone from `Room.players` by the
    time the game ends, but their rounds and guesses still belong in the
    recorded history - and so does their final standing.
    """

    player_id: str
    nickname: str
    user_id: str | None
    is_spectator: bool
    score: int
    # How the name renders. Carried because a departed player can still hold a
    # game highlight, and a name shown there in a different style than the one
    # it had all game reads as a different person.
    name_color: str | None = None
    is_anonymous: bool = True


@dataclass(frozen=True, slots=True)
class DrawingRecapEntry:
    # The durable UUIDv7 of the turn this drawing belongs to. Round and turn
    # numbers identify a drawing inside one live recap; only this survives into
    # history, where a turn is keyed by id.
    turn_id: str
    round_number: int
    turn_number: int
    drawer_id: str
    drawer_nickname: str
    drawer_name_color: str | None
    prompt: str
    action_count: int
    # None once a game's drawings outgrow the room's budget and this one no
    # longer fits. The entry itself stays: a recap that quietly listed fewer
    # turns than were played would be a worse answer than one admitting a
    # drawing is gone.
    canvas_history: bytes | None

    @property
    def is_available(self) -> bool:
        return self.canvas_history is not None

    def metadata(self, index: int) -> dict:
        return {
            "index": index,
            "roundNumber": self.round_number,
            "turnNumber": self.turn_number,
            "drawerId": self.drawer_id,
            "drawerNickname": self.drawer_nickname,
            "drawerNameColor": self.drawer_name_color,
            "prompt": self.prompt,
            "actionCount": self.action_count,
            "available": self.is_available,
        }

    def payload(self, index: int) -> dict:
        return {**self.metadata(index), "canvas": self.canvas_history}


@dataclass
class Room:
    id: str
    code: str
    name: str
    is_public: bool
    max_players: int
    rounds: int
    # Durable correlation scope for short-lived messages. The public/live room
    # id remains an implementation detail and is never stored as a code.
    retention_scope_id: str = field(default_factory=lambda: str(generate_uuid7()))
    # Wall clock, only ever used to measure how long the room lasted. Rooms do
    # not survive the process, so this needs no durable representation.
    created_at: float = field(default_factory=time.time, repr=False)
    # Durable configuration identity is separate from this fresh live instance.
    # No player, score, game, timer, canvas, or room ID is restored with it.
    # The account that opened this room, for as long as it lives. A room the
    # creator has left still counts against their ceiling, because it is still
    # this process holding it - and since #480 a room nobody is in no longer
    # outlives its last player, so what counts against them is only ever a
    # room somebody is actually playing in.
    created_by_user_id: str | None = field(default=None, repr=False)
    custom_prompts: list[str] = field(default_factory=list)
    # What this room's quick prompts cost, kept beside them so the process
    # total is a sum of integers rather than a walk of every string. Written
    # only by `RoomManager.set_custom_prompts`, which is what keeps it true.
    custom_prompt_characters: int = field(default=0, repr=False)
    custom_prompts_only: bool = False
    drawing_seconds: int = DEFAULT_ROOM_DRAWING_SECONDS
    hint_mode: str = DEFAULT_ROOM_HINT_MODE
    scoring_mode: str = "default"
    spectators_see_prompt: bool = False
    hide_masked_prompt: bool = False
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    color_mode: str = DEFAULT_COLOR_MODE
    prompt_language: str = "en"
    prompt_list_slugs: list[str] = field(default_factory=list)
    # Bearer capabilities used only to authorize unlisted content. Never expose
    # these in room state, settings responses, logs, or history.
    prompt_list_share_codes: list[str] = field(default_factory=list, repr=False)
    prompt_list_revision_ids: list[str] = field(default_factory=list)
    # What the pinned revisions hold, rather than the content itself. The pool
    # used to live here for the room's whole life so that a game could offer
    # three choices and price wheel letters; both need a number and a
    # distribution, and a game draws the prompts it will actually use when it
    # starts. `prompt_pool_size` also weights that draw, so a handful of quick
    # prompts stay as likely as they were when the two were merged in memory.
    prompt_pool_size: int = 0
    prompt_letter_counts: dict[str, int] = field(default_factory=dict, repr=False)
    prompt_letter_total: int = 0
    players: dict[str, Player] = field(default_factory=dict)
    state: str = "waiting"  # waiting | playing
    game: Optional[Game] = None
    canvas_generation: int = 0
    last_game_scores: list[dict] = field(default_factory=list)
    last_game_highlights: list[dict] = field(default_factory=list)
    last_game_drawings: list[DrawingRecapEntry] = field(default_factory=list)
    departed_seats: dict[str, DepartedSeat] = field(default_factory=dict)
    restart_vote: RestartVote | None = None
    restart_vote_cooldown_until: float = 0
    # A dismissal belongs to this in-memory room instance. It is neither an
    # account setting nor public room configuration and is never serialized.
    colorblind_suggestion_dismissed: bool = False
    # Held by the handlers that must not interleave on this room. Socket.IO
    # dispatches each event in its own task, so arriving first buys a handler
    # nothing once it awaits: without this, starting a game can overtake the
    # settings change that arrived ahead of it and the room plays the values
    # the host just replaced. See update_room_settings and start_game.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def player_list(self) -> list[Player]:
        return list(self.players.values())

    def connected_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.connected]

    def seated_players(self) -> list[Player]:
        """Everyone holding a player seat, connected or not. Spectators are not."""
        return [p for p in self.players.values() if not p.is_spectator]

    def active_players(self) -> list[Player]:
        """Seated players the game is currently waiting on: here, and not AFK."""
        return [
            p
            for p in self.players.values()
            if p.connected and not p.is_spectator and not p.is_afk
        ]

    def eligible_guessers(self) -> list[Player]:
        """Currently active non-drawers, independent of the frozen turn snapshot."""
        drawer = self.game.current_drawer if self.game else None
        return [p for p in self.active_players() if p.id != drawer]

    def moderation_voters(self) -> list[Player]:
        """Return players eligible to cast and count toward moderation votes.

        AFK players and the vote target remain in the population. Spectators and
        disconnected players do not participate.
        """
        return [
            p
            for p in self.players.values()
            if p.connected and not p.is_spectator
        ]

    def moderation_state_payload(self) -> dict:
        eligible_voter_ids = [p.id for p in self.moderation_voters()]
        return {
            "eligibleVoterIds": eligible_voter_ids,
            "requiredVotes": majority_of(len(eligible_voter_ids)),
        }

    def record_drawing_recap(self, entry: DrawingRecapEntry) -> None:
        """Keep this turn's drawing if the room still has room for it.

        The drawings a game keeps are the ones it showed first, so a recap
        does not rearrange itself while somebody is reading it. Only the
        bitmap is given up - the turn stays listed with its prompt and its
        drawer, because a recap quietly showing fewer turns than were played
        would be a worse answer than one admitting a drawing is gone.

        Per drawing rather than once and for all: a small drawing still fits
        after a large one was turned away.
        """
        retained = sum(
            len(drawing.canvas_history or b"")
            for drawing in self.last_game_drawings
        )
        if retained + len(entry.canvas_history or b"") > MAX_RECAP_CANVAS_BYTES:
            entry = replace(entry, canvas_history=None)
        self.last_game_drawings.append(entry)

    def drawing_recap_metadata(self) -> list[dict]:
        return [
            drawing.metadata(index)
            for index, drawing in enumerate(self.last_game_drawings)
        ]

    def allocate_canvas_generation(self) -> int:
        """Return the next room-lifetime canvas protocol identity."""
        self.canvas_generation += 1
        return self.canvas_generation

    def custom_prompt_match_keys(self) -> frozenset[str]:
        """Match keys of this room's quick prompts.

        Quick prompts shadow curated content of the same name, so these are
        both what a draw excludes and what tells a recorded turn that a prompt
        came from the room rather than a list.
        """
        return frozenset(
            prompt_match_key(prompt, self.prompt_language)
            for prompt in self.custom_prompts
        )

    def draws_from_prompt_lists(self) -> bool:
        """Whether a game here would draw anything from the pinned revisions."""
        return not self.custom_prompts_only and self.prompt_pool_size > 0

    def prompt_source_mode(self) -> str:
        """Where this room's prompts come from, read from its settings.

        Deliberately not derived from the prompts a game happens to hold: a
        game now draws a sample, and a mixed room that drew no quick prompts
        would otherwise be recorded for all time as a purely curated one.
        """
        curated = self.draws_from_prompt_lists()
        custom = bool(self.custom_prompts)
        if curated and custom:
            return GamePromptSourceMode.MIXED.value
        if curated:
            return GamePromptSourceMode.CURATED.value
        if custom:
            return GamePromptSourceMode.CUSTOM.value
        return GamePromptSourceMode.BUILTIN_FALLBACK.value

    def to_public_roster(self) -> list[dict]:
        """Who is holding a seat, for the lobby card a visitor has opened.

        Deliberately not part of `to_public_summary()`: that is polled for
        every public room every few seconds, and putting names in it would make
        the lobby a live directory of who is playing where. This is only ever
        answered for one room, and only when somebody asks for it.

        Nicknames and their colours, nothing else. No seat id, no account id
        (room payloads carry none anywhere), no score, no connection or AFK
        state - none of it helps someone decide whether to join, and each one
        would say more about a stranger than the question needs.
        """
        return [
            {
                "nickname": player.nickname,
                "nameColor": player.name_color,
                "isAnonymous": player.is_anonymous,
                "isHost": player.is_host,
            }
            for player in self.seated_players()
        ]

    def to_public_summary(self) -> dict:
        active_players = self.seated_players()
        spectators = [p for p in self.players.values() if p.is_spectator]
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "isPublic": self.is_public,
            "playerCount": len(active_players),
            "spectatorCount": len(spectators),
            "maxPlayers": self.max_players,
            "isFull": len(active_players) >= self.max_players,
            "rounds": self.rounds,
            "customPromptCount": len(self.custom_prompts),
            "customPromptsOnly": self.custom_prompts_only,
            "drawingSeconds": self.drawing_seconds,
            "hintMode": self.hint_mode,
            "scoringMode": self.scoring_mode,
            "spectatorsSeePrompt": self.spectators_see_prompt,
            "hideMaskedPrompt": self.hide_masked_prompt,
            "allowedTools": list(self.allowed_tools),
            "colorMode": self.color_mode,
            "promptLanguage": self.prompt_language,
            "promptListSlugs": list(self.prompt_list_slugs),
            "state": self.state,
        }

    def _player_entry(self, player: Player) -> dict:
        """One player as the room broadcasts them.

        The vote lists are carried only where somebody has actually voted.
        Every seat in the room receives every other seat's entry on every
        broadcast, so two empty arrays per player is the payload paying an
        O(N^2) price for a state almost every player is in almost always. The
        client already reads them as optional, so absence means no votes.
        """
        entry = {
            "playerId": player.id,
            "nickname": player.nickname,
            "nameColor": player.name_color,
            "isAnonymous": player.is_anonymous,
            "score": player.score,
            "connected": player.connected,
            "isHost": player.is_host,
            "isSpectator": player.is_spectator,
            "isAfk": player.is_afk,
        }
        if player.kick_votes:
            entry["kickVotes"] = list(player.kick_votes)
        if player.afk_votes:
            entry["afkVotes"] = list(player.afk_votes)
        return entry

    def to_state_payload(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "isPublic": self.is_public,
            "maxPlayers": self.max_players,
            "rounds": self.rounds,
            "customPromptCount": len(self.custom_prompts),
            "customPromptsOnly": self.custom_prompts_only,
            "drawingSeconds": self.drawing_seconds,
            "hintMode": self.hint_mode,
            "scoringMode": self.scoring_mode,
            "spectatorsSeePrompt": self.spectators_see_prompt,
            "hideMaskedPrompt": self.hide_masked_prompt,
            "allowedTools": list(self.allowed_tools),
            "colorMode": self.color_mode,
            "promptLanguage": self.prompt_language,
            "promptListSlugs": list(self.prompt_list_slugs),
            "state": self.state,
            "lastGameScores": self.last_game_scores,
            "lastGameHighlights": (
                self.last_game_highlights if self.state == "waiting" else []
            ),
            "lastGameDrawings": (
                self.drawing_recap_metadata()
                if self.state == "waiting"
                else []
            ),
            "moderation": self.moderation_state_payload(),
            "restartVote": (
                self.restart_vote.payload() if self.restart_vote else None
            ),
            "restartVoteCooldownUntil": round(
                self.restart_vote_cooldown_until * 1000
            ),
            "players": [self._player_entry(p) for p in self.player_list()],
        }


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def create_room(
        self,
        name: str | None = None,
        is_public: bool = True,
        max_players: int = 8,
        rounds: int = 3,
        custom_prompts: list[str] | None = None,
        custom_prompts_only: bool = False,
        drawing_seconds: int = DEFAULT_ROOM_DRAWING_SECONDS,
        hint_mode: str = DEFAULT_ROOM_HINT_MODE,
        scoring_mode: str = "default",
        spectators_see_prompt: bool = False,
        hide_masked_prompt: bool = False,
        allowed_tools: list[str] | None = None,
        color_mode: str = DEFAULT_COLOR_MODE,
        prompt_language: str = "en",
        prompt_list_slugs: list[str] | None = None,
        prompt_list_share_codes: list[str] | None = None,
        prompt_list_revision_ids: list[str] | None = None,
        prompt_pool_size: int = 0,
        prompt_letter_counts: dict[str, int] | None = None,
        prompt_letter_total: int = 0,
        code: str | None = None,
        created_by_user_id: str | None = None,
    ) -> Room:
        room_id = str(uuid.uuid4())
        final_name = name.strip() if name and name.strip() else generate_random_room_name()
        hint_mode = resolve_hint_mode(hint_mode, scoring_mode, hide_masked_prompt)
        final_code = code.strip().upper() if code else self._generate_unique_code()
        if any(room.code == final_code for room in self.rooms.values()):
            raise ValueError("room code is already active")
        room = Room(
            id=room_id,
            code=final_code,
            name=final_name,
            is_public=is_public,
            max_players=max_players,
            rounds=rounds,
            custom_prompts=custom_prompts or [],
            custom_prompts_only=custom_prompts_only,
            drawing_seconds=drawing_seconds,
            hint_mode=hint_mode,
            scoring_mode=scoring_mode,
            spectators_see_prompt=spectators_see_prompt,
            hide_masked_prompt=hide_masked_prompt,
            allowed_tools=list(allowed_tools or DEFAULT_ALLOWED_TOOLS),
            color_mode=color_mode,
            prompt_language=prompt_language,
            prompt_list_slugs=list(prompt_list_slugs or []),
            prompt_list_share_codes=list(prompt_list_share_codes or []),
            prompt_list_revision_ids=list(prompt_list_revision_ids or []),
            prompt_pool_size=prompt_pool_size,
            prompt_letter_counts=dict(prompt_letter_counts or {}),
            prompt_letter_total=prompt_letter_total,
            created_by_user_id=created_by_user_id,
        )
        self.set_custom_prompts(room, room.custom_prompts)
        self.rooms[room_id] = room
        metrics.record(RuntimeEventType.ROOM_CREATED, room_id=room_id)
        self._observe()
        return room

    def _generate_unique_code(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        existing = {r.code for r in self.rooms.values()}
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            if code not in existing:
                return code

    def get_room(self, room_id: str | None) -> Room | None:
        if not room_id:
            return None
        return self.rooms.get(room_id)

    def get_room_by_code(self, code: str | None) -> Room | None:
        if not code:
            return None
        code = code.strip().upper()
        for room in self.rooms.values():
            if room.code == code:
                return room
        return None

    def set_custom_prompts(self, room: Room, prompts: list[str]) -> None:
        """Give a room its quick prompts, and keep what they cost with them.

        The single writer, so that `retained_prompt_characters` cannot drift
        from what the rooms actually hold. `test_room_quotas.py` checks the
        two against a full recount.
        """
        room.custom_prompts = list(prompts)
        room.custom_prompt_characters = sum(len(prompt) for prompt in room.custom_prompts)

    def rooms_created_by(self, user_id: str | None) -> int:
        """How many live rooms this account opened and still has open."""
        if not user_id:
            return 0
        return sum(
            1 for room in self.rooms.values() if room.created_by_user_id == user_id
        )

    def retained_prompt_characters(self) -> int:
        """What every live room's quick prompts cost this process together."""
        return sum(room.custom_prompt_characters for room in self.rooms.values())

    def list_public_rooms(self) -> list[dict]:
        return [r.to_public_summary() for r in self.rooms.values() if r.is_public]

    def add_player(
        self,
        room: Room,
        nickname: str,
        is_spectator: bool = False,
        name_color: str | None = None,
        user_id: str | None = None,
        is_anonymous: bool = True,
        colorblind_safe_colors: bool = False,
    ) -> Player:
        active_players = room.seated_players()
        if not is_spectator and len(active_players) >= room.max_players:
            raise RoomFullError("Room is full")
        player_id = str(uuid.uuid4())
        player = Player(
            id=player_id,
            nickname=nickname,
            user_id=user_id,
            is_anonymous=is_anonymous,
            name_color=(
                ANONYMOUS_NAME_COLOR
                if is_anonymous
                else normalize_name_color(name_color) or generate_random_name_color()
            ),
            score=0,
            is_host=not is_spectator and len(active_players) == 0,
            is_spectator=is_spectator,
            colorblind_safe_colors=colorblind_safe_colors,
        )
        room.players[player_id] = player
        metrics.record(
            RuntimeEventType.PLAYER_JOINED,
            room_id=room.id,
            user_id=_metrics_user_id(user_id),
            details={"spectator": is_spectator},
        )
        self._observe()
        return player

    def seats_for_sid(self, sid: str | None) -> list[tuple[Room, Player]]:
        """Every live seat this socket holds, across all rooms.

        A socket is meant to hold exactly one, but the answer is a list so
        that a socket which somehow holds more can still be reconciled down to
        none rather than leaving the rest behind, connected, forever. Walked
        rather than indexed: at the product ceiling this is a few hundred
        comparisons on a disconnect, and an index is one more thing that can
        stop being true.
        """
        if not sid:
            return []
        return [
            (room, player)
            for room in list(self.rooms.values())
            for player in list(room.players.values())
            if player.sid == sid
        ]

    def get_player_by_user_id(self, room: Room, user_id: object) -> Player | None:
        """Find this account's existing seat in the room, if it has one.

        One seat per account per room: a second tab rebinds this same Player
        rather than creating another, which is what stops one account from
        occupying several seats and compounding its own score.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        return next(
            (
                player
                for player in room.players.values()
                if player.user_id and player.user_id == user_id
            ),
            None,
        )

    def remove_player(self, room: Room, player_id: str) -> None:
        departing = room.players.pop(player_id, None)
        if departing is not None:
            room.departed_seats[player_id] = DepartedSeat(
                player_id=player_id,
                nickname=departing.nickname,
                user_id=departing.user_id,
                is_spectator=departing.is_spectator,
                score=departing.score,
                name_color=departing.name_color,
                is_anonymous=departing.is_anonymous,
            )
        for p in room.players.values():
            p.kick_votes.discard(player_id)
            p.afk_votes.discard(player_id)
        self._promote_new_host_if_needed(room)
        if departing is not None:
            metrics.record(
                RuntimeEventType.PLAYER_LEFT,
                room_id=room.id,
                user_id=_metrics_user_id(departing.user_id),
            )
        self._observe()

    def _promote_new_host_if_needed(self, room: Room) -> None:
        if any(p.is_host for p in room.players.values()):
            return
        for p in room.players.values():
            if not p.is_spectator:
                p.is_host = True
                break
        else:
            for p in room.players.values():
                p.is_host = True
                break

    def remove_room_if_empty(self, room_id: str) -> Room | None:
        room = self.rooms.get(room_id)
        if room and not room.connected_players():
            del self.rooms[room_id]
            # How long the room existed, in seconds. Recorded as the event's
            # value so it can be summed and maxed without parsing anything.
            metrics.record(
                RuntimeEventType.ROOM_CLOSED,
                room_id=room_id,
                value=max(0, int(time.time() - room.created_at)),
            )
            self._observe()
            return room
        return None

    def _observe(self) -> None:
        """Tell the recorder what is live, from the object that knows.

        Passed rather than accumulated: a gauge that adds and subtracts drifts
        the first time an event is missed and then lies for the life of the
        process.
        """
        metrics.observe(
            rooms=len(self.rooms),
            players=sum(len(room.players) for room in self.rooms.values()),
            active_games=sum(
                1 for room in self.rooms.values() if room.game is not None
            ),
        )

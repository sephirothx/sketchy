"""In-memory Player/Room domain model and RoomManager."""
from __future__ import annotations

import random
import re
import string
import uuid
from dataclasses import dataclass, field, replace
from typing import Literal, Optional

from app.game import Game
from app.prompts import PROMPTS

DEFAULT_ROOM_DRAWING_SECONDS = 90
DEFAULT_ROOM_HINT_MODE = "checkpoints"
DRAWING_TIME_OPTIONS = (15, 30, 60, 90, 120, 180, 240, 300)
MAX_PLAYERS_MIN = 2
MAX_PLAYERS_MAX = 16

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


NAME_COLORS: tuple[str, ...] = (
    "#e11d48",
    "#c2410c",
    "#a16207",
    "#15803d",
    "#0f766e",
    "#0369a1",
    "#4f46e5",
    "#7e22ce",
    "#be185d",
)
NAME_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

# Guests render in grey italics everywhere, so a color would be meaningless
# and would also make an unclaimed name look like a registered one.
ANONYMOUS_NAME_COLOR = "#888888"


def normalize_name_color(value: object) -> str | None:
    if not isinstance(value, str) or not NAME_COLOR_PATTERN.fullmatch(value):
        return None
    return value.lower()


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


class RoomFullError(Exception):
    pass


@dataclass
class Player:
    id: str
    nickname: str
    # The account this seat belongs to. None when the client had no session
    # cookie (cookies blocked, embedded webview): such a player still plays
    # normally but cannot reconnect and is not recorded in game history.
    user_id: str | None = None
    is_anonymous: bool = True
    name_color: str = field(default_factory=generate_random_name_color)
    sid: Optional[str] = None
    score: int = 0
    connected: bool = True
    is_host: bool = False
    is_spectator: bool = False
    is_afk: bool = False
    kick_votes: set[str] = field(default_factory=set)
    afk_votes: set[str] = field(default_factory=set)


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


@dataclass(frozen=True, slots=True)
class DrawingRecapEntry:
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
    custom_prompts: list[str] = field(default_factory=list)
    custom_prompts_only: bool = False
    drawing_seconds: int = DEFAULT_ROOM_DRAWING_SECONDS
    hint_mode: str = DEFAULT_ROOM_HINT_MODE
    scoring_mode: str = "default"
    spectators_see_prompt: bool = False
    hide_masked_prompt: bool = False
    prompt_list_slugs: list[str] = field(default_factory=list)
    curated_prompts: list[str] = field(default_factory=list)
    players: dict[str, Player] = field(default_factory=dict)
    state: str = "waiting"  # waiting | playing
    game: Optional[Game] = None
    canvas_generation: int = 0
    last_game_scores: list[dict] = field(default_factory=list)
    last_game_drawings: list[DrawingRecapEntry] = field(default_factory=list)
    departed_seats: dict[str, DepartedSeat] = field(default_factory=dict)
    restart_vote: RestartVote | None = None
    restart_vote_cooldown_until: float = 0

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
        """Active players who still owe this turn a guess - everyone but the drawer.

        Decides both when a round can end early and the guesser count recorded
        against the turn, so the two can never disagree.
        """
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

    def effective_prompt_pool(self) -> list[str] | None:
        """Return the prompt pool a Game should draw from, or None for the default list.

        If custom_prompts_only is set and custom prompts exist, returns just those.
        Otherwise, merges custom prompts with curated prompts (or fallback PROMPTS if none provided),
        with custom prompts first, deduplicated case-insensitively.
        """
        base_prompts = self.curated_prompts if self.curated_prompts else PROMPTS
        if not self.custom_prompts and not self.curated_prompts:
            return None
        if not self.custom_prompts:
            return self.curated_prompts
        if self.custom_prompts_only:
            return self.custom_prompts
        seen = {w.lower() for w in self.custom_prompts}
        return self.custom_prompts + [w for w in base_prompts if w.lower() not in seen]

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
            "promptListSlugs": list(self.prompt_list_slugs),
            "state": self.state,
        }

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
            "promptListSlugs": list(self.prompt_list_slugs),
            "state": self.state,
            "lastGameScores": self.last_game_scores,
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
            "players": [
                {
                    "playerId": p.id,
                    "nickname": p.nickname,
                    "nameColor": p.name_color,
                    "isAnonymous": p.is_anonymous,
                    "score": p.score,
                    "connected": p.connected,
                    "isHost": p.is_host,
                    "isSpectator": p.is_spectator,
                    "isAfk": p.is_afk,
                    "kickVotes": list(p.kick_votes),
                    "afkVotes": list(p.afk_votes),
                }
                for p in self.player_list()
            ],
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
        prompt_list_slugs: list[str] | None = None,
        curated_prompts: list[str] | None = None,
    ) -> Room:
        room_id = str(uuid.uuid4())
        final_name = name.strip() if name and name.strip() else generate_random_room_name()
        hint_mode = resolve_hint_mode(hint_mode, scoring_mode, hide_masked_prompt)
        room = Room(
            id=room_id,
            code=self._generate_unique_code(),
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
            prompt_list_slugs=list(prompt_list_slugs or []),
            curated_prompts=list(curated_prompts or []),
        )
        self.rooms[room_id] = room
        return room

    def _generate_unique_code(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        existing = {r.code for r in self.rooms.values()}
        while True:
            code = "".join(random.choices(alphabet, k=6))
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
        )
        room.players[player_id] = player
        return player

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
            )
        for p in room.players.values():
            p.kick_votes.discard(player_id)
            p.afk_votes.discard(player_id)
        self._promote_new_host_if_needed(room)

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

    def remove_room_if_empty(self, room_id: str) -> None:
        room = self.rooms.get(room_id)
        if room and not room.connected_players():
            del self.rooms[room_id]

"""In-memory Player/Room domain model and RoomManager."""
from __future__ import annotations

import random
import re
import secrets
import string
import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional

from app.game import Game
from app.words import WORDS

STARTING_SCORE = 50
DEFAULT_ROOM_DRAWING_SECONDS = 90
DEFAULT_ROOM_HINT_MODE = "checkpoints"
DRAWING_TIME_OPTIONS = (15, 30, 60, 90, 120, 180, 240, 300)
MAX_PLAYERS_MIN = 2
MAX_PLAYERS_MAX = 16


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
    reconnect_secret: str
    nickname: str
    name_color: str = field(default_factory=generate_random_name_color)
    sid: Optional[str] = None
    score: int = STARTING_SCORE
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
        return (len(self.eligible_voter_ids) // 2) + 1

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
class DrawingRecapEntry:
    round_number: int
    turn_number: int
    drawer_id: str
    drawer_nickname: str
    drawer_name_color: str | None
    word: str
    action_count: int
    canvas_history: bytes

    def metadata(self, index: int) -> dict:
        return {
            "index": index,
            "roundNumber": self.round_number,
            "turnNumber": self.turn_number,
            "drawerId": self.drawer_id,
            "drawerNickname": self.drawer_nickname,
            "drawerNameColor": self.drawer_name_color,
            "word": self.word,
            "actionCount": self.action_count,
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
    custom_words: list[str] = field(default_factory=list)
    custom_words_only: bool = False
    drawing_seconds: int = DEFAULT_ROOM_DRAWING_SECONDS
    hint_mode: str = DEFAULT_ROOM_HINT_MODE
    scoring_mode: str = "default"
    spectators_see_solution: bool = False
    hide_masked_prompt: bool = False
    word_list_slugs: list[str] = field(default_factory=list)
    curated_words: list[str] = field(default_factory=list)
    players: dict[str, Player] = field(default_factory=dict)
    state: str = "waiting"  # waiting | playing
    game: Optional[Game] = None
    canvas_generation: int = 0
    last_game_scores: list[dict] = field(default_factory=list)
    last_game_drawings: list[DrawingRecapEntry] = field(default_factory=list)
    restart_vote: RestartVote | None = None
    restart_vote_cooldown_until: float = 0

    def player_list(self) -> list[Player]:
        return list(self.players.values())

    def connected_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.connected]

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
            "requiredVotes": (len(eligible_voter_ids) // 2) + 1,
        }

    def drawing_recap_metadata(self) -> list[dict]:
        return [
            drawing.metadata(index)
            for index, drawing in enumerate(self.last_game_drawings)
        ]

    def allocate_canvas_generation(self) -> int:
        """Return the next room-lifetime canvas protocol identity."""
        self.canvas_generation += 1
        return self.canvas_generation

    def effective_word_pool(self) -> list[str] | None:
        """Return the word pool a Game should draw from, or None for the default list.

        If custom_words_only is set and custom words exist, returns just the custom words.
        Otherwise, merges custom words with curated words (or fallback WORDS if none provided),
        with custom words first, deduplicated case-insensitively.
        """
        base_words = self.curated_words if self.curated_words else WORDS
        if not self.custom_words and not self.curated_words:
            return None
        if not self.custom_words:
            return self.curated_words
        if self.custom_words_only:
            return self.custom_words
        seen = {w.lower() for w in self.custom_words}
        return self.custom_words + [w for w in base_words if w.lower() not in seen]

    def to_public_summary(self) -> dict:
        active_players = [p for p in self.players.values() if not p.is_spectator]
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
            "customWordCount": len(self.custom_words),
            "customWordsOnly": self.custom_words_only,
            "drawingSeconds": self.drawing_seconds,
            "hintMode": self.hint_mode,
            "scoringMode": self.scoring_mode,
            "spectatorsSeeSolution": self.spectators_see_solution,
            "hideMaskedPrompt": self.hide_masked_prompt,
            "wordListSlugs": list(self.word_list_slugs),
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
            "customWordCount": len(self.custom_words),
            "customWordsOnly": self.custom_words_only,
            "drawingSeconds": self.drawing_seconds,
            "hintMode": self.hint_mode,
            "scoringMode": self.scoring_mode,
            "spectatorsSeeSolution": self.spectators_see_solution,
            "hideMaskedPrompt": self.hide_masked_prompt,
            "wordListSlugs": list(self.word_list_slugs),
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
        custom_words: list[str] | None = None,
        custom_words_only: bool = False,
        drawing_seconds: int = DEFAULT_ROOM_DRAWING_SECONDS,
        hint_mode: str = DEFAULT_ROOM_HINT_MODE,
        scoring_mode: str = "default",
        spectators_see_solution: bool = False,
        hide_masked_prompt: bool = False,
        word_list_slugs: list[str] | None = None,
        curated_words: list[str] | None = None,
    ) -> Room:
        room_id = str(uuid.uuid4())
        final_name = name.strip() if name and name.strip() else generate_random_room_name()
        if hide_masked_prompt:
            hint_mode = "none"
        room = Room(
            id=room_id,
            code=self._generate_unique_code(),
            name=final_name,
            is_public=is_public,
            max_players=max_players,
            rounds=rounds,
            custom_words=custom_words or [],
            custom_words_only=custom_words_only,
            drawing_seconds=drawing_seconds,
            hint_mode=hint_mode,
            scoring_mode=scoring_mode,
            spectators_see_solution=spectators_see_solution,
            hide_masked_prompt=hide_masked_prompt,
            word_list_slugs=list(word_list_slugs or []),
            curated_words=list(curated_words or []),
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
    ) -> Player:
        active_players = [p for p in room.players.values() if not p.is_spectator]
        if not is_spectator and len(active_players) >= room.max_players:
            raise RoomFullError("Room is full")
        player_id = str(uuid.uuid4())
        player = Player(
            id=player_id,
            reconnect_secret=secrets.token_urlsafe(32),
            nickname=nickname,
            name_color=normalize_name_color(name_color) or generate_random_name_color(),
            score=0 if is_spectator else (STARTING_SCORE if room.scoring_mode == "default" else 0),
            is_host=not is_spectator and len(active_players) == 0,
            is_spectator=is_spectator,
        )
        room.players[player_id] = player
        return player

    def get_player_by_reconnect_secret(
        self, room: Room, reconnect_secret: object
    ) -> Player | None:
        if not isinstance(reconnect_secret, str) or not reconnect_secret:
            return None
        return next(
            (
                player
                for player in room.players.values()
                if secrets.compare_digest(player.reconnect_secret, reconnect_secret)
            ),
            None,
        )

    def remove_player(self, room: Room, player_id: str) -> None:
        room.players.pop(player_id, None)
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

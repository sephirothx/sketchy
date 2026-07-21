"""In-memory Player/Room domain model and RoomManager."""
from __future__ import annotations

import random
import string
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.game import DRAWING_SECONDS, Game
from app.words import WORDS

STARTING_SCORE = 50


class RoomFullError(Exception):
    pass


@dataclass
class Player:
    token: str
    nickname: str
    sid: Optional[str] = None
    score: int = STARTING_SCORE
    connected: bool = True
    is_host: bool = False


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
    drawing_seconds: int = DRAWING_SECONDS
    hint_mode: str = "none"
    players: dict[str, Player] = field(default_factory=dict)
    state: str = "waiting"  # waiting | playing
    game: Optional[Game] = None

    def player_list(self) -> list[Player]:
        return list(self.players.values())

    def connected_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.connected]

    def effective_word_pool(self) -> list[str] | None:
        """Return the word pool a Game should draw from, or None for the default list.

        If no custom words were provided, returns None (Game falls back to the
        built-in WORDS). If `custom_words_only` is set, returns just the custom
        words. Otherwise, merges custom words with the default list (custom
        words first, deduped case-insensitively) so they extend the variety
        rather than replacing it.
        """
        if not self.custom_words:
            return None
        if self.custom_words_only:
            return self.custom_words
        seen = {w.lower() for w in self.custom_words}
        return self.custom_words + [w for w in WORDS if w.lower() not in seen]

    def to_public_summary(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "isPublic": self.is_public,
            "playerCount": len(self.connected_players()),
            "maxPlayers": self.max_players,
            "rounds": self.rounds,
            "customWordCount": len(self.custom_words),
            "customWordsOnly": self.custom_words_only,
            "drawingSeconds": self.drawing_seconds,
            "hintMode": self.hint_mode,
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
            "state": self.state,
            "players": [
                {
                    "token": p.token,
                    "nickname": p.nickname,
                    "score": p.score,
                    "connected": p.connected,
                    "isHost": p.is_host,
                }
                for p in self.player_list()
            ],
        }


class RoomManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}

    def create_room(
        self,
        name: str,
        is_public: bool,
        max_players: int = 8,
        rounds: int = 3,
        custom_words: list[str] | None = None,
        custom_words_only: bool = False,
        drawing_seconds: int = DRAWING_SECONDS,
        hint_mode: str = "none",
    ) -> Room:
        room_id = str(uuid.uuid4())
        room = Room(
            id=room_id,
            code=self._generate_unique_code(),
            name=name,
            is_public=is_public,
            max_players=max_players,
            rounds=rounds,
            custom_words=custom_words or [],
            custom_words_only=custom_words_only,
            drawing_seconds=drawing_seconds,
            hint_mode=hint_mode,
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

    def add_player(self, room: Room, nickname: str) -> Player:
        if len(room.players) >= room.max_players:
            raise RoomFullError("Room is full")
        token = str(uuid.uuid4())
        player = Player(token=token, nickname=nickname, is_host=len(room.players) == 0)
        room.players[token] = player
        return player

    def remove_player(self, room: Room, token: str) -> None:
        room.players.pop(token, None)
        self._promote_new_host_if_needed(room)

    def _promote_new_host_if_needed(self, room: Room) -> None:
        if any(p.is_host for p in room.players.values()):
            return
        for p in room.players.values():
            p.is_host = True
            break

    def remove_room_if_empty(self, room_id: str) -> None:
        room = self.rooms.get(room_id)
        if room and not room.connected_players():
            del self.rooms[room_id]

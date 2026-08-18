"""Typed validation for every client-originated Socket.IO command.

Payload policy
--------------
JSON commands accept objects only (``None`` is also accepted for commands with
no fields). Values are never coerced: strings and booleans must have their JSON
types, and integers must be integers (not booleans). Unknown fields are rejected.
All strings and integers are bounded here before handlers authorize or mutate.

The drawing protocol is the deliberate exception to the JSON-object rule. Its
``draw`` event carries a compact binary frame plus an optional two-integer action
identity; ``undo_stroke`` carries a fixed four-integer tuple. Both wire shapes are
validated here before the handler reads game state.

Command inventory (client request shape)
----------------------------------------
``create_room`` CreateRoomPayload; ``join_room`` JoinRoomPayload;
``get_room_preview`` RoomPreviewPayload; ``update_room_settings``
UpdateRoomSettingsPayload; ``update_player_settings`` PlayerSettingsPayload;
``get_recap_drawing`` RecapDrawingPayload; ``toggle_afk`` ToggleAfkPayload;
``vote_player`` VotePayload; ``cast_restart_vote`` RestartVotePayload;
``select_word`` SelectWordPayload; ``send_chat`` and
``guess`` TextPayload; ``buy_hint`` HintPayload; ``buy_wheel_letter``
WheelLetterPayload; ``draw`` DrawPayload; ``undo_stroke`` UndoPayload. The
remaining commands (room/custom-word reads, promotion, leave, game start,
session ping, and canvas sync) have EmptyPayload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.game import HINT_MODES, SCORING_MODES
from app.live_drawing import LiveDrawingPacket, decode_live_drawing
from app.auth.names import MAX_NAME_LENGTH, NAME_RULE_MESSAGE, NameError_, validate_name
from app.message_limits import MAX_CHAT_MESSAGE_LENGTH
from app.rooms import (
    DEFAULT_ROOM_DRAWING_SECONDS,
    DEFAULT_ROOM_HINT_MODE,
    DRAWING_TIME_OPTIONS,
    MAX_PLAYERS_MAX,
    MAX_PLAYERS_MIN,
)
from app.words import MAX_RAW_INPUT_LENGTH, MAX_WORD_LENGTH

MAX_CANVAS_SEQUENCE = 2**31 - 1
MAX_ROOM_NAME_LENGTH = 40
# Guest nicknames and account usernames share one rule (app/auth/names.py).
# Keep in sync with frontend/src/lib/roomEntryState.ts MAX_NICKNAME_LENGTH.
MAX_NICKNAME_LENGTH = MAX_NAME_LENGTH
MAX_IDENTIFIER_LENGTH = 128


class PayloadError(ValueError):
    """A safe validation failure suitable for a Socket.IO acknowledgement."""

    def __init__(self, error: str = "Invalid request payload", *, field: str | None = None):
        super().__init__(error)
        self.error = error
        self.field = field

    def acknowledgement(self) -> dict[str, object]:
        response: dict[str, object] = {"ok": False, "error": self.error}
        if self.field:
            response["field"] = self.field
        return response


class RequestModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)


class EmptyPayload(RequestModel):
    pass


class RoomSettingsFields(RequestModel):
    name: str = Field(default="", max_length=MAX_ROOM_NAME_LENGTH)
    is_public: bool = Field(default=True, alias="isPublic")
    max_players: int = Field(default=8, alias="maxPlayers", ge=MAX_PLAYERS_MIN, le=MAX_PLAYERS_MAX)
    rounds: int = Field(default=3, ge=1, le=10)
    drawing_seconds: int = Field(default=DEFAULT_ROOM_DRAWING_SECONDS, alias="drawingSeconds")
    custom_words: str = Field(default="", alias="customWords", max_length=MAX_RAW_INPUT_LENGTH)
    custom_words_only: bool = Field(default=False, alias="customWordsOnly")
    hint_mode: str = Field(default=DEFAULT_ROOM_HINT_MODE, alias="hintMode")
    scoring_mode: str = Field(default="default", alias="scoringMode")
    spectators_see_solution: bool = Field(default=False, alias="spectatorsSeeSolution")
    hide_masked_prompt: bool = Field(default=False, alias="hideMaskedPrompt")
    word_list_slugs: list[str] = Field(default_factory=lambda: ["english_standard"], alias="wordListSlugs")

    @field_validator("name", "custom_words")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("word_list_slugs")
    @classmethod
    def clean_word_list_slugs(cls, slugs: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for s in slugs:
            trimmed = s.strip().lower()
            if trimmed and trimmed not in seen:
                seen.add(trimmed)
                cleaned.append(trimmed)
        if len(cleaned) > 20:
            raise ValueError("too many word lists selected (max 20)")
        return cleaned if cleaned else ["english_standard"]

    @field_validator("drawing_seconds")
    @classmethod
    def valid_drawing_seconds(cls, value: int) -> int:
        if value not in DRAWING_TIME_OPTIONS:
            raise ValueError("must be a supported drawing duration")
        return value

    @field_validator("hint_mode")
    @classmethod
    def valid_hint_mode(cls, value: str) -> str:
        if value not in HINT_MODES:
            raise ValueError(f"must be one of {', '.join(sorted(HINT_MODES))}")
        return value

    @field_validator("scoring_mode")
    @classmethod
    def valid_scoring_mode(cls, value: str) -> str:
        if value not in SCORING_MODES:
            raise ValueError(f"must be one of {', '.join(sorted(SCORING_MODES))}")
        return value

    @model_validator(mode="after")
    def disable_incompatible_hints(self) -> "RoomSettingsFields":
        if self.hide_masked_prompt or (
            self.scoring_mode == "none" and self.hint_mode in {"purchase", "wheel"}
        ):
            self.hint_mode = "none"
        return self


class CreateRoomPayload(RoomSettingsFields):
    nickname: str = Field(default="Player", max_length=MAX_NICKNAME_LENGTH)
    name_color: str | None = Field(default=None, alias="nameColor", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value: str) -> str:
        try:
            return validate_name(value)
        except NameError_ as error:
            raise ValueError(str(error) or NAME_RULE_MESSAGE) from error


class UpdateRoomSettingsPayload(RequestModel):

    name: str | None = Field(default=None, max_length=MAX_ROOM_NAME_LENGTH)
    is_public: bool | None = Field(default=None, alias="isPublic")
    max_players: int | None = Field(default=None, alias="maxPlayers", ge=MAX_PLAYERS_MIN, le=MAX_PLAYERS_MAX)
    rounds: int | None = Field(default=None, ge=1, le=10)
    drawing_seconds: int | None = Field(default=None, alias="drawingSeconds")
    custom_words: str | None = Field(default=None, alias="customWords", max_length=MAX_RAW_INPUT_LENGTH)
    custom_words_only: bool | None = Field(default=None, alias="customWordsOnly")
    hint_mode: str | None = Field(default=None, alias="hintMode")
    scoring_mode: str | None = Field(default=None, alias="scoringMode")
    spectators_see_solution: bool | None = Field(default=None, alias="spectatorsSeeSolution")
    hide_masked_prompt: bool | None = Field(default=None, alias="hideMaskedPrompt")
    word_list_slugs: list[str] | None = Field(default=None, alias="wordListSlugs")

    @field_validator("word_list_slugs")
    @classmethod
    def clean_update_word_list_slugs(cls, slugs: list[str] | None) -> list[str] | None:
        if slugs is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for s in slugs:
            trimmed = s.strip().lower()
            if trimmed and trimmed not in seen:
                seen.add(trimmed)
                cleaned.append(trimmed)
        if len(cleaned) > 20:
            raise ValueError("too many word lists selected (max 20)")
        if not cleaned:
            raise ValueError("at least one word list must be selected")
        return cleaned

    @field_validator("name", "custom_words")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("drawing_seconds")
    @classmethod
    def valid_drawing_seconds(cls, value: int | None) -> int | None:
        if value is not None and value not in DRAWING_TIME_OPTIONS:
            raise ValueError("must be a supported drawing duration")
        return value

    @field_validator("hint_mode")
    @classmethod
    def valid_hint_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in HINT_MODES:
            raise ValueError("must be a supported hint mode")
        return value

    @field_validator("scoring_mode")
    @classmethod
    def valid_scoring_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in SCORING_MODES:
            raise ValueError("must be a supported scoring mode")
        return value


class JoinRoomPayload(RequestModel):
    room_id: str | None = Field(default=None, alias="roomId", max_length=MAX_IDENTIFIER_LENGTH)
    code: str | None = Field(default=None, max_length=16)
    nickname: str = Field(default="Player", max_length=MAX_NICKNAME_LENGTH)
    name_color: str | None = Field(default=None, alias="nameColor", pattern=r"^#[0-9a-fA-F]{6}$")
    as_spectator: bool = Field(default=False, alias="asSpectator")
    soft: bool = False
    # "Do I already hold a seat here?" - used by the invite screen, which must
    # not seat a visitor who is still deciding whether to play or spectate.
    resume_only: bool = Field(default=False, alias="resumeOnly")

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value: str) -> str:
        try:
            return validate_name(value)
        except NameError_ as error:
            raise ValueError(str(error) or NAME_RULE_MESSAGE) from error

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @model_validator(mode="after")
    def requires_room_reference(self) -> "JoinRoomPayload":
        if not self.room_id and not self.code:
            raise ValueError("roomId or code is required")
        return self


class RoomPreviewPayload(RequestModel):
    code: str = Field(min_length=1, max_length=16)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class PlayerSettingsPayload(RequestModel):
    name_color: str = Field(alias="nameColor", pattern=r"^#[0-9a-fA-F]{6}$")


class RecapDrawingPayload(RequestModel):
    index: int = Field(ge=0, le=MAX_CANVAS_SEQUENCE)


class ToggleAfkPayload(RequestModel):
    afk: bool | None = None


class VotePayload(RequestModel):
    target_player_id: str = Field(alias="targetPlayerId", min_length=1, max_length=MAX_IDENTIFIER_LENGTH)
    action: Literal["kick", "afk"]


class RestartVotePayload(RequestModel):
    vote: bool


class SelectWordPayload(RequestModel):
    word: str = Field(min_length=1, max_length=MAX_WORD_LENGTH)


class TextPayload(RequestModel):
    text: str = Field(max_length=MAX_CHAT_MESSAGE_LENGTH)


class HintPayload(RequestModel):
    slot: int = Field(ge=0, le=MAX_WORD_LENGTH - 1)


class WheelLetterPayload(RequestModel):
    letter: str = Field(min_length=1, max_length=1, pattern=r"^[A-Za-z]$")

    @field_validator("letter")
    @classmethod
    def normalize_letter(cls, value: str) -> str:
        return value.lower()


@dataclass(frozen=True, slots=True)
class DrawPayload:
    packet: LiveDrawingPacket
    wire_data: int | bytes
    action_identity: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class UndoPayload:
    generation: int
    sequence: int
    revision: int
    history_hash: int


def parse_payload(model: type[RequestModel], data: Any, *, allow_none: bool = False) -> Any:
    if data is None and allow_none:
        data = {}
    if not isinstance(data, dict):
        raise PayloadError("Request payload must be an object")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        location = exc.errors()[0].get("loc", ())
        field = str(location[0]) if location else None
        raise PayloadError(field=field) from exc


def parse_empty_payload(data: Any) -> EmptyPayload:
    return parse_payload(EmptyPayload, data, allow_none=True)


def _canvas_sequence(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CANVAS_SEQUENCE:
        return None
    return value


def parse_draw_payload(data: Any, action_identity: Any = None) -> DrawPayload:
    try:
        packet = decode_live_drawing(data)
    except (TypeError, ValueError) as exc:
        raise PayloadError("Invalid drawing payload") from exc
    starts_action = packet.event in {"draw_start", "draw_shape", "draw_fill", "clear_canvas"}
    identity: tuple[int, int] | None = None
    if action_identity is not None:
        if (
            not isinstance(action_identity, list)
            or len(action_identity) != 2
            or (generation := _canvas_sequence(action_identity[0])) is None
            or (sequence := _canvas_sequence(action_identity[1])) is None
        ):
            raise PayloadError("Invalid drawing action identity")
        identity = (generation, sequence)
    if starts_action and identity is None:
        raise PayloadError("Drawing action identity is required")
    if not starts_action and identity is not None:
        raise PayloadError("Drawing action identity is not allowed for this frame")
    wire_data = data if isinstance(data, int) else bytes(data)
    return DrawPayload(packet=packet, wire_data=wire_data, action_identity=identity)


def parse_undo_payload(data: Any) -> UndoPayload:
    if not isinstance(data, list) or len(data) != 4:
        raise PayloadError("Invalid undo request")
    generation = _canvas_sequence(data[0])
    sequence = _canvas_sequence(data[1])
    revision, history_hash = data[2], data[3]
    if (
        generation is None
        or sequence is None
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
        or revision > MAX_CANVAS_SEQUENCE
        or isinstance(history_hash, bool)
        or not isinstance(history_hash, int)
        or not 0 <= history_hash <= 0xFFFFFFFF
    ):
        raise PayloadError("Invalid undo request")
    return UndoPayload(generation, sequence, revision, history_hash)

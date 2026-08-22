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
``rename_player`` RenamePlayerPayload; ``get_recap_drawing`` RecapDrawingPayload; ``toggle_afk`` ToggleAfkPayload;
``vote_player`` VotePayload; ``cast_restart_vote`` RestartVotePayload;
``select_prompt`` SelectPromptPayload; ``send_chat`` and
``guess`` TextPayload; ``buy_hint`` HintPayload; ``buy_wheel_letter``
WheelLetterPayload; ``draw`` DrawPayload; ``undo_stroke`` UndoPayload. The
remaining commands (room/custom-prompt reads, promotion, leave, game start,
session ping, and canvas sync) have EmptyPayload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.drawing_rules import (
    DEFAULT_ALLOWED_TOOLS,
    DEFAULT_COLOR_MODE,
    check_color_mode,
    clean_allowed_tools,
)
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
from app.prompts import MAX_RAW_INPUT_LENGTH, MAX_PROMPT_LENGTH

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


MAX_PROMPT_LISTS = 20


def _clean_slugs(slugs: list[str]) -> list[str]:
    """Trim, lowercase and dedupe prompt-list slugs, order preserved.

    Returns [] when nothing survives, leaving each caller to decide what an
    empty selection means: create falls back to the default list, update
    rejects it.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for slug in slugs:
        trimmed = slug.strip().lower()
        if trimmed and trimmed not in seen:
            seen.add(trimmed)
            cleaned.append(trimmed)
    if len(cleaned) > MAX_PROMPT_LISTS:
        raise ValueError(f"too many prompt lists selected (max {MAX_PROMPT_LISTS})")
    return cleaned


def _check_drawing_seconds(value: int) -> int:
    if value not in DRAWING_TIME_OPTIONS:
        raise ValueError("must be a supported drawing duration")
    return value


def _check_hint_mode(value: str) -> str:
    if value not in HINT_MODES:
        raise ValueError(f"must be one of {', '.join(sorted(HINT_MODES))}")
    return value


def _check_scoring_mode(value: str) -> str:
    if value not in SCORING_MODES:
        raise ValueError(f"must be one of {', '.join(sorted(SCORING_MODES))}")
    return value


class RoomSettingsFields(RequestModel):
    name: str = Field(default="", max_length=MAX_ROOM_NAME_LENGTH)
    is_public: bool = Field(default=True, alias="isPublic")
    max_players: int = Field(default=8, alias="maxPlayers", ge=MAX_PLAYERS_MIN, le=MAX_PLAYERS_MAX)
    rounds: int = Field(default=3, ge=1, le=10)
    drawing_seconds: int = Field(default=DEFAULT_ROOM_DRAWING_SECONDS, alias="drawingSeconds")
    custom_prompts: str = Field(default="", alias="customPrompts", max_length=MAX_RAW_INPUT_LENGTH)
    custom_prompts_only: bool = Field(default=False, alias="customPromptsOnly")
    hint_mode: str = Field(default=DEFAULT_ROOM_HINT_MODE, alias="hintMode")
    scoring_mode: str = Field(default="default", alias="scoringMode")
    spectators_see_prompt: bool = Field(default=False, alias="spectatorsSeePrompt")
    hide_masked_prompt: bool = Field(default=False, alias="hideMaskedPrompt")
    allowed_tools: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS), alias="allowedTools"
    )
    color_mode: str = Field(default=DEFAULT_COLOR_MODE, alias="colorMode")
    prompt_list_slugs: list[str] = Field(default_factory=lambda: ["english_standard"], alias="promptListSlugs")

    @field_validator("name", "custom_prompts")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("prompt_list_slugs")
    @classmethod
    def clean_prompt_list_slugs(cls, slugs: list[str]) -> list[str]:
        return _clean_slugs(slugs) or ["english_standard"]

    @field_validator("drawing_seconds")
    @classmethod
    def valid_drawing_seconds(cls, value: int) -> int:
        return _check_drawing_seconds(value)

    @field_validator("hint_mode")
    @classmethod
    def valid_hint_mode(cls, value: str) -> str:
        return _check_hint_mode(value)

    @field_validator("scoring_mode")
    @classmethod
    def valid_scoring_mode(cls, value: str) -> str:
        return _check_scoring_mode(value)

    @field_validator("allowed_tools")
    @classmethod
    def valid_allowed_tools(cls, value: list[str]) -> list[str]:
        return clean_allowed_tools(value)

    @field_validator("color_mode")
    @classmethod
    def valid_color_mode(cls, value: str) -> str:
        return check_color_mode(value)


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
    custom_prompts: str | None = Field(default=None, alias="customPrompts", max_length=MAX_RAW_INPUT_LENGTH)
    custom_prompts_only: bool | None = Field(default=None, alias="customPromptsOnly")
    hint_mode: str | None = Field(default=None, alias="hintMode")
    scoring_mode: str | None = Field(default=None, alias="scoringMode")
    spectators_see_prompt: bool | None = Field(default=None, alias="spectatorsSeePrompt")
    hide_masked_prompt: bool | None = Field(default=None, alias="hideMaskedPrompt")
    allowed_tools: list[str] | None = Field(default=None, alias="allowedTools")
    color_mode: str | None = Field(default=None, alias="colorMode")
    prompt_list_slugs: list[str] | None = Field(default=None, alias="promptListSlugs")

    @field_validator("allowed_tools")
    @classmethod
    def valid_update_allowed_tools(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else clean_allowed_tools(value)

    @field_validator("color_mode")
    @classmethod
    def valid_update_color_mode(cls, value: str | None) -> str | None:
        return None if value is None else check_color_mode(value)

    @field_validator("prompt_list_slugs")
    @classmethod
    def clean_update_prompt_list_slugs(cls, slugs: list[str] | None) -> list[str] | None:
        if slugs is None:
            return None
        cleaned = _clean_slugs(slugs)
        if not cleaned:
            raise ValueError("at least one prompt list must be selected")
        return cleaned

    @field_validator("name", "custom_prompts")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("drawing_seconds")
    @classmethod
    def valid_drawing_seconds(cls, value: int | None) -> int | None:
        return _check_drawing_seconds(value) if value is not None else None

    @field_validator("hint_mode")
    @classmethod
    def valid_hint_mode(cls, value: str | None) -> str | None:
        return _check_hint_mode(value) if value is not None else None

    @field_validator("scoring_mode")
    @classmethod
    def valid_scoring_mode(cls, value: str | None) -> str | None:
        return _check_scoring_mode(value) if value is not None else None


class JoinRoomPayload(RequestModel):
    room_id: str | None = Field(default=None, alias="roomId", max_length=MAX_IDENTIFIER_LENGTH)
    code: str | None = Field(default=None, max_length=16)
    nickname: str = Field(default="Player", max_length=MAX_NICKNAME_LENGTH)
    name_color: str | None = Field(default=None, alias="nameColor", pattern=r"^#[0-9a-fA-F]{6}$")
    as_spectator: bool = Field(default=False, alias="asSpectator")
    soft: bool = False
    # "Do I already hold a seat here?" - used by the invite screen, which must
    # not seat a visitor who is still deciding whether to play or spectate.
    reconnect_only: bool = Field(default=False, alias="reconnectOnly")

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value: str) -> str:
        # Only trimmed here, deliberately. A join carrying an empty or stale
        # name still has to reach the handler, which resolves identity from the
        # session cookie - rejecting it at the payload would stop a returning
        # player from resuming their seat. resolve_identity applies the naming
        # rule at the point a genuinely new seat is created.
        return value.strip()

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


class RenamePlayerPayload(RequestModel):
    nickname: str = Field(max_length=MAX_NICKNAME_LENGTH)

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value: str) -> str:
        try:
            return validate_name(value)
        except NameError_ as error:
            raise ValueError(str(error) or NAME_RULE_MESSAGE) from error


class RecapDrawingPayload(RequestModel):
    index: int = Field(ge=0, le=MAX_CANVAS_SEQUENCE)


class ToggleAfkPayload(RequestModel):
    afk: bool | None = None


class VotePayload(RequestModel):
    target_player_id: str = Field(alias="targetPlayerId", min_length=1, max_length=MAX_IDENTIFIER_LENGTH)
    action: Literal["kick", "afk"]


class RestartVotePayload(RequestModel):
    vote: bool


class SelectPromptPayload(RequestModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)


class TextPayload(RequestModel):
    text: str = Field(max_length=MAX_CHAT_MESSAGE_LENGTH)


class HintPayload(RequestModel):
    slot: int = Field(ge=0, le=MAX_PROMPT_LENGTH - 1)


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

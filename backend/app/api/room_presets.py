"""Authenticated CRUD API for private reusable room-setting presets."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import ConfigDict, Field

from app.handlers.payloads import RequestModel, RoomSettingsFields
from app.services.room_presets import (
    RoomPresetConfig,
    RoomPresetAuthorizationError,
    RoomPresetConflict,
    RoomPresetError,
    RoomPresetNotFound,
    RoomPresetService,
    RoomPresetSummary,
    RoomPresetUnavailable,
)


class CreateRoomPresetRequest(RequestModel):
    name: str = Field(min_length=1, max_length=64)
    settings: RoomSettingsFields


class UpdateRoomPresetRequest(CreateRoomPresetRequest):
    model_config = ConfigDict(
        strict=True, extra="forbid", populate_by_name=True
    )
    expected_version: int = Field(alias="expectedVersion", ge=1)


def _summary_payload(preset: RoomPresetSummary) -> dict:
    return {
        "id": preset.id,
        "name": preset.name,
        "version": preset.version,
        "createdAt": preset.created_at.isoformat(),
        "updatedAt": preset.updated_at.isoformat(),
    }


def _config_payload(preset: RoomPresetConfig) -> dict:
    return {
        **_summary_payload(preset),
        "settings": {
            "name": preset.room_name,
            "isPublic": preset.is_public,
            "maxPlayers": preset.max_players,
            "rounds": preset.rounds,
            "drawingSeconds": preset.drawing_seconds,
            "customPrompts": "",
            "customPromptsOnly": False,
            "hintMode": preset.hint_mode,
            "scoringMode": preset.scoring_mode,
            "spectatorsSeePrompt": preset.spectators_see_prompt,
            "hideMaskedPrompt": preset.hide_masked_prompt,
            "allowedTools": list(preset.allowed_tools),
            "colorMode": preset.color_mode,
            "promptListSlugs": list(preset.prompt_list_slugs),
            "promptListShareCodes": [],
        },
    }


def _http_error(error: RoomPresetError) -> HTTPException:
    if isinstance(error, RoomPresetAuthorizationError):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, RoomPresetNotFound):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, RoomPresetConflict):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, RoomPresetUnavailable):
        return HTTPException(status_code=422, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


def create_room_preset_router(service: RoomPresetService) -> APIRouter:
    router = APIRouter(prefix="/api/room-presets")

    def user_id(request: Request) -> str:
        value = getattr(request.state, "user_id", None)
        if not value:
            raise HTTPException(status_code=401, detail="Sign in first.")
        return value

    @router.get("")
    async def list_room_presets(request: Request):
        try:
            return [
                _summary_payload(item)
                for item in await service.list_owned(user_id(request))
            ]
        except RoomPresetError as error:
            raise _http_error(error) from error

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_room_preset(body: CreateRoomPresetRequest, request: Request):
        try:
            preset = await service.create(
                owner_user_id=user_id(request),
                name=body.name,
                settings=body.settings.model_dump(),
            )
        except RoomPresetError as error:
            raise _http_error(error) from error
        return _config_payload(preset)

    @router.get("/{preset_id}")
    async def get_room_preset(preset_id: str, request: Request):
        try:
            preset = await service.get_owned(
                owner_user_id=user_id(request), preset_id=preset_id
            )
        except (RoomPresetError, ValueError) as error:
            if isinstance(error, RoomPresetError):
                raise _http_error(error) from error
            raise HTTPException(status_code=404, detail="Room preset not found") from error
        return _config_payload(preset)

    @router.put("/{preset_id}")
    async def update_room_preset(
        preset_id: str, body: UpdateRoomPresetRequest, request: Request
    ):
        try:
            preset = await service.update(
                owner_user_id=user_id(request),
                preset_id=preset_id,
                expected_version=body.expected_version,
                name=body.name,
                settings=body.settings.model_dump(),
            )
        except (RoomPresetError, ValueError) as error:
            if isinstance(error, RoomPresetError):
                raise _http_error(error) from error
            raise HTTPException(status_code=404, detail="Room preset not found") from error
        return _config_payload(preset)

    @router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_room_preset(preset_id: str, request: Request):
        try:
            await service.delete(
                owner_user_id=user_id(request), preset_id=preset_id
            )
        except (RoomPresetError, ValueError) as error:
            if isinstance(error, RoomPresetError):
                raise _http_error(error) from error
            raise HTTPException(status_code=404, detail="Room preset not found") from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router

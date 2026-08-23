"""Owner-facing discovery for persistent group rooms."""

from fastapi import APIRouter, HTTPException, Request

from app.services.persistent_rooms import PersistentRoomConfig, PersistentRoomService


def _payload(room: PersistentRoomConfig) -> dict:
    return {
        "id": room.id,
        "code": room.code,
        "name": room.name,
        "isPublic": room.is_public,
        "maxPlayers": room.max_players,
        "rounds": room.rounds,
        "drawingSeconds": room.drawing_seconds,
        "hintMode": room.hint_mode,
        "scoringMode": room.scoring_mode,
        "version": room.version,
    }


def create_persistent_room_router(service: PersistentRoomService) -> APIRouter:
    router = APIRouter(prefix="/api/persistent-rooms")

    @router.get("")
    async def list_owned_persistent_rooms(request: Request):
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(status_code=401, detail="Sign in first.")
        return [_payload(room) for room in await service.list_owned(user_id)]

    return router

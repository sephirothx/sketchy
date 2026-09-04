"""Uploading and serving player pictures (#573).

Four routes: the owner sets, picks a doodle for, or removes their own
picture, and anybody may fetch an uploaded picture by its content address. The address is the SHA-256 of the
bytes, so a fetched picture can be cached for ever - a changed picture is a
different URL - and served with sniffing disabled, as an image and nothing
else.
"""
from __future__ import annotations

import base64
import binascii
from typing import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.audit import audit_coordinates
from app.auth.avatars import (
    AVATAR_KEY_PATTERN,
    MAX_AVATAR_BYTES,
    AvatarError,
    avatar_url,
)
from app.auth.rate_limit import PersistentRateLimiter, client_key
from app.repositories.interfaces import UserRepository
from app.services.avatars import (
    AvatarBlocked,
    choose_doodle,
    read_avatar,
    remove_avatar,
    set_avatar,
)

# Base64 of the largest picture accepted, plus a little slack for padding.
MAX_AVATAR_BASE64 = ((MAX_AVATAR_BYTES + 2) // 3) * 4 + 8
AVATAR_UPLOAD_LIMIT = 10


class AvatarUploadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str = Field(min_length=1, max_length=MAX_AVATAR_BASE64)


class DoodleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=32)


def create_avatar_router(
    user_repo: UserRepository,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    # Called with the account and its new key (None once removed), so live
    # seats and the lobby's identity cache stop showing the old picture.
    on_avatar_changed: Callable[[str, str | None], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter()
    # Costs a write and a few kilobytes of storage per call; ten an hour is
    # room to get a crop right and no room to churn the table.
    upload_limiter = PersistentRateLimiter(
        session_factory,
        scope="avatar_upload",
        limit=AVATAR_UPLOAD_LIMIT,
        window_seconds=3600,
    )

    async def require_registered(request: Request):
        user_id = getattr(request.state, "user_id", None)
        user = await user_repo.get_by_id(user_id) if user_id else None
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in first.")
        if user.is_anonymous:
            # Guests play as the grey initial, so a name in the player list is
            # either a claimed account or an unclaimed guest (R-ACCT-05).
            raise HTTPException(
                status_code=403, detail="Create an account to choose a picture."
            )
        return user

    async def announce(user_id: str, key: str | None) -> None:
        if on_avatar_changed is not None:
            await on_avatar_changed(user_id, key)

    @router.post("/api/users/me/avatar")
    async def upload_avatar(body: AvatarUploadBody, request: Request):
        if not await upload_limiter.check(client_key(request)):
            raise HTTPException(
                status_code=429, detail="Too many pictures. Please wait and try again."
            )
        user = await require_registered(request)
        try:
            payload = base64.b64decode(body.image, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(
                status_code=400, detail="That is not a WebP or PNG picture."
            ) from error
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        try:
            key = await set_avatar(
                session_factory,
                user_id=user.id,
                payload=payload,
                request_id=request_id,
                ip_hash=ip_hash,
            )
        except AvatarBlocked as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except AvatarError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        await announce(user.id, key)
        return {"avatarKey": key, "avatarUrl": avatar_url(key)}

    @router.put("/api/users/me/avatar/doodle")
    async def pick_doodle(body: DoodleBody, request: Request):
        # No rate limit of its own: a doodle is one row update, nothing stored.
        user = await require_registered(request)
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        try:
            key = await choose_doodle(
                session_factory,
                user_id=user.id,
                name=body.name,
                request_id=request_id,
                ip_hash=ip_hash,
            )
        except AvatarError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        await announce(user.id, key)
        return {"avatarKey": key, "avatarUrl": avatar_url(key)}

    @router.delete("/api/users/me/avatar")
    async def delete_avatar(request: Request):
        user = await require_registered(request)
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        await remove_avatar(
            session_factory,
            user_id=user.id,
            actor_id=user.id,
            request_id=request_id,
            ip_hash=ip_hash,
        )
        await announce(user.id, None)
        return {"ok": True}

    @router.get("/api/avatars/{key}")
    async def serve_avatar(key: str):
        if not AVATAR_KEY_PATTERN.fullmatch(key):
            raise HTTPException(status_code=404, detail="No such picture.")
        found = await read_avatar(session_factory, key=key)
        if found is None:
            raise HTTPException(status_code=404, detail="No such picture.")
        payload, content_type = found
        return Response(
            content=payload,
            media_type=content_type,
            headers={
                # Content-addressed: these bytes never change under this URL.
                "Cache-Control": "public, max-age=31536000, immutable",
                # Only ever an image, whatever a crafted file might also be.
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline",
            },
        )

    return router

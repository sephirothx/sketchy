"""Registered-account preferences shared across devices."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User, UserSettings
from app.domain_values import AccountState, DEFAULT_USER_KEY_BINDINGS


KEY_BINDING_ACTIONS = (
    "brush",
    "fill",
    "eraser",
    "rectangle",
    "triangle",
    "ellipse",
    "brushDecrease",
    "brushIncrease",
    "undo",
)
DEFAULT_KEY_BINDINGS = DEFAULT_USER_KEY_BINDINGS


class UserSettingsError(RuntimeError):
    """A settings operation that does not apply to this account."""


def _validated_key_bindings(value: dict[str, list[str]] | None):
    if value is None:
        return value
    if set(value) != set(KEY_BINDING_ACTIONS):
        raise ValueError("keyBindings must contain every supported action exactly once")
    for keys in value.values():
        if not 1 <= len(keys) <= 2:
            raise ValueError("each action needs one or two key bindings")
        if len(set(keys)) != len(keys):
            raise ValueError("an action cannot bind the same key twice")
        if any(not key or len(key) > 24 for key in keys):
            raise ValueError("key bindings must be 1-24 characters")
    return value


class UserSettingsSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    theme: Literal["light", "dark", "system"] = "system"
    sound_effects: bool = Field(default=True, alias="soundEffects")
    confetti_effects: bool = Field(default=True, alias="confettiEffects")
    sound_effects_volume: float = Field(default=0.7, ge=0, le=1, alias="volume")
    brush_cursor: Literal["crosshair", "circle"] = Field(
        default="crosshair", alias="brushCursor"
    )
    key_bindings: dict[str, list[str]] = Field(
        default_factory=lambda: {key: list(value) for key, value in DEFAULT_KEY_BINDINGS.items()},
        alias="keyBindings",
    )
    colorblind_safe_colors: bool = Field(
        default=False, alias="colorblindSafeColors"
    )

    @field_validator("key_bindings")
    @classmethod
    def validate_key_bindings(cls, value):
        return _validated_key_bindings(value)


class UserSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    theme: Literal["light", "dark", "system"] | None = None
    sound_effects: bool | None = Field(default=None, alias="soundEffects")
    confetti_effects: bool | None = Field(default=None, alias="confettiEffects")
    sound_effects_volume: float | None = Field(
        default=None, ge=0, le=1, alias="volume"
    )
    brush_cursor: Literal["crosshair", "circle"] | None = Field(
        default=None, alias="brushCursor"
    )
    key_bindings: dict[str, list[str]] | None = Field(
        default=None, alias="keyBindings"
    )
    colorblind_safe_colors: bool | None = Field(
        default=None, alias="colorblindSafeColors"
    )

    @field_validator("key_bindings")
    @classmethod
    def validate_key_bindings(cls, value):
        return _validated_key_bindings(value)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("at least one setting is required")
        return self


def user_settings_payload(settings: UserSettings) -> dict:
    return {
        "theme": settings.theme,
        "soundEffects": settings.sound_effects,
        "confettiEffects": settings.confetti_effects,
        "volume": settings.sound_effects_volume,
        "brushCursor": settings.brush_cursor,
        "keyBindings": settings.key_bindings,
        "colorblindSafeColors": settings.colorblind_safe_colors,
        "createdAt": settings.created_at.isoformat(),
        "updatedAt": settings.updated_at.isoformat(),
    }


def _settings_values(values: UserSettingsSeed | UserSettingsPatch) -> dict:
    return {
        key: value
        for key, value in values.model_dump(by_alias=False).items()
        if value is not None
    }


async def _registered_user(session: AsyncSession, user_id: UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise UserSettingsError("account not found")
    if user.state != AccountState.REGISTERED.value:
        raise UserSettingsError("Create an account to sync settings across devices.")
    return user


async def get_or_create_user_settings(
    session_factory: async_sessionmaker[AsyncSession], *, user_id: str
) -> dict:
    db_user_id = UUID(user_id)
    async with session_factory() as session:
        async with session.begin():
            await _registered_user(session, db_user_id)
            settings = await session.get(UserSettings, db_user_id)
            if settings is None:
                settings = UserSettings(
                    user_id=db_user_id,
                    **_settings_values(UserSettingsSeed()),
                )
                session.add(settings)
                await session.flush()
        return user_settings_payload(settings)


async def seed_user_settings(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    values: UserSettingsSeed,
) -> dict:
    """Create once during registration; never overwrite an existing account."""
    db_user_id = UUID(user_id)
    async with session_factory() as session:
        async with session.begin():
            await _registered_user(session, db_user_id)
            settings = await session.get(UserSettings, db_user_id)
            if settings is None:
                settings = UserSettings(
                    user_id=db_user_id,
                    **_settings_values(values),
                )
                session.add(settings)
                await session.flush()
        return user_settings_payload(settings)


async def patch_user_settings(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    values: UserSettingsPatch,
) -> dict:
    db_user_id = UUID(user_id)
    async with session_factory() as session:
        async with session.begin():
            await _registered_user(session, db_user_id)
            settings = await session.scalar(
                select(UserSettings)
                .where(UserSettings.user_id == db_user_id)
                .with_for_update()
            )
            if settings is None:
                settings = UserSettings(
                    user_id=db_user_id,
                    **_settings_values(UserSettingsSeed()),
                )
                session.add(settings)
            for key, value in _settings_values(values).items():
                setattr(settings, key, value)
            await session.flush()
            # ``updated_at`` is generated by the database on UPDATE and is
            # expired by SQLAlchemy until explicitly reloaded.
            await session.refresh(settings)
        return user_settings_payload(settings)


def create_user_settings_router(
    session_factory: async_sessionmaker[AsyncSession],
) -> APIRouter:
    router = APIRouter(prefix="/api/users/me/settings")

    def user_id(request: Request) -> str:
        value = getattr(request.state, "user_id", None)
        if not value:
            raise HTTPException(status_code=401, detail="Sign in first.")
        return value

    @router.get("")
    async def get_settings(request: Request):
        try:
            return await get_or_create_user_settings(
                session_factory, user_id=user_id(request)
            )
        except UserSettingsError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @router.patch("")
    async def patch_settings(body: UserSettingsPatch, request: Request):
        try:
            return await patch_user_settings(
                session_factory, user_id=user_id(request), values=body
            )
        except UserSettingsError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    return router

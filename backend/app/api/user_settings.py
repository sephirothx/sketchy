"""Registered-account preferences shared across devices."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import Refusal
from app.refusals import ErrorCode
from app.db.models import User, UserSettings
from app.domain_values import AccountState, DEFAULT_BRUSH_SIZE, DEFAULT_USER_KEY_BINDINGS


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


# One of the slider's stops (`BRUSH_SIZES`). A literal is not coerced to, so
# `"6"` is refused rather than read as a size.
BrushSize = Literal[2, 4, 6, 8, 12, 16, 24, 32]


class UserSettingsSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    theme: Literal["light", "dark", "system"] = "system"
    sound_effects: bool = Field(default=True, alias="soundEffects")
    confetti_effects: bool = Field(default=True, alias="confettiEffects")
    sound_effects_volume: float = Field(default=0.7, ge=0, le=1, alias="volume")
    brush_cursor: Literal["crosshair", "circle"] = Field(
        default="crosshair", alias="brushCursor"
    )
    pen_pressure: bool = Field(default=True, alias="penPressure")
    default_brush_size: BrushSize = Field(default=DEFAULT_BRUSH_SIZE, alias="defaultBrushSize")
    key_bindings: dict[str, list[str]] = Field(
        default_factory=lambda: {key: list(value) for key, value in DEFAULT_KEY_BINDINGS.items()},
        alias="keyBindings",
    )
    colorblind_safe_colors: bool = Field(
        default=False, alias="colorblindSafeColors"
    )
    time_format: Literal["system", "12h", "24h"] = Field(
        default="system", alias="timeFormat"
    )
    # Seeded from the browser at registration and a setting from then on: the
    # language a player plays in follows them to another device, which is the
    # whole reason it is stored rather than read from the header each time.
    prompt_language: Literal["en", "de", "es", "fr", "it", "nl", "pt"] = Field(
        default="en", alias="promptLanguage"
    )
    # Which language the interface is read in. Seeded from the browser at
    # registration like the one above, and separate from it for the reason
    # `InterfaceLocale` gives: playing in English and reading in Dutch is
    # ordinary (R-I18N-06).
    locale: Literal["en", "de", "es", "fr", "it", "nl", "pt"] = Field(default="en", alias="locale")

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
    pen_pressure: bool | None = Field(default=None, alias="penPressure")
    default_brush_size: BrushSize | None = Field(default=None, alias="defaultBrushSize")
    key_bindings: dict[str, list[str]] | None = Field(
        default=None, alias="keyBindings"
    )
    colorblind_safe_colors: bool | None = Field(
        default=None, alias="colorblindSafeColors"
    )
    time_format: Literal["system", "12h", "24h"] | None = Field(
        default=None, alias="timeFormat"
    )
    prompt_language: Literal["en", "de", "es", "fr", "it", "nl", "pt"] | None = Field(
        default=None, alias="promptLanguage"
    )
    locale: Literal["en", "de", "es", "fr", "it", "nl", "pt"] | None = Field(default=None, alias="locale")

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
        "penPressure": settings.pen_pressure,
        "defaultBrushSize": settings.default_brush_size,
        "keyBindings": settings.key_bindings,
        "colorblindSafeColors": settings.colorblind_safe_colors,
        "timeFormat": settings.time_format,
        "promptLanguage": settings.prompt_language,
        "locale": settings.locale,
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


async def settings_of_registered_account(
    session_factory: async_sessionmaker[AsyncSession], *, user_id: str
) -> dict:
    """The settings of an account the caller has already read as registered.

    `GET /api/auth/me` carries them (#983), and has just read the account row,
    so this skips `_registered_user`'s second read of it: one statement in the
    steady state, where `get_or_create_user_settings` sends two (R-PLAT-17).
    An account registered before settings were seeded gets its row here, as it
    would there.
    """
    db_user_id = UUID(user_id)
    async with session_factory() as session:
        async with session.begin():
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
            raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        return value

    @router.get("")
    async def get_settings(request: Request):
        try:
            return await get_or_create_user_settings(
                session_factory, user_id=user_id(request)
            )
        except UserSettingsError as error:
            raise Refusal(403, ErrorCode.SETTING_REFUSED, str(error)) from error

    @router.patch("")
    async def patch_settings(body: UserSettingsPatch, request: Request):
        try:
            return await patch_user_settings(
                session_factory, user_id=user_id(request), values=body
            )
        except UserSettingsError as error:
            raise Refusal(403, ErrorCode.SETTING_REFUSED, str(error)) from error

    return router

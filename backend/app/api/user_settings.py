"""Registered-account preferences shared across devices."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import ConfigDict, Field, field_validator, model_validator
from app.request_text import ControlFreeModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import Refusal
from app.refusals import ErrorCode
from app.db.models import User, UserSettings
from app.domain_values import (
    AccountState,
    DEFAULT_BRUSH_SIZE,
    DEFAULT_USER_KEY_BINDINGS,
    PROMPT_LANGUAGES,
)


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


PlayLanguage = Literal["en", "de", "es", "fr", "it", "nl", "pt"]
# Every language but the default: the list can hold the rest of them, no more.
MAX_EXTRA_PROMPT_LANGUAGES = len(PROMPT_LANGUAGES) - 1
EXTRA_PROMPT_LANGUAGES_FIELD = "extraPromptLanguages"


def _validated_extra_prompt_languages(value: list[str] | None):
    """The other languages a player plays in (#1209): each once. The bound on
    how many is the field's own; that none is the default needs both fields,
    and is checked where both are known."""
    if value is not None and len(set(value)) != len(value):
        raise ValueError("a language can be listed once")
    return value


# One of the slider's stops (`BRUSH_SIZES`). A literal is not coerced to, so
# `"6"` is refused rather than read as a size.
BrushSize = Literal[2, 4, 6, 8, 12, 16, 24, 32]


class UserSettingsSeed(ControlFreeModel):
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
    prompt_language: PlayLanguage = Field(default="en", alias="promptLanguage")
    # The browser's other languages, in its player's order: a guest who added
    # some keeps them on becoming an account, like every other setting.
    extra_prompt_languages: list[PlayLanguage] = Field(
        default_factory=list,
        alias="extraPromptLanguages",
        max_length=MAX_EXTRA_PROMPT_LANGUAGES,
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

    @field_validator("extra_prompt_languages")
    @classmethod
    def validate_extra_prompt_languages(cls, value):
        return _validated_extra_prompt_languages(value)

    @model_validator(mode="before")
    @classmethod
    def default_is_not_an_extra(cls, data):
        """A browser whose copy lists its default among the others, or one of
        them twice, is read as meaning each once and the default as the
        default: the seed is not the place to refuse a registration over it.
        Before the fields are checked, so the bound on how many is counted
        after the repeats are gone rather than refusing a copy with all seven."""
        if not isinstance(data, dict):
            return data
        key = next(
            (name for name in ("extraPromptLanguages", "extra_prompt_languages") if name in data),
            None,
        )
        extras = data.get(key) if key else None
        if not isinstance(extras, list):
            return data
        default = data.get("promptLanguage", data.get("prompt_language", "en"))
        kept: list = []
        for language in extras:
            if language != default and language not in kept:
                kept.append(language)
        return {**data, key: kept}


class UserSettingsPatch(ControlFreeModel):
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
    prompt_language: PlayLanguage | None = Field(default=None, alias="promptLanguage")
    extra_prompt_languages: list[PlayLanguage] | None = Field(
        default=None,
        alias="extraPromptLanguages",
        max_length=MAX_EXTRA_PROMPT_LANGUAGES,
    )
    locale: Literal["en", "de", "es", "fr", "it", "nl", "pt"] | None = Field(default=None, alias="locale")

    @field_validator("key_bindings")
    @classmethod
    def validate_key_bindings(cls, value):
        return _validated_key_bindings(value)

    @field_validator("extra_prompt_languages")
    @classmethod
    def validate_extra_prompt_languages(cls, value):
        return _validated_extra_prompt_languages(value)

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
        "extraPromptLanguages": list(settings.extra_prompt_languages),
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


def _settings_insert(session: AsyncSession):
    """The dialect's INSERT, for the ON CONFLICT clause both databases share."""
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return postgresql_insert(UserSettings)
    if dialect == "sqlite":
        return sqlite_insert(UserSettings)
    raise RuntimeError(f"Unsupported user-settings dialect: {dialect}")


async def seed_user_settings(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    values: UserSettingsSeed,
) -> dict:
    """Seed the account's settings from the browser, once, at registration.

    Registration also starts the no-email reminder's clock (R-AUTH-15): the
    form has just called the address optional, so the first reminder is due a
    week after signing up rather than on the very next page.

    The account is already claimed when this runs, so a tab still holding its
    cookie can reach `settings_of_registered_account` and make the row first.
    Read-then-insert lost that race with an IntegrityError - a 500 after the
    account had been created - and doing nothing on the conflict would keep
    that tab's defaults over the browser's values, breaking R-SET-03's "the
    browser's copy becomes the account's, exactly once".

    So the conflict updates the row, but only a row nobody has seeded: the
    reminder stamp is what tells them apart. A row this function wrote carries
    one from the moment it exists; a row made anywhere else starts without one.
    The seed and the stamp land together, so a seeded account is never
    overwritten by a second call and a running clock is never pushed back.
    """
    db_user_id = UUID(user_id)
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        async with session.begin():
            await _registered_user(session, db_user_id)
            seeded = _settings_values(values)
            statement = _settings_insert(session).values(
                user_id=db_user_id,
                email_reminder_last_shown_at=now,
                **seeded,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["user_id"],
                    set_={
                        key: statement.excluded[key]
                        for key in (*seeded, "email_reminder_last_shown_at")
                    },
                    where=UserSettings.email_reminder_last_shown_at.is_(None),
                )
            )
            settings = await session.get(
                UserSettings, db_user_id, populate_existing=True
            )
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
            changes = _settings_values(values)
            _hold_play_languages(settings, changes)
            for key, value in changes.items():
                setattr(settings, key, value)
            try:
                await session.flush()
            except IntegrityError as error:
                # Only where the lock above is not one (SQLite): another
                # device's PATCH landed between the read and this write, and
                # the CHECK caught the pair naming the default twice.
                raise PlayLanguagesRefused(
                    "the play languages changed on another device"
                ) from error
            # ``updated_at`` is generated by the database on UPDATE and is
            # expired by SQLAlchemy until explicitly reloaded.
            await session.refresh(settings)
        return user_settings_payload(settings)


class PlayLanguagesRefused(ValueError):
    """The default listed among the other languages as well (#1209)."""


def _hold_play_languages(settings: UserSettings, changes: dict) -> None:
    """Keep the default out of the others, whichever of the two a PATCH sends.

    Promoting one of the others to the default is a swap: the old default takes
    its place in the order, so choosing a language never loses one. Sent
    together, the pair is taken as meant - and refused if it names the default
    twice, since no reading of that is the player's. The row is locked, so on
    PostgreSQL a second device's PATCH reads what this one wrote; SQLite has no
    row lock, and there `ck_user_settings_default_not_extra` refuses the loser.
    """
    default = changes.get("prompt_language", settings.prompt_language)
    if "extra_prompt_languages" in changes:
        if default in changes["extra_prompt_languages"]:
            raise PlayLanguagesRefused(
                "the default play language cannot also be another one"
            )
        return
    extras = list(settings.extra_prompt_languages)
    if default == settings.prompt_language or default not in extras:
        return
    extras[extras.index(default)] = settings.prompt_language
    changes["extra_prompt_languages"] = extras


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
        except PlayLanguagesRefused as error:
            raise Refusal(
                422,
                ErrorCode.SETTING_REFUSED,
                str(error),
                field=EXTRA_PROMPT_LANGUAGES_FIELD,
            ) from error

    return router

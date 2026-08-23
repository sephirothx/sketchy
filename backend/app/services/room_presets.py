"""Private, account-owned templates for ordinary room configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PromptList, RoomPreset, User
from app.domain_values import AccountState, PromptContentModerationState
from app.repositories.interfaces import PromptListRepository, PromptListSelectionError


MAX_ROOM_PRESETS_PER_OWNER = 20


class RoomPresetError(ValueError):
    """Safe validation or authorization failure for a room preset."""


class RoomPresetNotFound(RoomPresetError):
    """The requested private preset is not owned by the caller."""


class RoomPresetAuthorizationError(RoomPresetError):
    """The caller is not a registered account eligible to own presets."""


class RoomPresetConflict(RoomPresetError):
    """The preset changed since the caller loaded it."""


class RoomPresetUnavailable(RoomPresetError):
    """A stored prompt-list reference can no longer be applied."""


@dataclass(frozen=True)
class RoomPresetSummary:
    id: str
    name: str
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RoomPresetConfig(RoomPresetSummary):
    room_name: str
    is_public: bool
    max_players: int
    rounds: int
    drawing_seconds: int
    hint_mode: str
    scoring_mode: str
    spectators_see_prompt: bool
    hide_masked_prompt: bool
    allowed_tools: tuple[str, ...]
    color_mode: str
    prompt_list_ids: tuple[str, ...]
    prompt_list_slugs: tuple[str, ...]


def _summary(row: RoomPreset) -> RoomPresetSummary:
    return RoomPresetSummary(
        id=str(row.id),
        name=row.name,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _clean_name(value: str) -> tuple[str, str]:
    name = " ".join(value.split())
    if not name:
        raise RoomPresetError("Preset name is required")
    if len(name) > 64:
        raise RoomPresetError("Preset name must be at most 64 characters")
    return name, name.casefold()


class RoomPresetService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        prompt_list_repo: PromptListRepository,
    ) -> None:
        self._session_factory = session_factory
        self._prompt_list_repo = prompt_list_repo

    async def _require_registered(
        self, session: AsyncSession, owner_id: UUID
    ) -> None:
        owner = await session.get(User, owner_id)
        if owner is None or owner.state != AccountState.REGISTERED.value:
            raise RoomPresetAuthorizationError(
                "Create an account before saving room presets"
            )

    async def _durable_prompt_list_ids(
        self,
        session: AsyncSession,
        slugs: list[str],
        owner_id: UUID,
    ) -> list[str]:
        rows = (
            await session.scalars(select(PromptList).where(PromptList.slug.in_(slugs)))
        ).all()
        by_slug = {row.slug: row for row in rows}
        if any(
            slug not in by_slug
            or by_slug[slug].moderation_state
            != PromptContentModerationState.ACTIVE.value
            or not (
                by_slug[slug].is_bundled
                or by_slug[slug].owner_user_id == owner_id
            )
            for slug in slugs
        ):
            raise RoomPresetError(
                "Room presets may use only active built-in prompt lists or lists you own"
            )
        return [str(by_slug[slug].id) for slug in slugs]

    async def _slugs_for_row(
        self, row: RoomPreset, owner_id: UUID
    ) -> list[str]:
        try:
            ids = [UUID(value) for value in row.prompt_list_ids]
        except (TypeError, ValueError) as error:
            raise RoomPresetUnavailable(
                "This preset's saved prompt lists are unavailable"
            ) from error
        async with self._session_factory() as session:
            rows = (
                await session.scalars(select(PromptList).where(PromptList.id.in_(ids)))
            ).all()
        by_id = {str(item.id): item for item in rows}
        if any(
            value not in by_id
            or by_id[value].moderation_state
            != PromptContentModerationState.ACTIVE.value
            or not (
                by_id[value].is_bundled
                or by_id[value].owner_user_id == owner_id
            )
            for value in row.prompt_list_ids
        ):
            raise RoomPresetUnavailable(
                "This preset's saved prompt lists are unavailable"
            )
        slugs = [by_id[value].slug for value in row.prompt_list_ids]
        try:
            resolved = await self._prompt_list_repo.resolve_selection(
                slugs, requesting_user_id=str(owner_id)
            )
        except PromptListSelectionError as error:
            raise RoomPresetUnavailable(
                "This preset's saved prompt lists are unavailable"
            ) from error
        return list(resolved.slugs)

    @staticmethod
    def _validate_configuration(settings: dict) -> None:
        if settings.get("custom_prompts") or settings.get("custom_prompts_only"):
            raise RoomPresetError(
                "Save quick custom prompts as a private prompt list before using a preset"
            )
        if settings.get("prompt_list_share_codes"):
            raise RoomPresetError(
                "Room presets cannot retain another player's shared prompt list"
            )

    @staticmethod
    def _stored_settings(settings: dict) -> dict:
        return {
            "room_name": settings["name"],
            "is_public": settings["is_public"],
            "max_players": settings["max_players"],
            "rounds": settings["rounds"],
            "drawing_seconds": settings["drawing_seconds"],
            "hint_mode": settings["hint_mode"],
            "scoring_mode": settings["scoring_mode"],
            "spectators_see_prompt": settings["spectators_see_prompt"],
            "hide_masked_prompt": settings["hide_masked_prompt"],
            "allowed_tools": list(settings["allowed_tools"]),
            "color_mode": settings["color_mode"],
        }

    async def create(
        self, *, owner_user_id: str, name: str, settings: dict
    ) -> RoomPresetConfig:
        self._validate_configuration(settings)
        clean_name, name_key = _clean_name(name)
        owner_id = UUID(owner_user_id)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await self._require_registered(session, owner_id)
                    count = await session.scalar(
                        select(func.count(RoomPreset.id)).where(
                            RoomPreset.owner_user_id == owner_id
                        )
                    )
                    if (count or 0) >= MAX_ROOM_PRESETS_PER_OWNER:
                        raise RoomPresetError(
                            f"An account may save at most {MAX_ROOM_PRESETS_PER_OWNER} room presets"
                        )
                    prompt_list_ids = await self._durable_prompt_list_ids(
                        session, list(settings["prompt_list_slugs"]), owner_id
                    )
                    row = RoomPreset(
                        owner_user_id=owner_id,
                        name=clean_name,
                        name_key=name_key,
                        prompt_list_ids=prompt_list_ids,
                        **self._stored_settings(settings),
                    )
                    session.add(row)
                    await session.flush()
        except IntegrityError as error:
            raise RoomPresetConflict("A preset with that name already exists") from error
        return await self._config(row, owner_id)

    async def list_owned(self, owner_user_id: str) -> list[RoomPresetSummary]:
        owner_id = UUID(owner_user_id)
        async with self._session_factory() as session:
            await self._require_registered(session, owner_id)
            rows = (
                await session.scalars(
                    select(RoomPreset)
                    .where(RoomPreset.owner_user_id == owner_id)
                    .order_by(RoomPreset.updated_at.desc(), RoomPreset.id)
                )
            ).all()
        return [_summary(row) for row in rows]

    async def get_owned(
        self, *, owner_user_id: str, preset_id: str
    ) -> RoomPresetConfig:
        owner_id = UUID(owner_user_id)
        async with self._session_factory() as session:
            row = await session.scalar(
                select(RoomPreset).where(
                    RoomPreset.id == UUID(preset_id),
                    RoomPreset.owner_user_id == owner_id,
                )
            )
        if row is None:
            raise RoomPresetNotFound("Room preset not found")
        return await self._config(row, owner_id)

    async def _config(
        self, row: RoomPreset, owner_id: UUID
    ) -> RoomPresetConfig:
        slugs = await self._slugs_for_row(row, owner_id)
        return RoomPresetConfig(
            **_summary(row).__dict__,
            room_name=row.room_name,
            is_public=row.is_public,
            max_players=row.max_players,
            rounds=row.rounds,
            drawing_seconds=row.drawing_seconds,
            hint_mode=row.hint_mode,
            scoring_mode=row.scoring_mode,
            spectators_see_prompt=row.spectators_see_prompt,
            hide_masked_prompt=row.hide_masked_prompt,
            allowed_tools=tuple(row.allowed_tools),
            color_mode=row.color_mode,
            prompt_list_ids=tuple(row.prompt_list_ids),
            prompt_list_slugs=tuple(slugs),
        )

    async def update(
        self,
        *,
        owner_user_id: str,
        preset_id: str,
        expected_version: int,
        name: str,
        settings: dict,
    ) -> RoomPresetConfig:
        self._validate_configuration(settings)
        clean_name, name_key = _clean_name(name)
        owner_id = UUID(owner_user_id)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await session.scalar(
                        select(RoomPreset)
                        .where(
                            RoomPreset.id == UUID(preset_id),
                            RoomPreset.owner_user_id == owner_id,
                        )
                        .with_for_update()
                    )
                    if row is None:
                        raise RoomPresetNotFound("Room preset not found")
                    if row.version != expected_version:
                        raise RoomPresetConflict(
                            "Room preset changed; reload before editing"
                        )
                    prompt_list_ids = await self._durable_prompt_list_ids(
                        session, list(settings["prompt_list_slugs"]), owner_id
                    )
                    row.name = clean_name
                    row.name_key = name_key
                    row.prompt_list_ids = prompt_list_ids
                    for key, value in self._stored_settings(settings).items():
                        setattr(row, key, value)
                    row.version += 1
                    row.updated_at = datetime.now(timezone.utc)
                    await session.flush()
        except IntegrityError as error:
            raise RoomPresetConflict("A preset with that name already exists") from error
        return await self._config(row, owner_id)

    async def delete(self, *, owner_user_id: str, preset_id: str) -> None:
        owner_id = UUID(owner_user_id)
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(RoomPreset)
                    .where(
                        RoomPreset.id == UUID(preset_id),
                        RoomPreset.owner_user_id == owner_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise RoomPresetNotFound("Room preset not found")
                await session.delete(row)

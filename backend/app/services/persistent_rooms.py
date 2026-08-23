"""Owner-controlled persistent room configuration and live materialization."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PersistentRoom, PromptList, RoomCodeReservation, User
from app.domain_values import AccountState, PromptContentModerationState
from app.repositories.interfaces import PromptListRepository, PromptListSelectionError
from app.rooms import Room, RoomManager


MAX_PERSISTENT_ROOMS_PER_OWNER = 10


class PersistentRoomError(ValueError):
    """Safe validation/authorization failure for durable room configuration."""


class PersistentRoomUnavailable(PersistentRoomError):
    """A stored room cannot currently be materialized without lying."""


@dataclass(frozen=True)
class PersistentRoomConfig:
    id: str
    code: str
    owner_user_id: str
    name: str
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
    version: int


def _public_config(row: PersistentRoom) -> PersistentRoomConfig:
    return PersistentRoomConfig(
        id=str(row.id),
        code=row.code,
        owner_user_id=str(row.owner_user_id),
        name=row.name,
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
        version=row.version,
    )


class PersistentRoomService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        prompt_list_repo: PromptListRepository,
    ) -> None:
        self._session_factory = session_factory
        self._prompt_list_repo = prompt_list_repo
        self._materialize_lock = asyncio.Lock()

    async def _durable_prompt_lists(
        self,
        session: AsyncSession,
        slugs: list[str],
        owner_user_id: UUID,
    ) -> tuple[list[str], list[str]]:
        rows = (
            await session.scalars(select(PromptList).where(PromptList.slug.in_(slugs)))
        ).all()
        by_slug = {row.slug: row for row in rows}
        missing = [slug for slug in slugs if slug not in by_slug]
        unauthorized = [
            slug
            for slug in slugs
            if slug in by_slug
            and not (
                by_slug[slug].is_bundled
                or by_slug[slug].owner_user_id == owner_user_id
            )
        ]
        unavailable = [
            slug
            for slug in slugs
            if slug in by_slug
            and by_slug[slug].moderation_state
            != PromptContentModerationState.ACTIVE.value
        ]
        if missing or unauthorized or unavailable:
            raise PersistentRoomError(
                "Persistent rooms may use only active built-in prompt lists or "
                "lists owned by the room owner"
            )
        ordered = [by_slug[slug] for slug in slugs]
        return [str(row.id) for row in ordered], [row.slug for row in ordered]

    async def create(
        self,
        *,
        owner_user_id: str,
        code: str,
        settings: dict,
    ) -> PersistentRoomConfig:
        if settings.get("custom_prompts") or settings.get("custom_prompts_only"):
            raise PersistentRoomError(
                "Save custom prompts as a private prompt list before making this room persistent"
            )
        owner_id = UUID(owner_user_id)
        async with self._session_factory() as session:
            async with session.begin():
                owner = await session.get(User, owner_id)
                if owner is None or owner.state != AccountState.REGISTERED.value:
                    raise PersistentRoomError(
                        "Create an account before making a persistent room"
                    )
                reservation = await session.get(RoomCodeReservation, code)
                if reservation is None or reservation.kind != "persistent":
                    raise PersistentRoomError("Persistent room code was not reserved")
                count = await session.scalar(
                    select(func.count(PersistentRoom.id)).where(
                        PersistentRoom.owner_user_id == owner_id,
                        PersistentRoom.archived_at.is_(None),
                    )
                )
                if (count or 0) >= MAX_PERSISTENT_ROOMS_PER_OWNER:
                    raise PersistentRoomError(
                        f"An account may own at most {MAX_PERSISTENT_ROOMS_PER_OWNER} persistent rooms"
                    )
                prompt_list_ids, _ = await self._durable_prompt_lists(
                    session, list(settings["prompt_list_slugs"]), owner_id
                )
                row = PersistentRoom(
                    code=code,
                    owner_user_id=owner_id,
                    prompt_list_ids=prompt_list_ids,
                    **self._stored_settings(settings),
                )
                session.add(row)
                await session.flush()
                return _public_config(row)

    async def delete_unpublished(self, persistent_room_id: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    delete(PersistentRoom).where(
                        PersistentRoom.id == UUID(persistent_room_id)
                    )
                )

    async def get_active_by_code(self, code: str) -> PersistentRoomConfig | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(PersistentRoom).where(
                    PersistentRoom.code == code.strip().upper(),
                    PersistentRoom.archived_at.is_(None),
                )
            )
        return _public_config(row) if row is not None else None

    async def list_owned(self, owner_user_id: str) -> list[PersistentRoomConfig]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(PersistentRoom)
                    .where(
                        PersistentRoom.owner_user_id == UUID(owner_user_id),
                        PersistentRoom.archived_at.is_(None),
                    )
                    .order_by(PersistentRoom.updated_at.desc(), PersistentRoom.id)
                )
            ).all()
        return [_public_config(row) for row in rows]

    async def materialize(self, room_manager: RoomManager, code: str) -> Room | None:
        existing = room_manager.get_room_by_code(code)
        if existing is not None:
            return existing
        async with self._materialize_lock:
            existing = room_manager.get_room_by_code(code)
            if existing is not None:
                return existing
            config = await self.get_active_by_code(code)
            if config is None:
                return None
            slugs = await self._slugs_for_config(config)
            try:
                resolved = await self._prompt_list_repo.resolve_selection(
                    slugs,
                    requesting_user_id=config.owner_user_id,
                )
            except PromptListSelectionError as error:
                raise PersistentRoomUnavailable(
                    "This room's saved prompt lists are unavailable"
                ) from error
            return room_manager.create_room(
                code=config.code,
                name=config.name,
                is_public=config.is_public,
                max_players=config.max_players,
                rounds=config.rounds,
                drawing_seconds=config.drawing_seconds,
                hint_mode=config.hint_mode,
                scoring_mode=config.scoring_mode,
                spectators_see_prompt=config.spectators_see_prompt,
                hide_masked_prompt=config.hide_masked_prompt,
                allowed_tools=list(config.allowed_tools),
                color_mode=config.color_mode,
                prompt_language=resolved.language,
                prompt_list_slugs=list(resolved.slugs),
                prompt_list_revision_ids=list(resolved.revision_ids),
                prompt_aliases=dict(resolved.aliases),
                prompt_version_ids=dict(resolved.prompt_version_ids),
                prompt_source_revision_ids=dict(resolved.prompt_source_revision_ids),
                curated_prompts=list(resolved.prompts),
                persistent_room_id=config.id,
                persistent_owner_user_id=config.owner_user_id,
                persistent_config_version=config.version,
            )

    async def update(
        self,
        *,
        room: Room,
        owner_user_id: str,
        settings: dict,
    ) -> int:
        if room.persistent_room_id is None or room.persistent_config_version is None:
            raise PersistentRoomError("Room is not persistent")
        if settings.get("custom_prompts") or settings.get("custom_prompts_only"):
            raise PersistentRoomError(
                "Persistent rooms cannot store quick custom prompts; save a private prompt list"
            )
        owner_id = UUID(owner_user_id)
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(PersistentRoom)
                    .where(PersistentRoom.id == UUID(room.persistent_room_id))
                    .with_for_update()
                )
                if (
                    row is None
                    or row.archived_at is not None
                    or row.owner_user_id != owner_id
                ):
                    raise PersistentRoomError(
                        "Only the persistent room owner can change its settings"
                    )
                if row.version != room.persistent_config_version:
                    raise PersistentRoomError(
                        "Persistent room settings changed; reload before editing"
                    )
                prompt_list_ids, _ = await self._durable_prompt_lists(
                    session, list(settings["prompt_list_slugs"]), owner_id
                )
                for key, value in self._stored_settings(settings).items():
                    setattr(row, key, value)
                row.prompt_list_ids = prompt_list_ids
                row.version += 1
                row.updated_at = datetime.now(timezone.utc)
                await session.flush()
                return row.version

    async def archive(self, *, room: Room, owner_user_id: str) -> None:
        if room.persistent_room_id is None:
            raise PersistentRoomError("Room is not persistent")
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(PersistentRoom)
                    .where(PersistentRoom.id == UUID(room.persistent_room_id))
                    .with_for_update()
                )
                if row is None or str(row.owner_user_id) != owner_user_id:
                    raise PersistentRoomError(
                        "Only the persistent room owner can archive it"
                    )
                if row.archived_at is None:
                    row.archived_at = datetime.now(timezone.utc)
                    row.updated_at = row.archived_at

    async def _slugs_for_config(self, config: PersistentRoomConfig) -> list[str]:
        ids = [UUID(value) for value in config.prompt_list_ids]
        async with self._session_factory() as session:
            rows = (
                await session.scalars(select(PromptList).where(PromptList.id.in_(ids)))
            ).all()
        by_id = {str(row.id): row for row in rows}
        if any(
            value not in by_id
            or by_id[value].moderation_state
            != PromptContentModerationState.ACTIVE.value
            or not (
                by_id[value].is_bundled
                or str(by_id[value].owner_user_id) == config.owner_user_id
            )
            for value in config.prompt_list_ids
        ):
            raise PersistentRoomUnavailable(
                "This room's saved prompt lists are unavailable"
            )
        return [by_id[value].slug for value in config.prompt_list_ids]

    @staticmethod
    def _stored_settings(settings: dict) -> dict:
        return {
            "name": settings["name"],
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

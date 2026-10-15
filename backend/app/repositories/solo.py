"""Solo's reads and writes (#1434): what a player may be served, and their runs.

Solo's own repository rather than more of `sqlalchemy.py`: nothing else reads
its tables, and the one predicate everything here rests on -
`servable_clauses` - is easier to keep tight where it is the only thing on
the page.

A drawing is servable when the pool holds it (`app.services.solo_pool`: the
facts of a finished public game) and nothing since has taken it out: it is
still kept and readable, no moderator hid it, its drawer has not opted out
or taken it out, and its prompt is still active and rated for everyone.
To a given player it must also be a game they were not in, and a concept
they can guess in one of their play languages. Each of those is its own
clause, and this door's clauses are its own (R-HIST-16): never a disjunction
with the participant, pin or Gallery doors.
"""
from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.db.models import (
    GameParticipant,
    IdentityAlias,
    PromptVersion,
    SoloPoolEntry,
    TurnDrawing,
    User,
    UserSettings,
)
from app.domain_values import (
    AGNOSTIC_PROMPT_LANGUAGE,
    AccountState,
    PromptContentModerationState,
    TurnDrawingStatus,
)
from app.solo_rules import SOLO_CONTENT_RATING


def _playable_version(version):
    """A version Solo may put in front of a player: active, and for everyone."""
    return and_(
        version.moderation_state == PromptContentModerationState.ACTIVE.value,
        version.content_rating == SOLO_CONTENT_RATING,
    )


def servable_clauses() -> tuple:
    """What keeps a pool row servable to anybody, over `SoloPoolEntry` (the
    Daily's set is chosen by these alone). Each clause is something that can
    change after the game and be undone, which is why the pool does not
    store it."""
    drawn = aliased(PromptVersion)
    canonical_drawer = func.coalesce(
        select(IdentityAlias.target_user_id)
        .where(IdentityAlias.source_user_id == SoloPoolEntry.drawer_user_id)
        .scalar_subquery(),
        SoloPoolEntry.drawer_user_id,
    )
    return (
        exists().where(
            TurnDrawing.turn_id == SoloPoolEntry.turn_id,
            TurnDrawing.status == TurnDrawingStatus.READY.value,
            TurnDrawing.payload.is_not(None),
            TurnDrawing.moderation_erased_at.is_(None),
            # A moderator's hide is a judgement about strangers seeing it
            # (R-GAL-09), which is all Solo is.
            TurnDrawing.gallery_hidden_at.is_(None),
            TurnDrawing.solo_withdrawn_at.is_(None),
        ),
        # The version the drawer drew, taken down or re-rated since.
        exists().where(drawn.id == SoloPoolEntry.prompt_version_id, _playable_version(drawn)),
        ~exists().where(
            UserSettings.user_id == canonical_drawer,
            UserSettings.solo_opt_out.is_(True),
        ),
    )


def servable_to_clauses(identity_ids: Sequence[UUID], languages: Sequence[str]) -> tuple:
    """What a pool row must also be for this player: from a game none of
    their identities sat in, and a concept with a version they can guess -
    one of their play languages, or none at all (`zxx`)."""
    offered = aliased(PromptVersion)
    return (
        ~exists().where(
            GameParticipant.game_id == SoloPoolEntry.game_id,
            GameParticipant.user_id.in_(list(identity_ids)),
        ),
        exists().where(
            offered.concept_id == SoloPoolEntry.concept_id,
            offered.language.in_([*languages, AGNOSTIC_PROMPT_LANGUAGE]),
            _playable_version(offered),
        ),
    )


async def identity_ids(session: AsyncSession, user_id: UUID) -> tuple[UUID, ...]:
    """The canonical account and every identity merged into it."""
    canonical = (
        await session.scalar(
            select(IdentityAlias.target_user_id).where(IdentityAlias.source_user_id == user_id)
        )
        or user_id
    )
    aliases = (
        await session.scalars(
            select(IdentityAlias.source_user_id).where(IdentityAlias.target_user_id == canonical)
        )
    ).all()
    return (canonical, *aliases)


async def play_languages(session: AsyncSession, user_id: UUID) -> tuple[str, ...]:
    """A registered player's languages, default first (R-PROMPT-11): empty
    for anyone else, who is not served."""
    row = (
        await session.execute(
            select(UserSettings.prompt_language, UserSettings.extra_prompt_languages)
            .join(User, User.id == UserSettings.user_id)
            .where(UserSettings.user_id == user_id, User.state == AccountState.REGISTERED.value)
        )
    ).first()
    return () if row is None else (row[0], *row[1])


class SoloRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def servable_turn_ids(
        self, user_id: str | UUID, *, after_key: int = -1, limit: int = 50
    ) -> list[UUID]:
        """The pool rows this player may be served, in the pool's random
        order from `after_key` on."""
        viewer = UUID(str(user_id))
        async with self._session_factory() as session:
            ids = await identity_ids(session, viewer)
            languages = await play_languages(session, ids[0])
            if not languages:
                return []
            statement = (
                select(SoloPoolEntry.turn_id)
                .where(
                    SoloPoolEntry.sample_key > after_key,
                    *servable_clauses(),
                    *servable_to_clauses(ids, languages),
                )
                .order_by(SoloPoolEntry.sample_key)
                .limit(limit)
            )
            return list((await session.scalars(statement)).all())

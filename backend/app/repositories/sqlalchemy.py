"""SQLAlchemy implementations of domain repository interfaces."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from datetime import datetime, timezone
import hashlib
import json
import secrets
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.models import (
    GameParticipant,
    GamePromptSource,
    GameRecord,
    IdentityAlias,
    TurnDrawing,
    TurnGuess,
    TurnParticipantOutcome,
    TurnPromptOffer,
    TurnPromptOfferSource,
    TurnRecord,
    User,
    UserStatsDaily,
    UserBlock,
    AuditEvent,
    Prompt,
    PromptAlias,
    PromptConcept,
    PromptList,
    PromptListRevision,
    PromptListRevisionItem,
    PromptTag,
    PromptUsageFact,
    ScoreEvent,
    PromptVersion,
    PromptVersionAlias,
    PromptVersionTag,
    generate_uuid,
)
from app.canvas_storage import prepare_stored_drawing
from app.domain_values import (
    AccountState,
    AuditTargetType,
    GAME_OUTCOMES,
    GameOutcome,
    DRAWING_UNAVAILABLE_RECAP_BUDGET,
    GAME_PROMPT_SOURCE_MODES,
    PROMPT_OFFER_SOURCE_KINDS,
    PROMPT_SOURCE_KINDS,
    SCORE_EVENT_TYPES,
    PromptContentModerationState,
    PromptListVisibility,
    TURN_ELIGIBILITY_REASONS,
    TURN_PARTICIPANT_OUTCOMES,
    TURN_PARTICIPANT_STATES,
    TurnDrawingStatus,
)
from app.auth.avatars import validate_avatar_key
from app.services.user_stats_projection import (
    increment_user_stats_projection,
    rebuild_user_stats_in_session,
)
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    BundledPromptDefinition,
    PinnedPromptSelection,
    PromptSample,
    SampledPrompt,
    GameDetail,
    GameHistoryConflictError,
    GameHistoryRepository,
    GameParticipantInput,
    GameParticipantSummary,
    GameRecordInput,
    GameSummary,
    ScoreEventDetail,
    ScoreEventInput,
    InvalidProfileDataError,
    IdentityMergeError,
    TurnDetail,
    TurnDrawingDetail,
    TurnDrawingInput,
    TurnGuessDetail,
    TurnGuessInput,
    TurnParticipantOutcomeDetail,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
    UserCredentials,
    UserData,
    UserRepository,
    UserStats,
    UsernameTakenError,
    PromptListRepository,
    PromptListConflictError,
    PromptListEntry,
    PromptListEntryInput,
    PromptListMutationError,
    PromptListNotFoundError,
    PromptOfferDetail,
    PromptListSelectionError,
    PromptSeedConflictError,
    PromptListSummary,
    SharedPromptList,
    OwnedPromptList,
    PromptStatsSummary,
    PromptUsage,
    ResolvedPromptSelection,
)
from app.prompt_content import (
    clean_prompt_aliases,
    normalize_prompt_answer,
    prompt_match_key,
    validate_prompt_language,
)
from app.prompts import letter_histogram

MAX_PAGINATION_LIMIT = 100
DEFAULT_PAGINATION_LIMIT = 20
MAX_OWNED_PROMPT_LISTS = 25
MAX_PROMPTS_PER_OWNED_LIST = 500


def _entity_id(value: str | UUID) -> UUID:
    """Convert a domain/wire identifier at the persistence boundary."""
    return value if isinstance(value, UUID) else UUID(value)


def _optional_entity_id(value: str | UUID) -> UUID | None:
    try:
        return _entity_id(value)
    except (ValueError, AttributeError, TypeError):
        return None


def _public_id(value: UUID) -> str:
    return str(value)


def _turn_drawing(
    drawing: TurnDrawingInput, turn_id: UUID, game_id: UUID
) -> TurnDrawing:
    """Build the row for one turn's drawing, stored or explained.

    A drawing the recap had to drop is recorded as unavailable rather than
    omitted, so history says the same thing the players were told instead of
    implying the turn was never drawn.
    """

    if drawing.payload is None:
        return TurnDrawing(
            turn_id=turn_id,
            game_id=game_id,
            status=TurnDrawingStatus.UNAVAILABLE.value,
            unavailable_reason=(
                drawing.unavailable_reason or DRAWING_UNAVAILABLE_RECAP_BUDGET
            ),
        )
    blob, magic, version, checksum = prepare_stored_drawing(drawing.payload)
    return TurnDrawing(
        turn_id=turn_id,
        game_id=game_id,
        status=TurnDrawingStatus.READY.value,
        format_magic=magic.decode("ascii"),
        format_version=version,
        payload=blob,
        byte_size=len(blob),
        checksum_sha256=checksum,
        stored_at=datetime.now(timezone.utc),
    )


def _to_user_data(user: User) -> UserData:
    """Convert a database User entity to a public UserData DTO (without password_hash)."""
    return UserData(
        id=_public_id(user.id),
        username=user.username,
        display_name=user.display_name,
        name_color=user.name_color,
        avatar_key=user.avatar_key,
        is_anonymous=user.is_anonymous,
        state=user.state,
        role=user.role,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
        last_active_at=user.last_active_at,
    )


async def _canonical_user_id(session: AsyncSession, user_id: UUID) -> UUID:
    target = await session.scalar(
        select(IdentityAlias.target_user_id).where(
            IdentityAlias.source_user_id == user_id
        )
    )
    return target or user_id


async def _identity_ids(session: AsyncSession, user_id: UUID) -> tuple[UUID, ...]:
    canonical = await _canonical_user_id(session, user_id)
    aliases = (
        await session.scalars(
            select(IdentityAlias.source_user_id).where(
                IdentityAlias.target_user_id == canonical
            )
        )
    ).all()
    return (canonical, *aliases)


def _to_game_summary(game: GameRecord) -> GameSummary:
    """Convert a stored game and its participants to the DTO both read paths return."""
    return GameSummary(
        id=_public_id(game.id),
        room_name=game.room_name,
        scoring_mode=game.scoring_mode,
        scoring_version=game.scoring_version,
        score_ledger_version=game.score_ledger_version,
        rule_snapshot_version=game.rule_snapshot_version,
        rule_snapshot=game.rule_snapshot,
        prompt_source_mode=game.prompt_source_mode,
        hint_mode=game.hint_mode,
        drawing_seconds=game.drawing_seconds,
        total_rounds=game.total_rounds,
        player_count=game.player_count,
        started_at=game.started_at,
        finished_at=game.finished_at,
        outcome=game.outcome,
        participants=[
            GameParticipantSummary(
                seat_id=_public_id(p.id),
                user_id=_public_id(p.user_id) if p.user_id else None,
                display_name=p.display_name_snapshot,
                name_color=p.name_color_snapshot,
                is_anonymous=p.is_anonymous_snapshot,
                final_score=p.final_score,
                final_rank=p.final_rank,
            )
            for p in sorted(game.participants, key=lambda x: x.final_rank)
        ],
    )


def _to_prompt_list_summary(
    wl: PromptList, prompt_count: int, *, locale: str | None = None
) -> PromptListSummary:
    localization = (
        next(
            (
                candidate
                for candidate in wl.localizations
                if candidate.locale == locale
            ),
            None,
        )
        if locale
        else None
    )
    return PromptListSummary(
        id=_public_id(wl.id),
        slug=wl.slug,
        name=localization.name if localization else wl.name,
        description=localization.description if localization else wl.description,
        language=wl.language,
        prompt_count=prompt_count,
        is_bundled=wl.is_bundled,
        version=wl.version,
    )


def _to_owned_prompt_list(
    wl: PromptList,
    prompts: Sequence[PromptListEntry] = (),
    *,
    prompt_count: int | None = None,
) -> OwnedPromptList:
    return OwnedPromptList(
        id=_public_id(wl.id),
        slug=wl.slug,
        name=wl.name,
        description=wl.description,
        language=wl.language,
        visibility=wl.visibility,
        share_code=wl.share_code,
        moderation_state=wl.moderation_state,
        version=wl.version,
        prompt_count=len(prompts) if prompt_count is None else prompt_count,
        created_at=wl.created_at,
        updated_at=wl.updated_at,
        prompts=tuple(prompts),
    )
def _bundled_revision_hash(
    *, language: str, prompts: Sequence[BundledPromptDefinition]
) -> str:
    """Hash the exact ordered immutable content, independent of JSON layout."""
    payload = {
        "language": language,
        "prompts": [
            {
                "concept_id": prompt.concept_id,
                "prompt_version": prompt.prompt_version,
                "canonical_prompt": prompt.answer,
                "aliases": sorted(prompt.aliases),
                "difficulty": prompt.editorial_difficulty,
                "content_rating": prompt.content_rating,
                "tags": sorted(prompt.tags),
            }
            for prompt in prompts
        ],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SqlAlchemyUserRepository(UserRepository):
    """SQLAlchemy-backed implementation of UserRepository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_anonymous(
        self,
        display_name: str,
        name_color: str | None = None,
        user_id: str | None = None,
    ) -> UserData:
        async with self._session_factory() as session:
            async with session.begin():
                user = User(
                    id=_entity_id(user_id) if user_id else generate_uuid(),
                    username=None,
                    password_hash=None,
                    # Left empty on purpose: "has no name yet" is what tells
                    # the client this is a first run. Nothing is invented for
                    # the player - they choose, or they sign up.
                    display_name=display_name.strip(),
                    name_color=name_color,
                    avatar_key=None,
                    state=AccountState.ANONYMOUS.value,
                )
                session.add(user)
            await session.refresh(user)
            return _to_user_data(user)

    async def get_by_id(self, user_id: str) -> UserData | None:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return None
        async with self._session_factory() as session:
            canonical = await _canonical_user_id(session, db_user_id)
            stmt = select(User).where(User.id == canonical)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            return _to_user_data(user) if user else None

    async def get_by_username(self, username: str) -> UserData | None:
        clean = username.strip()
        if not clean:
            return None
        async with self._session_factory() as session:
            stmt = select(User).where(func.lower(User.username) == clean.lower())
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            return _to_user_data(user) if user else None

    async def get_credentials_by_username(self, username: str) -> UserCredentials | None:
        clean = username.strip()
        if not clean:
            return None
        async with self._session_factory() as session:
            stmt = select(User).where(func.lower(User.username) == clean.lower())
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if not user or not user.password_hash:
                return None
            return UserCredentials(user=_to_user_data(user), password_hash=user.password_hash)

    async def claim_account(
        self,
        user_id: str,
        username: str,
        password_hash: str,
    ) -> UserData:
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("Username cannot be empty")
        if not password_hash:
            raise ValueError("Password hash cannot be empty")
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            raise ValueError(f"User '{user_id}' not found")

        async with self._session_factory() as session:
            async with session.begin():
                # 1. Fetch user to claim
                stmt = select(User).where(User.id == db_user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                if user is None:
                    raise ValueError(f"User '{user_id}' not found")
                if not user.is_anonymous:
                    raise AccountAlreadyClaimedError("Account has already been claimed")

                # 2. Check case-insensitive username collision
                collision_stmt = select(User.id).where(
                    and_(
                        func.lower(User.username) == clean_username.lower(),
                        User.id != db_user_id,
                    )
                )
                existing_owner = (await session.execute(collision_stmt)).scalar_one_or_none()
                if existing_owner is not None:
                    raise UsernameTakenError(f"Username '{clean_username}' is already taken")

                user.username = clean_username
                user.password_hash = password_hash
                user.state = AccountState.REGISTERED.value
                # Registered players play as their username, so the display
                # name follows it rather than keeping the old guest nickname.
                user.display_name = clean_username
                try:
                    await session.flush()
                except IntegrityError as error:
                    # The check above can still lose to a concurrent claim of
                    # the same name; the unique index is the real arbiter, and
                    # callers should see the same error either way.
                    raise UsernameTakenError(
                        f"Username '{clean_username}' is already taken"
                    ) from error
            await session.refresh(user)
            return _to_user_data(user)

    async def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        name_color: str | None = None,
        avatar_key: str | None = None,
    ) -> UserData | None:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return None
        try:
            validated_avatar = (
                validate_avatar_key(avatar_key) if avatar_key is not None else None
            )
        except ValueError as error:
            raise InvalidProfileDataError(str(error)) from error
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(User).where(User.id == db_user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                if not user:
                    return None
                if display_name is not None:
                    user.display_name = display_name.strip() or user.display_name
                if name_color is not None:
                    user.name_color = name_color
                if avatar_key is not None:
                    user.avatar_key = validated_avatar
            await session.refresh(user)
            return _to_user_data(user)

    async def replace_password_hash(
        self, user_id: str, expected_hash: str, new_hash: str
    ) -> bool:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None or not expected_hash or not new_hash:
            return False
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(User)
                    .where(
                        User.id == db_user_id,
                        User.password_hash == expected_hash,
                    )
                    .values(password_hash=new_hash)
                )
                return bool(result.rowcount)

    async def merge_guest_into_account(
        self, source_user_id: str, target_user_id: str
    ) -> UserData:
        source_id = _optional_entity_id(source_user_id)
        target_id = _optional_entity_id(target_user_id)
        if source_id is None or target_id is None or source_id == target_id:
            raise IdentityMergeError("Guest and account identities must be distinct.")

        async with self._session_factory() as session:
            async with session.begin():
                source = await session.get(User, source_id)
                target = await session.get(User, target_id)
                existing_target = await session.scalar(
                    select(IdentityAlias.target_user_id).where(
                        IdentityAlias.source_user_id == source_id
                    )
                )
                if existing_target is not None:
                    if existing_target != target_id or target is None:
                        raise IdentityMergeError(
                            "Guest identity is already merged into another account."
                        )
                    return _to_user_data(target)
                if source is None or source.state != AccountState.ANONYMOUS.value:
                    raise IdentityMergeError("Only an anonymous guest can be merged.")
                if target is None or target.state != AccountState.REGISTERED.value:
                    raise IdentityMergeError(
                        "The merge target must be a registered account."
                    )

                source.state = AccountState.MERGED.value
                session.add(
                    IdentityAlias(
                        id=generate_uuid(),
                        source_user_id=source.id,
                        target_user_id=target.id,
                    )
                )
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type="identity.guest_merged",
                        actor_user_id=target.id,
                        target_user_id=target.id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(target.id),
                        details={"source_user_id": str(source.id)},
                    )
                )
                # Blocks are account preferences, not historical identity
                # facts. Carry both outgoing mutes and incoming protection to
                # the registered identity, collapsing duplicates and any
                # source/target pair that would become a self-block.
                blocks = (
                    await session.scalars(
                        select(UserBlock).where(
                            or_(
                                UserBlock.blocker_user_id == source.id,
                                UserBlock.blocked_user_id == source.id,
                            )
                        )
                    )
                ).all()
                for block in blocks:
                    blocker_id = (
                        target.id
                        if block.blocker_user_id == source.id
                        else block.blocker_user_id
                    )
                    blocked_id = (
                        target.id
                        if block.blocked_user_id == source.id
                        else block.blocked_user_id
                    )
                    if blocker_id == blocked_id:
                        await session.delete(block)
                        continue
                    duplicate = await session.scalar(
                        select(UserBlock.id).where(
                            UserBlock.id != block.id,
                            UserBlock.blocker_user_id == blocker_id,
                            UserBlock.blocked_user_id == blocked_id,
                        )
                    )
                    if duplicate is not None:
                        await session.delete(block)
                    else:
                        block.blocker_user_id = blocker_id
                        block.blocked_user_id = blocked_id
                await session.flush()
                await rebuild_user_stats_in_session(
                    session, user_id=target.id
                )
            await session.refresh(target)
            return _to_user_data(target)

    async def touch_last_login(
        self, user_id: str, min_interval_seconds: float = 0.0
    ) -> UserData | None:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return None
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(User).where(User.id == db_user_id)
                user = (await session.execute(stmt)).scalar_one_or_none()
                if not user:
                    return None
                now = datetime.now(timezone.utc)
                previous = user.last_login_at
                is_recent = (
                    min_interval_seconds > 0
                    and previous is not None
                    and (now - previous).total_seconds() < min_interval_seconds
                )
                if not is_recent:
                    user.last_login_at = now
            await session.refresh(user)
            return _to_user_data(user)

    async def touch_last_active(self, user_id: str) -> UserData | None:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return None
        async with self._session_factory() as session:
            async with session.begin():
                user = await session.get(User, db_user_id)
                if user is None:
                    return None
                user.last_active_at = datetime.now(timezone.utc)
            await session.refresh(user)
            return _to_user_data(user)

    async def get_stats(self, user_id: str) -> UserStats:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return UserStats(user_id=user_id)
        async with self._session_factory() as session:
            canonical_id = await _canonical_user_id(session, db_user_id)
            statement = select(
                func.coalesce(func.sum(UserStatsDaily.games_played), 0),
                func.coalesce(func.sum(UserStatsDaily.games_won), 0),
                func.coalesce(func.sum(UserStatsDaily.total_score), 0),
                func.coalesce(func.sum(UserStatsDaily.turns_played), 0),
                func.coalesce(func.sum(UserStatsDaily.prompts_guessed), 0),
                func.coalesce(func.sum(UserStatsDaily.drawings_made), 0),
            ).where(UserStatsDaily.user_id == canonical_id)
            row = (await session.execute(statement)).one()
            games_played = int(row[0] or 0)
            games_won = int(row[1] or 0)
            total_score = int(row[2] or 0)
            turns_played = int(row[3] or 0)
            prompts_guessed = int(row[4] or 0)
            drawings_made = int(row[5] or 0)
            win_rate = (games_won / games_played) if games_played > 0 else 0.0
            average_score = (total_score / games_played) if games_played > 0 else 0.0

            return UserStats(
                user_id=_public_id(canonical_id),
                games_played=games_played,
                games_won=games_won,
                win_rate=round(win_rate, 4),
                total_score=total_score,
                average_score=round(average_score, 2),
                turns_played=turns_played,
                prompts_guessed=prompts_guessed,
                drawings_made=drawings_made,
            )


class SqlAlchemyGameHistoryRepository(GameHistoryRepository):
    """SQLAlchemy-backed implementation of GameHistoryRepository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _payload_hash(
        game_record: GameRecordInput,
        participants: list[GameParticipantInput],
        turns: list[TurnRecordInput],
        guesses: list[TurnGuessInput],
        score_events: list[ScoreEventInput] | None = None,
    ) -> str:
        """Canonical digest used only to distinguish retries from conflicts."""
        payload = {
            "record": {
                "room_name": game_record.room_name,
                "scoring_mode": game_record.scoring_mode,
                "scoring_version": game_record.scoring_version,
                "score_ledger_version": game_record.score_ledger_version,
                "rule_snapshot_version": game_record.rule_snapshot_version,
                "rule_snapshot": game_record.rule_snapshot,
                "prompt_source_mode": game_record.prompt_source_mode,
                "prompt_source_revision_ids": sorted(
                    game_record.prompt_source_revision_ids
                ),
                "hint_mode": game_record.hint_mode,
                "drawing_seconds": game_record.drawing_seconds,
                "total_rounds": game_record.total_rounds,
                "player_count": game_record.player_count,
                "started_at": game_record.started_at.isoformat(),
                "finished_at": game_record.finished_at.isoformat(),
            },
            "participants": sorted(
                (
                    {
                        "seat_id": item.seat_id,
                        "user_id": item.user_id,
                        "display_name": item.display_name,
                        "name_color": item.name_color,
                        "is_anonymous": item.is_anonymous,
                        "final_score": item.final_score,
                        "final_rank": item.final_rank,
                        "turns_played": item.turns_played,
                    }
                    for item in participants
                ),
                key=lambda item: item["seat_id"] or item["user_id"] or "",
            ),
            "turns": sorted(
                (
                    {
                        "id": item.id,
                        "round_number": item.round_number,
                        "turn_number": item.turn_number,
                        "drawer_user_id": item.drawer_user_id,
                        "drawer_seat_id": item.drawer_seat_id,
                        "prompt": item.prompt,
                        "prompt_version_id": item.prompt_version_id,
                        "prompt_source_kind": item.prompt_source_kind,
                        "duration_seconds": item.duration_seconds,
                        "guesser_count": item.guesser_count,
                        "prompt_auto_picked": item.prompt_auto_picked,
                        "stroke_count": item.stroke_count,
                        "end_reason": item.end_reason,
                        "wrong_guess_count": item.wrong_guess_count,
                        "near_miss_count": item.near_miss_count,
                        "prompt_offers": [
                            {
                                "position": offer.position,
                                "prompt": offer.prompt,
                                "selected": offer.selected,
                                "source_kind": offer.source_kind,
                                "prompt_version_id": offer.prompt_version_id,
                                "source_revision_ids": sorted(
                                    offer.source_revision_ids
                                ),
                            }
                            for offer in sorted(
                                item.prompt_offers, key=lambda value: value.position
                            )
                        ],
                        "participant_outcomes": [
                            {
                                "seat_id": outcome.seat_id,
                                "user_id": outcome.user_id,
                                "eligible": outcome.eligible,
                                "eligibility_reason": outcome.eligibility_reason,
                                "outcome": outcome.outcome,
                                "terminal_state": outcome.terminal_state,
                                "correct_guess_time_seconds": (
                                    outcome.correct_guess_time_seconds
                                ),
                                "wrong_guess_count": outcome.wrong_guess_count,
                                "near_miss_count": outcome.near_miss_count,
                                "hints_used": outcome.hints_used,
                                "points_spent_on_hints": (
                                    outcome.points_spent_on_hints
                                ),
                            }
                            for outcome in sorted(
                                item.participant_outcomes,
                                key=lambda value: value.seat_id,
                            )
                        ],
                    }
                    for item in turns
                ),
                key=lambda item: item["id"],
            ),
            "guesses": sorted(
                (
                    {
                        "turn_id": item.turn_id,
                        "user_id": item.user_id,
                        "seat_id": item.seat_id,
                        "points_awarded": item.points_awarded,
                        "guess_time_seconds": item.guess_time_seconds,
                        "hints_used": item.hints_used,
                        "points_spent_on_hints": item.points_spent_on_hints,
                        "wrong_guesses_before": item.wrong_guesses_before,
                    }
                    for item in guesses
                ),
                key=lambda item: (
                    item["turn_id"],
                    item["seat_id"] or item["user_id"] or "",
                ),
            ),
            "score_events": sorted(
                (
                    {
                        "id": item.id,
                        "participant_seat_id": item.participant_seat_id,
                        "participant_user_id": item.participant_user_id,
                        "turn_id": item.turn_id,
                        "event_order": item.event_order,
                        "event_type": item.event_type,
                        "points_delta": item.points_delta,
                        "scoring_version": item.scoring_version,
                        "rule_snapshot_version": item.rule_snapshot_version,
                        "corrects_event_id": item.corrects_event_id,
                    }
                    for item in score_events or []
                ),
                key=lambda item: item["event_order"],
            ),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def save_game(
        self,
        game_record: GameRecordInput,
        participants: list[GameParticipantInput],
        turns: list[TurnRecordInput],
        guesses: list[TurnGuessInput],
        score_events: list[ScoreEventInput] | None = None,
        drawings: list[TurnDrawingInput] | None = None,
    ) -> str:
        score_events = list(score_events or [])
        record_id = (
            _entity_id(game_record.id) if game_record.id else generate_uuid()
        )
        game_source_ids = {
            _entity_id(revision_id)
            for revision_id in game_record.prompt_source_revision_ids
        }
        if game_record.prompt_source_mode not in GAME_PROMPT_SOURCE_MODES:
            raise ValueError("Unknown game prompt source mode")
        payload_hash = self._payload_hash(
            game_record, participants, turns, guesses, score_events
        )
        try:
            async with self._session_factory() as session:
                existing = await session.get(GameRecord, record_id)
                if existing is not None:
                    if existing.payload_hash == payload_hash:
                        return _public_id(record_id)
                    raise GameHistoryConflictError(
                        f"Game '{record_id}' already exists with different content."
                    )
                if game_record.player_count != len(participants):
                    raise ValueError(
                        "Game player_count must equal its persisted participant seats"
                    )
                referenced_user_ids = {
                    _entity_id(participant.user_id)
                    for participant in participants
                    if participant.user_id
                }
                referenced_user_ids.update(
                    _entity_id(turn.drawer_user_id)
                    for turn in turns
                    if turn.drawer_user_id
                )
                referenced_user_ids.update(
                    _entity_id(guess.user_id) for guess in guesses if guess.user_id
                )
                users = (
                    await session.scalars(
                        select(User).where(User.id.in_(referenced_user_ids))
                    )
                ).all()
                users_by_id = {user.id: user for user in users}
                missing = referenced_user_ids - users_by_id.keys()
                if missing:
                    raise ValueError(
                        "Cannot save game with unknown user ids: "
                        + ", ".join(sorted(str(value) for value in missing))
                    )

                # The database refuses an unknown outcome too. This one names
                # the offending value instead of surfacing an integrity error
                # from a constraint the caller cannot see.
                if game_record.outcome not in GAME_OUTCOMES:
                    raise ValueError(
                        f"Unknown game outcome {game_record.outcome!r}"
                    )
                game_db = GameRecord(
                    id=record_id,
                    payload_hash=payload_hash,
                    room_name=game_record.room_name,
                    scoring_mode=game_record.scoring_mode,
                    scoring_version=game_record.scoring_version,
                    score_ledger_version=game_record.score_ledger_version,
                    rule_snapshot_version=game_record.rule_snapshot_version,
                    rule_snapshot=game_record.rule_snapshot,
                    prompt_source_mode=game_record.prompt_source_mode,
                    hint_mode=game_record.hint_mode,
                    drawing_seconds=game_record.drawing_seconds,
                    total_rounds=game_record.total_rounds,
                    player_count=game_record.player_count,
                    started_at=game_record.started_at,
                    finished_at=game_record.finished_at,
                    outcome=game_record.outcome,
                )
                session.add(game_db)
                session.add_all(
                    GamePromptSource(
                        game_id=record_id,
                        prompt_list_revision_id=revision_id,
                    )
                    for revision_id in game_source_ids
                )

                participant_inputs_by_id: dict[UUID, GameParticipantInput] = {}
                participant_snapshots_by_id: dict[
                    UUID, tuple[str, str | None, bool]
                ] = {}
                participant_ids_by_user: dict[UUID, UUID] = {}
                for p in participants:
                    participant_id = (
                        _entity_id(p.seat_id) if p.seat_id else generate_uuid()
                    )
                    if participant_id in participant_inputs_by_id:
                        raise ValueError(f"Duplicate participant seat id '{p.seat_id}'")
                    participant_user_id = (
                        _entity_id(p.user_id) if p.user_id else None
                    )
                    participant_user = (
                        users_by_id[participant_user_id]
                        if participant_user_id is not None
                        else None
                    )
                    participant_inputs_by_id[participant_id] = p
                    display_name_snapshot = (
                        p.display_name
                        if p.seat_id or participant_user is None
                        else participant_user.display_name
                    )
                    name_color_snapshot = (
                        p.name_color
                        if p.seat_id or participant_user is None
                        else participant_user.name_color
                    )
                    is_anonymous_snapshot = (
                        p.is_anonymous
                        if p.seat_id or participant_user is None
                        else participant_user.is_anonymous
                    )
                    participant_snapshots_by_id[participant_id] = (
                        display_name_snapshot,
                        name_color_snapshot,
                        is_anonymous_snapshot,
                    )
                    if participant_user_id is not None:
                        participant_ids_by_user[participant_user_id] = participant_id
                    session.add(
                        GameParticipant(
                            id=participant_id,
                            game_id=record_id,
                            user_id=participant_user_id,
                            display_name_snapshot=display_name_snapshot,
                            name_color_snapshot=name_color_snapshot,
                            is_anonymous_snapshot=is_anonymous_snapshot,
                            final_score=p.final_score,
                            final_rank=p.final_rank,
                            turns_played=p.turns_played,
                        )
                    )

                created_turn_ids: set[UUID] = set()
                turn_inputs_by_id: dict[UUID, TurnRecordInput] = {}
                drawer_participant_ids_by_turn: dict[UUID, UUID] = {}
                outcome_ids_by_key: dict[tuple[UUID, UUID], UUID] = {}
                outcome_inputs_by_key: dict[
                    tuple[UUID, UUID], TurnParticipantOutcomeInput
                ] = {}
                turns_with_outcomes: set[UUID] = set()
                for r in turns:
                    if r.prompt_source_kind not in PROMPT_SOURCE_KINDS:
                        raise ValueError(
                            f"Turn '{r.id}' has an unknown prompt source kind"
                        )
                    if (r.prompt_source_kind == "curated") != bool(
                        r.prompt_version_id
                    ):
                        raise ValueError(
                            f"Turn '{r.id}' prompt source and version disagree"
                        )
                    rid = _entity_id(r.id)
                    if rid in created_turn_ids:
                        raise ValueError(f"Duplicate turn id '{r.id}'")
                    created_turn_ids.add(rid)
                    turn_inputs_by_id[rid] = r
                    drawer_user_id = (
                        _entity_id(r.drawer_user_id) if r.drawer_user_id else None
                    )
                    drawer_participant_id = (
                        _entity_id(r.drawer_seat_id)
                        if r.drawer_seat_id
                        else participant_ids_by_user.get(drawer_user_id)
                    )
                    drawer_participant = (
                        participant_inputs_by_id.get(drawer_participant_id)
                        if drawer_participant_id is not None
                        else None
                    )
                    if drawer_participant is None:
                        raise ValueError(
                            f"Turn '{r.id}' references an unknown drawer seat"
                        )
                    if drawer_participant.user_id != r.drawer_user_id:
                        raise ValueError(
                            f"Turn '{r.id}' drawer seat and user identity disagree"
                        )
                    drawer_participant_ids_by_turn[rid] = drawer_participant_id
                    drawer_snapshot = participant_snapshots_by_id[
                        drawer_participant_id
                    ]
                    session.add(
                        TurnRecord(
                            id=rid,
                            game_id=record_id,
                            round_number=r.round_number,
                            turn_number=r.turn_number,
                            drawer_user_id=drawer_user_id,
                            drawer_participant_id=drawer_participant_id,
                            drawer_display_name_snapshot=drawer_snapshot[0],
                            drawer_name_color_snapshot=drawer_snapshot[1],
                            drawer_is_anonymous_snapshot=drawer_snapshot[2],
                            prompt=r.prompt,
                            prompt_version_id=(
                                _entity_id(r.prompt_version_id)
                                if r.prompt_version_id
                                else None
                            ),
                            prompt_source_kind=r.prompt_source_kind,
                            duration_seconds=r.duration_seconds,
                            guesser_count=r.guesser_count,
                            prompt_auto_picked=r.prompt_auto_picked,
                            stroke_count=r.stroke_count,
                            end_reason=r.end_reason,
                            wrong_guess_count=r.wrong_guess_count,
                            near_miss_count=r.near_miss_count,
                        )
                    )
                    if r.prompt_offers and sum(
                        offer.selected for offer in r.prompt_offers
                    ) != 1:
                        raise ValueError(
                            f"Turn '{r.id}' must have exactly one selected prompt offer"
                        )
                    selected_offer = next(
                        (offer for offer in r.prompt_offers if offer.selected), None
                    )
                    if selected_offer is not None and (
                        selected_offer.prompt != r.prompt
                        or selected_offer.prompt_version_id != r.prompt_version_id
                        or selected_offer.source_kind != r.prompt_source_kind
                    ):
                        raise ValueError(
                            f"Turn '{r.id}' selected offer does not match its prompt identity"
                        )
                    for offer in r.prompt_offers:
                        if offer.source_kind not in PROMPT_OFFER_SOURCE_KINDS:
                            raise ValueError(
                                f"Turn '{r.id}' offer has an unknown source kind"
                            )
                        offer_source_ids = {
                            _entity_id(revision_id)
                            for revision_id in offer.source_revision_ids
                        }
                        if not offer_source_ids.issubset(game_source_ids):
                            raise ValueError(
                                f"Turn '{r.id}' offer source is not in the game pool"
                            )
                        if offer.source_kind == "curated" and (
                            not offer.prompt_version_id or not offer_source_ids
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' curated offer lacks exact source identity"
                            )
                        if offer.source_kind != "curated" and (
                            offer.prompt_version_id or offer_source_ids
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' ephemeral offer cannot claim curated identity"
                            )
                        offer_id = generate_uuid()
                        session.add(
                            TurnPromptOffer(
                                id=offer_id,
                                turn_id=rid,
                                position=offer.position,
                                prompt_version_id=(
                                    _entity_id(offer.prompt_version_id)
                                    if offer.prompt_version_id
                                    else None
                                ),
                                prompt_snapshot=offer.prompt,
                                selected=offer.selected,
                                source_kind=offer.source_kind,
                            )
                        )
                        session.add_all(
                            TurnPromptOfferSource(
                                offer_id=offer_id,
                                prompt_list_revision_id=_entity_id(revision_id),
                            )
                            for revision_id in offer_source_ids
                        )

                    if r.participant_outcomes:
                        turns_with_outcomes.add(rid)
                        if r.guesser_count != sum(
                            outcome.eligible for outcome in r.participant_outcomes
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' guesser count disagrees with outcomes"
                            )
                        if r.wrong_guess_count != sum(
                            outcome.wrong_guess_count
                            for outcome in r.participant_outcomes
                        ) or r.near_miss_count != sum(
                            outcome.near_miss_count
                            for outcome in r.participant_outcomes
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' aggregate attempts disagree with outcomes"
                            )
                    for outcome in r.participant_outcomes:
                        participant_id = _entity_id(outcome.seat_id)
                        participant = participant_inputs_by_id.get(participant_id)
                        if participant is None:
                            raise ValueError(
                                f"Turn '{r.id}' outcome references an unknown seat"
                            )
                        if participant_id == drawer_participant_id:
                            raise ValueError(
                                f"Turn '{r.id}' drawer cannot have a guesser outcome"
                            )
                        if participant.user_id != outcome.user_id:
                            raise ValueError(
                                f"Turn '{r.id}' outcome seat and user disagree"
                            )
                        if (
                            outcome.eligibility_reason
                            not in TURN_ELIGIBILITY_REASONS
                            or outcome.outcome not in TURN_PARTICIPANT_OUTCOMES
                            or outcome.terminal_state not in TURN_PARTICIPANT_STATES
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' outcome has an unknown stored state"
                            )
                        if outcome.eligible != (
                            outcome.eligibility_reason == "eligible"
                        ) or outcome.eligible == (outcome.outcome == "ineligible"):
                            raise ValueError(
                                f"Turn '{r.id}' outcome eligibility is inconsistent"
                            )
                        if (outcome.outcome == "correct") != (
                            outcome.correct_guess_time_seconds is not None
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' outcome and correct time disagree"
                            )
                        numeric_values = (
                            outcome.wrong_guess_count,
                            outcome.near_miss_count,
                            outcome.hints_used,
                            outcome.points_spent_on_hints,
                        )
                        if any(value < 0 for value in numeric_values) or (
                            outcome.correct_guess_time_seconds is not None
                            and not 0
                            <= outcome.correct_guess_time_seconds
                            <= r.duration_seconds
                        ):
                            raise ValueError(
                                f"Turn '{r.id}' outcome contains invalid counters or time"
                            )
                        key = (rid, participant_id)
                        if key in outcome_ids_by_key:
                            raise ValueError(
                                f"Turn '{r.id}' contains duplicate participant outcomes"
                            )
                        outcome_id = generate_uuid()
                        outcome_ids_by_key[key] = outcome_id
                        outcome_inputs_by_key[key] = outcome
                        session.add(
                            TurnParticipantOutcome(
                                id=outcome_id,
                                turn_id=rid,
                                participant_id=participant_id,
                                eligible=outcome.eligible,
                                eligibility_reason=outcome.eligibility_reason,
                                outcome=outcome.outcome,
                                terminal_state=outcome.terminal_state,
                                correct_guess_time_seconds=(
                                    outcome.correct_guess_time_seconds
                                ),
                                wrong_guess_count=outcome.wrong_guess_count,
                                near_miss_count=outcome.near_miss_count,
                                hints_used=outcome.hints_used,
                                points_spent_on_hints=(
                                    outcome.points_spent_on_hints
                                ),
                            )
                        )

                # Drawings ride in the same transaction as their turns: the
                # bytes live only in the process that just played the game, so
                # a row written now and filled in later could never be
                # completed by any retry.
                for drawing in drawings or []:
                    drawing_turn_id = _optional_entity_id(drawing.turn_id)
                    if (
                        drawing_turn_id is None
                        or drawing_turn_id not in created_turn_ids
                    ):
                        raise ValueError(
                            f"Drawing references unknown turn_id '{drawing.turn_id}'"
                        )
                    session.add(
                        _turn_drawing(drawing, drawing_turn_id, record_id)
                    )

                guess_outcome_keys: set[tuple[UUID, UUID]] = set()
                guess_inputs_by_key: dict[tuple[UUID, UUID], TurnGuessInput] = {}
                for g in guesses:
                    try:
                        target_turn_id = _entity_id(g.turn_id)
                    except (ValueError, AttributeError, TypeError) as error:
                        raise ValueError(
                            f"Invalid guess turn_id '{g.turn_id}'"
                        ) from error
                    if target_turn_id not in created_turn_ids:
                        raise ValueError(
                            f"Guess references unknown turn_id '{g.turn_id}'"
                        )
                    guess_user_id = _entity_id(g.user_id) if g.user_id else None
                    guess_participant_id = (
                        _entity_id(g.seat_id)
                        if g.seat_id
                        else participant_ids_by_user.get(guess_user_id)
                    )
                    guess_participant = (
                        participant_inputs_by_id.get(guess_participant_id)
                        if guess_participant_id is not None
                        else None
                    )
                    if guess_participant is None:
                        raise ValueError(
                            f"Guess references an unknown participant seat '{g.seat_id}'"
                        )
                    if guess_participant.user_id != g.user_id:
                        raise ValueError(
                            "Guess participant seat and user identity disagree"
                        )
                    guess_snapshot = participant_snapshots_by_id[
                        guess_participant_id
                    ]
                    outcome_key = (target_turn_id, guess_participant_id)
                    if outcome_key in guess_inputs_by_key:
                        raise ValueError(
                            "A participant seat cannot have two correct guesses in one turn"
                        )
                    guess_inputs_by_key[outcome_key] = g
                    outcome_input = outcome_inputs_by_key.get(outcome_key)
                    if target_turn_id in turns_with_outcomes:
                        if outcome_input is None or outcome_input.outcome != "correct":
                            raise ValueError(
                                "Correct guess lacks its participant outcome"
                            )
                        if (
                            outcome_input.correct_guess_time_seconds
                            != g.guess_time_seconds
                            or outcome_input.hints_used != g.hints_used
                            or outcome_input.points_spent_on_hints
                            != g.points_spent_on_hints
                            or outcome_input.wrong_guess_count
                            != g.wrong_guesses_before
                        ):
                            raise ValueError(
                                "Correct guess and participant outcome disagree"
                            )
                        guess_outcome_keys.add(outcome_key)
                    session.add(
                        TurnGuess(
                            id=generate_uuid(),
                            turn_id=target_turn_id,
                            user_id=guess_user_id,
                            participant_id=guess_participant_id,
                            outcome_id=outcome_ids_by_key.get(outcome_key),
                            display_name_snapshot=guess_snapshot[0],
                            name_color_snapshot=guess_snapshot[1],
                            is_anonymous_snapshot=guess_snapshot[2],
                            points_awarded=g.points_awarded,
                            guess_time_seconds=g.guess_time_seconds,
                            hints_used=g.hints_used,
                            points_spent_on_hints=g.points_spent_on_hints,
                            wrong_guesses_before=g.wrong_guesses_before,
                        )
                    )

                expected_correct_outcomes = {
                    key
                    for key, outcome in outcome_inputs_by_key.items()
                    if outcome.outcome == "correct"
                }
                if guess_outcome_keys != expected_correct_outcomes:
                    raise ValueError(
                        "Correct participant outcomes and guess rows disagree"
                    )

                if game_record.score_ledger_version not in (0, 1):
                    raise ValueError("Unsupported score ledger version")
                if game_record.score_ledger_version == 0 and score_events:
                    raise ValueError("Legacy games cannot claim score events")
                if game_record.score_ledger_version == 1:
                    if game_record.scoring_mode == "none":
                        if score_events:
                            raise ValueError(
                                "No-scoring games cannot contain hypothetical score events"
                            )
                        if any(participant.final_score != 0 for participant in participants):
                            raise ValueError(
                                "No-scoring game participant totals must remain zero"
                            )

                    ordered_events = sorted(
                        score_events, key=lambda event: event.event_order
                    )
                    if [event.event_order for event in ordered_events] != list(
                        range(1, len(ordered_events) + 1)
                    ):
                        raise ValueError(
                            "Score event order must be unique and consecutive from one"
                        )

                    event_inputs_by_id: dict[UUID, ScoreEventInput] = {}
                    actual_gameplay: defaultdict[
                        tuple[str, UUID, UUID], list[int]
                    ] = defaultdict(list)
                    ledger_totals: defaultdict[UUID, int] = defaultdict(int)
                    for event in ordered_events:
                        event_id = _entity_id(event.id)
                        if event_id in event_inputs_by_id:
                            raise ValueError("Duplicate score event id")
                        participant_id = _entity_id(event.participant_seat_id)
                        participant = participant_inputs_by_id.get(participant_id)
                        if participant is None:
                            raise ValueError(
                                "Score event references an unknown participant seat"
                            )
                        if participant.user_id != event.participant_user_id:
                            raise ValueError(
                                "Score event seat and user identity disagree"
                            )
                        if event.event_type not in SCORE_EVENT_TYPES:
                            raise ValueError("Score event has an unknown type")
                        if event.points_delta == 0 or (
                            event.event_type in {"guess_award", "drawer_bonus"}
                            and event.points_delta < 0
                        ) or (
                            event.event_type == "hint_charge"
                            and event.points_delta > 0
                        ):
                            raise ValueError("Score event delta is invalid for its type")
                        if (
                            event.scoring_version != game_record.scoring_version
                            or event.rule_snapshot_version
                            != game_record.rule_snapshot_version
                        ):
                            raise ValueError(
                                "Score event rule versions disagree with the game"
                            )
                        turn_id = _entity_id(event.turn_id) if event.turn_id else None
                        if turn_id is not None and turn_id not in turn_inputs_by_id:
                            raise ValueError("Score event references an unknown turn")
                        correction_id = (
                            _entity_id(event.corrects_event_id)
                            if event.corrects_event_id
                            else None
                        )
                        if event.event_type == "correction":
                            corrected = event_inputs_by_id.get(correction_id)
                            if corrected is None:
                                raise ValueError(
                                    "A correction must target an earlier score event"
                                )
                            if (
                                corrected.participant_seat_id
                                != event.participant_seat_id
                            ):
                                raise ValueError(
                                    "A correction must target the same participant"
                                )
                        elif correction_id is not None or turn_id is None:
                            raise ValueError(
                                "Gameplay score events require a turn and cannot correct"
                            )
                        else:
                            actual_gameplay[
                                (event.event_type, turn_id, participant_id)
                            ].append(event.points_delta)

                        event_inputs_by_id[event_id] = event
                        ledger_totals[participant_id] += event.points_delta
                        session.add(
                            ScoreEvent(
                                id=event_id,
                                game_id=record_id,
                                participant_id=participant_id,
                                turn_id=turn_id,
                                event_order=event.event_order,
                                event_type=event.event_type,
                                points_delta=event.points_delta,
                                scoring_version=event.scoring_version,
                                rule_snapshot_version=event.rule_snapshot_version,
                                corrects_event_id=correction_id,
                            )
                        )

                    expected_gameplay: defaultdict[
                        tuple[str, UUID, UUID], list[int]
                    ] = defaultdict(list)
                    if game_record.scoring_mode != "none":
                        drawer_bonuses: defaultdict[tuple[UUID, UUID], int] = (
                            defaultdict(int)
                        )
                        for (turn_id, participant_id), guess in guess_inputs_by_key.items():
                            gross_award = (
                                guess.points_awarded + guess.points_spent_on_hints
                            )
                            if gross_award > 0:
                                expected_gameplay[
                                    ("guess_award", turn_id, participant_id)
                                ].append(gross_award)
                            if guess.points_spent_on_hints > 0:
                                expected_gameplay[
                                    ("hint_charge", turn_id, participant_id)
                                ].append(-guess.points_spent_on_hints)
                            drawer_bonuses[
                                (turn_id, drawer_participant_ids_by_turn[turn_id])
                            ] += guess.points_awarded
                        for (turn_id, drawer_id), bonus in drawer_bonuses.items():
                            if bonus > 0:
                                expected_gameplay[
                                    ("drawer_bonus", turn_id, drawer_id)
                                ].append(bonus)
                    if dict(actual_gameplay) != dict(expected_gameplay):
                        raise ValueError(
                            "Score events do not match guess awards, hint charges, and drawer bonuses"
                        )
                    for participant_id, participant in participant_inputs_by_id.items():
                        if ledger_totals[participant_id] != participant.final_score:
                            raise ValueError(
                                "Score event ledger does not reconcile to final participant scores"
                            )

                await increment_user_stats_projection(
                    session,
                    finished_at=game_record.finished_at,
                    counts_as_played=(
                        game_record.outcome == GameOutcome.FINISHED.value
                    ),
                    participants=[
                        (
                            _entity_id(participant.user_id)
                            if participant.user_id
                            else None,
                            participant.final_score,
                            participant.final_rank,
                        )
                        for participant in participants
                    ],
                    turn_drawer_ids=[
                        _entity_id(turn.drawer_user_id)
                        if turn.drawer_user_id
                        else None
                        for turn in turns
                    ],
                    guess_user_ids=[
                        _entity_id(guess.user_id) if guess.user_id else None
                        for guess in guesses
                    ],
                )

                if referenced_user_ids:
                    await session.execute(
                        update(User)
                        .where(User.id.in_(referenced_user_ids))
                        .values(last_active_at=datetime.now(timezone.utc))
                    )
                await session.commit()
        except IntegrityError as error:
            # A concurrent writer may have committed the same stable ID after
            # our preflight read. Re-read outside the rolled-back transaction.
            async with self._session_factory() as session:
                existing = await session.get(GameRecord, record_id)
                if existing is None:
                    # Preserve unrelated natural-key/check failures; they are
                    # not evidence that the stable game ID was reused.
                    raise
                if existing.payload_hash == payload_hash:
                    return _public_id(record_id)
                raise GameHistoryConflictError(
                    f"Game '{record_id}' conflicted with a concurrent write."
                ) from error
        return _public_id(record_id)

    async def get_turn_drawing(
        self,
        game_id: str,
        turn_id: str,
        *,
        requesting_user_id: str,
    ) -> TurnDrawingDetail | None:
        db_game_id = _optional_entity_id(game_id)
        db_turn_id = _optional_entity_id(turn_id)
        db_requesting_user_id = _optional_entity_id(requesting_user_id)
        if db_game_id is None or db_turn_id is None or db_requesting_user_id is None:
            return None
        async with self._session_factory() as session:
            identity_ids = await _identity_ids(session, db_requesting_user_id)
            # Authorization is part of the query rather than a check on the
            # result, so the blob is never read for someone who may not see it.
            # Filtering the drawing by game as well as by turn means a turn id
            # borrowed from another game matches nothing by construction.
            participated = (
                select(GameParticipant.id)
                .where(
                    GameParticipant.game_id == db_game_id,
                    GameParticipant.user_id.in_(identity_ids),
                )
                .exists()
            )
            row = await session.scalar(
                select(TurnDrawing).where(
                    TurnDrawing.turn_id == db_turn_id,
                    TurnDrawing.game_id == db_game_id,
                    TurnDrawing.status == TurnDrawingStatus.READY.value,
                    TurnDrawing.payload.is_not(None),
                    participated,
                )
            )
        if row is None:
            return None
        return TurnDrawingDetail(
            turn_id=_public_id(row.turn_id),
            payload=row.payload,
            checksum_sha256=row.checksum_sha256 or "",
        )

    async def get_user_games(
        self,
        user_id: str,
        limit: int = DEFAULT_PAGINATION_LIMIT,
        offset: int = 0,
        *,
        include_abandoned: bool = False,
    ) -> list[GameSummary]:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return []
        clamped_limit = max(1, min(limit, MAX_PAGINATION_LIMIT))
        clamped_offset = max(0, offset)

        async with self._session_factory() as session:
            identity_ids = await _identity_ids(session, db_user_id)
            # Find game IDs the user was a participant in
            user_games_subq = (
                select(GameParticipant.game_id)
                .where(GameParticipant.user_id.in_(identity_ids))
                .scalar_subquery()
            )

            stmt = (
                select(GameRecord)
                .where(
                    GameRecord.id.in_(user_games_subq),
                    *(
                        ()
                        if include_abandoned
                        else (GameRecord.outcome == GameOutcome.FINISHED.value,)
                    ),
                )
                .options(
                    selectinload(GameRecord.participants).selectinload(GameParticipant.user)
                )
                .order_by(GameRecord.finished_at.desc())
                .limit(clamped_limit)
                .offset(clamped_offset)
            )

            result = await session.execute(stmt)
            games = result.scalars().all()

            return [_to_game_summary(g) for g in games]

    async def get_game_detail(
        self,
        game_id: str,
        requesting_user_id: str,
    ) -> GameDetail | None:
        db_game_id = _optional_entity_id(game_id)
        if db_game_id is None:
            return None
        db_requesting_user_id = _optional_entity_id(requesting_user_id)
        if db_requesting_user_id is None:
            return None
        async with self._session_factory() as session:
            requesting_identity_ids = await _identity_ids(
                session, db_requesting_user_id
            )
            stmt = (
                select(GameRecord)
                .where(GameRecord.id == db_game_id)
                .options(
                    selectinload(GameRecord.participants).selectinload(GameParticipant.user),
                    selectinload(GameRecord.turns).selectinload(TurnRecord.drawer),
                    # Status only; the blob is fetched by its own route so a
                    # game detail never carries megabytes of canvas.
                    selectinload(GameRecord.turns).selectinload(
                        TurnRecord.drawing
                    ).load_only(TurnDrawing.status),
                    selectinload(GameRecord.turns).selectinload(TurnRecord.guesses).selectinload(TurnGuess.user),
                    selectinload(GameRecord.turns).selectinload(
                        TurnRecord.participant_outcomes
                    ),
                    selectinload(GameRecord.turns)
                    .selectinload(TurnRecord.prompt_offers)
                    .selectinload(TurnPromptOffer.sources),
                    selectinload(GameRecord.score_events),
                )
            )
            result = await session.execute(stmt)
            g = result.scalar_one_or_none()
            if not g:
                return None

            # The prompts drawn, who guessed them and how fast belong to the
            # players who were there, not to anyone holding the game id.
            if not any(p.user_id in requesting_identity_ids for p in g.participants):
                return None

            summary = _to_game_summary(g)

            turn_details: list[TurnDetail] = []
            for r in sorted(g.turns, key=lambda x: (x.round_number, x.turn_number)):
                guess_details = [
                    TurnGuessDetail(
                        user_id=_public_id(guess.user_id) if guess.user_id else None,
                        seat_id=(
                            _public_id(guess.participant_id)
                            if guess.participant_id
                            else None
                        ),
                        display_name=guess.display_name_snapshot,
                        name_color=guess.name_color_snapshot,
                        is_anonymous=guess.is_anonymous_snapshot,
                        points_awarded=guess.points_awarded,
                        guess_time_seconds=guess.guess_time_seconds,
                    )
                    for guess in sorted(r.guesses, key=lambda x: x.guess_time_seconds)
                ]
                outcome_details = [
                    TurnParticipantOutcomeDetail(
                        seat_id=_public_id(outcome.participant_id),
                        eligible=outcome.eligible,
                        eligibility_reason=outcome.eligibility_reason,
                        outcome=outcome.outcome,
                        terminal_state=outcome.terminal_state,
                        correct_guess_time_seconds=(
                            outcome.correct_guess_time_seconds
                        ),
                        wrong_guess_count=outcome.wrong_guess_count,
                        near_miss_count=outcome.near_miss_count,
                        hints_used=outcome.hints_used,
                        points_spent_on_hints=outcome.points_spent_on_hints,
                    )
                    for outcome in sorted(
                        r.participant_outcomes,
                        key=lambda value: str(value.participant_id),
                    )
                ]
                turn_details.append(
                    TurnDetail(
                        id=_public_id(r.id),
                        stroke_count=r.stroke_count,
                        drawing_status=(
                            r.drawing.status if r.drawing is not None else None
                        ),
                        round_number=r.round_number,
                        turn_number=r.turn_number,
                        drawer_user_id=(
                            _public_id(r.drawer_user_id) if r.drawer_user_id else None
                        ),
                        drawer_seat_id=(
                            _public_id(r.drawer_participant_id)
                            if r.drawer_participant_id
                            else None
                        ),
                        drawer_display_name=r.drawer_display_name_snapshot,
                        drawer_name_color=r.drawer_name_color_snapshot,
                        drawer_is_anonymous=r.drawer_is_anonymous_snapshot,
                        prompt=r.prompt,
                        duration_seconds=r.duration_seconds,
                        prompt_version_id=(
                            _public_id(r.prompt_version_id)
                            if r.prompt_version_id
                            else None
                        ),
                        prompt_source_kind=r.prompt_source_kind,
                        guesses=guess_details,
                        participant_outcomes=outcome_details,
                        prompt_offers=[
                            PromptOfferDetail(
                                position=offer.position,
                                prompt=offer.prompt_snapshot,
                                selected=offer.selected,
                                source_kind=offer.source_kind,
                                prompt_version_id=(
                                    _public_id(offer.prompt_version_id)
                                    if offer.prompt_version_id
                                    else None
                                ),
                                source_revision_ids=tuple(
                                    _public_id(source.prompt_list_revision_id)
                                    for source in offer.sources
                                ),
                            )
                            for offer in sorted(
                                r.prompt_offers, key=lambda item: item.position
                            )
                        ],
                    )
                )

            participants_by_id = {
                participant.id: participant for participant in g.participants
            }
            score_event_details = [
                ScoreEventDetail(
                    id=_public_id(event.id),
                    participant_seat_id=_public_id(event.participant_id),
                    participant_user_id=(
                        _public_id(participants_by_id[event.participant_id].user_id)
                        if participants_by_id[event.participant_id].user_id
                        else None
                    ),
                    turn_id=_public_id(event.turn_id) if event.turn_id else None,
                    event_order=event.event_order,
                    event_type=event.event_type,
                    points_delta=event.points_delta,
                    scoring_version=event.scoring_version,
                    rule_snapshot_version=event.rule_snapshot_version,
                    corrects_event_id=(
                        _public_id(event.corrects_event_id)
                        if event.corrects_event_id
                        else None
                    ),
                )
                for event in sorted(g.score_events, key=lambda item: item.event_order)
            ]
            return GameDetail(
                summary=summary,
                turns=turn_details,
                score_events=score_event_details,
            )


class SqlAlchemyPromptListRepository(PromptListRepository):
    """SQLAlchemy-backed implementation of PromptListRepository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _prompt_count():
        return (
            select(func.count(Prompt.id))
            .where(Prompt.prompt_list_id == PromptList.id)
            .correlate(PromptList)
            .scalar_subquery()
        )

    async def list_all(
        self, *, language: str | None = None, locale: str | None = None
    ) -> list[PromptListSummary]:
        async with self._session_factory() as session:
            stmt = (
                select(PromptList, self._prompt_count())
                .options(selectinload(PromptList.localizations))
                .where(
                    PromptList.is_bundled.is_(True),
                    PromptList.moderation_state
                    == PromptContentModerationState.ACTIVE.value,
                )
                .order_by(PromptList.name)
            )
            if language is not None:
                stmt = stmt.where(PromptList.language == language)
            result = await session.execute(stmt)
            return [
                _to_prompt_list_summary(
                    prompt_list, int(prompt_count), locale=locale
                )
                for prompt_list, prompt_count in result.all()
            ]

    async def get_by_slug(
        self, slug: str, *, locale: str | None = None
    ) -> PromptListSummary | None:
        async with self._session_factory() as session:
            stmt = (
                select(PromptList, self._prompt_count())
                .options(selectinload(PromptList.localizations))
                .where(
                    PromptList.slug == slug,
                    PromptList.is_bundled.is_(True),
                    PromptList.moderation_state
                    == PromptContentModerationState.ACTIVE.value,
                )
            )
            result = await session.execute(stmt)
            row = result.one_or_none()
            return (
                _to_prompt_list_summary(row[0], int(row[1]), locale=locale)
                if row
                else None
            )

    @staticmethod
    def _clean_owned_entries(
        entries: Sequence[PromptListEntryInput], *, language: str
    ) -> tuple[PromptListEntryInput, ...]:
        if not entries:
            raise PromptListMutationError("Add at least one prompt.")
        if len(entries) > MAX_PROMPTS_PER_OWNED_LIST:
            raise PromptListMutationError(
                f"A prompt list can contain at most {MAX_PROMPTS_PER_OWNED_LIST} prompts."
            )
        cleaned: list[PromptListEntryInput] = []
        seen_matches: set[str] = set()
        seen_concepts: set[str] = set()
        for entry in entries:
            answer = " ".join(entry.answer.split())
            try:
                match_key = normalize_prompt_answer(answer, language)
                aliases = clean_prompt_aliases(
                    list(entry.aliases),
                    canonical_answer=answer,
                    language=language,
                )
            except ValueError as error:
                raise PromptListMutationError(str(error)) from error
            accepted_keys = {
                match_key,
                *(normalize_prompt_answer(alias, language) for alias in aliases),
            }
            if seen_matches.intersection(accepted_keys):
                raise PromptListMutationError(
                    "Prompt answers and aliases must be unambiguous within a list."
                )
            seen_matches.update(accepted_keys)
            if entry.concept_id:
                try:
                    concept_id = str(UUID(entry.concept_id))
                except (ValueError, TypeError, AttributeError) as error:
                    raise PromptListMutationError("Invalid prompt identity.") from error
                if concept_id in seen_concepts:
                    raise PromptListMutationError(
                        "A prompt can appear only once in a list revision."
                    )
                seen_concepts.add(concept_id)
            else:
                concept_id = None
            cleaned.append(
                PromptListEntryInput(
                    answer=answer,
                    concept_id=concept_id,
                    aliases=aliases,
                )
            )
        return tuple(cleaned)

    @staticmethod
    def _clean_owned_metadata(
        *, name: str, description: str, language: str, visibility: str
    ) -> tuple[str, str, str, str]:
        name = " ".join(name.split())
        description = " ".join(description.split())
        if not name or len(name) > 64:
            raise PromptListMutationError("Name must be 1-64 characters.")
        if len(description) > 255:
            raise PromptListMutationError("Description must be at most 255 characters.")
        try:
            language = validate_prompt_language(language)
        except ValueError as error:
            raise PromptListMutationError(str(error)) from error
        if visibility not in {
            PromptListVisibility.PRIVATE.value,
            PromptListVisibility.UNLISTED.value,
        }:
            raise PromptListMutationError(
                "Player prompt lists may be private or unlisted."
            )
        return name, description, language, visibility

    async def _new_share_code(self, session: AsyncSession) -> str:
        for _ in range(8):
            code = secrets.token_urlsafe(9)
            exists = await session.scalar(
                select(PromptList.id).where(PromptList.share_code == code)
            )
            if exists is None:
                return code
        raise PromptListMutationError("Could not generate a share code. Try again.")

    async def list_owned(self, owner_user_id: str) -> list[OwnedPromptList]:
        owner_id = _optional_entity_id(owner_user_id)
        if owner_id is None:
            return []
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(PromptList, self._prompt_count())
                    .where(
                        PromptList.owner_user_id == owner_id,
                        PromptList.is_bundled.is_(False),
                    )
                    .order_by(PromptList.updated_at.desc(), PromptList.name)
                )
            ).all()
            return [
                _to_owned_prompt_list(prompt_list, prompt_count=int(prompt_count))
                for prompt_list, prompt_count in rows
            ]

    async def _owned_with_entries(
        self, session: AsyncSession, owner_id: UUID, prompt_list_id: UUID
    ) -> OwnedPromptList | None:
        prompt_list = await session.scalar(
            select(PromptList).where(
                PromptList.id == prompt_list_id,
                PromptList.owner_user_id == owner_id,
                PromptList.is_bundled.is_(False),
            )
        )
        if prompt_list is None:
            return None
        revision = await session.scalar(
            select(PromptListRevision)
            .where(
                PromptListRevision.prompt_list_id == prompt_list.id,
                PromptListRevision.version == prompt_list.version,
            )
            .options(
                selectinload(PromptListRevision.items)
                .selectinload(PromptListRevisionItem.prompt_version)
                .selectinload(PromptVersion.version_aliases)
                .selectinload(PromptVersionAlias.alias)
            )
        )
        entries = tuple(
            PromptListEntry(
                concept_id=_public_id(item.prompt_version.concept_id),
                prompt_version_id=_public_id(item.prompt_version.id),
                answer=item.prompt_version.canonical_answer,
                aliases=tuple(
                    sorted(link.alias.answer for link in item.prompt_version.version_aliases)
                ),
                moderation_state=item.prompt_version.moderation_state,
            )
            for item in (revision.items if revision else ())
        )
        return _to_owned_prompt_list(prompt_list, entries)

    async def get_owned(
        self, owner_user_id: str, prompt_list_id: str
    ) -> OwnedPromptList | None:
        owner_id = _optional_entity_id(owner_user_id)
        list_id = _optional_entity_id(prompt_list_id)
        if owner_id is None or list_id is None:
            return None
        async with self._session_factory() as session:
            return await self._owned_with_entries(session, owner_id, list_id)

    async def get_shared(self, share_code: str) -> SharedPromptList | None:
        async with self._session_factory() as session:
            prompt_list = await session.scalar(
                select(PromptList).where(
                    PromptList.share_code == share_code,
                    PromptList.visibility == PromptListVisibility.UNLISTED.value,
                    PromptList.moderation_state
                    == PromptContentModerationState.ACTIVE.value,
                    PromptList.is_bundled.is_(False),
                )
            )
            if prompt_list is None:
                return None
            revision = await session.scalar(
                select(PromptListRevision)
                .where(
                    PromptListRevision.prompt_list_id == prompt_list.id,
                    PromptListRevision.version == prompt_list.version,
                )
                .options(
                    selectinload(PromptListRevision.items).selectinload(
                        PromptListRevisionItem.prompt_version
                    )
                )
            )
            entries = tuple(
                PromptListEntry(
                    concept_id=_public_id(item.prompt_version.concept_id),
                    prompt_version_id=_public_id(item.prompt_version.id),
                    answer=item.prompt_version.canonical_answer,
                )
                for item in (revision.items if revision else ())
                if item.prompt_version.moderation_state
                == PromptContentModerationState.ACTIVE.value
            )
            return SharedPromptList(
                id=_public_id(prompt_list.id),
                slug=prompt_list.slug,
                name=prompt_list.name,
                description=prompt_list.description,
                language=prompt_list.language,
                prompt_count=len(entries),
                is_bundled=False,
                version=prompt_list.version,
                prompts=entries,
            )

    async def create_owned(
        self,
        owner_user_id: str,
        *,
        name: str,
        description: str,
        language: str,
        visibility: str,
        prompts: Sequence[PromptListEntryInput],
    ) -> OwnedPromptList:
        owner_id = _optional_entity_id(owner_user_id)
        if owner_id is None:
            raise PromptListMutationError("Invalid owner.")
        name, description, language, visibility = self._clean_owned_metadata(
            name=name,
            description=description,
            language=language,
            visibility=visibility,
        )
        entries = self._clean_owned_entries(prompts, language=language)
        if any(entry.concept_id for entry in entries):
            raise PromptListMutationError(
                "New lists cannot claim existing prompt identities."
            )
        async with self._session_factory() as session:
            async with session.begin():
                count = await session.scalar(
                    select(func.count(PromptList.id)).where(
                        PromptList.owner_user_id == owner_id,
                        PromptList.is_bundled.is_(False),
                    )
                )
                if int(count or 0) >= MAX_OWNED_PROMPT_LISTS:
                    raise PromptListMutationError(
                        f"An account can own at most {MAX_OWNED_PROMPT_LISTS} prompt lists."
                    )
                list_id = generate_uuid()
                prompt_list = PromptList(
                    id=list_id,
                    owner_user_id=owner_id,
                    slug=f"user-{list_id}",
                    name=name,
                    description=description,
                    language=language,
                    is_bundled=False,
                    visibility=visibility,
                    share_code=(
                        await self._new_share_code(session)
                        if visibility == PromptListVisibility.UNLISTED.value
                        else None
                    ),
                    moderation_state=PromptContentModerationState.ACTIVE.value,
                    version=1,
                )
                session.add(prompt_list)
                await session.flush()
                await self._write_owned_revision(
                    session, prompt_list=prompt_list, entries=entries, version=1
                )
            result = await self._owned_with_entries(session, owner_id, list_id)
            assert result is not None
            return result

    async def update_owned(
        self,
        owner_user_id: str,
        prompt_list_id: str,
        *,
        expected_version: int,
        name: str,
        description: str,
        visibility: str,
        prompts: Sequence[PromptListEntryInput],
    ) -> OwnedPromptList:
        owner_id = _optional_entity_id(owner_user_id)
        list_id = _optional_entity_id(prompt_list_id)
        if owner_id is None or list_id is None:
            raise PromptListNotFoundError("Prompt list not found.")
        async with self._session_factory() as session:
            async with session.begin():
                prompt_list = await session.scalar(
                    select(PromptList)
                    .where(
                        PromptList.id == list_id,
                        PromptList.owner_user_id == owner_id,
                        PromptList.is_bundled.is_(False),
                    )
                    .with_for_update()
                )
                if prompt_list is None:
                    raise PromptListNotFoundError("Prompt list not found.")
                name, description, language, visibility = self._clean_owned_metadata(
                    name=name,
                    description=description,
                    language=prompt_list.language,
                    visibility=visibility,
                )
                entries = self._clean_owned_entries(
                    prompts, language=prompt_list.language
                )
                if prompt_list.version != expected_version:
                    raise PromptListConflictError(
                        "This list changed since you opened it. Reload before saving."
                    )
                next_version = prompt_list.version + 1
                await self._write_owned_revision(
                    session,
                    prompt_list=prompt_list,
                    entries=entries,
                    version=next_version,
                )
                prompt_list.name = name
                prompt_list.description = description
                if visibility == PromptListVisibility.UNLISTED.value:
                    prompt_list.share_code = (
                        prompt_list.share_code or await self._new_share_code(session)
                    )
                else:
                    prompt_list.share_code = None
                prompt_list.visibility = visibility
                prompt_list.version = next_version
                prompt_list.updated_at = datetime.now(timezone.utc)
            result = await self._owned_with_entries(session, owner_id, list_id)
            assert result is not None
            return result

    async def delete_owned(self, owner_user_id: str, prompt_list_id: str) -> bool:
        owner_id = _optional_entity_id(owner_user_id)
        list_id = _optional_entity_id(prompt_list_id)
        if owner_id is None or list_id is None:
            return False
        async with self._session_factory() as session:
            async with session.begin():
                prompt_list = await session.scalar(
                    select(PromptList).where(
                        PromptList.id == list_id,
                        PromptList.owner_user_id == owner_id,
                        PromptList.is_bundled.is_(False),
                    )
                )
                if prompt_list is None:
                    return False
                await session.delete(prompt_list)
            return True

    async def _write_owned_revision(
        self,
        session: AsyncSession,
        *,
        prompt_list: PromptList,
        entries: Sequence[PromptListEntryInput],
        version: int,
    ) -> None:
        previous = await session.scalar(
            select(PromptListRevision)
            .where(
                PromptListRevision.prompt_list_id == prompt_list.id,
                PromptListRevision.version == prompt_list.version,
            )
            .options(
                selectinload(PromptListRevision.items)
                .selectinload(PromptListRevisionItem.prompt_version)
                .selectinload(PromptVersion.version_aliases)
                .selectinload(PromptVersionAlias.alias)
            )
        )
        current_by_concept = {
            item.prompt_version.concept_id: item.prompt_version
            for item in (previous.items if previous else ())
        }
        supplied_ids = {
            UUID(entry.concept_id) for entry in entries if entry.concept_id is not None
        }
        if not supplied_ids.issubset(current_by_concept):
            raise PromptListMutationError(
                "A prompt identity does not belong to the current list revision."
            )

        alias_map: dict[tuple[UUID, str], PromptAlias] = {}
        if current_by_concept:
            aliases = (
                await session.scalars(
                    select(PromptAlias).where(
                        PromptAlias.concept_id.in_(current_by_concept),
                        PromptAlias.language == prompt_list.language,
                    )
                )
            ).all()
            alias_map = {
                (alias.concept_id, alias.match_key): alias for alias in aliases
            }

        resolved: list[tuple[UUID, PromptVersion, PromptListEntryInput]] = []
        pending_links: list[tuple[PromptVersion, PromptAlias]] = []
        for entry in entries:
            concept_id = UUID(entry.concept_id) if entry.concept_id else generate_uuid()
            existing = current_by_concept.get(concept_id)
            actual_aliases = (
                tuple(sorted(link.alias.answer for link in existing.version_aliases))
                if existing
                else ()
            )
            if (
                existing is not None
                and existing.canonical_answer == entry.answer
                and actual_aliases == tuple(sorted(entry.aliases))
            ):
                resolved.append((concept_id, existing, entry))
                continue
            if existing is None:
                session.add(PromptConcept(id=concept_id))
                prompt_version_number = 1
            else:
                prompt_version_number = existing.version + 1
            prompt_version = PromptVersion(
                id=generate_uuid(),
                concept_id=concept_id,
                language=prompt_list.language,
                version=prompt_version_number,
                canonical_answer=entry.answer,
                match_key=normalize_prompt_answer(entry.answer, prompt_list.language),
            )
            session.add(prompt_version)
            for alias_answer in entry.aliases:
                alias_key = normalize_prompt_answer(alias_answer, prompt_list.language)
                alias = alias_map.get((concept_id, alias_key))
                if alias is None:
                    alias = PromptAlias(
                        id=generate_uuid(),
                        concept_id=concept_id,
                        language=prompt_list.language,
                        answer=alias_answer,
                        match_key=alias_key,
                    )
                    session.add(alias)
                    alias_map[(concept_id, alias_key)] = alias
                pending_links.append((prompt_version, alias))
            resolved.append((concept_id, prompt_version, entry))
        await session.flush()
        session.add_all(
            PromptVersionAlias(
                prompt_version_id=prompt_version.id, alias_id=alias.id
            )
            for prompt_version, alias in pending_links
        )

        content_payload = {
            "language": prompt_list.language,
            "prompts": [
                {
                    "concept_id": str(concept_id),
                    "prompt_version_id": str(prompt_version.id),
                    "prompt": entry.answer,
                    "aliases": sorted(entry.aliases),
                }
                for concept_id, prompt_version, entry in resolved
            ],
        }
        content_hash = hashlib.sha256(
            json.dumps(
                content_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        # Every member, whatever moderation currently says about it. The
        # tallies are stored because a revision's membership never changes;
        # filtering on a mutable state would make them drift the moment it
        # does - a version hidden after this is written would stay counted, and
        # one restored after being hidden would never be counted at all.
        letter_counts, letter_total = letter_histogram(
            prompt_version.canonical_answer for _, prompt_version, _ in resolved
        )
        revision = PromptListRevision(
            id=generate_uuid(),
            prompt_list_id=prompt_list.id,
            version=version,
            language=prompt_list.language,
            content_hash=content_hash,
            letter_counts=letter_counts,
            letter_total=letter_total,
        )
        session.add(revision)
        await session.flush()
        session.add_all(
            PromptListRevisionItem(
                revision_id=revision.id,
                prompt_version_id=prompt_version.id,
                position=position,
            )
            for position, (_, prompt_version, _) in enumerate(resolved)
        )

        transitional_rows = (
            await session.scalars(
                select(Prompt).where(Prompt.prompt_list_id == prompt_list.id)
            )
        ).all()
        rows_by_concept = {
            row.concept_id: row for row in transitional_rows if row.concept_id
        }
        retained = {concept_id for concept_id, _, _ in resolved}
        for row in transitional_rows:
            if row.concept_id not in retained:
                await session.delete(row)
            else:
                row.text = f"__editing__{row.id}"
        await session.flush()
        for concept_id, prompt_version, entry in resolved:
            row = rows_by_concept.get(concept_id)
            if row is None:
                row = Prompt(
                    id=generate_uuid(),
                    prompt_list_id=prompt_list.id,
                    concept_id=concept_id,
                )
                session.add(row)
            row.prompt_version_id = prompt_version.id
            row.text = entry.answer

    async def get_prompts(self, prompt_list_id: str) -> list[str]:
        db_prompt_list_id = _optional_entity_id(prompt_list_id)
        if db_prompt_list_id is None:
            return []
        async with self._session_factory() as session:
            stmt = (
                select(Prompt.text)
                .where(Prompt.prompt_list_id == db_prompt_list_id)
                .order_by(Prompt.text)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _pinned_revisions(
        self,
        session: AsyncSession,
        slugs: list[str],
        *,
        requesting_user_id: str | None,
        share_codes: Sequence[str],
        load_items: bool,
    ) -> tuple[list[PromptListRevision], str]:
        """Authorize a selection and pin the revision each list is currently on.

        Shared by `resolve_selection` and `authorize_selection` so the two can
        never disagree about which lists a caller may combine: the checks a room
        is admitted by are the checks the game's prompts are drawn under.
        `load_items` is the only difference - pinning does not read the prompts.
        """
        requester_id = _optional_entity_id(requesting_user_id)
        supplied_share_codes = set(share_codes)
        list_rows = (
            await session.execute(
                select(
                    PromptList.id,
                    PromptList.slug,
                    PromptList.language,
                    PromptList.is_bundled,
                    PromptList.owner_user_id,
                    PromptList.visibility,
                    PromptList.share_code,
                    PromptList.moderation_state,
                )
                .where(PromptList.slug.in_(slugs))
            )
        ).all()
        authorized_rows = [
            row
            for row in list_rows
            if row.moderation_state == PromptContentModerationState.ACTIVE.value
            and (
                row.is_bundled
                or (requester_id is not None and row.owner_user_id == requester_id)
                or (
                    row.visibility == PromptListVisibility.UNLISTED.value
                    and row.share_code in supplied_share_codes
                )
            )
        ]
        found = {row.slug for row in authorized_rows}
        missing = [slug for slug in slugs if slug not in found]
        if missing:
            raise PromptListSelectionError(
                f"Prompt list{'s' if len(missing) != 1 else ''} not found: "
                + ", ".join(missing)
            )
        languages = {row.language for row in authorized_rows}
        if len(languages) != 1:
            raise PromptListSelectionError(
                "Selected prompt lists must use the same language"
            )
        rows_by_slug = {row.slug: row for row in authorized_rows}
        revisions: list[PromptListRevision] = []
        for slug in slugs:
            row = rows_by_slug[slug]
            stmt = select(PromptListRevision).where(
                PromptListRevision.prompt_list_id == row.id,
                PromptListRevision.version
                == select(PromptList.version)
                .where(PromptList.id == row.id)
                .scalar_subquery(),
            )
            if load_items:
                stmt = stmt.options(
                    selectinload(PromptListRevision.items)
                    .selectinload(PromptListRevisionItem.prompt_version)
                    .selectinload(PromptVersion.version_aliases)
                    .selectinload(PromptVersionAlias.alias)
                )
            revision = await session.scalar(stmt)
            if revision is None:
                raise PromptListSelectionError(
                    f"Prompt list has no seeded revision: {slug}"
                )
            revisions.append(revision)
        return revisions, languages.pop()

    async def resolve_selection(
        self,
        slugs: list[str],
        *,
        requesting_user_id: str | None = None,
        share_codes: Sequence[str] = (),
    ) -> ResolvedPromptSelection:
        if not slugs:
            raise PromptListSelectionError("Select at least one prompt list")
        async with self._session_factory() as session:
            revisions, language = await self._pinned_revisions(
                session,
                slugs,
                requesting_user_id=requesting_user_id,
                share_codes=share_codes,
                load_items=True,
            )
            languages = {language}

            prompts: list[str] = []
            aliases: dict[str, tuple[str, ...]] = {}
            prompt_version_ids: dict[str, str] = {}
            source_revisions_by_version: dict[UUID, list[str]] = defaultdict(list)
            seen_versions: set[UUID] = set()
            seen_match_versions: dict[str, UUID] = {}
            for revision in revisions:
                for item in revision.items:
                    prompt_version = item.prompt_version
                    if (
                        prompt_version.moderation_state
                        != PromptContentModerationState.ACTIVE.value
                    ):
                        continue
                    source_revisions_by_version[prompt_version.id].append(
                        _public_id(revision.id)
                    )
                    if prompt_version.id in seen_versions:
                        continue
                    accepted_keys = {
                        prompt_version.match_key,
                        *(link.alias.match_key for link in prompt_version.version_aliases),
                    }
                    if any(key in seen_match_versions for key in accepted_keys):
                        raise PromptListSelectionError(
                            "Selected prompt lists contain ambiguous answers or aliases"
                        )
                    seen_versions.add(prompt_version.id)
                    seen_match_versions.update(
                        (key, prompt_version.id) for key in accepted_keys
                    )
                    answer = prompt_version.canonical_answer
                    prompts.append(answer)
                    aliases[answer] = tuple(
                        sorted(
                            link.alias.answer
                            for link in prompt_version.version_aliases
                        )
                    )
                    prompt_version_ids[answer] = _public_id(prompt_version.id)
            if not prompts:
                raise PromptListSelectionError(
                    "Selected prompt lists do not contain any prompts"
                )
            return ResolvedPromptSelection(
                slugs=tuple(slugs),
                language=languages.pop(),
                prompts=tuple(prompts),
                revision_ids=tuple(_public_id(revision.id) for revision in revisions),
                aliases=aliases,
                prompt_version_ids=prompt_version_ids,
                prompt_source_revision_ids={
                    answer: tuple(source_revisions_by_version[UUID(version_id)])
                    for answer, version_id in prompt_version_ids.items()
                },
            )

    async def authorize_selection(
        self,
        slugs: list[str],
        *,
        requesting_user_id: str | None = None,
        share_codes: Sequence[str] = (),
    ) -> PinnedPromptSelection:
        if not slugs:
            raise PromptListSelectionError("Select at least one prompt list")
        async with self._session_factory() as session:
            revisions, language = await self._pinned_revisions(
                session,
                slugs,
                requesting_user_id=requesting_user_id,
                share_codes=share_codes,
                load_items=False,
            )
            revision_ids = [revision.id for revision in revisions]

            active_versions = (
                select(PromptListRevisionItem.prompt_version_id)
                .join(
                    PromptVersion,
                    PromptVersion.id == PromptListRevisionItem.prompt_version_id,
                )
                .where(
                    PromptListRevisionItem.revision_id.in_(revision_ids),
                    PromptVersion.moderation_state
                    == PromptContentModerationState.ACTIVE.value,
                )
            )
            prompt_count = await session.scalar(
                select(func.count()).select_from(
                    active_versions.distinct().subquery()
                )
            )
            if not prompt_count:
                raise PromptListSelectionError(
                    "Selected prompt lists do not contain any prompts"
                )

            # `resolve_selection` catches colliding answers by walking every
            # prompt it loads. Pinning loads none, so the same question is asked
            # of the database instead: does any match key - an answer's own or
            # one of its aliases - reach two different prompt versions?
            own_keys = select(
                PromptListRevisionItem.prompt_version_id.label("version_id"),
                PromptVersion.match_key.label("match_key"),
            ).join(
                PromptVersion,
                PromptVersion.id == PromptListRevisionItem.prompt_version_id,
            ).where(
                PromptListRevisionItem.revision_id.in_(revision_ids),
                PromptVersion.moderation_state
                == PromptContentModerationState.ACTIVE.value,
            )
            alias_keys = select(
                PromptListRevisionItem.prompt_version_id.label("version_id"),
                PromptAlias.match_key.label("match_key"),
            ).join(
                PromptVersion,
                PromptVersion.id == PromptListRevisionItem.prompt_version_id,
            ).join(
                PromptVersionAlias,
                PromptVersionAlias.prompt_version_id == PromptVersion.id,
            ).join(
                PromptAlias, PromptAlias.id == PromptVersionAlias.alias_id
            ).where(
                PromptListRevisionItem.revision_id.in_(revision_ids),
                PromptVersion.moderation_state
                == PromptContentModerationState.ACTIVE.value,
            )
            keys = own_keys.union(alias_keys).subquery()
            collision = await session.scalar(
                select(keys.c.match_key)
                .group_by(keys.c.match_key)
                .having(func.count(func.distinct(keys.c.version_id)) > 1)
                .limit(1)
            )
            if collision is not None:
                raise PromptListSelectionError(
                    "Selected prompt lists contain ambiguous answers or aliases"
                )

            letter_counts: Counter[str] = Counter()
            letter_total = 0
            for revision in revisions:
                letter_counts.update(revision.letter_counts or {})
                letter_total += revision.letter_total or 0

            return PinnedPromptSelection(
                slugs=tuple(slugs),
                language=language,
                revision_ids=tuple(_public_id(rid) for rid in revision_ids),
                prompt_count=int(prompt_count),
                letter_counts=dict(letter_counts),
                letter_total=letter_total,
            )

    async def sample_prompts(
        self,
        revision_ids: Sequence[str],
        *,
        limit: int,
        exclude_match_keys: Collection[str] = (),
    ) -> PromptSample:
        if limit <= 0 or not revision_ids:
            return PromptSample()
        pinned = [_entity_id(revision_id) for revision_id in revision_ids]
        excluded = set(exclude_match_keys)
        async with self._session_factory() as session:
            # Shadowed answers are excluded in the query rather than filtered
            # afterwards, so a draw returns what was asked for however much of
            # a list the room has claimed. Quick prompts are capped at
            # MAX_CUSTOM_PROMPTS (2000), well inside what either backend binds.
            eligible = [
                PromptVersion.id.in_(
                    select(PromptListRevisionItem.prompt_version_id).where(
                        PromptListRevisionItem.revision_id.in_(pinned)
                    )
                ),
                PromptVersion.moderation_state
                == PromptContentModerationState.ACTIVE.value,
            ]
            if excluded:
                eligible.append(PromptVersion.match_key.notin_(excluded))

            versions = (
                (
                    await session.execute(
                        select(PromptVersion)
                        .where(*eligible)
                        .order_by(func.random())
                        .limit(limit)
                        .options(
                            selectinload(PromptVersion.version_aliases).selectinload(
                                PromptVersionAlias.alias
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not versions:
                return PromptSample()

            # The draw comes first and the count second, so a `drawable` this
            # draw already disproved is never reported. Postgres reads each
            # statement at its own snapshot, so a takedown committing between
            # the two would otherwise leave a count saying there is content and
            # a draw holding none - and a caller weighting on that count, or
            # trusting it to mean the lists are playable, would be wrong in the
            # one direction that matters. Fewer rows than asked for means there
            # are no more; only a full draw needs asking.
            if len(versions) < limit:
                drawable = len(versions)
            else:
                drawable = max(
                    await session.scalar(
                        select(func.count()).select_from(
                            select(PromptVersion.id).where(*eligible).subquery()
                        )
                    )
                    or 0,
                    len(versions),
                )

            # Which of the pinned revisions each drawn prompt came from: a
            # version can sit in several selected lists, and a turn records
            # every source it was legitimately offered from.
            order = {revision_id: index for index, revision_id in enumerate(pinned)}
            sources: dict[UUID, list[UUID]] = defaultdict(list)
            source_rows = await session.execute(
                select(
                    PromptListRevisionItem.prompt_version_id,
                    PromptListRevisionItem.revision_id,
                ).where(
                    PromptListRevisionItem.revision_id.in_(pinned),
                    PromptListRevisionItem.prompt_version_id.in_(
                        [version.id for version in versions]
                    ),
                )
            )
            for version_id, revision_id in source_rows:
                sources[version_id].append(revision_id)

            return PromptSample(
                prompts=tuple(
                    SampledPrompt(
                        answer=version.canonical_answer,
                        match_key=version.match_key,
                        aliases=tuple(
                            sorted(
                                link.alias.answer
                                for link in version.version_aliases
                            )
                        ),
                        prompt_version_id=_public_id(version.id),
                        source_revision_ids=tuple(
                            _public_id(revision_id)
                            for revision_id in sorted(
                                sources[version.id], key=lambda rid: order[rid]
                            )
                        ),
                    )
                    for version in versions
                ),
                drawable=drawable,
            )

    async def get_prompts_by_slugs(self, slugs: list[str]) -> list[str]:
        if not slugs:
            return []
        return list((await self.resolve_selection(slugs)).prompts)

    async def upsert_bundled(
        self,
        slug: str,
        name: str,
        description: str,
        language: str,
        prompts: Sequence[BundledPromptDefinition],
        version: int,
    ) -> PromptListSummary:
        source_prompts = tuple(prompts)
        if not source_prompts:
            raise PromptSeedConflictError("bundled prompt lists cannot be empty")
        concept_ids = [UUID(prompt.concept_id) for prompt in source_prompts]
        if len(set(concept_ids)) != len(concept_ids):
            raise PromptSeedConflictError(
                "a concept may appear only once in a prompt-list revision"
            )
        answer_keys = [
            normalize_prompt_answer(prompt.answer, language)
            for prompt in source_prompts
        ]
        if len(set(answer_keys)) != len(answer_keys):
            raise PromptSeedConflictError(
                "a prompt-list revision cannot contain duplicate displayed answers"
            )
        content_hash = _bundled_revision_hash(
            language=language, prompts=source_prompts
        )

        async with self._session_factory() as session:
            async with session.begin():
                stmt = (
                    select(PromptList)
                    .where(PromptList.slug == slug)
                    .options(
                        selectinload(PromptList.prompts),
                        selectinload(PromptList.revisions),
                    )
                )
                result = await session.execute(stmt)
                wl = result.scalar_one_or_none()

                if wl is None:
                    existing_prompts: tuple[Prompt, ...] = ()
                    existing_revisions: tuple[PromptListRevision, ...] = ()
                    wl = PromptList(
                        id=generate_uuid(),
                        slug=slug,
                        name=name,
                        description=description,
                        language=language,
                        is_bundled=True,
                        visibility=PromptListVisibility.PUBLIC.value,
                        moderation_state=PromptContentModerationState.ACTIVE.value,
                        version=version,
                    )
                    session.add(wl)
                    await session.flush()
                elif not wl.is_bundled:
                    raise PromptSeedConflictError(
                        f"bundled seed cannot replace user-owned list {slug}"
                    )
                else:
                    existing_prompts = tuple(wl.prompts)
                    existing_revisions = tuple(wl.revisions)

                existing_revision = next(
                    (
                        revision
                        for revision in existing_revisions
                        if revision.version == version
                    ),
                    None,
                )
                if existing_revision is not None:
                    if (
                        existing_revision.content_hash != content_hash
                        or existing_revision.language != language
                    ):
                        raise PromptSeedConflictError(
                            f"bundled list {slug} version {version} changed in place"
                        )
                    wl.name = name
                    wl.description = description
                    wl.visibility = PromptListVisibility.PUBLIC.value
                    wl.moderation_state = PromptContentModerationState.ACTIVE.value
                elif version < wl.version:
                    raise PromptSeedConflictError(
                        f"bundled list {slug} cannot roll back from version "
                        f"{wl.version} to {version}"
                    )
                else:
                    prompt_versions = await self._ensure_bundled_prompt_versions(
                        session, definitions=source_prompts, language=language
                    )
                    revision_counts, revision_total = letter_histogram(
                        prompt_version.canonical_answer
                        for prompt_version in prompt_versions
                    )
                    revision = PromptListRevision(
                        id=generate_uuid(),
                        prompt_list_id=wl.id,
                        version=version,
                        language=language,
                        content_hash=content_hash,
                        letter_counts=revision_counts,
                        letter_total=revision_total,
                    )
                    session.add(revision)
                    await session.flush()
                    session.add_all(
                        [
                            PromptListRevisionItem(
                                revision_id=revision.id,
                                prompt_version_id=prompt_version.id,
                                position=position,
                            )
                            for position, prompt_version in enumerate(prompt_versions)
                        ]
                    )

                    existing_by_concept = {
                        prompt.concept_id: prompt
                        for prompt in existing_prompts
                        if prompt.concept_id is not None
                    }
                    unlinked_by_key = {
                        prompt_match_key(prompt.text, language): prompt
                        for prompt in existing_prompts
                        if prompt.concept_id is None
                    }
                    selected_rows: dict[UUID, Prompt] = {}
                    # prompt_versions rides along unused so strict= keeps
                    # proving the three lists describe the same prompts.
                    for definition, _prompt_version, answer_key in zip(
                        source_prompts, prompt_versions, answer_keys, strict=True
                    ):
                        concept_id = UUID(definition.concept_id)
                        prompt_row = existing_by_concept.get(concept_id)
                        if prompt_row is None:
                            prompt_row = unlinked_by_key.get(answer_key)
                        if prompt_row is not None:
                            selected_rows[concept_id] = prompt_row

                    retained_ids = {id(prompt) for prompt in selected_rows.values()}
                    for prompt_row in existing_prompts:
                        if id(prompt_row) not in retained_ids:
                            await session.delete(prompt_row)
                    await session.flush()

                    for definition, prompt_version in zip(
                        source_prompts, prompt_versions, strict=True
                    ):
                        concept_id = UUID(definition.concept_id)
                        prompt_row = selected_rows.get(concept_id)
                        if prompt_row is None:
                            prompt_row = Prompt(
                                id=generate_uuid(),
                                prompt_list_id=wl.id,
                                text=definition.answer,
                            )
                            session.add(prompt_row)
                        prompt_row.concept_id = concept_id
                        prompt_row.prompt_version_id = prompt_version.id
                        prompt_row.text = definition.answer

                    wl.name = name
                    wl.description = description
                    wl.language = language
                    wl.visibility = PromptListVisibility.PUBLIC.value
                    wl.moderation_state = PromptContentModerationState.ACTIVE.value
                    wl.version = version

            await session.refresh(wl)
            prompt_count = await session.scalar(
                select(func.count(Prompt.id)).where(Prompt.prompt_list_id == wl.id)
            )
            return _to_prompt_list_summary(wl, int(prompt_count or 0))

    async def _ensure_bundled_prompt_versions(
        self,
        session: AsyncSession,
        *,
        definitions: Sequence[BundledPromptDefinition],
        language: str,
    ) -> list[PromptVersion]:
        """Resolve one source revision with bounded, set-based database reads."""
        concept_ids = [UUID(definition.concept_id) for definition in definitions]

        existing_concept_ids: set[UUID] = set()
        existing_versions: list[PromptVersion] = []
        for offset in range(0, len(concept_ids), 500):
            concept_chunk = concept_ids[offset : offset + 500]
            existing_concept_ids.update(
                (
                    await session.scalars(
                        select(PromptConcept.id).where(
                            PromptConcept.id.in_(concept_chunk)
                        )
                    )
                ).all()
            )
            existing_versions.extend(
                (
                    await session.scalars(
                        select(PromptVersion)
                        .where(
                            PromptVersion.concept_id.in_(concept_chunk),
                            PromptVersion.language == language,
                        )
                        .options(
                            selectinload(PromptVersion.version_aliases).selectinload(
                                PromptVersionAlias.alias
                            ),
                            selectinload(PromptVersion.version_tags).selectinload(
                                PromptVersionTag.tag
                            ),
                        )
                    )
                ).all()
            )

        session.add_all(
            PromptConcept(id=concept_id)
            for concept_id in concept_ids
            if concept_id not in existing_concept_ids
        )
        version_map = {
            (entry.concept_id, entry.version): entry for entry in existing_versions
        }
        latest_versions: dict[UUID, int] = defaultdict(int)
        for entry in existing_versions:
            latest_versions[entry.concept_id] = max(
                latest_versions[entry.concept_id], entry.version
            )

        resolved: list[PromptVersion] = []
        new_pairs: list[tuple[BundledPromptDefinition, PromptVersion]] = []
        for definition, concept_id in zip(definitions, concept_ids, strict=True):
            match_key = normalize_prompt_answer(definition.answer, language)
            prompt_version = version_map.get(
                (concept_id, definition.prompt_version)
            )
            if prompt_version is not None:
                actual_aliases = tuple(
                    sorted(
                        link.alias.answer
                        for link in prompt_version.version_aliases
                    )
                )
                actual_tags = tuple(
                    sorted(
                        link.tag.slug for link in prompt_version.version_tags
                    )
                )
                if (
                    prompt_version.canonical_answer != definition.answer
                    or prompt_version.match_key != match_key
                    or prompt_version.editorial_difficulty
                    != definition.editorial_difficulty
                    or prompt_version.content_rating != definition.content_rating
                    or actual_aliases != tuple(sorted(definition.aliases))
                    or actual_tags != tuple(sorted(definition.tags))
                ):
                    raise PromptSeedConflictError(
                        f"prompt concept {definition.concept_id} version "
                        f"{definition.prompt_version} changed in place"
                    )
                resolved.append(prompt_version)
                continue

            expected_version = latest_versions[concept_id] + 1
            if definition.prompt_version != expected_version:
                raise PromptSeedConflictError(
                    f"prompt concept {definition.concept_id} expected version "
                    f"{expected_version}, got {definition.prompt_version}"
                )
            prompt_version = PromptVersion(
                id=generate_uuid(),
                concept_id=concept_id,
                language=language,
                version=definition.prompt_version,
                canonical_answer=definition.answer,
                match_key=match_key,
                editorial_difficulty=definition.editorial_difficulty,
                content_rating=definition.content_rating,
            )
            session.add(prompt_version)
            latest_versions[concept_id] = definition.prompt_version
            new_pairs.append((definition, prompt_version))
            resolved.append(prompt_version)
        await session.flush()

        requested_alias_keys = {
            (UUID(definition.concept_id), normalize_prompt_answer(alias, language))
            for definition, _ in new_pairs
            for alias in definition.aliases
        }
        alias_map: dict[tuple[UUID, str], PromptAlias] = {}
        if requested_alias_keys:
            alias_concepts = {key[0] for key in requested_alias_keys}
            aliases = (
                await session.scalars(
                    select(PromptAlias).where(
                        PromptAlias.concept_id.in_(alias_concepts),
                        PromptAlias.language == language,
                    )
                )
            ).all()
            alias_map = {
                (alias.concept_id, alias.match_key): alias for alias in aliases
            }

        requested_tags = {
            tag for definition, _ in new_pairs for tag in definition.tags
        }
        tag_map = {
            tag.slug: tag
            for tag in (
                (
                    await session.scalars(
                        select(PromptTag).where(PromptTag.slug.in_(requested_tags))
                    )
                ).all()
                if requested_tags
                else []
            )
        }

        alias_links: list[tuple[PromptVersion, PromptAlias]] = []
        tag_links: list[tuple[PromptVersion, PromptTag]] = []
        for definition, prompt_version in new_pairs:
            concept_id = UUID(definition.concept_id)
            for alias_answer in definition.aliases:
                alias_key = normalize_prompt_answer(alias_answer, language)
                alias = alias_map.get((concept_id, alias_key))
                if alias is None:
                    alias = PromptAlias(
                        id=generate_uuid(),
                        concept_id=concept_id,
                        language=language,
                        answer=alias_answer,
                        match_key=alias_key,
                    )
                    session.add(alias)
                    alias_map[(concept_id, alias_key)] = alias
                elif alias.answer != alias_answer:
                    raise PromptSeedConflictError(
                        f"prompt alias {alias_answer!r} changes immutable display copy"
                    )
                alias_links.append((prompt_version, alias))
            for tag_slug in definition.tags:
                tag = tag_map.get(tag_slug)
                if tag is None:
                    tag = PromptTag(
                        id=generate_uuid(),
                        slug=tag_slug,
                        name=tag_slug.replace("-", " ").title(),
                    )
                    session.add(tag)
                    tag_map[tag_slug] = tag
                tag_links.append((prompt_version, tag))
        await session.flush()
        session.add_all(
            PromptVersionAlias(
                prompt_version_id=prompt_version.id, alias_id=alias.id
            )
            for prompt_version, alias in alias_links
        )
        session.add_all(
            PromptVersionTag(
                prompt_version_id=prompt_version.id, tag_id=tag.id
            )
            for prompt_version, tag in tag_links
        )
        return resolved

    async def record_prompt_usage(
        self,
        prompt_list_revision_ids: Sequence[str],
        usage: PromptUsage,
    ) -> None:
        """Append a game's ID-attributed facts to its pinned revisions.

        Both the revision and prompt-version IDs came from the game's start
        snapshot. Their intersection is checked again here so no display-text
        collision—or malformed internal call—can credit unrelated content.
        """
        revision_ids = [
            revision_id
            for raw in prompt_list_revision_ids
            if (revision_id := _optional_entity_id(raw)) is not None
        ]
        batch_id = _optional_entity_id(usage.batch_id)
        if not revision_ids or not usage:
            return
        if batch_id is None:
            raise ValueError("Prompt usage batch ID must be a UUID.")
        async with self._session_factory() as session:
            async with session.begin():
                if await session.scalar(
                    select(PromptUsageFact.id).where(
                        PromptUsageFact.batch_id == batch_id
                    ).limit(1)
                ):
                    # A committed-after-timeout retry of the same finished game
                    # is harmless. One transaction means a batch is all-or-none.
                    return
                memberships = (
                    await session.execute(
                        select(
                            PromptListRevisionItem.revision_id,
                            PromptListRevisionItem.prompt_version_id,
                        ).where(
                            PromptListRevisionItem.revision_id.in_(revision_ids)
                        )
                    )
                ).all()
                facts: list[PromptUsageFact] = []
                for revision_id, prompt_version_id in memberships:
                    version_key = _public_id(prompt_version_id)
                    offer_count = usage.offers.get(version_key, 0)
                    totals = usage.picks.get(version_key)
                    if offer_count <= 0 and totals is None:
                        continue
                    facts.append(
                        PromptUsageFact(
                            id=generate_uuid(),
                            batch_id=batch_id,
                            prompt_list_revision_id=revision_id,
                            prompt_version_id=prompt_version_id,
                            occurred_at=usage.occurred_at,
                            scoring_mode=usage.scoring_mode,
                            hint_mode=usage.hint_mode,
                            offer_count=offer_count,
                            pick_count=totals.picks if totals else 0,
                            correct_guess_count=(
                                totals.correct_guesses if totals else 0
                            ),
                            total_guesser_count=(
                                totals.total_guessers if totals else 0
                            ),
                        )
                    )
                session.add_all(facts)

    async def get_prompt_stats(
        self,
        prompt_list_slug: str,
        *,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        scoring_mode: str | None = None,
        hint_mode: str | None = None,
    ) -> list[PromptStatsSummary]:
        async with self._session_factory() as session:
            prompt_list = await session.scalar(
                select(PromptList).where(
                    PromptList.slug == prompt_list_slug,
                    PromptList.is_bundled.is_(True),
                    PromptList.moderation_state
                    == PromptContentModerationState.ACTIVE.value,
                )
            )
            if prompt_list is None:
                return []
            prompts = (
                await session.scalars(
                    select(Prompt)
                    .where(Prompt.prompt_list_id == prompt_list.id)
                    .order_by(Prompt.text)
                )
            ).all()

            fact_filters = [
                PromptListRevision.prompt_list_id == prompt_list.id,
            ]
            if from_time is not None:
                fact_filters.append(PromptUsageFact.occurred_at >= from_time)
            if to_time is not None:
                fact_filters.append(PromptUsageFact.occurred_at < to_time)
            if scoring_mode is not None:
                fact_filters.append(PromptUsageFact.scoring_mode == scoring_mode)
            if hint_mode is not None:
                fact_filters.append(PromptUsageFact.hint_mode == hint_mode)
            aggregates = {
                concept_id: (offers, picks, correct, guessers)
                for concept_id, offers, picks, correct, guessers in (
                    await session.execute(
                        select(
                            PromptVersion.concept_id,
                            func.sum(PromptUsageFact.offer_count),
                            func.sum(PromptUsageFact.pick_count),
                            func.sum(PromptUsageFact.correct_guess_count),
                            func.sum(PromptUsageFact.total_guesser_count),
                        )
                        .join(
                            PromptUsageFact,
                            PromptUsageFact.prompt_version_id == PromptVersion.id,
                        )
                        .join(
                            PromptListRevision,
                            PromptListRevision.id
                            == PromptUsageFact.prompt_list_revision_id,
                        )
                        .where(*fact_filters)
                        .group_by(PromptVersion.concept_id)
                    )
                ).all()
            }

            summaries: list[PromptStatsSummary] = []
            for prompt in prompts:
                offer_count, pick_count, correct_count, guesser_count = (
                    aggregates.get(prompt.concept_id, (0, 0, 0, 0))
                )
                pick_rate = pick_count / offer_count if offer_count > 0 else 0.0
                ratio = correct_count / guesser_count if guesser_count > 0 else 0.0
                summaries.append(
                    PromptStatsSummary(
                        text=prompt.text,
                        offer_count=offer_count,
                        pick_count=pick_count,
                        correct_guess_count=correct_count,
                        total_guesser_count=guesser_count,
                        pick_rate=round(pick_rate, 4),
                        correct_guess_ratio=round(ratio, 4),
                    )
                )
            return summaries

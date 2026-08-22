"""SQLAlchemy implementations of domain repository interfaces."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, case, distinct, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.models import (
    GameParticipant,
    GameRecord,
    IdentityAlias,
    TurnGuess,
    TurnRecord,
    User,
    AuditEvent,
    Prompt,
    PromptList,
    generate_uuid,
)
from app.domain_values import AccountState
from app.auth.avatars import validate_avatar_key
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    GameDetail,
    GameHistoryRepository,
    GameParticipantInput,
    GameParticipantSummary,
    GameRecordInput,
    GameSummary,
    InvalidProfileDataError,
    IdentityMergeError,
    TurnDetail,
    TurnGuessDetail,
    TurnGuessInput,
    TurnRecordInput,
    UserCredentials,
    UserData,
    UserRepository,
    UserStats,
    UsernameTakenError,
    PromptListRepository,
    PromptListSummary,
    PromptPickTotals,
    PromptStatsSummary,
    PromptUsage,
)

MAX_PAGINATION_LIMIT = 100
DEFAULT_PAGINATION_LIMIT = 20


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
        hint_mode=game.hint_mode,
        drawing_seconds=game.drawing_seconds,
        total_rounds=game.total_rounds,
        player_count=game.player_count,
        started_at=game.started_at,
        finished_at=game.finished_at,
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
    wl: PromptList, prompt_count: int
) -> PromptListSummary:
    return PromptListSummary(
        id=_public_id(wl.id),
        slug=wl.slug,
        name=wl.name,
        description=wl.description,
        language=wl.language,
        prompt_count=prompt_count,
        is_bundled=wl.is_bundled,
        version=wl.version,
    )


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
                        details={"source_user_id": str(source.id)},
                    )
                )
                await session.flush()
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

    async def get_stats(self, user_id: str) -> UserStats:
        db_user_id = _optional_entity_id(user_id)
        if db_user_id is None:
            return UserStats(user_id=user_id)
        async with self._session_factory() as session:
            identity_ids = await _identity_ids(session, db_user_id)
            canonical_id = identity_ids[0]
            # 1. Games count, wins, and score
            part_stmt = select(
                func.count(distinct(GameParticipant.game_id)).label("games_played"),
                func.count(
                    distinct(
                        case(
                            (GameParticipant.final_rank == 1, GameParticipant.game_id),
                            else_=None,
                        )
                    )
                ).label("games_won"),
                func.coalesce(func.sum(GameParticipant.final_score), 0).label("total_score"),
            ).where(GameParticipant.user_id.in_(identity_ids))
            part_res = (await session.execute(part_stmt)).one()
            games_played = int(part_res.games_played or 0)
            games_won = int(part_res.games_won or 0)
            total_score = int(part_res.total_score or 0)
            win_rate = (games_won / games_played) if games_played > 0 else 0.0
            average_score = (total_score / games_played) if games_played > 0 else 0.0

            # 2. Total turns played across games where user participated
            turns_stmt = (
                select(func.count(distinct(TurnRecord.id)))
                .select_from(TurnRecord)
                .join(
                    GameParticipant,
                    and_(
                        GameParticipant.game_id == TurnRecord.game_id,
                        GameParticipant.user_id.in_(identity_ids),
                    ),
                )
            )
            turns_played = int((await session.execute(turns_stmt)).scalar() or 0)

            # 3. Correct guesses made
            guesses_stmt = select(func.count(TurnGuess.id)).where(
                TurnGuess.user_id.in_(identity_ids)
            )
            prompts_guessed = int((await session.execute(guesses_stmt)).scalar() or 0)

            # 4. Drawings made
            drawings_stmt = select(func.count(TurnRecord.id)).where(
                TurnRecord.drawer_user_id.in_(identity_ids)
            )
            drawings_made = int((await session.execute(drawings_stmt)).scalar() or 0)

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

    async def save_game(
        self,
        game_record: GameRecordInput,
        participants: list[GameParticipantInput],
        turns: list[TurnRecordInput],
        guesses: list[TurnGuessInput],
    ) -> str:
        record_id = (
            _entity_id(game_record.id) if game_record.id else generate_uuid()
        )
        async with self._session_factory() as session:
            async with session.begin():
                referenced_user_ids = {
                    _entity_id(participant.user_id) for participant in participants
                }
                referenced_user_ids.update(
                    _entity_id(turn.drawer_user_id) for turn in turns
                )
                referenced_user_ids.update(
                    _entity_id(guess.user_id) for guess in guesses
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

                game_db = GameRecord(
                    id=record_id,
                    room_name=game_record.room_name,
                    scoring_mode=game_record.scoring_mode,
                    hint_mode=game_record.hint_mode,
                    drawing_seconds=game_record.drawing_seconds,
                    total_rounds=game_record.total_rounds,
                    player_count=game_record.player_count,
                    started_at=game_record.started_at,
                    finished_at=game_record.finished_at,
                )
                session.add(game_db)

                for p in participants:
                    participant_user_id = _entity_id(p.user_id)
                    participant_user = users_by_id[participant_user_id]
                    session.add(
                        GameParticipant(
                            id=generate_uuid(),
                            game_id=record_id,
                            user_id=participant_user_id,
                            display_name_snapshot=participant_user.display_name,
                            name_color_snapshot=participant_user.name_color,
                            is_anonymous_snapshot=participant_user.is_anonymous,
                            final_score=p.final_score,
                            final_rank=p.final_rank,
                            turns_played=p.turns_played,
                        )
                    )

                created_turn_ids: set[UUID] = set()
                for r in turns:
                    rid = _entity_id(r.id)
                    if rid in created_turn_ids:
                        raise ValueError(f"Duplicate turn id '{r.id}'")
                    created_turn_ids.add(rid)
                    drawer_user_id = _entity_id(r.drawer_user_id)
                    drawer_user = users_by_id[drawer_user_id]
                    session.add(
                        TurnRecord(
                            id=rid,
                            game_id=record_id,
                            round_number=r.round_number,
                            turn_number=r.turn_number,
                            drawer_user_id=drawer_user_id,
                            drawer_display_name_snapshot=drawer_user.display_name,
                            drawer_name_color_snapshot=drawer_user.name_color,
                            drawer_is_anonymous_snapshot=drawer_user.is_anonymous,
                            prompt=r.prompt,
                            duration_seconds=r.duration_seconds,
                            guesser_count=r.guesser_count,
                            prompt_auto_picked=r.prompt_auto_picked,
                            stroke_count=r.stroke_count,
                            end_reason=r.end_reason,
                            wrong_guess_count=r.wrong_guess_count,
                            near_miss_count=r.near_miss_count,
                        )
                    )

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
                    guess_user_id = _entity_id(g.user_id)
                    guess_user = users_by_id[guess_user_id]
                    session.add(
                        TurnGuess(
                            id=generate_uuid(),
                            turn_id=target_turn_id,
                            user_id=guess_user_id,
                            display_name_snapshot=guess_user.display_name,
                            name_color_snapshot=guess_user.name_color,
                            is_anonymous_snapshot=guess_user.is_anonymous,
                            points_awarded=g.points_awarded,
                            guess_time_seconds=g.guess_time_seconds,
                            hints_used=g.hints_used,
                            points_spent_on_hints=g.points_spent_on_hints,
                            wrong_guesses_before=g.wrong_guesses_before,
                        )
                    )

        return _public_id(record_id)

    async def get_user_games(
        self,
        user_id: str,
        limit: int = DEFAULT_PAGINATION_LIMIT,
        offset: int = 0,
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
                .where(GameRecord.id.in_(user_games_subq))
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
        requesting_user_id: str | None = None,
    ) -> GameDetail | None:
        db_game_id = _optional_entity_id(game_id)
        if db_game_id is None:
            return None
        db_requesting_user_id = (
            _optional_entity_id(requesting_user_id)
            if requesting_user_id is not None
            else None
        )
        if requesting_user_id is not None and db_requesting_user_id is None:
            return None
        async with self._session_factory() as session:
            requesting_identity_ids = (
                await _identity_ids(session, db_requesting_user_id)
                if db_requesting_user_id is not None
                else ()
            )
            stmt = (
                select(GameRecord)
                .where(GameRecord.id == db_game_id)
                .options(
                    selectinload(GameRecord.participants).selectinload(GameParticipant.user),
                    selectinload(GameRecord.turns).selectinload(TurnRecord.drawer),
                    selectinload(GameRecord.turns).selectinload(TurnRecord.guesses).selectinload(TurnGuess.user),
                )
            )
            result = await session.execute(stmt)
            g = result.scalar_one_or_none()
            if not g:
                return None

            # Authorization scoping: If a requesting user is specified, ensure they participated in this game
            if db_requesting_user_id is not None:
                is_participant = any(
                    p.user_id in requesting_identity_ids for p in g.participants
                )
                if not is_participant:
                    return None

            summary = _to_game_summary(g)

            turn_details: list[TurnDetail] = []
            for r in sorted(g.turns, key=lambda x: (x.round_number, x.turn_number)):
                guess_details = [
                    TurnGuessDetail(
                        user_id=_public_id(guess.user_id) if guess.user_id else None,
                        display_name=guess.display_name_snapshot,
                        points_awarded=guess.points_awarded,
                        guess_time_seconds=guess.guess_time_seconds,
                    )
                    for guess in sorted(r.guesses, key=lambda x: x.guess_time_seconds)
                ]
                turn_details.append(
                    TurnDetail(
                        round_number=r.round_number,
                        turn_number=r.turn_number,
                        drawer_user_id=(
                            _public_id(r.drawer_user_id) if r.drawer_user_id else None
                        ),
                        drawer_display_name=r.drawer_display_name_snapshot,
                        prompt=r.prompt,
                        duration_seconds=r.duration_seconds,
                        guesses=guess_details,
                    )
                )

            return GameDetail(summary=summary, turns=turn_details)


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

    async def list_all(self) -> list[PromptListSummary]:
        async with self._session_factory() as session:
            stmt = select(PromptList, self._prompt_count()).order_by(PromptList.name)
            result = await session.execute(stmt)
            return [
                _to_prompt_list_summary(prompt_list, int(prompt_count))
                for prompt_list, prompt_count in result.all()
            ]

    async def get_by_slug(self, slug: str) -> PromptListSummary | None:
        async with self._session_factory() as session:
            stmt = select(PromptList, self._prompt_count()).where(
                PromptList.slug == slug
            )
            result = await session.execute(stmt)
            row = result.one_or_none()
            return (
                _to_prompt_list_summary(row[0], int(row[1])) if row else None
            )

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

    async def get_prompts_by_slugs(self, slugs: list[str]) -> list[str]:
        if not slugs:
            return []
        async with self._session_factory() as session:
            stmt = (
                select(distinct(Prompt.text))
                .join(PromptList, Prompt.prompt_list_id == PromptList.id)
                .where(PromptList.slug.in_(slugs))
                .order_by(Prompt.text)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def upsert_bundled(
        self,
        slug: str,
        name: str,
        description: str,
        language: str,
        prompts: list[str],
        version: int,
    ) -> PromptListSummary:
        # Deduplicate incoming prompts case-insensitively
        seen_prompts: set[str] = set()
        clean_prompts: list[str] = []
        for w in prompts:
            trimmed = w.strip()
            lower = trimmed.lower()
            if trimmed and lower not in seen_prompts:
                seen_prompts.add(lower)
                clean_prompts.append(lower)

        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(PromptList).where(PromptList.slug == slug).options(selectinload(PromptList.prompts))
                result = await session.execute(stmt)
                wl = result.scalar_one_or_none()

                if wl is None:
                    wl = PromptList(
                        id=generate_uuid(),
                        slug=slug,
                        name=name,
                        description=description,
                        language=language,
                        is_bundled=True,
                        version=version,
                    )
                    session.add(wl)
                    for text in clean_prompts:
                        session.add(
                            Prompt(
                                id=generate_uuid(),
                                prompt_list_id=wl.id,
                                text=text,
                                offer_count=0,
                                pick_count=0,
                                correct_guess_count=0,
                                total_guesser_count=0,
                            )
                        )
                elif version > wl.version:
                    wl.name = name
                    wl.description = description
                    wl.language = language
                    wl.version = version

                    existing_prompts_map = {w.text.lower(): w for w in wl.prompts}
                    target_set = set(clean_prompts)

                    # Remove deleted prompts
                    for old_text, prompt_obj in list(existing_prompts_map.items()):
                        if old_text not in target_set:
                            await session.delete(prompt_obj)

                    # Add new prompts
                    for text in clean_prompts:
                        if text not in existing_prompts_map:
                            session.add(
                                Prompt(
                                    id=generate_uuid(),
                                    prompt_list_id=wl.id,
                                    text=text,
                                    offer_count=0,
                                    pick_count=0,
                                    correct_guess_count=0,
                                    total_guesser_count=0,
                                )
                            )

            await session.refresh(wl)
            prompt_count = await session.scalar(
                select(func.count(Prompt.id)).where(Prompt.prompt_list_id == wl.id)
            )
            return _to_prompt_list_summary(wl, int(prompt_count or 0))

    async def record_prompt_usage(
        self,
        prompt_list_slugs: Sequence[str],
        usage: PromptUsage,
    ) -> None:
        """Apply a whole game's counters to every named list in one transaction.

        Prompts carrying the same increment are updated together, so the cost is
        a handful of statements rather than one per prompt per list. A game ends
        with as many turns as it had players and rounds, and this used to be a
        commit apiece.
        """
        slugs = list(prompt_list_slugs)
        if not slugs or not usage:
            return
        async with self._session_factory() as session:
            async with session.begin():
                list_ids = (
                    await session.execute(
                        select(PromptList.id).where(PromptList.slug.in_(slugs))
                    )
                ).scalars().all()
                if not list_ids:
                    return

                offers_by_count: dict[int, list[str]] = defaultdict(list)
                for text, count in usage.offers.items():
                    offers_by_count[count].append(text)
                for count, texts in offers_by_count.items():
                    await session.execute(
                        update(Prompt)
                        .where(
                            and_(
                                Prompt.prompt_list_id.in_(list_ids),
                                Prompt.text.in_(texts),
                            )
                        )
                        .values(offer_count=Prompt.offer_count + count)
                    )

                picks_by_totals: dict[PromptPickTotals, list[str]] = defaultdict(list)
                for text, totals in usage.picks.items():
                    picks_by_totals[totals].append(text)
                for totals, texts in picks_by_totals.items():
                    await session.execute(
                        update(Prompt)
                        .where(
                            and_(
                                Prompt.prompt_list_id.in_(list_ids),
                                Prompt.text.in_(texts),
                            )
                        )
                        .values(
                            pick_count=Prompt.pick_count + totals.picks,
                            correct_guess_count=(
                                Prompt.correct_guess_count + totals.correct_guesses
                            ),
                            total_guesser_count=(
                                Prompt.total_guesser_count + totals.total_guessers
                            ),
                        )
                    )

    async def get_prompt_stats(
        self,
        prompt_list_slug: str,
    ) -> list[PromptStatsSummary]:
        async with self._session_factory() as session:
            stmt = (
                select(Prompt)
                .join(PromptList, Prompt.prompt_list_id == PromptList.id)
                .where(PromptList.slug == prompt_list_slug)
                .order_by(Prompt.text)
            )
            result = await session.execute(stmt)
            prompts = result.scalars().all()

            summaries: list[PromptStatsSummary] = []
            for w in prompts:
                pick_rate = (w.pick_count / w.offer_count) if w.offer_count > 0 else 0.0
                ratio = (w.correct_guess_count / w.total_guesser_count) if w.total_guesser_count > 0 else 0.0
                summaries.append(
                    PromptStatsSummary(
                        text=w.text,
                        offer_count=w.offer_count,
                        pick_count=w.pick_count,
                        correct_guess_count=w.correct_guess_count,
                        total_guesser_count=w.total_guesser_count,
                        pick_rate=round(pick_rate, 4),
                        correct_guess_ratio=round(ratio, 4),
                    )
                )
            return summaries

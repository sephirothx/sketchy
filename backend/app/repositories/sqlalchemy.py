"""SQLAlchemy implementations of domain repository interfaces."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, case, distinct, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.models import (
    GameParticipant,
    GameRecord,
    RoundGuess,
    RoundRecord,
    User,
    Word,
    WordList,
    generate_uuid,
)
from app.repositories.interfaces import (
    AccountAlreadyClaimedError,
    GameDetail,
    GameHistoryRepository,
    GameParticipantInput,
    GameParticipantSummary,
    GameRecordInput,
    GameSummary,
    InvalidProfileDataError,
    RoundDetail,
    RoundGuessDetail,
    RoundGuessInput,
    RoundRecordInput,
    UserCredentials,
    UserData,
    UserRepository,
    UserStats,
    UsernameTakenError,
    WordListRepository,
    WordListSummary,
    WordStatsSummary,
)

MAX_PAGINATION_LIMIT = 100
DEFAULT_PAGINATION_LIMIT = 20


def _to_user_data(user: User) -> UserData:
    """Convert a database User entity to a public UserData DTO (without password_hash)."""
    return UserData(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        name_color=user.name_color,
        avatar_url=user.avatar_url,
        is_anonymous=user.is_anonymous,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def _to_word_list_summary(wl: WordList) -> WordListSummary:
    return WordListSummary(
        id=wl.id,
        slug=wl.slug,
        name=wl.name,
        description=wl.description,
        language=wl.language,
        word_count=wl.word_count,
        is_bundled=wl.is_bundled,
        version=wl.version,
    )


def _validate_avatar_url(url: str | None) -> str | None:
    if url is None:
        return None
    trimmed = url.strip()
    if not trimmed:
        return None
    lower = trimmed.lower()
    # Allow http, https, or root-relative paths only. Disallow control chars, quotes, and dangerous schemes.
    is_valid_scheme = lower.startswith("https://") or lower.startswith("http://") or lower.startswith("/")
    has_forbidden_chars = any(c in trimmed for c in ("\r", "\n", "<", ">", '"', "'"))
    if not is_valid_scheme or has_forbidden_chars or lower.startswith("javascript:") or lower.startswith("data:"):
        raise InvalidProfileDataError("Invalid avatar_url: must be a valid http/https or relative URL")
    return trimmed


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
                    id=user_id or generate_uuid(),
                    username=None,
                    password_hash=None,
                    # Left empty on purpose: "has no name yet" is what tells
                    # the client this is a first run. Nothing is invented for
                    # the player - they choose, or they sign up.
                    display_name=display_name.strip(),
                    name_color=name_color,
                    avatar_url=None,
                    is_anonymous=True,
                )
                session.add(user)
            await session.refresh(user)
            return _to_user_data(user)

    async def get_by_id(self, user_id: str) -> UserData | None:
        async with self._session_factory() as session:
            stmt = select(User).where(User.id == user_id)
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

        async with self._session_factory() as session:
            async with session.begin():
                # 1. Fetch user to claim
                stmt = select(User).where(User.id == user_id)
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
                        User.id != user_id,
                    )
                )
                existing_owner = (await session.execute(collision_stmt)).scalar_one_or_none()
                if existing_owner is not None:
                    raise UsernameTakenError(f"Username '{clean_username}' is already taken")

                user.username = clean_username
                user.password_hash = password_hash
                user.is_anonymous = False
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
        avatar_url: str | None = None,
    ) -> UserData | None:
        validated_avatar = _validate_avatar_url(avatar_url) if avatar_url is not None else None
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(User).where(User.id == user_id)
                result = await session.execute(stmt)
                user = result.scalar_one_or_none()
                if not user:
                    return None
                if display_name is not None:
                    user.display_name = display_name.strip() or user.display_name
                if name_color is not None:
                    user.name_color = name_color
                if avatar_url is not None:
                    user.avatar_url = validated_avatar
            await session.refresh(user)
            return _to_user_data(user)

    async def touch_last_login(
        self, user_id: str, min_interval_seconds: float = 0.0
    ) -> UserData | None:
        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(User).where(User.id == user_id)
                user = (await session.execute(stmt)).scalar_one_or_none()
                if not user:
                    return None
                now = datetime.now(timezone.utc)
                previous = user.last_login_at
                if previous is not None and previous.tzinfo is None:
                    # SQLite hands back naive datetimes; treat them as UTC so the
                    # comparison below does not raise on mixed awareness.
                    previous = previous.replace(tzinfo=timezone.utc)
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
        async with self._session_factory() as session:
            # 1. Games count, wins, and score
            part_stmt = select(
                func.count(GameParticipant.id).label("games_played"),
                func.coalesce(
                    func.sum(
                        case(
                            (GameParticipant.final_rank == 1, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("games_won"),
                func.coalesce(func.sum(GameParticipant.final_score), 0).label("total_score"),
            ).where(GameParticipant.user_id == user_id)
            part_res = (await session.execute(part_stmt)).one()
            games_played = int(part_res.games_played or 0)
            games_won = int(part_res.games_won or 0)
            total_score = int(part_res.total_score or 0)
            win_rate = (games_won / games_played) if games_played > 0 else 0.0
            average_score = (total_score / games_played) if games_played > 0 else 0.0

            # 2. Total rounds played across games where user participated
            rounds_stmt = (
                select(func.count(RoundRecord.id))
                .select_from(RoundRecord)
                .join(
                    GameParticipant,
                    and_(
                        GameParticipant.game_id == RoundRecord.game_id,
                        GameParticipant.user_id == user_id,
                    ),
                )
            )
            rounds_played = int((await session.execute(rounds_stmt)).scalar() or 0)

            # 3. Correct guesses made
            guesses_stmt = select(func.count(RoundGuess.id)).where(RoundGuess.user_id == user_id)
            words_guessed = int((await session.execute(guesses_stmt)).scalar() or 0)

            # 4. Drawings made
            drawings_stmt = select(func.count(RoundRecord.id)).where(RoundRecord.drawer_user_id == user_id)
            drawings_made = int((await session.execute(drawings_stmt)).scalar() or 0)

            return UserStats(
                user_id=user_id,
                games_played=games_played,
                games_won=games_won,
                win_rate=round(win_rate, 4),
                total_score=total_score,
                average_score=round(average_score, 2),
                rounds_played=rounds_played,
                words_guessed=words_guessed,
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
        rounds: list[RoundRecordInput],
        guesses: list[RoundGuessInput],
    ) -> str:
        record_id = game_record.id or generate_uuid()
        async with self._session_factory() as session:
            async with session.begin():
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
                    session.add(
                        GameParticipant(
                            id=generate_uuid(),
                            game_id=record_id,
                            user_id=p.user_id,
                            final_score=p.final_score,
                            final_rank=p.final_rank,
                        )
                    )

                created_round_ids: list[str] = []
                for r in rounds:
                    rid = r.id or generate_uuid()
                    created_round_ids.append(rid)
                    session.add(
                        RoundRecord(
                            id=rid,
                            game_id=record_id,
                            round_number=r.round_number,
                            turn_number=r.turn_number,
                            drawer_user_id=r.drawer_user_id,
                            word=r.word,
                            duration_seconds=r.duration_seconds,
                        )
                    )

                for g in guesses:
                    if not (0 <= g.round_index < len(created_round_ids)):
                        raise ValueError(
                            f"Invalid guess round_index {g.round_index}: out of bounds for {len(created_round_ids)} rounds"
                        )
                    target_round_id = created_round_ids[g.round_index]
                    session.add(
                        RoundGuess(
                            id=generate_uuid(),
                            round_id=target_round_id,
                            user_id=g.user_id,
                            points_awarded=g.points_awarded,
                            guess_time_seconds=g.guess_time_seconds,
                        )
                    )

        return record_id

    async def get_user_games(
        self,
        user_id: str,
        limit: int = DEFAULT_PAGINATION_LIMIT,
        offset: int = 0,
    ) -> list[GameSummary]:
        clamped_limit = max(1, min(limit, MAX_PAGINATION_LIMIT))
        clamped_offset = max(0, offset)

        async with self._session_factory() as session:
            # Find game IDs the user was a participant in
            user_games_subq = (
                select(GameParticipant.game_id)
                .where(GameParticipant.user_id == user_id)
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

            summaries: list[GameSummary] = []
            for g in games:
                part_summaries = [
                    GameParticipantSummary(
                        user_id=p.user_id,
                        display_name=p.user.display_name if p.user else "Unknown",
                        name_color=p.user.name_color if p.user else None,
                        is_anonymous=p.user.is_anonymous if p.user else True,
                        final_score=p.final_score,
                        final_rank=p.final_rank,
                    )
                    for p in sorted(g.participants, key=lambda x: x.final_rank)
                ]
                summaries.append(
                    GameSummary(
                        id=g.id,
                        room_name=g.room_name,
                        scoring_mode=g.scoring_mode,
                        hint_mode=g.hint_mode,
                        drawing_seconds=g.drawing_seconds,
                        total_rounds=g.total_rounds,
                        player_count=g.player_count,
                        started_at=g.started_at,
                        finished_at=g.finished_at,
                        participants=part_summaries,
                    )
                )
            return summaries

    async def get_game_detail(
        self,
        game_id: str,
        requesting_user_id: str | None = None,
    ) -> GameDetail | None:
        async with self._session_factory() as session:
            stmt = (
                select(GameRecord)
                .where(GameRecord.id == game_id)
                .options(
                    selectinload(GameRecord.participants).selectinload(GameParticipant.user),
                    selectinload(GameRecord.rounds).selectinload(RoundRecord.drawer),
                    selectinload(GameRecord.rounds).selectinload(RoundRecord.guesses).selectinload(RoundGuess.user),
                )
            )
            result = await session.execute(stmt)
            g = result.scalar_one_or_none()
            if not g:
                return None

            # Authorization scoping: If a requesting user is specified, ensure they participated in this game
            if requesting_user_id is not None:
                is_participant = any(p.user_id == requesting_user_id for p in g.participants)
                if not is_participant:
                    return None

            part_summaries = [
                GameParticipantSummary(
                    user_id=p.user_id,
                    display_name=p.user.display_name if p.user else "Unknown",
                    name_color=p.user.name_color if p.user else None,
                    is_anonymous=p.user.is_anonymous if p.user else True,
                    final_score=p.final_score,
                    final_rank=p.final_rank,
                )
                for p in sorted(g.participants, key=lambda x: x.final_rank)
            ]
            summary = GameSummary(
                id=g.id,
                room_name=g.room_name,
                scoring_mode=g.scoring_mode,
                hint_mode=g.hint_mode,
                drawing_seconds=g.drawing_seconds,
                total_rounds=g.total_rounds,
                player_count=g.player_count,
                started_at=g.started_at,
                finished_at=g.finished_at,
                participants=part_summaries,
            )

            round_details: list[RoundDetail] = []
            for r in sorted(g.rounds, key=lambda x: (x.round_number, x.turn_number)):
                guess_details = [
                    RoundGuessDetail(
                        user_id=guess.user_id,
                        display_name=guess.user.display_name if guess.user else "Unknown",
                        points_awarded=guess.points_awarded,
                        guess_time_seconds=guess.guess_time_seconds,
                    )
                    for guess in sorted(r.guesses, key=lambda x: x.guess_time_seconds)
                ]
                round_details.append(
                    RoundDetail(
                        round_number=r.round_number,
                        turn_number=r.turn_number,
                        drawer_user_id=r.drawer_user_id,
                        drawer_display_name=r.drawer.display_name if r.drawer else "Unknown",
                        word=r.word,
                        duration_seconds=r.duration_seconds,
                        guesses=guess_details,
                    )
                )

            return GameDetail(summary=summary, rounds=round_details)


class SqlAlchemyWordListRepository(WordListRepository):
    """SQLAlchemy-backed implementation of WordListRepository."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_all(self) -> list[WordListSummary]:
        async with self._session_factory() as session:
            stmt = select(WordList).order_by(WordList.name)
            result = await session.execute(stmt)
            return [_to_word_list_summary(wl) for wl in result.scalars().all()]

    async def get_by_slug(self, slug: str) -> WordListSummary | None:
        async with self._session_factory() as session:
            stmt = select(WordList).where(WordList.slug == slug)
            result = await session.execute(stmt)
            wl = result.scalar_one_or_none()
            return _to_word_list_summary(wl) if wl else None

    async def get_words(self, word_list_id: str) -> list[str]:
        async with self._session_factory() as session:
            stmt = select(Word.text).where(Word.word_list_id == word_list_id).order_by(Word.text)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_words_by_slugs(self, slugs: list[str]) -> list[str]:
        if not slugs:
            return []
        async with self._session_factory() as session:
            stmt = (
                select(distinct(Word.text))
                .join(WordList, Word.word_list_id == WordList.id)
                .where(WordList.slug.in_(slugs))
                .order_by(Word.text)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def upsert_bundled(
        self,
        slug: str,
        name: str,
        description: str,
        language: str,
        words: list[str],
        version: int,
    ) -> WordListSummary:
        # Deduplicate incoming words case-insensitively
        seen_words: set[str] = set()
        clean_words: list[str] = []
        for w in words:
            trimmed = w.strip()
            lower = trimmed.lower()
            if trimmed and lower not in seen_words:
                seen_words.add(lower)
                clean_words.append(lower)

        async with self._session_factory() as session:
            async with session.begin():
                stmt = select(WordList).where(WordList.slug == slug).options(selectinload(WordList.words))
                result = await session.execute(stmt)
                wl = result.scalar_one_or_none()

                if wl is None:
                    wl = WordList(
                        id=generate_uuid(),
                        slug=slug,
                        name=name,
                        description=description,
                        language=language,
                        word_count=len(clean_words),
                        is_bundled=True,
                        version=version,
                    )
                    session.add(wl)
                    for text in clean_words:
                        session.add(
                            Word(
                                id=generate_uuid(),
                                word_list_id=wl.id,
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
                    wl.word_count = len(clean_words)

                    existing_words_map = {w.text.lower(): w for w in wl.words}
                    target_set = set(clean_words)

                    # Remove deleted words
                    for old_text, word_obj in list(existing_words_map.items()):
                        if old_text not in target_set:
                            await session.delete(word_obj)

                    # Add new words
                    for text in clean_words:
                        if text not in existing_words_map:
                            session.add(
                                Word(
                                    id=generate_uuid(),
                                    word_list_id=wl.id,
                                    text=text,
                                    offer_count=0,
                                    pick_count=0,
                                    correct_guess_count=0,
                                    total_guesser_count=0,
                                )
                            )

            await session.refresh(wl)
            return _to_word_list_summary(wl)

    async def increment_word_offers(
        self,
        word_list_slug: str,
        word_texts: list[str],
    ) -> None:
        if not word_texts:
            return
        async with self._session_factory() as session:
            async with session.begin():
                wl_stmt = select(WordList.id).where(WordList.slug == word_list_slug)
                wl_id = (await session.execute(wl_stmt)).scalar_one_or_none()
                if not wl_id:
                    return

                lower_texts = [t.strip().lower() for t in word_texts]
                stmt = (
                    update(Word)
                    .where(
                        and_(
                            Word.word_list_id == wl_id,
                            Word.text.in_(lower_texts),
                        )
                    )
                    .values(offer_count=Word.offer_count + 1)
                )
                await session.execute(stmt)

    async def increment_word_stats(
        self,
        word_list_slug: str,
        word_text: str,
        correct_guesses: int,
        total_guessers: int,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                wl_stmt = select(WordList.id).where(WordList.slug == word_list_slug)
                wl_id = (await session.execute(wl_stmt)).scalar_one_or_none()
                if not wl_id:
                    return

                stmt = (
                    update(Word)
                    .where(
                        and_(
                            Word.word_list_id == wl_id,
                            Word.text == word_text.strip().lower(),
                        )
                    )
                    .values(
                        pick_count=Word.pick_count + 1,
                        correct_guess_count=Word.correct_guess_count + correct_guesses,
                        total_guesser_count=Word.total_guesser_count + total_guessers,
                    )
                )
                await session.execute(stmt)

    async def get_word_stats(
        self,
        word_list_slug: str,
    ) -> list[WordStatsSummary]:
        async with self._session_factory() as session:
            stmt = (
                select(Word)
                .join(WordList, Word.word_list_id == WordList.id)
                .where(WordList.slug == word_list_slug)
                .order_by(Word.text)
            )
            result = await session.execute(stmt)
            words = result.scalars().all()

            summaries: list[WordStatsSummary] = []
            for w in words:
                pick_rate = (w.pick_count / w.offer_count) if w.offer_count > 0 else 0.0
                ratio = (w.correct_guess_count / w.total_guesser_count) if w.total_guesser_count > 0 else 0.0
                summaries.append(
                    WordStatsSummary(
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

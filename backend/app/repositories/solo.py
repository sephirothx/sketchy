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

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.db.models import (
    GameParticipant,
    IdentityAlias,
    PromptAlias,
    PromptVersion,
    PromptVersionAlias,
    SoloPoolEntry,
    SoloRun,
    SoloServe,
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
from app.prompt_content import prompt_match_variants
from app.repositories.interfaces import TurnDrawingDetail
from app.solo_rules import (
    MAX_OPEN_SERVES,
    SAMPLE_KEY_SPACE,
    SOLO_CONTENT_RATING,
    SOLVED,
    encode_answers,
    points_for,
    run_is_over,
)


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
    # Correlated to the pool row itself, never to the EXISTS it sits in:
    # left to auto-correlation it ran once over the whole pool, refused two
    # merged drawers on PostgreSQL ("more than one row") and pinned one
    # account's opt-out on every row (#1491 review).
    canonical_drawer = func.coalesce(
        select(IdentityAlias.target_user_id)
        .where(IdentityAlias.source_user_id == SoloPoolEntry.drawer_user_id)
        .correlate(SoloPoolEntry)
        .scalar_subquery(),
        SoloPoolEntry.drawer_user_id,
    )
    return (
        exists().where(
            TurnDrawing.turn_id == SoloPoolEntry.turn_id,
            # Kept, by whatever stores it (`ck_turn_drawings_ready_identity`):
            # the door reads the bytes, and answers 404 if there are none. An
            # administrator's erasure is `deleted` by its own CHECK.
            TurnDrawing.status == TurnDrawingStatus.READY.value,
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


@dataclass(frozen=True)
class ServeView:
    """A drawing served, as its player's client sees it: its own id, never
    the turn's, and the answer forms it is judged by, encoded
    (`solo_rules.encode_answers`). Settled serves say what they came to."""

    serve_id: str
    position: int
    forms: str
    outcome: str | None = None
    points: int | None = None
    prompt: str | None = None
    prompt_language: str | None = None


@dataclass(frozen=True)
class RunView:
    run_id: str
    mode: str
    length: int | None
    state: str
    end_reason: str | None
    position: int
    solved: int
    points: int
    daily_date: str | None
    serves: tuple[ServeView, ...] = ()


class SoloRefused(Exception):
    """A Solo write that cannot apply: `missing` for a run or serve that is
    not the caller's (always a 404 outside), `conflict` for one whose state
    refuses it, `empty` when there is nothing left to serve."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class AnswerForms:
    """What a serve is judged by: the JSON `guess_judge.JudgeTarget` is built
    from, and the answer the player is shown when it is over."""

    target: dict
    prompt: str
    language: str

    def encoded(self, serve_id) -> str:
        return encode_answers(serve_id, json.dumps(self.target, ensure_ascii=False))


def _run_view(run: SoloRun, serves: Sequence[SoloServe], forms: dict) -> RunView:
    return RunView(
        run_id=str(run.id),
        mode=run.mode,
        length=run.length,
        state=run.state,
        end_reason=run.end_reason,
        position=run.position,
        solved=run.solved,
        points=run.points,
        daily_date=run.daily_date.isoformat() if run.daily_date else None,
        serves=tuple(_serve_view(serve, forms.get(serve.id)) for serve in serves),
    )


def _serve_view(serve: SoloServe, encoded: str | None) -> ServeView:
    settled = serve.outcome is not None
    return ServeView(
        serve_id=str(serve.id),
        position=serve.position,
        forms=encoded or "",
        outcome=serve.outcome,
        points=serve.points,
        prompt=serve.prompt if settled else None,
        prompt_language=serve.prompt_language if settled else None,
    )


async def answer_forms(
    session: AsyncSession, concept_id: UUID, languages: Sequence[str]
) -> AnswerForms | None:
    """The concept as this player guesses it (#1434): right in any of their
    play languages.

    An agnostic version (`zxx`) is the one answer in every fold. Otherwise
    the player's first-ranked language that has the concept is their own -
    what they are shown at the end - and the rest are the others, each folded
    its own way. A spelling of another language that is a different concept
    in the player's own is taken out (#1367's false-friend guard): German
    "Hut" is a hat, and must not win an English hut.
    """
    rows = (
        await session.execute(
            select(PromptVersion.id, PromptVersion.language, PromptVersion.canonical_answer)
            .where(
                PromptVersion.concept_id == concept_id,
                PromptVersion.language.in_([*languages, AGNOSTIC_PROMPT_LANGUAGE]),
                _playable_version(PromptVersion),
            )
            .order_by(PromptVersion.language, PromptVersion.version.desc())
        )
    ).all()
    newest: dict[str, tuple[UUID, str]] = {}
    for version_id, language, text in rows:
        newest.setdefault(language, (version_id, text))
    if not newest:
        return None
    alias_rows = (
        await session.execute(
            select(PromptVersionAlias.prompt_version_id, PromptAlias.answer)
            .join(PromptAlias, PromptAlias.id == PromptVersionAlias.alias_id)
            .where(PromptVersionAlias.prompt_version_id.in_([v for v, _ in newest.values()]))
            .order_by(PromptAlias.answer)
        )
    ).all()
    aliases: dict[UUID, list[str]] = {}
    for version_id, text in alias_rows:
        aliases.setdefault(version_id, []).append(text)

    def form(language: str) -> dict:
        version_id, text = newest[language]
        return {"prompt": text, "aliases": aliases.get(version_id, [])}

    if AGNOSTIC_PROMPT_LANGUAGE in newest:
        own = form(AGNOSTIC_PROMPT_LANGUAGE)
        target = {"language": languages[0], "own": own, "others": {}, "taken": []}
        return AnswerForms(target, own["prompt"], AGNOSTIC_PROMPT_LANGUAGE)
    ranked = [language for language in languages if language in newest]
    own_language, other_languages = ranked[0], ranked[1:]
    others = {language: form(language) for language in other_languages}
    candidates = {
        spelling
        for language, other in others.items()
        for text in (other["prompt"], *other["aliases"])
        for spelling in prompt_match_variants(text, language)
    }
    taken: set[str] = set()
    if candidates:
        # Every version counts, hidden ones too, as in a mixed room: a
        # hidden word still means what it means to the player.
        meanings = (
            await session.execute(
                select(PromptVersion.canonical_answer).where(
                    PromptVersion.language == own_language,
                    PromptVersion.concept_id != concept_id,
                    PromptVersion.match_key.in_(candidates),
                )
                .union(
                    select(PromptAlias.answer).where(
                        PromptAlias.language == own_language,
                        PromptAlias.concept_id != concept_id,
                        PromptAlias.match_key.in_(candidates),
                    )
                )
            )
        ).scalars().all()
        for text in meanings:
            taken |= prompt_match_variants(text, own_language) & candidates
    own = form(own_language)
    target = {
        "language": own_language,
        "own": own,
        "others": others,
        "taken": sorted(taken),
    }
    return AnswerForms(target, own["prompt"], own_language)


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

    # --- runs -------------------------------------------------------------

    async def start_free_run(self, user_id: str, *, length: int | None, now: datetime) -> RunView:
        """A new free run, abandoning the one in play (#1434): a 5 or 10 run
        left unfinished records nothing; an unlimited one ends at the streak
        it reached, which is a result like any other."""
        for attempt in range(2):
            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        player = (await identity_ids(session, UUID(user_id)))[0]
                        active = await session.scalar(
                            select(SoloRun)
                            .where(
                                SoloRun.user_id == player,
                                SoloRun.mode == "free",
                                SoloRun.state == "active",
                            )
                            .with_for_update()
                        )
                        if active is not None:
                            await self._abandon(session, active, now=now)
                        run = SoloRun(
                            user_id=player, mode="free", length=length, state="active",
                            position=0, solved=0, points=0, started_at=now,
                        )
                        session.add(run)
                        await session.flush()
                        return _run_view(run, (), {})
            except IntegrityError:
                # Two starts at once: the other one's run is in play now, and
                # this one abandons it on the retry.
                if attempt:
                    raise SoloRefused("conflict") from None
        raise SoloRefused("conflict")

    async def _abandon(self, session: AsyncSession, run: SoloRun, *, now: datetime) -> None:
        unlimited = run.length is None
        run.state = "ended" if unlimited else "abandoned"
        run.end_reason = "abandoned"
        run.ended_at = now
        await self._drop_open_serves(session, run.id)

    async def _drop_open_serves(self, session: AsyncSession, run_id: UUID) -> None:
        """Serves fetched ahead and never settled go with a run that ends:
        a drawing the player never saw is not one they were served."""
        await session.execute(
            delete(SoloServe).where(SoloServe.run_id == run_id, SoloServe.settled_at.is_(None))
        )

    async def active_free_run(self, user_id: str) -> RunView | None:
        """The free run a player can continue, with what it served."""
        async with self._session_factory() as session:
            player = (await identity_ids(session, UUID(user_id)))[0]
            run = await session.scalar(
                select(SoloRun).where(
                    SoloRun.user_id == player, SoloRun.mode == "free", SoloRun.state == "active"
                )
            )
            if run is None:
                return None
            return await self._view_with_serves(session, run, player)

    async def get_run(self, user_id: str, run_id: str) -> RunView:
        async with self._session_factory() as session:
            player = (await identity_ids(session, UUID(user_id)))[0]
            run = await session.get(SoloRun, _uuid(run_id))
            if run is None or run.user_id != player:
                raise SoloRefused("missing")
            return await self._view_with_serves(session, run, player)

    async def _view_with_serves(self, session: AsyncSession, run: SoloRun, player: UUID) -> RunView:
        serves = (
            await session.scalars(
                select(SoloServe).where(SoloServe.run_id == run.id).order_by(SoloServe.position)
            )
        ).all()
        forms: dict[UUID, str] = {}
        open_serves = [serve for serve in serves if serve.outcome is None]
        if open_serves:
            languages = await play_languages(session, player)
            concepts = dict(
                (
                    await session.execute(
                        select(SoloPoolEntry.turn_id, SoloPoolEntry.concept_id).where(
                            SoloPoolEntry.turn_id.in_([serve.turn_id for serve in open_serves])
                        )
                    )
                ).all()
            )
            for serve in open_serves:
                concept = concepts.get(serve.turn_id)
                found = (
                    await answer_forms(session, concept, languages or (serve.prompt_language,))
                    if concept is not None
                    else None
                )
                if found is not None:
                    forms[serve.id] = found.encoded(serve.id)
        return _run_view(run, serves, forms)

    async def serve_next(
        self, user_id: str, run_id: str, *, count: int, now: datetime
    ) -> list[ServeView]:
        """Serve up to `count` more drawings in a free run, so the client can
        hold one ahead: never more than `MAX_OPEN_SERVES` unsettled, never
        past a finite run's length."""
        async with self._session_factory() as session:
            async with session.begin():
                ids = await identity_ids(session, UUID(user_id))
                player = ids[0]
                run = await session.scalar(
                    select(SoloRun).where(SoloRun.id == _uuid(run_id)).with_for_update()
                )
                if run is None or run.user_id != player or run.mode != "free":
                    raise SoloRefused("missing")
                if run.state != "active":
                    raise SoloRefused("conflict")
                languages = await play_languages(session, player)
                if not languages:
                    raise SoloRefused("missing")
                open_count = await session.scalar(
                    select(func.count()).where(
                        SoloServe.run_id == run.id, SoloServe.settled_at.is_(None)
                    )
                )
                room = MAX_OPEN_SERVES - int(open_count or 0)
                if run.length is not None:
                    room = min(room, run.length - run.position)
                served: list[ServeView] = []
                for _ in range(max(0, min(count, room))):
                    picked = await self._pick(session, ids, languages, run.id)
                    if picked is None:
                        break
                    turn_id, forms = picked
                    run.position += 1
                    serve = SoloServe(
                        run_id=run.id, user_id=player, turn_id=turn_id, position=run.position,
                        prompt=forms.prompt, prompt_language=forms.language, served_at=now,
                    )
                    session.add(serve)
                    await session.flush()
                    served.append(_serve_view(serve, forms.encoded(serve.id)))
                if not served and room > 0:
                    raise SoloRefused("empty")
                return served

    async def _pick(
        self,
        session: AsyncSession,
        ids: Sequence[UUID],
        languages: Sequence[str],
        run_id: UUID,
    ) -> tuple[UUID, AnswerForms] | None:
        """One drawing for a free run: unseen first, in the pool's random
        order from a random point, wrapping round once; once the player has
        seen every drawing they may be served, the one they saw longest ago -
        one this run has not served, while there is one (#1434: a thin pool
        repeats).

        Two bounded index walks on `sample_key`, never a sort of the pool."""
        player = ids[0]
        seen = exists().where(SoloServe.user_id == player, SoloServe.turn_id == SoloPoolEntry.turn_id)
        base = select(SoloPoolEntry.turn_id, SoloPoolEntry.concept_id).where(
            *servable_clauses(), *servable_to_clauses(ids, languages)
        )
        start = random.randrange(SAMPLE_KEY_SPACE)
        for window in (SoloPoolEntry.sample_key >= start, SoloPoolEntry.sample_key < start):
            row = (
                await session.execute(
                    base.where(window, ~seen).order_by(SoloPoolEntry.sample_key).limit(1)
                )
            ).first()
            if row is not None:
                forms = await answer_forms(session, row.concept_id, languages)
                if forms is not None:
                    return row.turn_id, forms
        last_seen = (
            select(SoloServe.turn_id, func.max(SoloServe.served_at).label("at"))
            .where(SoloServe.user_id == player)
            .group_by(SoloServe.turn_id)
            .subquery()
        )
        in_run = exists().where(SoloServe.run_id == run_id, SoloServe.turn_id == SoloPoolEntry.turn_id)
        repeat = base.join(last_seen, last_seen.c.turn_id == SoloPoolEntry.turn_id).order_by(
            last_seen.c.at, SoloPoolEntry.sample_key
        )
        # One this run has not served yet, if there is one; a pool smaller
        # than the run repeats within it too, rather than end it early.
        for statement in (repeat.where(~in_run), repeat):
            row = (await session.execute(statement.limit(1))).first()
            if row is not None:
                forms = await answer_forms(session, row.concept_id, languages)
                if forms is not None:
                    return row.turn_id, forms
        return None

    async def settle(
        self,
        user_id: str,
        serve_id: str,
        *,
        outcome: str,
        seconds: float,
        now: datetime,
    ) -> tuple[ServeView, RunView]:
        """Record what a served drawing came to, once (#1434: play is local,
        so this is the client's word). The server bounds the time and derives
        the points; a run settles in order, and ends with its last drawing or,
        unlimited, its first miss."""
        async with self._session_factory() as session:
            async with session.begin():
                player = (await identity_ids(session, UUID(user_id)))[0]
                serve = await session.get(SoloServe, _uuid(serve_id))
                if serve is None or serve.user_id != player:
                    raise SoloRefused("missing")
                run = await session.scalar(
                    select(SoloRun).where(SoloRun.id == serve.run_id).with_for_update()
                )
                await session.refresh(serve)
                if serve.outcome is not None or run.state != "active":
                    raise SoloRefused("conflict")
                earlier_open = await session.scalar(
                    select(func.count()).where(
                        SoloServe.run_id == run.id,
                        SoloServe.position < serve.position,
                        SoloServe.settled_at.is_(None),
                    )
                )
                if earlier_open:
                    raise SoloRefused("conflict")
                bounded = min(max(float(seconds), 0.0), 30.0)
                serve.outcome = outcome
                serve.settled_at = now
                serve.solve_seconds = bounded
                serve.points = points_for(bounded) if outcome == SOLVED else None
                if outcome == SOLVED:
                    run.solved += 1
                    run.points += serve.points
                settled = int(
                    await session.scalar(
                        select(func.count()).where(
                            SoloServe.run_id == run.id, SoloServe.settled_at.is_not(None)
                        )
                    )
                    or 0
                )
                if run_is_over(run.length, settled=settled, missed=outcome != SOLVED):
                    run.state = "ended"
                    run.end_reason = "completed" if run.length is not None else "missed"
                    run.ended_at = now
                    await session.flush()
                    await self._drop_open_serves(session, run.id)
                await session.flush()
                serves = (
                    await session.scalars(
                        select(SoloServe).where(SoloServe.run_id == run.id).order_by(SoloServe.position)
                    )
                ).all()
                return _serve_view(serve, None), _run_view(run, serves, {})

    # --- the fourth drawing door (R-HIST-16) -------------------------------

    def _served_drawing(self, player_ids: Sequence[UUID], serve_id: UUID, *columns):
        """A served drawing the player may still see: their serve, and the
        drawing still servable to anybody - a hide, a take-out, an opt-out or
        an erasure closes the door at once, as on every other door.

        The row read is an alias, so the servable clauses' own subquery over
        `turn_drawings` stays a subquery rather than correlating to it."""
        drawing = aliased(TurnDrawing)
        return (
            select(*(getattr(drawing, name) for name in columns))
            .join(SoloServe, SoloServe.turn_id == drawing.turn_id)
            .join(SoloPoolEntry, SoloPoolEntry.turn_id == SoloServe.turn_id)
            .where(
                SoloServe.id == serve_id,
                SoloServe.user_id.in_(list(player_ids)),
                *servable_clauses(),
            )
        )

    async def served_drawing(self, user_id: str, serve_id: str) -> TurnDrawingDetail | None:
        serve = _optional_uuid(serve_id)
        if serve is None:
            return None
        async with self._session_factory() as session:
            ids = await identity_ids(session, UUID(user_id))
            row = (
                await session.execute(
                    self._served_drawing(ids, serve, "turn_id", "payload", "checksum_sha256")
                )
            ).first()
        if row is None or row.payload is None:
            return None
        return TurnDrawingDetail(
            turn_id=str(row.turn_id), payload=row.payload, checksum_sha256=row.checksum_sha256 or ""
        )

    async def served_drawing_checksum(self, user_id: str, serve_id: str) -> str | None:
        """The served drawing's checksum, by the same query and no blob."""
        serve = _optional_uuid(serve_id)
        if serve is None:
            return None
        async with self._session_factory() as session:
            ids = await identity_ids(session, UUID(user_id))
            checksum = await session.scalar(self._served_drawing(ids, serve, "checksum_sha256"))
        return checksum or None


def _optional_uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _uuid(value: str) -> UUID:
    parsed = _optional_uuid(value)
    if parsed is None:
        raise SoloRefused("missing")
    return parsed

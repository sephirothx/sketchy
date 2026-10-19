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
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select, text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.auth.erasure import AccountErasedError, require_live_account
from app.db.models import (
    SOLO_DAILY_CANDIDATE,
    GameParticipant,
    IdentityAlias,
    Prompt,
    PromptAlias,
    PromptList,
    PromptVersion,
    PromptVersionAlias,
    SoloBest,
    SoloDailyDay,
    SoloDailyConcept,
    SoloDailyResult,
    SoloDailySet,
    SoloPoolEntry,
    SoloRun,
    SoloServe,
    TurnDrawing,
    User,
    UserSettings,
)
from app.domain_values import (
    AGNOSTIC_PROMPT_LANGUAGE,
    PROMPT_LANGUAGES,
    AccountState,
    PromptContentModerationState,
    PromptLanguage,
    TurnDrawingStatus,
)
from app.prompt_content import prompt_match_variants
from app.repositories.interfaces import TurnDrawingDetail
from app.solo_rules import (
    DAILY_LENGTH,
    DAILY_REUSE_DAYS,
    SKIPPED_RETRY,
    MAX_OPEN_SERVES,
    SAMPLE_KEY_SPACE,
    SOLO_CONTENT_RATING,
    SOLVED,
    daily_start_key,
    daily_streak,
    longest_daily_streak,
    date_is_open,
    encode_answers,
    open_dates,
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


def _in_official_list(version):
    """A version some official (bundled) list plays. The official catalogue
    is what every language's wording of a concept is read from: a player's
    own list rewording a concept in a private working copy - unmoderated,
    unpublished - must not become what strangers are judged against
    (#1492 review)."""
    return exists().where(
        Prompt.prompt_version_id == version.id,
        Prompt.prompt_list_id == PromptList.id,
        PromptList.is_bundled.is_(True),
    )


def offerable_version(version, drawn_version_id):
    """A version Solo may judge a guess against and show at the end: playable,
    and either the very one the drawer drew or one in an official list."""
    return and_(
        _playable_version(version),
        or_(version.id == drawn_version_id, _in_official_list(version)),
    )


def servable_to_clauses(identity_ids: Sequence[UUID], languages: Sequence[str]) -> tuple:
    """What a pool row must also be for this player: from a game none of
    their identities sat in, and a concept with an offerable version they can
    guess - in one of their play languages, or in none at all (`zxx`)."""
    offered = aliased(PromptVersion)
    return (
        ~exists().where(
            GameParticipant.game_id == SoloPoolEntry.game_id,
            GameParticipant.user_id.in_(list(identity_ids)),
        ),
        exists().where(
            offered.concept_id == SoloPoolEntry.concept_id,
            offered.language.in_([*languages, AGNOSTIC_PROMPT_LANGUAGE]),
            offerable_version(offered, SoloPoolEntry.prompt_version_id),
        ),
    )


async def require_live_player(session: AsyncSession, user_id: str) -> None:
    """Refuse, inside a Solo write's own transaction, an account deleted
    since its request was let in (R-PRIV-15): the route's check is before
    the transaction, and a deletion that commits in between leaves the user
    row as a tombstone that an insert would happily point at. The row is read
    under a share lock, so a deletion in progress is waited for, never raced.
    Every Solo write that adds to what the player owns asks this first."""
    try:
        await require_live_account(session, user_id)
    except AccountErasedError:
        raise SoloRefused("erased") from None


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
    if row is not None:
        return (row[0], *row[1])
    # A registered account with no settings row yet plays the default, as
    # its settings would say once written (R-PROMPT-11).
    registered = await session.scalar(
        select(User.id).where(User.id == user_id, User.state == AccountState.REGISTERED.value)
    )
    return (PromptLanguage.ENGLISH.value,) if registered is not None else ()


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
    refuses it, `empty` when there is nothing left to serve, `erased` for an
    account deleted since the request was let in."""

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

    def text(self) -> str:
        return json.dumps(self.target, ensure_ascii=False)


def _run_view(run: SoloRun, serves: Sequence[SoloServe]) -> RunView:
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
        serves=tuple(_serve_view(serve) for serve in serves),
    )


def _serve_view(serve: SoloServe) -> ServeView:
    settled = serve.outcome is not None
    return ServeView(
        serve_id=str(serve.id),
        position=serve.position,
        # Only while it is open: once settled, the prompt is said plainly.
        forms="" if settled else encode_answers(serve.id, serve.forms),
        outcome=serve.outcome,
        points=serve.points,
        prompt=serve.prompt if settled else None,
        prompt_language=serve.prompt_language if settled else None,
    )


class OfficialMeanings:
    """What each spelling means in each language's official lists, for the
    false-friend guard (#1367): language -> spelling -> concepts.

    By every spelling `prompt_match_variants` accepts, not the stored key - a
    guess is accepted on those, and German "Lüge" is "luge" too, the French
    sled, which the canonical key `luege` never meets (#1492 review). Hidden
    versions count, as in a mixed room: a hidden word still means what it
    means. A text in no language (`zxx`) is every language's word too. Read
    once per language and kept for `TTL_SECONDS`: the official catalogue is
    seeded with a deploy, not edited while one runs.
    """

    TTL_SECONDS = 600.0

    def __init__(self) -> None:
        self._by_language: dict[str, tuple[float, dict[str, frozenset[UUID]]]] = {}

    async def of(self, session: AsyncSession, language: str) -> dict[str, frozenset[UUID]]:
        now = time.monotonic()
        held = self._by_language.get(language)
        if held is not None and now - held[0] < self.TTL_SECONDS:
            return held[1]
        official = (
            select(Prompt.prompt_version_id)
            .join(PromptList, PromptList.id == Prompt.prompt_list_id)
            .where(PromptList.is_bundled.is_(True))
        )
        in_language = PromptVersion.language.in_([language, AGNOSTIC_PROMPT_LANGUAGE])
        rows = (
            await session.execute(
                select(PromptVersion.concept_id, PromptVersion.canonical_answer)
                .where(in_language, PromptVersion.id.in_(official))
                .union_all(
                    select(PromptVersion.concept_id, PromptAlias.answer)
                    .join(PromptVersionAlias, PromptVersionAlias.prompt_version_id == PromptVersion.id)
                    .join(PromptAlias, PromptAlias.id == PromptVersionAlias.alias_id)
                    .where(in_language, PromptVersion.id.in_(official))
                )
            )
        ).all()
        owners: dict[str, set[UUID]] = {}
        for concept, text in rows:
            for spelling in prompt_match_variants(text, language):
                owners.setdefault(spelling, set()).add(concept)
        found = {spelling: frozenset(concepts) for spelling, concepts in owners.items()}
        self._by_language[language] = (now, found)
        return found


async def answer_forms(
    session: AsyncSession,
    concept_id: UUID,
    languages: Sequence[str],
    *,
    drawn_version_id: UUID | None,
    meanings: OfficialMeanings,
) -> AnswerForms | None:
    """The concept as this player guesses it (#1434): right in any of their
    play languages.

    Each language's wording is the version the drawer drew, in its language,
    and otherwise the newest version an official list plays - never a
    player's private rewording (#1492 review). An agnostic version (`zxx`) is
    the one answer in every fold. Otherwise the player's first-ranked
    language that has the concept is their own - what they are shown at the
    end - and the rest are the others, each folded its own way. A spelling of
    another language that is a different concept in the player's own official
    lists is taken out (#1367's false-friend guard): German "Hut" is a hat,
    and must not win an English hut.
    """
    rows = (
        await session.execute(
            select(PromptVersion.id, PromptVersion.language, PromptVersion.canonical_answer)
            .where(
                PromptVersion.concept_id == concept_id,
                PromptVersion.language.in_([*languages, AGNOSTIC_PROMPT_LANGUAGE]),
                offerable_version(PromptVersion, drawn_version_id),
            )
            .order_by(PromptVersion.language, PromptVersion.version.desc())
        )
    ).all()
    newest: dict[str, tuple[UUID, str]] = {}
    for version_id, language, text in rows:
        if version_id == drawn_version_id:
            newest[language] = (version_id, text)
        else:
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
    taken: set[str] = set()
    if others:
        meaning = await meanings.of(session, own_language)
        for language, other in others.items():
            for text in (other["prompt"], *other["aliases"]):
                for spelling in prompt_match_variants(text, language):
                    if meaning.get(spelling, frozenset()) - {concept_id}:
                        taken.add(spelling)
    own = form(own_language)
    target = {
        "language": own_language,
        "own": own,
        "others": others,
        "taken": sorted(taken),
    }
    return AnswerForms(target, own["prompt"], own_language)


def daily_result_payload(result: SoloDailyResult) -> dict:
    """A Daily as the page shows it and the copied result is written from."""
    return {
        "date": result.daily_date.isoformat(),
        "positionsPlayed": result.positions_played,
        "solved": result.solved,
        "points": result.points,
        "completed": result.completed_at is not None,
        "marks": [
            {"outcome": mark["outcome"], "seconds": mark["seconds"], "late": mark["late"]}
            for mark in result.marks
        ],
    }


def _month_end(first: date) -> date:
    """The last date of `first`'s month."""
    following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return following - timedelta(days=1)


def _length_key(length: int | None) -> str:
    return "unlimited" if length is None else str(length)


def run_best(run: SoloRun) -> int | None:
    """What a free run counts for, or None if it counts for nothing: points
    for a 5 or 10 run that was finished, drawings named for an unlimited one
    however it ended (#1434). Nothing named, nothing scored, is no best: a
    best of 0 is only a run that went nowhere."""
    if run.mode != "free" or run.state != "ended":
        return None
    value = run.solved if run.length is None else (
        run.points if run.end_reason == "completed" else None
    )
    return value or None


async def _raise_best(session: AsyncSession, run: SoloRun, *, now: datetime) -> None:
    """Raise the player's best for the run's length if the run beat it, in
    the transaction that ended the run. A best is never lowered."""
    value = run_best(run)
    if value is None:
        return
    key = _length_key(run.length)
    best = await session.get(SoloBest, (run.user_id, key), with_for_update=True)
    if best is None:
        session.add(
            SoloBest(user_id=run.user_id, length_key=key, best=value, run_id=run.id, achieved_at=now)
        )
    elif value > best.best:
        best.best, best.run_id, best.achieved_at = value, run.id, now


async def rebuild_bests(session: AsyncSession) -> int:
    """Every player's bests again from their ended free runs: the projection's
    rebuild (`python -m app.services.solo_pool --bests`)."""
    await session.execute(delete(SoloBest))
    runs = (
        await session.scalars(
            select(SoloRun)
            .where(SoloRun.mode == "free", SoloRun.state == "ended")
            .order_by(SoloRun.ended_at, SoloRun.id)
        )
    ).all()
    found: dict[tuple[UUID, str], SoloBest] = {}
    for run in runs:
        value = run_best(run)
        if value is None:
            continue
        key = (run.user_id, _length_key(run.length))
        best = found.get(key)
        if best is None:
            found[key] = SoloBest(
                user_id=run.user_id, length_key=key[1], best=value, run_id=run.id,
                achieved_at=run.ended_at,
            )
        elif value > best.best:
            best.best, best.run_id, best.achieved_at = value, run.id, run.ended_at
    session.add_all(found.values())
    return len(found)


async def _record_daily(session: AsyncSession, run: SoloRun, serve: SoloServe, *, now: datetime) -> None:
    """Add a settled drawing to the player's Daily for its date (#1434): the
    result row is written by the first and grows with each, so a Daily left
    half played keeps what was played. A drawing played after the date had
    ended everywhere - from the archive - is marked `late`."""
    result = await session.get(
        SoloDailyResult, (run.user_id, run.daily_date), with_for_update=True
    )
    if result is None:
        result = SoloDailyResult(
            user_id=run.user_id,
            daily_date=run.daily_date,
            run_id=run.id,
            positions_played=0,
            solved=0,
            points=0,
            marks=[],
            started_on_date=date_is_open(run.daily_date, now),
            started_at=now,
        )
        session.add(result)
    mark = {
        "position": serve.position,
        "outcome": serve.outcome,
        "seconds": serve.solve_seconds,
        "late": not date_is_open(run.daily_date, now),
    }
    result.marks = [*result.marks, mark]
    result.positions_played += 1
    if serve.outcome == SOLVED:
        result.solved += 1
        result.points += serve.points or 0
    if result.positions_played >= DAILY_LENGTH:
        result.completed_at = now


def _all_languages_or_agnostic():
    """A concept every player can be asked to name: a playable version in
    all eight languages, or an agnostic one (#1434: the Daily is the same
    for everybody, in every language)."""
    version = aliased(PromptVersion)
    in_every_language = (
        select(func.count(func.distinct(version.language)))
        .where(
            version.concept_id == SoloPoolEntry.concept_id,
            version.language.in_(PROMPT_LANGUAGES),
            offerable_version(version, SoloPoolEntry.prompt_version_id),
        )
        .correlate(SoloPoolEntry)
        .scalar_subquery()
    )
    agnostic = aliased(PromptVersion)
    return or_(
        in_every_language == len(PROMPT_LANGUAGES),
        exists().where(
            agnostic.concept_id == SoloPoolEntry.concept_id,
            agnostic.language == AGNOSTIC_PROMPT_LANGUAGE,
            offerable_version(agnostic, SoloPoolEntry.prompt_version_id),
        ),
    )


# How many candidate rows the Daily's walk reads at a time, and at most.
DAILY_WALK_CHUNK = 200
DAILY_WALK_LIMIT = 4000


async def pick_daily(
    session: AsyncSession,
    day: date,
    *,
    count: int,
    exclude_concepts: Sequence[UUID] = (),
    start: int | None = None,
) -> list[tuple[UUID, UUID, float]]:
    """Up to `count` drawings for `day`'s Daily, as (turn, concept, solve
    rate): from the pool's Daily candidates, servable to anybody, a concept
    every player can name, not already in the Gallery (a stranger may have
    seen it there, prompt and all), and no concept a Daily used within
    `DAILY_REUSE_DAYS` of `day`. Deterministic: a walk of the partial index
    from the date's own starting key, wrapping round once, the same for
    every request."""
    start = daily_start_key(day) if start is None else start
    window = and_(
        SoloDailyConcept.daily_date > day - timedelta(days=DAILY_REUSE_DAYS),
        SoloDailyConcept.daily_date < day + timedelta(days=DAILY_REUSE_DAYS),
    )
    # Every concept a Daily held, replacements and what they replaced
    # included: each was that day's for whoever played it then (#1493 review).
    reused = select(SoloDailyConcept.concept_id).where(window).scalar_subquery()
    shared = exists().where(
        TurnDrawing.turn_id == SoloPoolEntry.turn_id, TurnDrawing.gallery_share_count > 0
    )
    base = select(
        SoloPoolEntry.turn_id,
        SoloPoolEntry.concept_id,
        SoloPoolEntry.correct_count,
        SoloPoolEntry.guesser_count,
        SoloPoolEntry.sample_key,
    ).where(
        sql_text(SOLO_DAILY_CANDIDATE),
        *servable_clauses(),
        _all_languages_or_agnostic(),
        ~shared,
        SoloPoolEntry.concept_id.not_in(reused),
        SoloPoolEntry.concept_id.not_in(list(exclude_concepts)),
    )
    chosen: dict[UUID, tuple[UUID, UUID, float, int]] = {}
    for low, high in ((start, None), (0, start)):
        after = low - 1
        read = 0
        while len(chosen) < count and read < DAILY_WALK_LIMIT:
            statement = base.where(SoloPoolEntry.sample_key > after)
            if high is not None:
                statement = statement.where(SoloPoolEntry.sample_key < high)
            rows = (
                await session.execute(
                    statement.order_by(SoloPoolEntry.sample_key).limit(DAILY_WALK_CHUNK)
                )
            ).all()
            if not rows:
                break
            read += len(rows)
            for row in rows:
                if row.concept_id not in chosen and len(chosen) < count:
                    rate = row.correct_count / row.guesser_count
                    chosen[row.concept_id] = (row.turn_id, row.concept_id, rate, row.sample_key)
            after = rows[-1].sample_key
        if len(chosen) >= count:
            break
    # Easiest first: the solve rate of the game it came from.
    ordered = sorted(chosen.values(), key=lambda item: (-item[2], item[3]))
    return [(turn, concept, rate) for turn, concept, rate, _ in ordered]


def _servable_set_rows(rows: Sequence[SoloDailySet]):
    """The set rows whose drawing a Daily may still play for everybody: still
    servable (R-SOLO-02), and its concept still nameable in every language -
    a takedown of one language's wording would leave that language's
    players a position they could never be served (#1493 review)."""
    return select(SoloPoolEntry.turn_id).where(
        SoloPoolEntry.turn_id.in_([row.turn_id for row in rows]),
        *servable_clauses(),
        _all_languages_or_agnostic(),
    )


async def _set_rows(session: AsyncSession, day: date, *, refresh: bool = False):
    statement = (
        select(SoloDailySet).where(SoloDailySet.daily_date == day).order_by(SoloDailySet.position)
    )
    if refresh:
        statement = statement.execution_options(populate_existing=True)
    return list((await session.scalars(statement)).all())


# The one lock every Daily pick and replacement takes (PostgreSQL), so two
# dates open at once cannot each read the same unused concepts before either
# commits: the 60-day rule is read after it, and sees what the other picked.
DAILY_PICK_LOCK_ID = int.from_bytes(b"SOLODAY", "big")


async def _lock_daily_picks(session: AsyncSession) -> None:
    """Serialize choosing Daily drawings across every date, until commit.
    SQLite has one writer already, and is a test database (#1493 review)."""
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(
            sql_text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": DAILY_PICK_LOCK_ID}
        )


def skipped_retry_due(day_row: SoloDailyDay, now: datetime) -> bool:
    """Whether a date stored with no Daily is due another look: still open
    somewhere, and not looked at within `SKIPPED_RETRY`."""
    looked = day_row.picked_at
    if looked.tzinfo is None:
        looked = looked.replace(tzinfo=timezone.utc)
    return date_is_open(day_row.daily_date, now) and now - looked >= SKIPPED_RETRY


async def _write_set(session: AsyncSession, day: date, picked) -> None:
    session.add_all(
        SoloDailySet(
            daily_date=day, position=index + 1, turn_id=turn, concept_id=concept,
            solve_rate=rate,
        )
        for index, (turn, concept, rate) in enumerate(picked)
    )
    session.add_all(
        SoloDailyConcept(daily_date=day, concept_id=concept) for _, concept, _ in picked
    )
    await session.flush()


async def daily_set(session: AsyncSession, day: date, *, now: datetime) -> list[SoloDailySet] | None:
    """`day`'s five, chosen by the first request for the date and the same
    for everybody after it; None for a day with too few to choose from - a
    day looked at again, while it is open, every `SKIPPED_RETRY`.

    A pick takes the Daily pick lock first, so picks for different dates
    happen one at a time and each reads the concepts the others used; then
    the day row is what two first requests for one date race for: the one
    that inserts it picks, in its transaction; the other reads. A drawing
    that has stopped being playable for everybody since is replaced for
    everybody by the same walk, under the same lock and the day row's -
    taken only then, so the opens of an untouched Daily never queue behind
    one another."""
    existing = await session.get(SoloDailyDay, day)
    if existing is None:
        await _lock_daily_picks(session)
        existing = await session.get(SoloDailyDay, day, populate_existing=True)
    if existing is None:
        picked = await pick_daily(session, day, count=DAILY_LENGTH)
        state = "set" if len(picked) == DAILY_LENGTH else "skipped"
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as build
        else:
            from sqlalchemy.dialects.sqlite import insert as build
        inserted = await session.execute(
            build(SoloDailyDay)
            .values(daily_date=day, state=state, picked_at=now)
            .on_conflict_do_nothing(index_elements=[SoloDailyDay.daily_date])
            .returning(SoloDailyDay.daily_date)
        )
        if inserted.first() is not None and state == "set":
            await _write_set(session, day, picked)
        existing = await session.get(SoloDailyDay, day, populate_existing=True)
    if existing.state == "skipped" and skipped_retry_due(existing, now):
        # Nobody can have played a date with no Daily, so looking again
        # changes nothing for anybody: a date asked for before its games had
        # finished gets one once they have (#1434). Under the same lock as a
        # first pick, and the day row's, so one request does it.
        await _lock_daily_picks(session)
        existing = await session.get(
            SoloDailyDay, day, with_for_update=True, populate_existing=True
        )
        if existing.state == "skipped" and skipped_retry_due(existing, now):
            picked = await pick_daily(session, day, count=DAILY_LENGTH)
            existing.picked_at = now
            if len(picked) == DAILY_LENGTH:
                existing.state = "set"
                await _write_set(session, day, picked)
            await session.flush()
    if existing.state != "set":
        return None
    rows = await _set_rows(session, day)
    if len(set((await session.scalars(_servable_set_rows(rows))).all())) == len(rows):
        return rows
    await _lock_daily_picks(session)
    await session.get(SoloDailyDay, day, with_for_update=True, populate_existing=True)
    rows = await _set_rows(session, day, refresh=True)
    servable = set((await session.scalars(_servable_set_rows(rows))).all())
    for row in rows:
        if row.turn_id in servable:
            continue
        others = [other.concept_id for other in rows if other is not row]
        replacement = await pick_daily(
            session, day, count=1, exclude_concepts=others,
            start=(daily_start_key(day) + row.position) % SAMPLE_KEY_SPACE,
        )
        if not replacement:
            # Nothing left to put there: the position stays as it was, its
            # door closed, and a player can only give it up (R-SOLO-13).
            continue
        turn, concept, rate = replacement[0]
        row.replaced_turn_id, row.replaced_concept_id, row.replaced_at = (
            row.turn_id, row.concept_id, now
        )
        row.turn_id, row.concept_id, row.solve_rate = turn, concept, rate
        # Never already the date's: the walk leaves out every concept it held.
        session.add(SoloDailyConcept(daily_date=day, concept_id=concept))
    await session.flush()
    return rows


async def ensure_open_dailies(
    session_factory: async_sessionmaker[AsyncSession], now: datetime
) -> None:
    """Pick the Daily of every date open somewhere that nobody has asked for
    yet - and look again at one stored as skipped whose retry is due - so a
    free run's exclusion of open Dailies knows their concepts before the first
    player of the new date arrives (#1493 review). A free run that served a
    drawing a due retry was about to pick would hand out a Daily's answer."""
    async with session_factory() as session:
        settled = {
            row.daily_date
            for row in (
                await session.scalars(
                    select(SoloDailyDay).where(SoloDailyDay.daily_date.in_(open_dates(now)))
                )
            ).all()
            if row.state == "set" or not skipped_retry_due(row, now)
        }
    for day in open_dates(now):
        if day in settled:
            continue
        async with session_factory() as session:
            async with session.begin():
                await daily_set(session, day, now=now)


# How often a start that met another start's run tries again.
START_ATTEMPTS = 4


class SoloRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._meanings = OfficialMeanings()

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
        """A new free run, abandoning the one of its length in play (#1434):
        a 5 or 10 run left unfinished records nothing; an unlimited one ends
        at the streak it reached, which is a result like any other. Runs of
        the other lengths go on - one of each can be in play at once."""
        for attempt in range(START_ATTEMPTS):
            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        await require_live_player(session, user_id)
                        player = (await identity_ids(session, UUID(user_id)))[0]
                        active = await session.scalar(
                            select(SoloRun)
                            .where(
                                SoloRun.user_id == player,
                                SoloRun.mode == "free",
                                SoloRun.state == "active",
                                SoloRun.length.is_(None)
                                if length is None
                                else SoloRun.length == length,
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
                        return _run_view(run, ())
            except IntegrityError:
                # Starts of one length at once: another one's run is in play
                # now, and this one abandons it on the retry.
                if attempt == START_ATTEMPTS - 1:
                    raise SoloRefused("conflict") from None
        raise SoloRefused("conflict")

    async def _abandon(self, session: AsyncSession, run: SoloRun, *, now: datetime) -> None:
        unlimited = run.length is None
        run.state = "ended" if unlimited else "abandoned"
        run.end_reason = "abandoned"
        run.ended_at = now
        await self._drop_open_serves(session, run)
        if unlimited:
            await _raise_best(session, run, now=now)

    async def _drop_open_serves(self, session: AsyncSession, run: SoloRun) -> None:
        """Serves fetched ahead and never settled go with a run that ends:
        a drawing the player never saw is not one they were served, and the
        run's count of drawings served says so (#1492 review)."""
        dropped = await session.execute(
            delete(SoloServe).where(SoloServe.run_id == run.id, SoloServe.settled_at.is_(None))
        )
        run.position -= dropped.rowcount or 0

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
        return _run_view(run, serves)

    async def serve_next(
        self, user_id: str, run_id: str, *, count: int, now: datetime
    ) -> list[ServeView]:
        """Serve up to `count` more drawings in a free run, so the client can
        hold one ahead: never more than `MAX_OPEN_SERVES` unsettled, never
        past a finite run's length.

        A run with nothing to serve from its very first drawing ends there,
        recording nothing: left active it would sit in its length's row as a
        run in progress the player never saw a drawing of."""
        await ensure_open_dailies(self._session_factory, now)
        async with self._session_factory() as session:
            async with session.begin():
                await require_live_player(session, user_id)
                ids = await identity_ids(session, UUID(user_id))
                player = ids[0]
                # Every free run of the player's in play, in one order: their
                # Quick and Endless served at once would each miss the other's
                # uncommitted serve and hand out the same drawing as unseen
                # (R-SOLO-07). One order, so two such serves never deadlock.
                await session.execute(
                    select(SoloRun.id)
                    .where(
                        SoloRun.user_id == player,
                        SoloRun.mode == "free",
                        SoloRun.state == "active",
                    )
                    .order_by(SoloRun.id)
                    .with_for_update()
                )
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
                    picked = await self._pick(session, ids, languages, run.id, now)
                    if picked is None:
                        break
                    turn_id, forms = picked
                    run.position += 1
                    serve = SoloServe(
                        run_id=run.id, user_id=player, turn_id=turn_id, position=run.position,
                        prompt=forms.prompt, prompt_language=forms.language,
                        forms=forms.text(), served_at=now,
                    )
                    session.add(serve)
                    await session.flush()
                    served.append(_serve_view(serve))
                if not served and room > 0:
                    if run.position > 0:
                        raise SoloRefused("empty")
                    run.state, run.end_reason, run.ended_at = "abandoned", "abandoned", now
                else:
                    return served
        # Committed first: the run ends, and then the player is told why.
        raise SoloRefused("empty")

    async def _pick(
        self,
        session: AsyncSession,
        ids: Sequence[UUID],
        languages: Sequence[str],
        run_id: UUID,
        now: datetime,
    ) -> tuple[UUID, AnswerForms] | None:
        """One drawing for a free run: unseen first, in the pool's random
        order from a random point, wrapping round once; once the player has
        seen every drawing they may be served, the one they saw longest ago -
        one this run has not served, while there is one (#1434: a thin pool
        repeats).

        Two bounded index walks on `sample_key`, never a sort of the pool."""
        player = ids[0]
        seen = exists().where(SoloServe.user_id == player, SoloServe.turn_id == SoloPoolEntry.turn_id)
        # A Daily still open somewhere is nobody's free-run drawing: it
        # would hand its prompt to a player before their Daily (#1434).
        # By concept, not drawing: another drawing of today's concept hands
        # over the same prompt (#1493 review).
        in_open_daily = exists().where(
            SoloDailySet.concept_id == SoloPoolEntry.concept_id,
            SoloDailySet.daily_date.in_(open_dates(now)),
        )
        base = select(
            SoloPoolEntry.turn_id, SoloPoolEntry.concept_id, SoloPoolEntry.prompt_version_id
        ).where(
            *servable_clauses(), *servable_to_clauses(ids, languages), ~in_open_daily
        )
        start = random.randrange(SAMPLE_KEY_SPACE)
        for window in (SoloPoolEntry.sample_key >= start, SoloPoolEntry.sample_key < start):
            row = (
                await session.execute(
                    base.where(window, ~seen).order_by(SoloPoolEntry.sample_key).limit(1)
                )
            ).first()
            if row is not None:
                forms = await answer_forms(
                    session, row.concept_id, languages,
                    drawn_version_id=row.prompt_version_id, meanings=self._meanings,
                )
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
                forms = await answer_forms(
                    session, row.concept_id, languages,
                    drawn_version_id=row.prompt_version_id, meanings=self._meanings,
                )
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
                await require_live_player(session, user_id)
                player = (await identity_ids(session, UUID(user_id)))[0]
                # The run first, locked, and the serve read again under it:
                # an abandon that deleted an open serve meanwhile is a
                # conflict, not an error (#1492 review).
                run = await session.scalar(
                    select(SoloRun)
                    .join(SoloServe, SoloServe.run_id == SoloRun.id)
                    .where(SoloServe.id == _uuid(serve_id), SoloServe.user_id == player)
                    .with_for_update(of=SoloRun)
                )
                if run is None:
                    raise SoloRefused("missing")
                serve = await session.scalar(
                    select(SoloServe)
                    .where(SoloServe.id == _uuid(serve_id))
                    .execution_options(populate_existing=True)
                )
                if serve is None or serve.outcome is not None or run.state != "active":
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
                if run.mode == "daily":
                    await _record_daily(session, run, serve, now=now)
                if run_is_over(run.length, settled=settled, missed=outcome != SOLVED):
                    run.state = "ended"
                    run.end_reason = "completed" if run.length is not None else "missed"
                    run.ended_at = now
                    await session.flush()
                    await self._drop_open_serves(session, run)
                    if run.mode == "free":
                        await _raise_best(session, run, now=now)
                await session.flush()
                serves = (
                    await session.scalars(
                        select(SoloServe).where(SoloServe.run_id == run.id).order_by(SoloServe.position)
                    )
                ).all()
                return _serve_view(serve), _run_view(run, serves)

    # --- the Daily ------------------------------------------------------------

    async def open_daily(self, user_id: str, day: date, *, now: datetime) -> RunView:
        """The player's Daily for `day`: created with its five serves the
        first time, resumed after - never restarted (#1434). A drawing the
        set replaced since the player was served it is swapped in their open
        serves too; what they already played keeps its mark. `missing` for a
        day with no Daily."""
        # The set first, in a transaction of its own: a day found too thin is
        # stored as skipped even though this request is refused.
        async with self._session_factory() as session:
            async with session.begin():
                picked = await daily_set(session, day, now=now)
        if picked is None:
            raise SoloRefused("missing")
        for attempt in range(2):
            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        player = (await identity_ids(session, UUID(user_id)))[0]
                        rows = list(
                            (
                                await session.scalars(
                                    select(SoloDailySet)
                                    .where(SoloDailySet.daily_date == day)
                                    .order_by(SoloDailySet.position)
                                )
                            ).all()
                        )
                        languages = await play_languages(session, player)
                        if not languages:
                            raise SoloRefused("missing")
                        run = await session.scalar(
                            select(SoloRun)
                            .where(
                                SoloRun.user_id == player,
                                SoloRun.mode == "daily",
                                SoloRun.daily_date == day,
                            )
                            .with_for_update()
                        )
                        if run is None:
                            run = SoloRun(
                                user_id=player, mode="daily", length=DAILY_LENGTH,
                                daily_date=day, state="active", position=0, solved=0,
                                points=0, started_at=now,
                            )
                            session.add(run)
                            await session.flush()
                        await self._sync_daily_serves(session, run, rows, languages, now=now)
                        return await self._view_with_serves(session, run, player)
            except IntegrityError:
                # Two first opens at once: the other made the run; read it.
                if attempt:
                    raise SoloRefused("conflict") from None
        raise SoloRefused("conflict")

    async def _sync_daily_serves(
        self,
        session: AsyncSession,
        run: SoloRun,
        rows: Sequence[SoloDailySet],
        languages: Sequence[str],
        *,
        now: datetime,
    ) -> None:
        serves = {
            serve.position: serve
            for serve in (
                await session.scalars(select(SoloServe).where(SoloServe.run_id == run.id))
            ).all()
        }
        drawn = dict(
            (
                await session.execute(
                    select(SoloPoolEntry.turn_id, SoloPoolEntry.prompt_version_id).where(
                        SoloPoolEntry.turn_id.in_([row.turn_id for row in rows])
                    )
                )
            ).all()
        )
        for row in rows:
            serve = serves.get(row.position)
            if serve is not None and (serve.outcome is not None or serve.turn_id == row.turn_id):
                continue
            forms = await answer_forms(
                session, row.concept_id, languages,
                drawn_version_id=drawn.get(row.turn_id), meanings=self._meanings,
            )
            if forms is None:
                # Every set concept is nameable in every language
                # (`_servable_set_rows`); a position left without a serve
                # would hold the Daily open for good, so refuse instead.
                raise SoloRefused("conflict")
            if serve is None:
                session.add(
                    SoloServe(
                        run_id=run.id, user_id=run.user_id, turn_id=row.turn_id,
                        position=row.position, prompt=forms.prompt,
                        prompt_language=forms.language, forms=forms.text(), served_at=now,
                    )
                )
            else:
                serve.turn_id, serve.prompt, serve.prompt_language, serve.forms = (
                    row.turn_id, forms.prompt, forms.language, forms.text()
                )
        run.position = DAILY_LENGTH
        await session.flush()

    async def summary(self, user_id: str, today: date, *, now: datetime) -> dict:
        """What Solo's page opens on: today's Daily and how far it got, the
        free runs there are to continue (one a length) with how far each got,
        the bests, the streak and what the player's Dailies came to - each
        computed from the results here, never kept (N-03). The days
        themselves are `month`'s."""
        async with self._session_factory() as session:
            day = await session.get(SoloDailyDay, today)
        if day is not None and day.state == "skipped" and skipped_retry_due(day, now):
            # The page would say there is no Daily and offer nothing to press:
            # look again first (`daily_set`).
            async with self._session_factory() as session:
                async with session.begin():
                    await daily_set(session, today, now=now)
        async with self._session_factory() as session:
            player = (await identity_ids(session, UUID(user_id)))[0]
            day = await session.get(SoloDailyDay, today)
            result = await session.get(SoloDailyResult, (player, today))
            run = await session.scalar(
                select(SoloRun).where(
                    SoloRun.user_id == player, SoloRun.mode == "daily", SoloRun.daily_date == today
                )
            )
            if day is not None and day.state == "skipped":
                state = "unavailable"
            elif result is not None and result.completed_at is not None:
                state = "done"
            elif run is not None:
                state = "in_progress"
            else:
                state = "not_started"
            played = (
                await session.execute(
                    select(
                        func.count(),
                        func.coalesce(func.sum(SoloDailyResult.positions_played), 0),
                        func.coalesce(func.sum(SoloDailyResult.solved), 0),
                    ).where(SoloDailyResult.user_id == player)
                )
            ).one()
            bests = (
                await session.scalars(select(SoloBest).where(SoloBest.user_id == player))
            ).all()
            # A run that has served nothing is one the page is about to serve,
            # or one the pool had nothing for: either way nothing to continue.
            active = (
                await session.scalars(
                    select(SoloRun).where(
                        SoloRun.user_id == player,
                        SoloRun.mode == "free",
                        SoloRun.state == "active",
                        SoloRun.position > 0,
                    )
                )
            ).all()
            outcomes: dict[UUID, list[str]] = {run.id: [] for run in active}
            if active:
                for run_id, outcome in (
                    await session.execute(
                        select(SoloServe.run_id, SoloServe.outcome)
                        .where(
                            SoloServe.run_id.in_(list(outcomes)),
                            SoloServe.settled_at.is_not(None),
                        )
                        .order_by(SoloServe.run_id, SoloServe.position)
                    )
                ).all():
                    outcomes[run_id].append(outcome)
            # Every date started on its own day, not the page of history: a
            # streak is as long as it is. A date with no Daily breaks nobody's.
            started = list(
                (
                    await session.scalars(
                        select(SoloDailyResult.daily_date).where(
                            SoloDailyResult.user_id == player,
                            SoloDailyResult.started_on_date.is_(True),
                        )
                    )
                ).all()
            )
            skipped = list(
                (
                    await session.scalars(
                        select(SoloDailyDay.daily_date).where(SoloDailyDay.state == "skipped")
                    )
                ).all()
            )
        return {
            "today": {
                "date": today.isoformat(),
                "state": state,
                "result": daily_result_payload(result) if result is not None else None,
            },
            # Quick, Classic, Endless: the page's order.
            "activeRuns": [
                {
                    "runId": str(run.id),
                    "length": run.length,
                    "solved": run.solved,
                    "points": run.points,
                    "outcomes": outcomes[run.id],
                }
                for run in sorted(active, key=lambda run: (run.length is None, run.length or 0))
            ],
            "bests": {best.length_key: best.best for best in bests if best.best > 0},
            "streak": daily_streak(started, today, skipped=skipped),
            "stats": {
                "dailiesPlayed": played[0],
                "drawingsPlayed": int(played[1]),
                "drawingsNamed": int(played[2]),
                "longestStreak": longest_daily_streak(started, skipped=skipped),
            },
        }

    async def month(self, user_id: str, first: date, today: date) -> dict:
        """One month of the player's Dailies, for the page's calendar: each
        date of it up to `today`, whether it had a Daily, and the player's
        result for it if any. `first` is the player's first Daily, so the
        calendar knows how far back there is anything to show."""
        last = min(today, _month_end(first))
        async with self._session_factory() as session:
            player = (await identity_ids(session, UUID(user_id)))[0]
            had = set(
                (
                    await session.scalars(
                        select(SoloDailyDay.daily_date).where(
                            SoloDailyDay.daily_date.between(first, last),
                            SoloDailyDay.state == "set",
                        )
                    )
                ).all()
            )
            results = {
                row.daily_date: row
                for row in (
                    await session.scalars(
                        select(SoloDailyResult).where(
                            SoloDailyResult.user_id == player,
                            SoloDailyResult.daily_date.between(first, last),
                        )
                    )
                ).all()
            }
            earliest = await session.scalar(
                select(func.min(SoloDailyResult.daily_date)).where(
                    SoloDailyResult.user_id == player
                )
            )
        days = []
        day = first
        while day <= last:
            result = results.get(day)
            days.append(
                {
                    "date": day.isoformat(),
                    "daily": day in had,
                    "result": daily_result_payload(result) if result is not None else None,
                }
            )
            day += timedelta(days=1)
        return {
            "month": first.isoformat()[:7],
            "first": earliest.isoformat() if earliest is not None else None,
            "days": days,
        }

    # --- the fourth drawing door (R-HIST-16) -------------------------------

    def _served_drawing(self, player_ids: Sequence[UUID], serve_id: UUID, *columns):
        """A served drawing the player may still see: their serve, and the
        drawing still servable to anybody - a hide, a take-out, an opt-out or
        an erasure closes the door at once, as on every other door - and, for
        a Daily, still one every language can name.

        The row read is an alias, so the servable clauses' own subquery over
        `turn_drawings` stays a subquery rather than correlating to it."""
        drawing = aliased(TurnDrawing)
        return (
            select(*(getattr(drawing, name) for name in columns))
            .join(SoloServe, SoloServe.turn_id == drawing.turn_id)
            .join(SoloRun, SoloRun.id == SoloServe.run_id)
            .join(SoloPoolEntry, SoloPoolEntry.turn_id == SoloServe.turn_id)
            .where(
                SoloServe.id == serve_id,
                SoloServe.user_id.in_(list(player_ids)),
                *servable_clauses(),
                # A Daily's drawing also needs its concept nameable in every
                # language: one with no replacement after a language's
                # wording came down stays in the set, and its door closes for
                # everybody, as R-SOLO-13 says (#1493 review).
                or_(SoloRun.mode != "daily", _all_languages_or_agnostic()),
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

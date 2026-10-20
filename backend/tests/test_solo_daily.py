"""The Daily and personal bests (#1434, #1467).

The Daily is the same five drawings for everybody, chosen by the first
request for a date; nobody gets a substitute, and a drawing that stops being
servable is replaced for everybody. A player's Daily keeps its progress as it
is played. Bests only go up and rebuild from the runs.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.api.errors import install_refusal_handler
from app.api.solo import create_solo_router, drawing_limiter, run_limiter, serve_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.db.models import (
    PromptVersion,
    SoloPoolEntry,
    SoloBest,
    SoloDailyDay,
    SoloDailyResult,
    SoloDailySet,
    SoloServe,
    TurnDrawing,
)
from app.repositories.solo import SoloRefused, SoloRepository, rebuild_bests
from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository, SqlAlchemyUserRepository
from app.solo_rules import DAILY_REUSE_DAYS
from tests.dbfixtures import create_test_db
from tests.solo_fixtures import player, record_turn, seed_concept
from tests.test_api_profiles import sign_in_as

DAY = date(2026, 10, 15)
NOON = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def env():
    factory, engine = await create_test_db()
    for limiter in (run_limiter, serve_limiter, drawing_limiter):
        limiter.reset()
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_solo_router(factory))
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, users, history, SoloRepository(factory), factory
    await engine.dispose()


async def _candidates(
    users, history, factory, count, *, correct=(1,), guessers=2, forms=None, tag=""
):
    """`count` Daily candidates, each its own agnostic concept, drawn by one
    player and guessed by `guessers` others; `correct[i % len]` named it."""
    drawer = await player(users, factory, f"Drawer{tag}")
    seats = [await player(users, factory, f"Guesser{tag}{i}") for i in range(guessers)]
    turns = []
    for index in range(count):
        concept = await seed_concept(factory, forms or {"zxx": f"Name{tag}{index}"})
        language = next(iter(concept.versions))
        turns.append(
            await record_turn(
                history,
                drawer=drawer.id,
                guessers=[seat.id for seat in seats],
                version_id=concept.versions[language],
                correct=correct[index % len(correct)],
            )
        )
    return drawer, seats, turns


async def _set(factory, day=DAY) -> list[SoloDailySet]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(SoloDailySet)
                    .where(SoloDailySet.daily_date == day)
                    .order_by(SoloDailySet.position)
                )
            ).all()
        )


async def _served_turns(factory, run_id: str) -> list[UUID]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(SoloServe.turn_id)
                    .where(SoloServe.run_id == UUID(run_id))
                    .order_by(SoloServe.position)
                )
            ).all()
        )


async def test_everybody_gets_the_same_five_easiest_first_and_their_own_game_too(env):
    http, users, history, solo, factory = env
    drawer, seats, turns = await _candidates(
        users, history, factory, 7, correct=(1, 2, 1, 2, 1, 2, 1), guessers=3
    )
    first = await player(users, factory, "First")
    run_a = await solo.open_daily(first.id, DAY, now=NOON)
    # The drawer and a guesser of every candidate: no substitution for anybody.
    run_b = await solo.open_daily(seats[0].id, DAY, now=NOON)
    run_c = await solo.open_daily(drawer.id, DAY, now=NOON)
    picked = await _set(factory)
    assert len(picked) == 5 and len({row.concept_id for row in picked}) == 5
    rates = [row.solve_rate for row in picked]
    assert rates == sorted(rates, reverse=True)
    expected = [row.turn_id for row in picked]
    for run in (run_a, run_b, run_c):
        assert await _served_turns(factory, run.run_id) == expected
        assert [serve.position for serve in run.serves] == [1, 2, 3, 4, 5]
        assert all(serve.forms for serve in run.serves)


async def test_a_daily_is_picked_once_by_the_first_two_requests_at_once(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    one = await player(users, factory, "One")
    two = await player(users, factory, "Two")
    await asyncio.gather(
        solo.open_daily(one.id, DAY, now=NOON), solo.open_daily(two.id, DAY, now=NOON)
    )
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(SoloDailyDay)) == 1
        assert await session.scalar(select(func.count()).select_from(SoloDailySet)) == 5


async def test_a_thin_day_is_looked_at_again_while_it_is_open(env):
    """A date first asked for before its games had finished is skipped; while
    it is still open it is looked at again every SKIPPED_RETRY - nobody can
    have played it - and gets a Daily once there are five candidates. The
    page's summary does the looking too, since it is what offers Play."""
    http, users, history, solo, factory = env
    from app.repositories.solo import SoloRefused
    from app.solo_rules import SKIPPED_RETRY

    await _candidates(users, history, factory, 4)
    stranger = await player(users, factory, "Stranger")
    for at in (NOON, NOON + SKIPPED_RETRY / 2):
        try:
            await solo.open_daily(stranger.id, DAY, now=at)
        except SoloRefused as error:
            assert error.kind == "missing"
        else:
            raise AssertionError("a day with four candidates has no Daily")
    await _candidates(users, history, factory, 3, tag="b")
    # Within the wait it stays as it was, however many arrived.
    assert (await solo.summary(stranger.id, DAY, now=NOON + SKIPPED_RETRY / 2))["today"]["state"] == "unavailable"
    later = NOON + SKIPPED_RETRY
    assert (await solo.summary(stranger.id, DAY, now=later))["today"]["state"] == "not_started"
    run = await solo.open_daily(stranger.id, DAY, now=later)
    assert len(run.serves) == 5
    async with factory() as session:
        assert (await session.get(SoloDailyDay, DAY)).state == "set"


async def test_a_thin_day_that_has_ended_stays_without_a_daily(env):
    """Once a date has ended everywhere it is not picked late: the archive
    plays the Dailies there were (#1470)."""
    http, users, history, solo, factory = env
    from app.repositories.solo import daily_set

    await _candidates(users, history, factory, 4)
    async with factory() as session, session.begin():
        assert await daily_set(session, DAY, now=NOON) is None
    await _candidates(users, history, factory, 3, tag="b")
    async with factory() as session, session.begin():
        assert await daily_set(session, DAY, now=NOON + timedelta(days=3)) is None
    async with factory() as session:
        assert (await session.get(SoloDailyDay, DAY)).state == "skipped"


async def test_the_daily_bar_is_two_guessers_and_a_fifth_named_it(env):
    http, users, history, solo, factory = env
    # One guesser: no Daily candidate, however right they were.
    await _candidates(users, history, factory, 5, guessers=1)
    stranger = await player(users, factory, "Stranger")
    from app.repositories.solo import SoloRefused

    try:
        await solo.open_daily(stranger.id, DAY, now=NOON)
    except SoloRefused:
        pass
    else:
        raise AssertionError("single-guesser drawings are no Daily")


async def test_a_concept_is_not_the_daily_again_within_sixty_days_nor_a_shared_drawing(env):
    http, users, history, solo, factory = env
    _, _, turns = await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    await solo.open_daily(stranger.id, DAY, now=NOON)
    first = {row.concept_id for row in await _set(factory)}
    # Only one concept is left unused, so the next day cannot fill.
    later = DAY + timedelta(days=DAILY_REUSE_DAYS - 1)
    from app.repositories.solo import SoloRefused

    try:
        await solo.open_daily(stranger.id, later, now=NOON)
    except SoloRefused:
        pass
    else:
        raise AssertionError("a concept came back within sixty days")
    beyond = DAY + timedelta(days=DAILY_REUSE_DAYS)
    await solo.open_daily(stranger.id, beyond, now=NOON)
    assert {row.concept_id for row in await _set(factory, beyond)} & first

    # A drawing somebody shared to the Gallery is never picked: a stranger
    # may have seen it there, prompt and all.
    async with factory() as session:
        async with session.begin():
            await session.execute(update(TurnDrawing).values(gallery_share_count=1))
    try:
        await solo.open_daily(stranger.id, beyond + timedelta(days=DAILY_REUSE_DAYS * 2), now=NOON)
    except SoloRefused:
        pass
    else:
        raise AssertionError("a Gallery drawing was picked")
    del turns


async def test_a_drawing_that_stops_being_servable_is_replaced_for_everybody(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 7)
    early = await player(users, factory, "Early")
    run = await solo.open_daily(early.id, DAY, now=NOON)
    await solo.settle(early.id, run.serves[0].serve_id, outcome="solved", seconds=5, now=NOON)
    picked = await _set(factory)
    played, hidden = picked[0].turn_id, picked[1].turn_id
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(TurnDrawing)
                .where(TurnDrawing.turn_id.in_([played, hidden]))
                .values(gallery_hidden_at=NOON)
            )
    late = await player(users, factory, "Late")
    await solo.open_daily(late.id, DAY, now=NOON)
    replaced = await _set(factory)
    assert replaced[1].replaced_turn_id == hidden and replaced[1].turn_id != hidden
    assert replaced[0].replaced_turn_id == played
    # The late player gets the replacements; the early one keeps the mark of
    # what they played, and their open serves swap too.
    resumed = await solo.open_daily(early.id, DAY, now=NOON)
    early_turns = await _served_turns(factory, resumed.run_id)
    assert early_turns[0] == played and early_turns[1] == replaced[1].turn_id
    assert resumed.serves[0].outcome == "solved"
    assert await _served_turns(factory, (await solo.open_daily(late.id, DAY, now=NOON)).run_id) == [
        row.turn_id for row in replaced
    ]


async def test_a_daily_keeps_its_progress_and_resumes_never_restarts(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    # The route reads the real clock: today, wherever the suite runs.
    today = datetime.now(timezone.utc).date().isoformat()
    opened = await http.post(f"/api/solo/daily/{today}")
    assert opened.status_code == 200, opened.text
    run = opened.json()
    assert run["mode"] == "daily" and run["length"] == 5 and run["dailyDate"] == today
    first, second = run["serves"][0], run["serves"][1]
    assert (await http.post(
        f"/api/solo/serves/{first['serveId']}/result", json={"outcome": "solved", "seconds": 3}
    )).status_code == 200
    await http.post(
        f"/api/solo/serves/{second['serveId']}/result", json={"outcome": "given_up", "seconds": 8}
    )
    again = (await http.post(f"/api/solo/daily/{today}")).json()
    assert again["runId"] == run["runId"]
    assert [serve["outcome"] for serve in again["serves"]] == ["solved", "given_up", None, None, None]
    me = (await http.get("/api/solo/me", params={"today": today})).json()
    assert me["today"]["state"] == "in_progress"
    result = me["today"]["result"]
    assert (result["positionsPlayed"], result["solved"], result["points"]) == (2, 1, 280)
    assert [mark["outcome"] for mark in result["marks"]] == ["solved", "given_up"]
    assert me["streak"] == 1
    for serve in again["serves"][2:]:
        await http.post(
            f"/api/solo/serves/{serve['serveId']}/result", json={"outcome": "timed_out", "seconds": 30}
        )
    me = (await http.get("/api/solo/me", params={"today": today})).json()
    assert me["today"]["state"] == "done" and me["today"]["result"]["completed"] is True


async def test_a_date_that_is_nobody_s_today_is_refused(env):
    http, users, history, solo, factory = env
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    real_today = datetime.now(timezone.utc).date()
    # A past date is the archive's (#1470, tests/test_solo_archive.py).
    for day in (real_today + timedelta(days=2), "2026-13-40"):
        refused = await http.post(f"/api/solo/daily/{day}")
        assert refused.status_code == 422
        assert refused.json()["errorCode"] == "solo_date_out_of_range"
    refused = await http.get("/api/solo/me", params={"today": str(real_today + timedelta(days=3))})
    assert refused.status_code == 422


async def test_a_drawing_played_after_its_date_is_marked_late_and_the_streak_counts_dates(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    run = await solo.open_daily(stranger.id, DAY, now=NOON)
    await solo.settle(stranger.id, run.serves[0].serve_id, outcome="solved", seconds=4, now=NOON)
    later = NOON + timedelta(days=3)
    await solo.settle(stranger.id, run.serves[1].serve_id, outcome="solved", seconds=4, now=later)
    async with factory() as session:
        result = await session.get(SoloDailyResult, (UUID(stranger.id), DAY))
    assert [mark["late"] for mark in result.marks] == [False, True]
    assert result.started_on_date is True
    summary = await solo.summary(stranger.id, DAY + timedelta(days=1), now=NOON)
    assert summary["streak"] == 1
    summary = await solo.summary(stranger.id, DAY + timedelta(days=2), now=NOON)
    assert summary["streak"] == 0


async def test_free_runs_never_serve_a_daily_still_open(env, monkeypatch):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 5)
    stranger = await player(users, factory, "Stranger")
    now = datetime.now(timezone.utc)
    await solo.open_daily(stranger.id, now.date(), now=now)
    other = await player(users, factory, "Other")
    run = await solo.start_free_run(other.id, length=5, now=now)
    from app.repositories.solo import SoloRefused

    try:
        await solo.serve_next(other.id, run.run_id, count=1, now=now)
    except SoloRefused as error:
        assert error.kind == "empty"
    else:
        raise AssertionError("a free run served an open Daily's drawing")
    # Once the date has ended everywhere, its drawings are free-run drawings.
    later = now + timedelta(days=3)
    run = await solo.start_free_run(other.id, length=5, now=later)
    assert await solo.serve_next(other.id, run.run_id, count=1, now=later)


async def test_bests_only_go_up_and_rebuild_from_the_runs(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12, guessers=1)
    stranger = await player(users, factory, "Stranger")

    async def play(length, outcomes):
        run = await solo.start_free_run(stranger.id, length=length, now=NOON)
        for outcome, seconds in outcomes:
            [serve] = await solo.serve_next(stranger.id, run.run_id, count=1, now=NOON)
            await solo.settle(
                stranger.id, serve.serve_id, outcome=outcome, seconds=seconds, now=NOON
            )
        return run

    async def bests():
        async with factory() as session:
            return {
                row.length_key: row.best
                for row in (await session.scalars(select(SoloBest))).all()
            }

    await play(5, [("solved", 0)] * 5)
    assert await bests() == {"5": 1500}
    await play(5, [("solved", 30)] * 5)
    assert await bests() == {"5": 1500}
    # An unfinished 5 counts for nothing; an unlimited one counts its streak,
    # ended by a miss or by starting another run.
    await play(5, [("solved", 0)] * 2)
    await play(None, [("solved", 3), ("solved", 3), ("timed_out", 30)])
    assert await bests() == {"5": 1500, "unlimited": 2}
    await play(None, [("solved", 3)] * 3)
    # Another length leaves the unlimited run going; another unlimited ends it.
    await solo.start_free_run(stranger.id, length=10, now=NOON)
    assert await bests() == {"5": 1500, "unlimited": 2}
    await solo.start_free_run(stranger.id, length=None, now=NOON)
    assert await bests() == {"5": 1500, "unlimited": 3}

    async with factory() as session:
        async with session.begin():
            await session.execute(SoloBest.__table__.delete())
            assert await rebuild_bests(session) == 2
    assert await bests() == {"5": 1500, "unlimited": 3}
    summary = await solo.summary(stranger.id, DAY, now=NOON)
    assert summary["bests"] == {"5": 1500, "unlimited": 3}
    # One a length, each with what it has come to; the 10 and the unlimited
    # just started have served nothing yet, so there is nothing to continue.
    assert [(run["length"], run["outcomes"]) for run in summary["activeRuns"]] == [
        (5, ["solved", "solved"]),
    ]


async def test_only_a_concept_every_language_can_name_is_the_daily(env):
    http, users, history, solo, factory = env
    every = {lang: f"thing-{lang}" for lang in ("en", "de", "es", "fr", "it", "nl", "pl", "pt")}
    seven = {lang: word for lang, word in every.items() if lang != "pl"}
    # Four agnostic, one in all eight, one missing Polish: exactly five qualify.
    await _candidates(users, history, factory, 4)
    _, _, [eight] = await _candidates(users, history, factory, 1, forms=every, tag="e")
    _, _, [short] = await _candidates(users, history, factory, 1, forms=seven, tag="s")
    stranger = await player(users, factory, "Stranger")
    await solo.open_daily(stranger.id, DAY, now=NOON)
    turns = {row.turn_id for row in await _set(factory)}
    assert UUID(eight.turn_id) in turns and UUID(short.turn_id) not in turns


def test_a_date_is_open_from_utc_plus_14_midnight_to_two_hours_past_utc_minus_12():
    from app.solo_rules import date_is_open, open_dates

    day = date(2026, 10, 15)
    opens = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    closes = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)
    assert not date_is_open(day, opens - timedelta(seconds=1))
    assert date_is_open(day, opens)
    assert date_is_open(day, closes - timedelta(seconds=1))
    assert not date_is_open(day, closes)
    assert open_dates(datetime(2026, 10, 15, 9, 59, tzinfo=timezone.utc)) == (
        date(2026, 10, 14), date(2026, 10, 15),
    )
    assert open_dates(datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)) == (
        date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16),
    )


def test_a_day_with_no_daily_breaks_nobody_s_streak():
    from app.solo_rules import daily_streak

    today = date(2026, 10, 15)
    played = [date(2026, 10, 15), date(2026, 10, 13), date(2026, 10, 12)]
    assert daily_streak(played, today) == 1
    assert daily_streak(played, today, skipped=[date(2026, 10, 14)]) == 3


async def test_a_language_s_wording_taken_down_replaces_the_drawing_for_everybody(env):
    http, users, history, solo, factory = env
    every = {lang: f"t-{lang}" for lang in ("en", "de", "es", "fr", "it", "nl", "pl", "pt")}
    await _candidates(users, history, factory, 4, tag="z")
    _, _, [eight] = await _candidates(users, history, factory, 1, forms=every, tag="e")
    stranger = await player(users, factory, "Stranger")
    await solo.open_daily(stranger.id, DAY, now=NOON)
    assert UUID(eight.turn_id) in {row.turn_id for row in await _set(factory)}
    # One more candidate, for the replacement.
    await _candidates(users, history, factory, 1, tag="x")

    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(PromptVersion)
                .where(PromptVersion.language == "pl", PromptVersion.canonical_answer == "t-pl")
                .values(moderation_state="hidden")
            )
    polish = await player(users, factory, "Polish", languages=("pl",))
    run = await solo.open_daily(polish.id, DAY, now=NOON)
    assert len(run.serves) == 5
    assert UUID(eight.turn_id) not in {row.turn_id for row in await _set(factory)}


async def test_free_runs_skip_another_drawing_of_an_open_daily_s_concept(env):
    http, users, history, solo, factory = env
    drawer, seats, _ = await _candidates(users, history, factory, 5)
    now = datetime.now(timezone.utc)
    # Nobody has opened today's Daily: a free run picks it first anyway.
    other = await player(users, factory, "Other")
    async with factory() as session:
        concepts = [row.concept_id for row in (await session.scalars(select(SoloPoolEntry))).all()]
    single = await player(users, factory, "Single")
    # A second drawing of one of the concepts, by one guesser: no Daily
    # candidate itself, but the same prompt.
    async with factory() as session:
        version = await session.scalar(
            select(PromptVersion.id).where(PromptVersion.concept_id == concepts[0])
        )
    twin = await record_turn(history, drawer=drawer.id, guessers=[single.id], version_id=version)
    run = await solo.start_free_run(other.id, length=5, now=now)
    from app.repositories.solo import SoloRefused

    try:
        served = await solo.serve_next(other.id, run.run_id, count=1, now=now)
    except SoloRefused:
        served = []
    async with factory() as session:
        turns = set((await session.scalars(select(SoloServe.turn_id))).all())
    assert UUID(twin.turn_id) not in turns and not served
    async with factory() as session:
        assert await session.get(SoloDailyDay, now.date()) is not None


async def test_a_daily_first_played_after_its_date_is_not_started_on_it(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    run = await solo.open_daily(stranger.id, DAY, now=NOON)
    later = NOON + timedelta(days=3)
    await solo.settle(stranger.id, run.serves[0].serve_id, outcome="solved", seconds=4, now=later)
    async with factory() as session:
        result = await session.get(SoloDailyResult, (UUID(stranger.id), DAY))
    assert result.started_on_date is False and result.marks[0]["late"] is True
    summary = await solo.summary(stranger.id, DAY, now=NOON)
    assert summary["streak"] == 0


async def test_reuse_looks_both_ways_and_counts_a_replaced_concept(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    later = DAY + timedelta(days=30)
    await solo.open_daily(stranger.id, later, now=NOON)
    from app.repositories.solo import SoloRefused

    # The earlier day, picked after the later one, may not reuse its concepts.
    try:
        await solo.open_daily(stranger.id, DAY, now=NOON)
    except SoloRefused:
        pass
    else:
        raise AssertionError("an earlier day reused a later day's concepts")
    picked = await _set(factory, later)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(TurnDrawing)
                .where(TurnDrawing.turn_id == picked[0].turn_id)
                .values(gallery_hidden_at=NOON)
            )
    await solo.open_daily(stranger.id, later, now=NOON)
    replaced = (await _set(factory, later))[0]
    assert replaced.replaced_concept_id == picked[0].concept_id
    # A fresh drawing of the replaced concept: servable, and still not the
    # next day's Daily, since that concept was this one's.
    async with factory() as session:
        version = await session.scalar(
            select(PromptVersion.id).where(PromptVersion.concept_id == picked[0].concept_id)
        )
    fresh = [await player(users, factory, f"Fresh{i}") for i in range(3)]
    await record_turn(
        history, drawer=fresh[0].id, guessers=[fresh[1].id, fresh[2].id], version_id=version
    )
    from app.repositories.solo import pick_daily

    async with factory() as session:
        again = await pick_daily(session, later + timedelta(days=1), count=6)
    assert replaced.replaced_concept_id not in {concept for _, concept, _ in again}


async def test_a_skipped_day_reads_as_unavailable(env):
    http, users, history, solo, factory = env
    stranger = await player(users, factory, "Stranger")
    from app.repositories.solo import SoloRefused

    try:
        await solo.open_daily(stranger.id, DAY, now=NOON)
    except SoloRefused:
        pass
    summary = await solo.summary(stranger.id, DAY, now=NOON)
    assert summary["today"]["state"] == "unavailable"


async def test_deleting_an_account_takes_its_daily_results_and_bests(env):
    from app.auth.account_data import anonymize_account
    from app.db.models import SoloRun

    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    run = await solo.open_daily(stranger.id, DAY, now=NOON)
    await solo.settle(stranger.id, run.serves[0].serve_id, outcome="solved", seconds=4, now=NOON)
    free = await solo.start_free_run(stranger.id, length=None, now=NOON)
    await solo.start_free_run(stranger.id, length=5, now=NOON)
    del free
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(SoloDailyResult)) == 1
    await anonymize_account(factory, user_id=stranger.id)
    async with factory() as session:
        for model in (SoloRun, SoloServe, SoloDailyResult, SoloBest):
            assert await session.scalar(select(func.count()).select_from(model)) == 0, model


async def test_a_daily_already_past_the_door_is_refused_once_its_account_is_deleted(env):
    # Opening or playing a Daily writes a run, its serves and a result: a
    # deletion that commits after the route's check must not get them back.
    from app.auth.account_data import anonymize_account
    from app.db.models import SoloRun

    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    gone = await player(users, factory, "Gone")
    run = await solo.open_daily(gone.id, DAY, now=NOON)
    await anonymize_account(factory, user_id=gone.id)
    for write in (
        lambda: solo.open_daily(gone.id, DAY, now=NOON),
        lambda: solo.settle(gone.id, run.serves[0].serve_id, outcome="solved", seconds=4, now=NOON),
    ):
        with pytest.raises(SoloRefused) as refused:
            await write()
        assert refused.value.kind == "erased"
    async with factory() as session:
        for model in (SoloRun, SoloServe, SoloDailyResult):
            assert await session.scalar(select(func.count()).select_from(model)) == 0, model


async def test_every_concept_a_position_held_stays_the_day_s_through_two_replacements(env):
    """A position replaced A -> B -> C keeps A that day's: restoring A's
    drawing must not make A tomorrow's (#1493 review)."""
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 7, tag="d")
    early = await player(users, factory, "Early")
    await solo.open_daily(early.id, DAY, now=NOON)
    first = (await _set(factory))[0]
    original_turn, original_concept = first.turn_id, first.concept_id

    async def hide(turn_id, at=NOON):
        async with factory() as session, session.begin():
            await session.execute(
                update(TurnDrawing).where(TurnDrawing.turn_id == turn_id).values(gallery_hidden_at=at)
            )

    for _ in range(2):
        await hide((await _set(factory))[0].turn_id)
        await solo.open_daily(early.id, DAY, now=NOON)
    replaced = (await _set(factory))[0]
    assert replaced.concept_id != original_concept and replaced.replaced_concept_id != original_concept
    await hide(original_turn, at=None)

    # Four fresh candidates and A: with A held back the next day is too thin.
    await _candidates(users, history, factory, 4, tag="n")
    async with factory() as session, session.begin():
        from app.repositories.solo import daily_set
        tomorrow = await daily_set(session, DAY + timedelta(days=1), now=NOON + timedelta(days=1))
    assert tomorrow is None


async def test_a_daily_drawing_left_unnameable_in_a_language_closes_its_door_for_everybody(env):
    """No spare to replace it with: the drawing stays in the set, and every
    player's serve of it stops showing it (R-SOLO-13, #1493 review)."""
    http, users, history, solo, factory = env
    every = {lang: f"u-{lang}" for lang in ("en", "de", "es", "fr", "it", "nl", "pl", "pt")}
    await _candidates(users, history, factory, 4, tag="y")
    _, _, [eight] = await _candidates(users, history, factory, 1, forms=every, tag="f")
    polish = await player(users, factory, "Polish", languages=("pl",))
    stranger = await player(users, factory, "Stranger")
    runs = [await solo.open_daily(who.id, DAY, now=NOON) for who in (polish, stranger)]

    async def door(who, run):
        turns = await _served_turns(factory, run.run_id)
        serve = run.serves[turns.index(UUID(eight.turn_id))]
        return await solo.served_drawing(who.id, serve.serve_id)

    assert await door(polish, runs[0]) is not None
    async with factory() as session, session.begin():
        await session.execute(
            update(PromptVersion)
            .where(PromptVersion.language == "pl", PromptVersion.canonical_answer == "u-pl")
            .values(moderation_state="hidden")
        )
    assert UUID(eight.turn_id) in {row.turn_id for row in await _set(factory)}
    assert await door(polish, runs[0]) is None
    assert await door(stranger, runs[1]) is None


async def test_two_dates_picked_at_once_never_share_a_concept(env, monkeypatch):
    """Today and tomorrow are both open at noon UTC: two first opens at once,
    with five candidates between them, must not both take all five (#1493
    review). PostgreSQL only: it is the database two transactions overlap
    in; SQLite has one writer."""
    http, users, history, solo, factory = env
    async with factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("concurrent transactions are PostgreSQL's")
    await _candidates(users, history, factory, 5)
    import app.repositories.solo as solo_module
    from app.repositories.solo import daily_set

    # Each pick waits, briefly, for the other to have picked as well: without
    # the lock both read the same five before either writes, every time; with
    # it the second cannot start until the first commits, and the wait runs out.
    original, both, picks = solo_module.pick_daily, asyncio.Event(), []

    async def overlapping(*args, **kwargs):
        rows = await original(*args, **kwargs)
        picks.append(rows)
        if len(picks) >= 2:
            both.set()
        try:
            await asyncio.wait_for(both.wait(), 0.5)
        except TimeoutError:
            pass
        return rows

    monkeypatch.setattr(solo_module, "pick_daily", overlapping)

    async def pick(day):
        async with factory() as session, session.begin():
            return await daily_set(session, day, now=NOON)

    picked = await asyncio.gather(pick(DAY), pick(DAY + timedelta(days=1)))
    assert sum(rows is not None for rows in picked) == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(SoloDailySet)) == 5


def test_the_longest_streak_steps_over_a_day_with_no_daily_too():
    from app.solo_rules import longest_daily_streak

    played = [date(2026, 10, d) for d in (1, 2, 3, 6, 7, 9, 10, 11, 12)]
    assert longest_daily_streak([]) == 0
    assert longest_daily_streak(played) == 4
    # The 8th had no Daily: 6 to 12 is one run of six played days.
    assert longest_daily_streak(played, skipped=[date(2026, 10, 8)]) == 6
    # A skipped day only bridges; it is never a day played.
    assert longest_daily_streak([date(2026, 10, 1)], skipped=[date(2026, 10, 2)]) == 1


async def test_the_calendar_reads_a_month_and_the_totals_come_with_me(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    run = await solo.open_daily(stranger.id, DAY, now=NOON)
    await solo.settle(stranger.id, run.serves[0].serve_id, outcome="solved", seconds=4, now=NOON)
    await solo.settle(stranger.id, run.serves[1].serve_id, outcome="timed_out", seconds=30, now=NOON)

    month = await solo.month(stranger.id, date(2026, 10, 1), DAY + timedelta(days=2), now=NOON)
    assert month["month"] == "2026-10" and month["first"] == DAY.isoformat()
    # Every date up to the player's today, and no further.
    assert [day["date"] for day in month["days"]][-1] == "2026-10-17"
    assert len(month["days"]) == 17
    played = {day["date"]: day for day in month["days"]}
    assert played["2026-10-15"]["daily"] is True
    assert played["2026-10-15"]["result"]["solved"] == 1
    # Nobody asked for the 14th: it had no Daily, which is no missed day.
    assert played["2026-10-14"] == {"date": "2026-10-14", "daily": False, "open": False, "result": None}
    september = await solo.month(stranger.id, date(2026, 9, 1), DAY, now=NOON)
    assert len(september["days"]) == 30 and not any(day["result"] for day in september["days"])

    summary = await solo.summary(stranger.id, DAY, now=NOON)
    assert summary["stats"] == {
        "dailiesPlayed": 1, "drawingsPlayed": 2, "drawingsNamed": 1, "longestStreak": 1,
    }

    await sign_in_as(http, factory, stranger.id)
    today = datetime.now(timezone.utc).date()
    later = (today.replace(day=28) + timedelta(days=4)).isoformat()[:7]
    for value in (later, "2026-13", "2026-1", "nope"):
        refused = await http.get(
            "/api/solo/daily/month", params={"today": today.isoformat(), "month": value}
        )
        assert refused.status_code == 422, value
    answered = await http.get(
        "/api/solo/daily/month", params={"today": today.isoformat(), "month": today.isoformat()[:7]}
    )
    assert answered.status_code == 200 and len(answered.json()["days"]) == today.day


async def test_a_run_that_went_nowhere_is_no_best_and_nothing_to_continue(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 3, guessers=1)
    stranger = await player(users, factory, "Stranger")
    # An Endless run that missed its first drawing names nothing.
    run = await solo.start_free_run(stranger.id, length=None, now=NOON)
    [serve] = await solo.serve_next(stranger.id, run.run_id, count=1, now=NOON)
    await solo.settle(stranger.id, serve.serve_id, outcome="given_up", seconds=3, now=NOON)
    # A Quick run started and never served a drawing.
    await solo.start_free_run(stranger.id, length=5, now=NOON)
    summary = await solo.summary(stranger.id, DAY, now=NOON)
    assert summary["bests"] == {} and summary["activeRuns"] == []
    async with factory() as session:
        assert (await session.scalars(select(SoloBest))).all() == []


async def test_a_due_retry_is_picked_before_a_free_run_serves(env):
    """Every open date stored as skipped, five candidates arrive, the retry
    falls due: a free run must not serve one of the five before the retry
    picks them as a Daily, or it hands out that Daily's answer (#1493 review)."""
    http, users, history, solo, factory = env
    from app.repositories.solo import SoloRefused, ensure_open_dailies
    from app.solo_rules import SKIPPED_RETRY

    await _candidates(users, history, factory, 4)
    await ensure_open_dailies(factory, NOON)
    async with factory() as session:
        assert {row.state for row in (await session.scalars(select(SoloDailyDay))).all()} == {"skipped"}
    await _candidates(users, history, factory, 1, tag="b")
    other = await player(users, factory, "Other")
    later = NOON + SKIPPED_RETRY
    run = await solo.start_free_run(other.id, length=5, now=later)
    with pytest.raises(SoloRefused) as refused:
        await solo.serve_next(other.id, run.run_id, count=1, now=later)
    assert refused.value.kind == "empty"
    async with factory() as session:
        assert "set" in {row.state for row in (await session.scalars(select(SoloDailyDay))).all()}

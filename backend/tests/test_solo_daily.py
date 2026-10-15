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

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.api.errors import install_refusal_handler
from app.api.solo import create_solo_router, drawing_limiter, run_limiter, serve_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.db.models import (
    SoloBest,
    SoloDailyDay,
    SoloDailyResult,
    SoloDailySet,
    SoloServe,
    TurnDrawing,
)
from app.repositories.solo import SoloRepository, rebuild_bests
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


async def test_a_thin_day_is_skipped_and_stays_skipped(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 4)
    stranger = await player(users, factory, "Stranger")
    from app.repositories.solo import SoloRefused

    try:
        await solo.open_daily(stranger.id, DAY, now=NOON)
    except SoloRefused as error:
        assert error.kind == "missing"
    else:
        raise AssertionError("a day with four candidates has no Daily")
    await _candidates(users, history, factory, 3, tag="b")
    try:
        await solo.open_daily(stranger.id, DAY, now=NOON)
    except SoloRefused:
        pass
    else:
        raise AssertionError("a skipped day stays skipped")
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
    today = NOON.date().isoformat()
    opened = await http.post(f"/api/solo/daily/{today}")
    if opened.status_code != 200:
        # The route reads the real clock; run the day the server thinks it is.
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
    for day in (real_today - timedelta(days=2), real_today + timedelta(days=2), "2026-13-40"):
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
    await solo.start_free_run(stranger.id, length=10, now=NOON)
    assert await bests() == {"5": 1500, "unlimited": 3}

    async with factory() as session:
        async with session.begin():
            await session.execute(SoloBest.__table__.delete())
            assert await rebuild_bests(session) == 2
    assert await bests() == {"5": 1500, "unlimited": 3}
    summary = await solo.summary(stranger.id, DAY, now=NOON)
    assert summary["bests"] == {"5": 1500, "unlimited": 3}
    assert summary["activeRunId"] is not None


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

"""The Daily archive (#1470).

A date that has ended everywhere is played through the archive's door: a
Daily never started there is recorded late and counts for no streak, one
left unfinished is finished, and one already finished is opened as it was
played, to review. Only Dailies chosen while their date was open are there.
One gate decides who may open the door.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update

from app.api import solo as solo_api
from app.db.models import PromptVersion, SoloDailyDay, SoloDailyResult, SoloDailySet, SoloRun, TurnDrawing
from tests.solo_fixtures import player
from tests.test_api_profiles import sign_in_as
from tests import test_solo_daily

TODAY = datetime.now(timezone.utc).date()
# Ended everywhere, whatever the clock says when the suite runs.
PAST = TODAY - timedelta(days=3)

# The Daily suite's app and seeding: the archive is that Daily, later.
env = test_solo_daily.env
_candidates = test_solo_daily._candidates


def _noon(day):
    return datetime.combine(day, time(12), tzinfo=timezone.utc)


async def _settle_all(http, serves, outcome="solved"):
    for serve in serves:
        answer = await http.post(
            f"/api/solo/serves/{serve['serveId']}/result", json={"outcome": outcome, "seconds": 5}
        )
        assert answer.status_code == 200, answer.text


async def _result(factory, user_id, day):
    async with factory() as session:
        return await session.get(SoloDailyResult, (UUID(user_id), day))


async def test_a_past_day_nobody_opened_has_no_daily_and_gets_none_late(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    refused = await http.post(f"/api/solo/daily/{PAST.isoformat()}")
    assert refused.status_code == 404 and refused.json()["errorCode"] == "no_such_daily"
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(SoloDailyDay)) == 0
    # A date still to come is nobody's yet.
    later = await http.post(f"/api/solo/daily/{(TODAY + timedelta(days=2)).isoformat()}")
    assert later.status_code == 422 and later.json()["errorCode"] == "solo_date_out_of_range"


async def test_a_past_daily_never_started_is_recorded_late_and_counts_for_no_streak(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    on_time = await player(users, factory, "OnTime")
    await solo.open_daily(on_time.id, PAST, now=_noon(PAST))
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    run = (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).json()
    assert run["dailyDate"] == PAST.isoformat()
    await _settle_all(http, run["serves"][:2])
    result = await _result(factory, stranger.id, PAST)
    assert result.started_on_date is False
    assert [mark["late"] for mark in result.marks] == [True, True]
    me = (await http.get("/api/solo/me", params={"today": TODAY.isoformat()})).json()
    assert me["streak"] == 0


async def test_an_unfinished_daily_is_finished_from_the_archive(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    begun = await solo.open_daily(stranger.id, PAST, now=_noon(PAST))
    for serve in begun.serves[:2]:
        await solo.settle(stranger.id, serve.serve_id, outcome="solved", seconds=4, now=_noon(PAST))
    await sign_in_as(http, factory, stranger.id)
    run = (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).json()
    assert run["runId"] == begun.run_id
    assert [serve["outcome"] for serve in run["serves"]][:2] == ["solved", "solved"]
    await _settle_all(http, run["serves"][2:], outcome="given_up")
    result = await _result(factory, stranger.id, PAST)
    assert result.completed_at is not None and result.started_on_date is True
    assert [mark["late"] for mark in result.marks] == [False, False, True, True, True]


async def _calendar(solo, user_id, *, now, archive=True) -> dict:
    """The calendar's dates from a week before PAST to TODAY, by date: the
    months they fall in, read as the page reads them."""
    months = sorted({(TODAY - timedelta(days=offset)).replace(day=1) for offset in range(11)})
    days = {}
    for first in months:
        read = await solo.month(user_id, first, TODAY, now=now, archive=archive)
        days.update({day["date"]: day for day in read["days"]})
    return days


async def test_a_finished_past_daily_opens_as_it_was_played_to_review(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    begun = await solo.open_daily(stranger.id, PAST, now=_noon(PAST))
    for serve in begun.serves:
        await solo.settle(stranger.id, serve.serve_id, outcome="given_up", seconds=9, now=_noon(PAST))
    before = await _result(factory, stranger.id, PAST)
    await sign_in_as(http, factory, stranger.id)
    review = (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).json()
    # The same run, ended, its five with what each came to: nothing new
    # served and nothing recorded.
    assert review["runId"] == begun.run_id and review["state"] == "ended"
    assert [serve["outcome"] for serve in review["serves"]] == ["given_up"] * 5
    assert all(serve["prompt"] for serve in review["serves"])
    after = await _result(factory, stranger.id, PAST)
    assert (after.positions_played, after.solved, after.points) == (
        before.positions_played, before.solved, before.points,
    )
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(SoloRun)) == 1


async def test_the_calendar_opens_the_dailies_there_were_with_what_the_player_made_of_them(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 15)
    stranger = await player(users, factory, "Stranger")
    other = await player(users, factory, "Other")
    days = [PAST, PAST - timedelta(days=1), PAST - timedelta(days=2)]
    for day in days:
        await solo.open_daily(other.id, day, now=_noon(day))
    finished = await solo.open_daily(stranger.id, days[0], now=_noon(days[0]))
    for serve in finished.serves:
        await solo.settle(stranger.id, serve.serve_id, outcome="solved", seconds=4, now=_noon(days[0]))
    part = await solo.open_daily(stranger.id, days[1], now=_noon(days[1]))
    await solo.settle(stranger.id, part.serves[0].serve_id, outcome="given_up", seconds=4, now=_noon(days[1]))
    skipped = PAST - timedelta(days=4)
    async with factory() as session, session.begin():
        session.add(SoloDailyDay(daily_date=skipped, state="skipped", picked_at=_noon(PAST)))

    calendar = await _calendar(solo, stranger.id, now=datetime.now(timezone.utc))
    complete, partial, none = (calendar[day.isoformat()] for day in days)
    assert all(day["daily"] and day["open"] for day in (complete, partial, none))
    assert complete["result"]["completed"] is True and complete["result"]["solved"] == 5
    assert partial["result"]["completed"] is False and partial["result"]["positionsPlayed"] == 1
    assert none["result"] is None
    # A date too thin for a Daily, and one nobody asked for, have none to play.
    for day in (skipped, PAST - timedelta(days=5)):
        assert (calendar[day.isoformat()]["daily"], calendar[day.isoformat()]["open"]) == (False, False)
    # It reaches back to the first Daily there was, played or not.
    read = await solo.month(stranger.id, TODAY.replace(day=1), TODAY, now=datetime.now(timezone.utc))
    assert read["earliest"] == days[-1].isoformat()
    # The gate closed, the calendar still shows the days but opens none.
    closed = await _calendar(solo, stranger.id, now=datetime.now(timezone.utc), archive=False)
    assert not any(day["open"] for day in closed.values())
    assert closed[PAST.isoformat()]["result"]["completed"] is True
    # Closed, it still reaches the player's own first Daily, however played:
    # their finished ones stay reviewable (#1496 review).
    shut = await solo.month(
        stranger.id, TODAY.replace(day=1), TODAY, now=datetime.now(timezone.utc), archive=False
    )
    assert shut["earliest"] == days[1].isoformat()


async def test_one_gate_closes_every_archive_door_and_leaves_today_s(env, monkeypatch):
    http, users, history, solo, factory = env
    # Twice five: a concept is not the Daily twice within sixty days.
    await _candidates(users, history, factory, 12)
    stranger = await player(users, factory, "Stranger")
    await solo.open_daily(stranger.id, PAST, now=_noon(PAST))
    real = solo_api.solo_door_open
    monkeypatch.setattr(
        solo_api, "solo_door_open", lambda **kwargs: kwargs["door"] != "archive" and real(**kwargs)
    )
    await sign_in_as(http, factory, stranger.id)
    for refused in (
        await http.post(f"/api/solo/daily/{PAST.isoformat()}"),
    ):
        assert refused.status_code == 403, refused.text
    assert (await http.post(f"/api/solo/daily/{TODAY.isoformat()}")).status_code == 200


async def test_the_calendar_holds_back_a_date_still_open_somewhere(env):
    """At 05:00 UTC the player's yesterday is still today west of UTC-5:
    played from the archive it would go through today's door and count
    toward a streak (#1496 review)."""
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12)
    other = await player(users, factory, "Other")
    yesterday = TODAY - timedelta(days=1)
    for day in (yesterday, PAST):
        await solo.open_daily(other.id, day, now=_noon(day))
    stranger = await player(users, factory, "Stranger")
    early = datetime.combine(TODAY, time(5), tzinfo=timezone.utc)
    calendar = await _calendar(solo, stranger.id, now=early)
    assert [day for day, read in calendar.items() if read["open"]] == [PAST.isoformat()]
    # Once it has ended everywhere, it is open.
    late = datetime.combine(TODAY, time(15), tzinfo=timezone.utc)
    calendar = await _calendar(solo, stranger.id, now=late)
    assert sorted(day for day, read in calendar.items() if read["open"]) == [
        PAST.isoformat(), yesterday.isoformat(),
    ]


async def test_opening_a_past_daily_never_changes_its_set(env):
    """A past date's set is read as it stands: a replacement walk from it
    would not avoid today's Daily, and could hand a late player today's
    answer (#1496 review). A position whose drawing has gone is given up."""
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12)
    other = await player(users, factory, "Other")
    await solo.open_daily(other.id, PAST, now=_noon(PAST))
    before = [(row.position, row.turn_id) for row in await test_solo_daily._set(factory, PAST)]
    gone = before[0][1]
    async with factory() as session, session.begin():
        await session.execute(
            update(TurnDrawing).where(TurnDrawing.turn_id == gone).values(solo_withdrawn_at=_noon(TODAY))
        )
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    opened = await http.post(f"/api/solo/daily/{PAST.isoformat()}")
    assert opened.status_code == 200, opened.text
    after = [(row.position, row.turn_id) for row in await test_solo_daily._set(factory, PAST)]
    assert after == before
    async with factory() as session:
        assert all(row.replaced_at is None for row in await test_solo_daily._set(factory, PAST))


async def test_a_past_daily_opens_when_one_of_its_prompts_can_no_longer_be_named(env):
    """A takedown can leave a past date's concept with no wording for the
    player, and the set never changes after its date: the other four are
    still played, and that one can only be given up (#1496 review)."""
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12)
    other = await player(users, factory, "Other")
    await solo.open_daily(other.id, PAST, now=_noon(PAST))
    unnamed = (await test_solo_daily._set(factory, PAST))[0]
    async with factory() as session, session.begin():
        await session.execute(
            update(PromptVersion)
            .where(PromptVersion.concept_id == unnamed.concept_id)
            .values(moderation_state="hidden")
        )
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    opened = await http.post(f"/api/solo/daily/{PAST.isoformat()}")
    assert opened.status_code == 200, opened.text
    serves = opened.json()["serves"]
    assert serves[0]["forms"] is None
    assert all(serve["forms"] for serve in serves[1:])

    named = await http.post(
        f"/api/solo/serves/{serves[0]['serveId']}/result", json={"outcome": "solved", "seconds": 5}
    )
    assert named.status_code == 409
    await _settle_all(http, serves[:1], outcome="given_up")
    await _settle_all(http, serves[1:])
    result = await _result(factory, stranger.id, PAST)
    assert result.completed_at is not None and result.solved == 4
    run = (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).json()
    assert run["serves"][0]["outcome"] == "given_up" and run["serves"][0]["prompt"] is None


async def test_a_past_daily_sharing_today_s_concept_waits_and_a_finished_one_is_reviewed(env, monkeypatch):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12)
    other = await player(users, factory, "Other")
    finisher = await player(users, factory, "Finisher")
    begun = await solo.open_daily(finisher.id, PAST, now=_noon(PAST))
    for serve in begun.serves:
        await solo.settle(finisher.id, serve.serve_id, outcome="solved", seconds=4, now=_noon(PAST))
    now = datetime.now(timezone.utc)
    await solo.open_daily(other.id, TODAY, now=now)
    # Today's Daily holds one of the past date's concepts: no pick does that
    # within sixty days, but the archive reaches further back than that.
    past_concept = (await test_solo_daily._set(factory, PAST))[0].concept_id
    async with factory() as session, session.begin():
        await session.execute(
            update(SoloDailySet)
            .where(SoloDailySet.daily_date == TODAY, SoloDailySet.position == 1)
            .values(concept_id=past_concept)
        )
    stranger = await player(users, factory, "Stranger")
    calendar = await _calendar(solo, stranger.id, now=now)
    assert calendar[PAST.isoformat()]["daily"] is True and calendar[PAST.isoformat()]["open"] is False
    await sign_in_as(http, factory, stranger.id)
    held = await http.post(f"/api/solo/daily/{PAST.isoformat()}")
    assert held.status_code == 409, held.text
    # One who finished it reviews it - whatever the gate says (#1496 review).
    real = solo_api.solo_door_open
    monkeypatch.setattr(
        solo_api, "solo_door_open", lambda **kwargs: kwargs["door"] != "archive" and real(**kwargs)
    )
    await sign_in_as(http, factory, finisher.id)
    review = await http.post(f"/api/solo/daily/{PAST.isoformat()}")
    assert review.status_code == 200, review.text
    assert review.json()["runId"] == begun.run_id


async def test_a_daily_played_late_does_not_mark_the_weeks_before_it_missed(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12)
    other = await player(users, factory, "Other")
    early = PAST - timedelta(days=2)
    for day in (early, PAST):
        await solo.open_daily(other.id, day, now=_noon(day))
    stranger = await player(users, factory, "Stranger")
    # Played on its date, then the earlier one from the archive, late.
    on_time = await solo.open_daily(stranger.id, PAST, now=_noon(PAST))
    await solo.settle(stranger.id, on_time.serves[0].serve_id, outcome="solved", seconds=4, now=_noon(PAST))
    late = await solo.open_daily(stranger.id, early, now=datetime.now(timezone.utc), archive=True)
    await solo.settle(
        stranger.id, late.serves[0].serve_id, outcome="solved", seconds=4, now=datetime.now(timezone.utc)
    )
    read = await solo.month(stranger.id, PAST.replace(day=1), TODAY, now=datetime.now(timezone.utc))
    assert read["first"] == PAST.isoformat()

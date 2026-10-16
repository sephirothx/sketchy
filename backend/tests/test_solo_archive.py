"""The Daily archive (#1470).

A date that has ended everywhere is played through the archive's door: a
Daily never started there is recorded late and counts for no streak, one
left unfinished is finished, and one already finished is replayed for fun -
a run beside the date's own that records nothing. Only Dailies chosen while
their date was open are there. One gate decides who may open the door.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update

from app.api import solo as solo_api
from app.db.models import SoloDailyDay, SoloDailyResult, SoloRun, SoloServe, TurnDrawing
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
    assert run["dailyDate"] == PAST.isoformat() and run["replay"] is False
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


async def test_a_finished_daily_is_replayed_for_fun_and_nothing_is_recorded(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    begun = await solo.open_daily(stranger.id, PAST, now=_noon(PAST))
    for serve in begun.serves:
        await solo.settle(stranger.id, serve.serve_id, outcome="given_up", seconds=9, now=_noon(PAST))
    before = await _result(factory, stranger.id, PAST)
    await sign_in_as(http, factory, stranger.id)

    # The date's own door still answers with the Daily as it was played.
    own = (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).json()
    assert own["runId"] == begun.run_id and own["state"] == "ended"

    replay = (await http.post(f"/api/solo/daily/{PAST.isoformat()}/replay")).json()
    assert replay["replay"] is True and replay["runId"] != begun.run_id
    assert replay["mode"] == "daily" and len(replay["serves"]) == 5
    await _settle_all(http, replay["serves"][:1])
    # Asked again, the replay going is resumed rather than begun anew.
    again = (await http.post(f"/api/solo/daily/{PAST.isoformat()}/replay")).json()
    assert again["runId"] == replay["runId"] and again["serves"][0]["outcome"] == "solved"
    await _settle_all(http, again["serves"][1:])
    ended = (await http.get(f"/api/solo/runs/{replay['runId']}")).json()
    assert ended["state"] == "ended" and ended["points"] > 0

    after = await _result(factory, stranger.id, PAST)
    assert (after.solved, after.points, after.marks) == (before.solved, before.points, before.marks)
    # Played through, the replay is done; the next one is a new run.
    fresh = (await http.post(f"/api/solo/daily/{PAST.isoformat()}/replay")).json()
    assert fresh["runId"] not in (replay["runId"], begun.run_id)


async def test_a_replay_of_another_date_abandons_the_one_going(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12)
    stranger = await player(users, factory, "Stranger")
    days = (PAST, PAST - timedelta(days=1))
    for day in days:
        begun = await solo.open_daily(stranger.id, day, now=_noon(day))
        for serve in begun.serves:
            await solo.settle(stranger.id, serve.serve_id, outcome="solved", seconds=4, now=_noon(day))
    await sign_in_as(http, factory, stranger.id)
    first = (await http.post(f"/api/solo/daily/{days[0].isoformat()}/replay")).json()
    second = (await http.post(f"/api/solo/daily/{days[1].isoformat()}/replay")).json()
    assert second["runId"] != first["runId"]
    async with factory() as session:
        states = dict(
            (await session.execute(
                select(SoloRun.id, SoloRun.state).where(SoloRun.replay.is_(True))
            )).all()
        )
    assert states == {UUID(first["runId"]): "abandoned", UUID(second["runId"]): "active"}


async def test_only_a_finished_past_daily_is_replayed(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    begun = await solo.open_daily(stranger.id, PAST, now=_noon(PAST))
    await solo.settle(stranger.id, begun.serves[0].serve_id, outcome="solved", seconds=4, now=_noon(PAST))
    await sign_in_as(http, factory, stranger.id)
    unfinished = await http.post(f"/api/solo/daily/{PAST.isoformat()}/replay")
    assert unfinished.status_code == 409
    never = await http.post(f"/api/solo/daily/{(PAST - timedelta(days=5)).isoformat()}/replay")
    assert never.status_code == 404
    today = await http.post(f"/api/solo/daily/{TODAY.isoformat()}/replay")
    assert today.status_code == 422


async def test_the_archive_lists_the_dailies_there_were_with_what_the_player_made_of_them(env):
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
    async with factory() as session, session.begin():
        session.add(SoloDailyDay(daily_date=PAST - timedelta(days=4), state="skipped", picked_at=_noon(PAST)))
    await sign_in_as(http, factory, stranger.id)

    page = (await http.get("/api/solo/daily/archive", params={"today": TODAY.isoformat()})).json()
    assert [entry["date"] for entry in page["days"]] == [day.isoformat() for day in days]
    assert page["next"] is None
    complete, partial, none = (entry["result"] for entry in page["days"])
    assert complete["completed"] is True and complete["solved"] == 5
    assert partial["completed"] is False and partial["positionsPlayed"] == 1
    assert none is None

    first, cursor = await solo.archive(stranger.id, TODAY, before=None, limit=2, now=datetime.now(timezone.utc))
    assert [entry["date"] for entry in first] == [day.isoformat() for day in days[:2]]
    rest, end = await solo.archive(
        stranger.id, TODAY, before=datetime.fromisoformat(cursor).date(), limit=2,
        now=datetime.now(timezone.utc),
    )
    assert [entry["date"] for entry in rest] == [days[2].isoformat()] and end is None


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
        await http.get("/api/solo/daily/archive", params={"today": TODAY.isoformat()}),
        await http.post(f"/api/solo/daily/{PAST.isoformat()}"),
        await http.post(f"/api/solo/daily/{PAST.isoformat()}/replay"),
    ):
        assert refused.status_code == 403, refused.text
    assert (await http.post(f"/api/solo/daily/{TODAY.isoformat()}")).status_code == 200


async def test_the_archive_holds_back_a_date_still_open_somewhere(env):
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
    listed, _ = await solo.archive(stranger.id, TODAY, before=None, limit=30, now=early)
    assert [entry["date"] for entry in listed] == [PAST.isoformat()]
    # Once it has ended everywhere, it is there.
    late = datetime.combine(TODAY, time(15), tzinfo=timezone.utc)
    listed, _ = await solo.archive(stranger.id, TODAY, before=None, limit=30, now=late)
    assert [entry["date"] for entry in listed] == [yesterday.isoformat(), PAST.isoformat()]


async def test_a_replay_resumed_takes_a_drawing_replaced_since(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 7)
    stranger = await player(users, factory, "Stranger")
    begun = await solo.open_daily(stranger.id, PAST, now=_noon(PAST))
    for serve in begun.serves:
        await solo.settle(stranger.id, serve.serve_id, outcome="solved", seconds=4, now=_noon(PAST))
    await sign_in_as(http, factory, stranger.id)
    replay = (await http.post(f"/api/solo/daily/{PAST.isoformat()}/replay")).json()

    async def turns():
        async with factory() as session:
            return list((await session.scalars(
                select(SoloServe.turn_id).where(SoloServe.run_id == UUID(replay["runId"]))
                .order_by(SoloServe.position)
            )).all())

    hidden = (await turns())[2]
    async with factory() as session, session.begin():
        await session.execute(
            update(TurnDrawing).where(TurnDrawing.turn_id == hidden).values(gallery_hidden_at=_noon(TODAY))
        )
    again = (await http.post(f"/api/solo/daily/{PAST.isoformat()}/replay")).json()
    assert again["runId"] == replay["runId"]
    assert hidden not in await turns()


async def test_recovering_a_replay_by_its_id_never_starts_another(env):
    """A tab recovering its replay names it: if another tab began a replay
    of another date meanwhile, the recovery is refused and nothing new is
    started or abandoned (#1496 review)."""
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12)
    stranger = await player(users, factory, "Stranger")
    days = (PAST, PAST - timedelta(days=1))
    for day in days:
        begun = await solo.open_daily(stranger.id, day, now=_noon(day))
        for serve in begun.serves:
            await solo.settle(stranger.id, serve.serve_id, outcome="solved", seconds=4, now=_noon(day))
    await sign_in_as(http, factory, stranger.id)
    first = (await http.post(f"/api/solo/daily/{days[0].isoformat()}/replay")).json()
    # Its own tab, still the replay going: brought up to date, the same run.
    same = await http.post(f"/api/solo/daily/{days[0].isoformat()}/replay", params={"run": first["runId"]})
    assert same.status_code == 200 and same.json()["runId"] == first["runId"]

    other = (await http.post(f"/api/solo/daily/{days[1].isoformat()}/replay")).json()
    stale = await http.post(f"/api/solo/daily/{days[0].isoformat()}/replay", params={"run": first["runId"]})
    assert stale.status_code == 409
    async with factory() as session:
        replays = dict(
            (await session.execute(select(SoloRun.id, SoloRun.state).where(SoloRun.replay.is_(True)))).all()
        )
    assert replays == {UUID(first["runId"]): "abandoned", UUID(other["runId"]): "active"}

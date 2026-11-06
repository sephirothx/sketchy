"""Solo's two doors that come with the supporter pass (#1477, R-SUP-18)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import update

from app.db.models import SoloDailySet, SupportPurchase, generate_uuid
from app.services.solo_access import SUPPORTER_DOORS, free_run_door, solo_door_open

from tests import test_solo_daily
from tests.dbfixtures import lapse_passes
from tests.solo_fixtures import player
from tests.test_api_profiles import sign_in_as
from tests.test_solo_archive import PAST, TODAY, _candidates, _noon, _settle_all, env  # noqa: F401

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def tier(monkeypatch):
    monkeypatch.setenv("SUPPORT_PROVIDER", "stub")


async def _pass(factory, user_id, *, end=NOW + timedelta(days=30)):
    async with factory() as session:
        async with session.begin():
            session.add(
                SupportPurchase(
                    id=generate_uuid(),
                    user_id=user_id,
                    provider="stub",
                    provider_event_id=f"e-{user_id}",
                    provider_order_id=f"o-{user_id}",
                    kind="purchase",
                    period_start=NOW - timedelta(days=1),
                    period_end=end,
                    amount_minor=1900,
                    currency="EUR",
                )
            )


async def _lapse(factory, user_id):
    await lapse_passes(factory, user_id, NOW - timedelta(minutes=1))


async def _me(http):
    return (await http.get(f"/api/solo/me?today={TODAY.isoformat()}")).json()


def test_the_gate_is_one_function_and_opens_only_what_it_should():
    registered = {"state": "registered", "is_anonymous": False}
    assert solo_door_open(**registered, door="daily_today", perks=False)
    assert solo_door_open(**registered, door=free_run_door(5), perks=False)
    assert solo_door_open(**registered, door=free_run_door(10), perks=False)
    for door in SUPPORTER_DOORS:
        assert not solo_door_open(**registered, door=door, perks=False)
        assert solo_door_open(**registered, door=door, perks=True)
    assert not solo_door_open(state="anonymous", is_anonymous=True, door="free_5", perks=True)


async def test_a_non_supporter_sees_the_doors_closed_and_gets_supporter_only(env):  # noqa: F811
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    assert (await _me(http))["doors"] == {"freeUnlimited": False, "archive": False}
    refused = await http.post("/api/solo/runs", json={"length": None})
    assert refused.status_code == 403 and refused.json()["errorCode"] == "supporter_only"
    assert refused.json()["params"]["door"] == "free_unlimited"
    # Today's and the short runs stay everybody's.
    assert (await http.post("/api/solo/runs", json={"length": 5})).status_code == 201


async def test_a_supporter_opens_both_doors(env):  # noqa: F811
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    other = await player(users, factory, "OnTime")
    await solo.open_daily(other.id, PAST, now=_noon(PAST))
    fan = await player(users, factory, "Fan")
    await _pass(factory, UUID(fan.id))
    await sign_in_as(http, factory, fan.id)
    assert (await _me(http))["doors"] == {"freeUnlimited": True, "archive": True}
    assert (await http.post("/api/solo/runs", json={"length": None})).status_code == 201
    assert (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).status_code == 200


async def test_a_run_in_progress_when_a_pass_ends_finishes(env):  # noqa: F811
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    fan = await player(users, factory, "Fan")
    await _pass(factory, UUID(fan.id))
    await sign_in_as(http, factory, fan.id)
    run = (await http.post("/api/solo/runs", json={"length": None})).json()
    await _lapse(factory, UUID(fan.id))
    assert (await http.get(f"/api/solo/runs/{run['runId']}")).status_code == 200
    assert (await http.post(f"/api/solo/runs/{run['runId']}/serves?count=1")).status_code == 200
    # A new one is another matter.
    assert (await http.post("/api/solo/runs", json={"length": None})).status_code == 403


async def test_a_past_daily_started_before_a_lapse_stays_open(env):  # noqa: F811
    http, users, history, solo, factory = env
    # Twice five: a concept is not the Daily twice within sixty days.
    await _candidates(users, history, factory, 12)
    other = await player(users, factory, "OnTime")
    await solo.open_daily(other.id, PAST, now=_noon(PAST))
    older = PAST - timedelta(days=1)
    await solo.open_daily(other.id, older, now=_noon(older))
    fan = await player(users, factory, "Fan")
    await _pass(factory, UUID(fan.id))
    await sign_in_as(http, factory, fan.id)
    run = (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).json()
    await _settle_all(http, run["serves"][:1], outcome="given_up")
    # Opened and never answered is not started.
    assert (await http.post(f"/api/solo/daily/{older.isoformat()}")).status_code == 200
    await _lapse(factory, UUID(fan.id))
    assert (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).status_code == 200
    refused = await http.post(f"/api/solo/daily/{older.isoformat()}")
    assert refused.status_code == 403 and refused.json()["errorCode"] == "supporter_only"
    month = (
        await http.get(
            f"/api/solo/daily/month?today={TODAY.isoformat()}&month={PAST.isoformat()[:7]}"
        )
    ).json()
    days = {day["date"]: day for day in month["days"]}
    assert days[PAST.isoformat()]["open"] is True
    if older.isoformat() in days:
        assert days[older.isoformat()]["open"] is False


async def test_saved_ids_cannot_begin_a_past_daily_after_a_lapse(env):  # noqa: F811
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12)
    other = await player(users, factory, "OnTime")
    await solo.open_daily(other.id, PAST, now=_noon(PAST))
    fan = await player(users, factory, "Fan")
    await _pass(factory, UUID(fan.id))
    await sign_in_as(http, factory, fan.id)
    run = (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).json()
    await _lapse(factory, UUID(fan.id))
    first = run["serves"][0]["serveId"]
    answer = await http.post(
        f"/api/solo/serves/{first}/result", json={"outcome": "given_up", "seconds": 5}
    )
    assert answer.status_code == 403 and answer.json()["errorCode"] == "supporter_only"
    read = await http.get(f"/api/solo/runs/{run['runId']}")
    assert read.status_code == 403 and read.json()["errorCode"] == "supporter_only"
    drawing = await http.get(f"/api/solo/serves/{first}/drawing")
    assert drawing.status_code == 404 and drawing.json()["errorCode"] == "no_such_drawing"
    # And it did not make the date a started one.
    assert (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).status_code == 403


async def test_a_past_daily_begun_with_a_pass_is_finished_after_a_lapse(env):  # noqa: F811
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 12)
    other = await player(users, factory, "OnTime")
    await solo.open_daily(other.id, PAST, now=_noon(PAST))
    fan = await player(users, factory, "Fan")
    await _pass(factory, UUID(fan.id))
    await sign_in_as(http, factory, fan.id)
    run = (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).json()
    await _settle_all(http, run["serves"][:1], outcome="given_up")
    await _lapse(factory, UUID(fan.id))
    assert (await http.get(f"/api/solo/runs/{run['runId']}")).status_code == 200
    # Begun with a pass, so its drawings stay, the unanswered ones too.
    assert (await http.get(f"/api/solo/serves/{run['serves'][1]['serveId']}/drawing")).status_code == 200
    await _settle_all(http, run["serves"][1:], outcome="given_up")
    assert (await http.get(f"/api/solo/runs/{run['runId']}")).status_code == 200


async def test_a_started_daily_held_back_is_not_offered_after_a_lapse(env):  # noqa: F811
    http, users, history, solo, factory = env
    # Five for the past date and five for each date open now: up to three of them,
    # picked oldest first, so today's has its own at any hour of the day.
    await _candidates(users, history, factory, 20)
    other = await player(users, factory, "OnTime")
    await solo.open_daily(other.id, PAST, now=_noon(PAST))
    fan = await player(users, factory, "Fan")
    await _pass(factory, UUID(fan.id))
    await sign_in_as(http, factory, fan.id)
    run = (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).json()
    await _settle_all(http, run["serves"][:1], outcome="given_up")
    await _lapse(factory, UUID(fan.id))
    # Today's Daily takes one of its concepts: the door would answer 409.
    await solo.open_daily(other.id, TODAY, now=NOW)
    past_concept = (await test_solo_daily._set(factory, PAST))[0].concept_id
    async with factory() as session, session.begin():
        await session.execute(
            update(SoloDailySet)
            .where(SoloDailySet.daily_date == TODAY, SoloDailySet.position == 1)
            .values(concept_id=past_concept)
        )
    month = (
        await http.get(
            f"/api/solo/daily/month?today={TODAY.isoformat()}&month={PAST.isoformat()[:7]}"
        )
    ).json()
    day = next(day for day in month["days"] if day["date"] == PAST.isoformat())
    assert day["open"] is False
    assert (await http.post(f"/api/solo/daily/{PAST.isoformat()}")).status_code == 409


async def test_with_no_provider_every_door_stays_open(env, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SUPPORT_PROVIDER")
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    assert (await _me(http))["doors"] == {"freeUnlimited": True, "archive": True}
    assert (await http.post("/api/solo/runs", json={"length": None})).status_code == 201

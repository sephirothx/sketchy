"""Solo's doors at launch (owner's decision, 2026-11-23): today's Daily alone.

The free runs and the Daily archive stay built behind the one gate
(`services/solo_access`); these hold the gate as it ships. A registered player
at a closed door is told it is closed, never asked to make the account they
have; a guest is still asked for one. A past Daily is never played late - not
opened, and not answered from a run begun on its date - but one finished is
still the player's to review, and the calendar still reads every month.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from app.services import solo_access
from tests import test_solo_daily
from tests.solo_fixtures import player
from tests.test_api_profiles import sign_in_as

TODAY = datetime.now(timezone.utc).date()
# Ended everywhere, whatever the clock says when the suite runs.
PAST = TODAY - timedelta(days=3)

env = test_solo_daily.env
_candidates = test_solo_daily._candidates


def _noon(day):
    return datetime.combine(day, time(12), tzinfo=timezone.utc)


def test_only_todays_daily_is_open():
    assert solo_access.OPEN_DOORS == {"daily_today"}
    for door in solo_access.ALL_DOORS:
        assert solo_access.solo_door_open(state="registered", is_anonymous=False, door=door) is (
            door == "daily_today"
        )
        assert solo_access.solo_door_open(state="registered", is_anonymous=True, door=door) is False


async def test_a_free_run_is_refused_as_closed_and_the_page_is_told(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    someone = await player(users, factory, "Someone")
    await sign_in_as(http, factory, someone.id)
    for length in (5, 10, None):
        answer = await http.post("/api/solo/runs", json={"length": length})
        assert answer.status_code == 403, answer.text
        assert answer.json()["errorCode"] == "solo_door_closed"
    me = (await http.get("/api/solo/me", params={"today": TODAY.isoformat()})).json()
    assert me["doors"] == {"free5": False, "free10": False, "freeUnlimited": False, "archive": False}
    # Today's Daily is still everybody's, and says when its date ends
    # everywhere: 14 h after the next UTC midnight.
    today = await http.post(f"/api/solo/daily/{TODAY.isoformat()}")
    assert today.status_code == 200, today.text
    ends = datetime.fromisoformat(today.json()["dailyEndsAt"])
    assert ends == datetime.combine(TODAY + timedelta(days=1), time(14), tzinfo=timezone.utc)


async def test_a_past_daily_is_not_played_late(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    on_time = await player(users, factory, "OnTime")
    await solo.open_daily(on_time.id, PAST, now=_noon(PAST))
    stranger = await player(users, factory, "Stranger")
    await sign_in_as(http, factory, stranger.id)
    refused = await http.post(f"/api/solo/daily/{PAST.isoformat()}")
    assert refused.status_code == 403 and refused.json()["errorCode"] == "solo_door_closed"
    # Nor one begun on its date and left unfinished: its drawings stay unanswered.
    begun = await solo.open_daily(stranger.id, PAST, now=_noon(PAST))
    await solo.settle(stranger.id, begun.serves[0].serve_id, outcome="solved", seconds=4, now=_noon(PAST))
    again = await http.post(f"/api/solo/daily/{PAST.isoformat()}")
    assert again.status_code == 403 and again.json()["errorCode"] == "solo_door_closed"
    late = await http.post(
        f"/api/solo/serves/{begun.serves[1].serve_id}/result", json={"outcome": "solved", "seconds": 5}
    )
    assert late.status_code == 403 and late.json()["errorCode"] == "solo_door_closed"
    # The calendar still shows the day, as one it cannot open.
    month = (
        await http.get(
            "/api/solo/daily/month",
            params={"today": TODAY.isoformat(), "month": PAST.strftime("%Y-%m")},
        )
    ).json()
    day = next(day for day in month["days"] if day["date"] == PAST.isoformat())
    assert day["open"] is False and day["result"]["positionsPlayed"] == 1


async def test_a_finished_past_daily_still_opens_to_review(env):
    http, users, history, solo, factory = env
    await _candidates(users, history, factory, 6)
    stranger = await player(users, factory, "Stranger")
    begun = await solo.open_daily(stranger.id, PAST, now=_noon(PAST))
    for serve in begun.serves:
        await solo.settle(stranger.id, serve.serve_id, outcome="given_up", seconds=9, now=_noon(PAST))
    await sign_in_as(http, factory, stranger.id)
    review = await http.post(f"/api/solo/daily/{PAST.isoformat()}")
    assert review.status_code == 200, review.text
    assert review.json()["runId"] == begun.run_id


async def test_a_guest_is_asked_for_an_account_not_told_the_door_is_closed(env):
    http, users, history, solo, factory = env
    guest = await users.create_anonymous(display_name="Visitor")
    await sign_in_as(http, factory, guest.id)
    for length in (5, None):
        answer = await http.post("/api/solo/runs", json={"length": length})
        assert answer.status_code == 403 and answer.json()["errorCode"] == "account_required"

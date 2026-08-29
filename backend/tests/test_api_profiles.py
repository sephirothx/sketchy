"""The public profile endpoints: stats, history pages, and who may see detail."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.profiles import create_profile_router, profile_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.db.models import Base, generate_uuid
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    ScoreEventInput,
    TurnDrawingInput,
    TurnGuessInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)

pytestmark = pytest.mark.asyncio

START = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    profile_limiter.reset()

    users = SqlAlchemyUserRepository(session_factory)
    history = SqlAlchemyGameHistoryRepository(session_factory)
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(create_profile_router(users, history))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, users, history, session_factory
    await engine.dispose()


async def sign_in_as(http, session_factory, user_id: str) -> None:
    issued = await create_session(
        session_factory, user_id=user_id, device_label="Test browser"
    )
    http.cookies.set(COOKIE_NAME, issued.token)


async def record_game(
    history, users, *, winner, loser, index: int = 0, drawing: bytes | None = None
) -> str:
    winner_seat = str(generate_uuid())
    loser_seat = str(generate_uuid())
    turn_id = str(generate_uuid())
    record_game.last_turn_id = turn_id
    drawer_bonus_event_id = str(generate_uuid())
    return await history.save_game(
        GameRecordInput(
            room_name=f"Studio {index}",
            scoring_mode="default",
            scoring_version=1,
            score_ledger_version=1,
            rule_snapshot_version=1,
            hint_mode="checkpoints",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=START + timedelta(hours=index),
            finished_at=START + timedelta(hours=index, minutes=10),
        ),
        [
            GameParticipantInput(
                user_id=winner,
                final_score=300,
                final_rank=1,
                seat_id=winner_seat,
                display_name="Ann",
            ),
            GameParticipantInput(
                user_id=loser,
                final_score=100,
                final_rank=2,
                seat_id=loser_seat,
                display_name="Bob",
            ),
        ],
        [
            TurnRecordInput(
                id=turn_id,
                round_number=1,
                turn_number=1,
                drawer_user_id=winner,
                drawer_seat_id=winner_seat,
                prompt="jackpot",
                duration_seconds=42.5,
                guesser_count=1,
                participant_outcomes=(
                    TurnParticipantOutcomeInput(
                        seat_id=loser_seat,
                        user_id=loser,
                        eligible=True,
                        eligibility_reason="eligible",
                        outcome="correct",
                        terminal_state="active",
                        correct_guess_time_seconds=12.0,
                    ),
                ),
            )
        ],
        [
            TurnGuessInput(
                turn_id=turn_id,
                user_id=loser,
                seat_id=loser_seat,
                points_awarded=100,
                guess_time_seconds=12.0,
            )
        ],
        [
            ScoreEventInput(
                id=str(generate_uuid()),
                participant_seat_id=loser_seat,
                participant_user_id=loser,
                turn_id=turn_id,
                event_order=1,
                event_type="guess_award",
                points_delta=100,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            ScoreEventInput(
                id=drawer_bonus_event_id,
                participant_seat_id=winner_seat,
                participant_user_id=winner,
                turn_id=turn_id,
                event_order=2,
                event_type="drawer_bonus",
                points_delta=100,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            ScoreEventInput(
                id=str(generate_uuid()),
                participant_seat_id=winner_seat,
                participant_user_id=winner,
                event_order=3,
                event_type="correction",
                points_delta=200,
                scoring_version=1,
                rule_snapshot_version=1,
                corrects_event_id=drawer_bonus_event_id,
            ),
        ],
        [TurnDrawingInput(turn_id=turn_id, payload=drawing)] if drawing else None,
    )


async def test_stats_carry_the_account_they_describe(env):
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    await record_game(history, users, winner=ann.id, loser=bob.id)

    response = await http.get(f"/api/users/{ann.id}/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["displayName"] == "Ann"
    assert body["user"]["isAnonymous"] is True
    assert body["stats"]["gamesPlayed"] == 1
    assert body["stats"]["gamesWon"] == 1
    assert body["stats"]["winRate"] == 1.0
    assert body["stats"]["drawingsMade"] == 1
    assert body["stats"]["promptsGuessed"] == 0


async def test_stats_for_an_unknown_player_are_a_404_not_a_row_of_zeroes(env):
    http, *_ = env
    response = await http.get("/api/users/nobody/stats")
    assert response.status_code == 404


async def test_stats_are_readable_without_a_session(env):
    """Viewing another player's profile cannot require being that player."""
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    await record_game(history, users, winner=ann.id, loser=bob.id)

    assert (await http.get(f"/api/users/{ann.id}/stats")).status_code == 200
    assert (await http.get(f"/api/users/{ann.id}/games")).status_code == 200


async def test_history_pages_report_whether_more_remain(env):
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    for index in range(3):
        await record_game(history, users, winner=ann.id, loser=bob.id, index=index)

    first = (await http.get(f"/api/users/{ann.id}/games?limit=2")).json()
    assert len(first["games"]) == 2
    assert first["hasMore"] is True

    second = (await http.get(f"/api/users/{ann.id}/games?limit=2&offset=2")).json()
    assert len(second["games"]) == 1
    assert second["hasMore"] is False

    # Newest first, and each row carries the standings.
    assert first["games"][0]["roomName"] == "Studio 2"
    assert [p["finalRank"] for p in first["games"][0]["participants"]] == [1, 2]


async def test_timestamps_are_serialized_with_an_offset(env):
    """SQLite hands back naive datetimes, and an ISO string with no offset is
    read by the browser as local time - shifting every game by the caller's."""
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    await record_game(history, users, winner=ann.id, loser=bob.id)

    profile = (await http.get(f"/api/users/{ann.id}/stats")).json()
    game = (await http.get(f"/api/users/{ann.id}/games")).json()["games"][0]

    for label, value in (
        ("createdAt", profile["user"]["createdAt"]),
        ("lastLoginAt", profile["user"]["lastLoginAt"]),
        ("startedAt", game["startedAt"]),
        ("finishedAt", game["finishedAt"]),
    ):
        assert datetime.fromisoformat(value).tzinfo is not None, label

    assert datetime.fromisoformat(game["startedAt"]) == START


async def test_history_page_size_is_bounded(env):
    http, users, _, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    assert (await http.get(f"/api/users/{ann.id}/games?limit=500")).status_code == 422
    assert (await http.get(f"/api/users/{ann.id}/games?offset=-1")).status_code == 422


async def test_participants_see_the_turn_by_turn_detail(env):
    http, users, history, session_factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id)
    await sign_in_as(http, session_factory, bob.id)

    body = (await http.get(f"/api/games/{game_id}")).json()

    assert body["roomName"] == "Studio 0"
    assert body["scoringVersion"] == 1
    assert body["scoreLedgerVersion"] == 1
    assert body["ruleSnapshotVersion"] == 1
    assert body["ruleSnapshot"] == {}
    assert [event["eventType"] for event in body["scoreEvents"]] == [
        "guess_award",
        "drawer_bonus",
        "correction",
    ]
    assert sum(
        event["pointsDelta"]
        for event in body["scoreEvents"]
        if event["participantUserId"] == ann.id
    ) == 300
    assert body["scoreEvents"][2]["correctsEventId"] == body["scoreEvents"][1]["id"]
    assert body["promptSourceMode"] == "custom"
    assert len(body["turns"]) == 1
    assert body["turns"][0]["prompt"] == "jackpot"
    assert body["turns"][0]["promptVersionId"] is None
    assert body["turns"][0]["promptSourceKind"] == "custom"
    assert body["turns"][0]["promptOffers"] == []
    assert body["turns"][0]["drawerDisplayName"] == "Ann"
    assert body["turns"][0]["drawerNameColor"] is None
    assert body["turns"][0]["drawerIsAnonymous"] is True
    assert body["turns"][0]["guesses"][0]["displayName"] == "Bob"
    assert body["turns"][0]["guesses"][0]["nameColor"] is None
    assert body["turns"][0]["guesses"][0]["isAnonymous"] is True
    assert body["turns"][0]["guesses"][0]["pointsAwarded"] == 100
    assert body["turns"][0]["participantOutcomes"] == [
        {
            "seatId": body["turns"][0]["guesses"][0]["seatId"],
            "eligible": True,
            "eligibilityReason": "eligible",
            "outcome": "correct",
            "terminalState": "active",
            "correctGuessTimeSeconds": 12.0,
            "wrongGuessCount": 0,
            "nearMissCount": 0,
            "hintsUsed": 0,
            "pointsSpentOnHints": 0,
        }
    ]


async def test_a_stranger_cannot_read_the_words_of_a_game_they_did_not_play(env):
    http, users, history, session_factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    outsider = await users.create_anonymous(display_name="Nosy")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id)

    assert (await http.get(f"/api/games/{game_id}")).status_code == 404

    await sign_in_as(http, session_factory, outsider.id)
    assert (await http.get(f"/api/games/{game_id}")).status_code == 404


def _skch() -> bytes:
    fixtures = json.loads(
        (Path(__file__).parents[2] / "fixtures" / "canvas_protocol_v1.json").read_text()
    )
    entry = next(
        item for item in fixtures["histories"] if item["name"] == "representative"
    )
    return bytes.fromhex(entry["binary"])


async def test_a_participant_receives_the_drawing_in_wire_form(env):
    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    blob = _skch()
    game_id = await record_game(
        history, users, winner=ann.id, loser=bob.id, drawing=blob
    )
    await sign_in_as(http, factory, ann.id)

    response = await http.get(
        f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    # Participant-scoped bytes must never land in a shared cache.
    assert "private" in response.headers["cache-control"]
    assert response.content == blob, "the client must get exactly what it decodes"


async def test_the_game_detail_says_which_turns_have_a_drawing(env):
    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    game_id = await record_game(
        history, users, winner=ann.id, loser=bob.id, drawing=_skch()
    )
    await sign_in_as(http, factory, ann.id)

    detail = (await http.get(f"/api/games/{game_id}")).json()

    turn = detail["turns"][0]
    assert turn["drawingStatus"] == "ready"
    assert turn["id"] == record_game.last_turn_id


async def test_a_stranger_is_told_the_drawing_does_not_exist(env):
    """404 rather than 403: whether a game exists is not a stranger's business."""

    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    outsider = await users.create_anonymous(display_name="Cid")
    game_id = await record_game(
        history, users, winner=ann.id, loser=bob.id, drawing=_skch()
    )
    turn_id = record_game.last_turn_id
    await sign_in_as(http, factory, outsider.id)

    response = await http.get(f"/api/games/{game_id}/turns/{turn_id}/drawing")

    assert response.status_code == 404


async def test_a_signed_out_visitor_gets_nothing(env):
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    game_id = await record_game(
        history, users, winner=ann.id, loser=bob.id, drawing=_skch()
    )

    response = await http.get(
        f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing"
    )

    assert response.status_code == 404


async def test_a_turn_from_another_game_cannot_be_borrowed(env):
    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    mine = await record_game(history, users, winner=ann.id, loser=bob.id)
    await record_game(
        history, users, winner=bob.id, loser=ann.id, index=1, drawing=_skch()
    )
    other_turn = record_game.last_turn_id
    await sign_in_as(http, factory, ann.id)

    response = await http.get(f"/api/games/{mine}/turns/{other_turn}/drawing")

    assert response.status_code == 404


async def test_a_turn_whose_drawing_was_never_kept_has_none_to_fetch(env):
    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id)
    await sign_in_as(http, factory, ann.id)

    response = await http.get(
        f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing"
    )

    assert response.status_code == 404

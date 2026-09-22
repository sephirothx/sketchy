"""The public profile endpoints: stats, history pages, and who may see detail."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_refusal_handler
from app.api.gallery import create_gallery_router
from app.api.profiles import create_profile_router, profile_limiter
from app.auth.middleware import SessionAuthMiddleware
from app.auth.sessions import COOKIE_NAME, create_session
from app.db.models import generate_uuid
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    ScoreEventInput,
    TurnDrawingInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
)

from tests.dbfixtures import create_test_db


START = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def env():
    session_factory, engine = await create_test_db()
    profile_limiter.reset()

    users = SqlAlchemyUserRepository(session_factory)
    history = SqlAlchemyGameHistoryRepository(session_factory)
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(create_profile_router(users, history))
    app.include_router(create_gallery_router(history))

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
    history,
    users,
    *,
    winner,
    loser,
    index: int = 0,
    drawing: bytes | None = None,
    visibility: str = "public",
) -> str:
    winner_seat = str(generate_uuid())
    loser_seat = str(generate_uuid())
    turn_id = str(generate_uuid())
    record_game.last_turn_id = turn_id
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
            visibility=visibility,
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
                        points_awarded=100,
                    ),
                ),
            )
        ],
        [
            ScoreEventInput(
                participant_seat_id=loser_seat,
                participant_user_id=loser,
                turn_id=turn_id,
                event_order=1,
                event_type="guess_award",
                points_delta=100,
            ),
            ScoreEventInput(
                participant_seat_id=winner_seat,
                participant_user_id=winner,
                turn_id=turn_id,
                event_order=2,
                event_type="drawer_bonus",
                points_delta=100,
            ),
            ScoreEventInput(
                participant_seat_id=winner_seat,
                participant_user_id=winner,
                event_order=3,
                event_type="correction",
                points_delta=200,
                corrects_event_order=2,
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


async def test_the_public_profile_is_the_presentation_a_seat_already_shows(env):
    """Role, last login and username stay on `/auth/me` (#469): the first
    names staff to whoever is hunting for them, the second is a schedule,
    the third is the login identifier the nickname lookup is throttled to
    protect."""
    http, users, _, _ = env
    ann = await users.create_anonymous(display_name="Ann")

    body = (await http.get(f"/api/users/{ann.id}/stats")).json()

    assert set(body["user"]) == {
        "id",
        "displayName",
        "nameColor",
        "avatarUrl",
        "isAnonymous",
        "createdAt",
        "isOnline",
        "lastSeenAt",
    }


async def test_the_profile_says_whether_the_player_is_here_or_when_they_last_were(env):
    """Online is the presence registry's answer; otherwise the time the
    account's last socket closed, null for one that never connected."""
    http, users, history, session_factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    online = {ann.id}
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.include_router(
        create_profile_router(users, history, is_online=lambda user_id: user_id in online)
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(f"/api/users/{ann.id}/stats")).json()["user"]["isOnline"] is True

        never = (await client.get(f"/api/users/{bob.id}/stats")).json()["user"]
        assert never["isOnline"] is False
        assert never["lastSeenAt"] is None

        await users.touch_last_seen(bob.id)
        gone = (await client.get(f"/api/users/{bob.id}/stats")).json()["user"]
        assert gone["isOnline"] is False
        assert datetime.fromisoformat(gone["lastSeenAt"]).tzinfo is not None


async def test_a_private_rooms_game_is_shown_only_to_the_players_who_were_in_it(env):
    """Two games on Ann's profile, one from a public room and one from a
    private room (#469). Bob, who sat in both, sees both. Cara, who sat in
    neither, and a visitor with no session see only the public one - the
    lobby listed that room with its players; nobody listed the other."""
    http, users, history, session_factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    cara = await users.create_anonymous(display_name="Cara")
    public_game = await record_game(history, users, winner=ann.id, loser=bob.id, index=0)
    private_game = await record_game(
        history, users, winner=ann.id, loser=bob.id, index=1, visibility="private"
    )

    def ids(body):
        return {game["id"] for game in body["games"]}

    visitor = (await http.get(f"/api/users/{ann.id}/games")).json()
    assert ids(visitor) == {public_game}
    assert visitor["games"][0]["visibility"] == "public"

    await sign_in_as(http, session_factory, cara.id)
    assert ids((await http.get(f"/api/users/{ann.id}/games")).json()) == {public_game}

    await sign_in_as(http, session_factory, bob.id)
    as_bob = (await http.get(f"/api/users/{ann.id}/games")).json()
    assert ids(as_bob) == {public_game, private_game}
    assert {game["visibility"] for game in as_bob["games"]} == {"public", "private"}

    await sign_in_as(http, session_factory, ann.id)
    assert ids((await http.get(f"/api/users/{ann.id}/games")).json()) == {
        public_game,
        private_game,
    }


async def test_a_private_game_is_not_counted_toward_the_page_a_stranger_gets(env):
    """`hasMore` is answered from the games the caller may see, so a page of
    public games is not cut short by private ones it never lists."""
    http, users, history, _ = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    for index in range(3):
        await record_game(
            history, users, winner=ann.id, loser=bob.id, index=index,
            visibility="private" if index == 1 else "public",
        )

    page = (await http.get(f"/api/users/{ann.id}/games?limit=2")).json()

    assert [game["roomName"] for game in page["games"]] == ["Studio 2", "Studio 0"]
    assert page["hasMore"] is False


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
    assert body["scoreEvents"][2]["correctsEventOrder"] == body["scoreEvents"][1]["eventOrder"]
    assert "id" not in body["scoreEvents"][0]
    assert body["promptSourceMode"] == "custom"
    assert len(body["turns"]) == 1
    assert body["turns"][0]["prompt"] == "jackpot"
    assert body["turns"][0]["promptVersionId"] is None
    assert body["turns"][0]["promptSourceKind"] == "custom"
    assert body["turns"][0]["promptOffers"] == []
    assert body["turns"][0]["drawerDisplayName"] == "Ann"
    assert body["turns"][0]["drawerNameColor"] is None
    assert body["turns"][0]["drawerIsAnonymous"] is True
    assert "guesses" not in body["turns"][0]
    loser_seat = next(
        seat["seatId"] for seat in body["participants"] if seat["displayName"] == "Bob"
    )
    assert body["turns"][0]["participantOutcomes"] == [
        {
            "seatId": loser_seat,
            "eligible": True,
            "eligibilityReason": "eligible",
            "outcome": "correct",
            "terminalState": "active",
            "correctGuessTimeSeconds": 12.0,
            "wrongGuessCount": 0,
            "nearMissCount": 0,
            "hintsUsed": 0,
            "pointsSpentOnHints": 0,
            "pointsAwarded": 100,
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


async def _registered(users, name: str):
    guest = await users.create_anonymous(display_name=name)
    return await users.claim_account(guest.id, name.lower(), "hashed")


async def test_a_participant_reacts_to_a_stored_drawing_and_sees_it_in_the_detail(env):
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    turn_id = record_game.last_turn_id
    await sign_in_as(http, factory, bob.id)
    path = f"/api/games/{game_id}/turns/{turn_id}/reaction"

    put = await http.put(path, json={"emoji": "heart"})
    assert put.status_code == 200
    body = put.json()
    assert body["turnId"] == turn_id and body["emoji"] == "heart"
    assert body["reactions"] == [{"seatId": body["seatId"], "emoji": "heart"}]

    detail = (await http.get(f"/api/games/{game_id}")).json()
    assert detail["turns"][0]["reactions"] == [{"seatId": body["seatId"], "emoji": "heart"}]
    assert detail["mySeatId"] == body["seatId"]
    stats = (await http.get(f"/api/users/{ann.id}/stats")).json()["stats"]
    assert stats["reactionsReceived"] == 1

    changed = await http.put(path, json={"emoji": "fire"})
    assert changed.json()["reactions"] == [{"seatId": body["seatId"], "emoji": "fire"}]

    cleared = await http.delete(path)
    assert cleared.status_code == 200
    assert cleared.json() == {
        "turnId": turn_id,
        "seatId": body["seatId"],
        "emoji": None,
        "myReaction": None,
        "reactions": [],
        "reactionCounts": {},
    }
    stats = (await http.get(f"/api/users/{ann.id}/stats")).json()["stats"]
    assert stats["reactionsReceived"] == 0


async def test_every_reaction_refusal_is_a_404(env):
    """Stranger, guest, the drawer, signed out, an unknown code, a borrowed turn:
    none of them learns whether the game exists (R-HIST-16)."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    guest = await users.create_anonymous(display_name="Guest")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    turn_id = record_game.last_turn_id
    await record_game(history, users, winner=cid.id, loser=ann.id, index=1, drawing=_skch())
    other_turn = record_game.last_turn_id
    path = f"/api/games/{game_id}/turns/{turn_id}/reaction"

    assert (await http.put(path, json={"emoji": "heart"})).status_code == 404, "signed out"
    assert (await http.delete(path)).status_code == 404

    for user, why in ((cid, "a stranger"), (guest, "a guest"), (ann, "the drawer")):
        await sign_in_as(http, factory, user.id)
        assert (await http.put(path, json={"emoji": "heart"})).status_code == 404, why

    await sign_in_as(http, factory, bob.id)
    assert (await http.put(path, json={"emoji": "thumbs_down"})).status_code == 404
    assert (await http.put(path, json={"emoji": 1})).status_code == 422
    assert (
        await http.put(
            f"/api/games/{game_id}/turns/{other_turn}/reaction", json={"emoji": "heart"}
        )
    ).status_code == 404
    assert (await http.get(f"/api/games/{game_id}")).json()["turns"][0]["reactions"] == []


# ---- the gallery door for a reaction (#524)


async def test_an_outsider_reacts_through_the_gallery_route_and_is_counted_unnamed(env):
    """Any registered account may react to a public-game drawing at
    `/api/gallery/{turn}/reaction` (R-GAL-06): the answer carries no seat, the
    counts include it, the named list does not (R-REACT-05), a participant's
    detail shows the count, and the pinned shelf shows the outsider their own
    pick without naming them to anyone."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    turn_id = record_game.last_turn_id
    path = f"/api/gallery/{turn_id}/reaction"

    await sign_in_as(http, factory, bob.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [turn_id]})).status_code == 200
    seated = await http.put(f"/api/games/{game_id}/turns/{turn_id}/reaction", json={"emoji": "heart"})
    bob_seat = seated.json()["seatId"]

    await sign_in_as(http, factory, cid.id)
    put = await http.put(path, json={"emoji": "wow"})
    assert put.status_code == 200
    assert put.json() == {
        "turnId": turn_id,
        "seatId": None,
        "emoji": "wow",
        "myReaction": "wow",
        "reactions": [{"seatId": bob_seat, "emoji": "heart"}],
        "reactionCounts": {"heart": 1, "wow": 1},
    }
    [entry] = (await http.get(f"/api/users/{bob.id}/pins")).json()["pins"]
    assert entry["reactions"] == [{"seatId": bob_seat, "emoji": "heart"}]
    assert entry["reactionCounts"] == {"heart": 1, "wow": 1}
    assert entry["myReaction"] == "wow" and entry["drawnByMe"] is False
    stats = (await http.get(f"/api/users/{ann.id}/stats")).json()["stats"]
    assert stats["reactionsReceived"] == 2

    await sign_in_as(http, factory, ann.id)
    turn = (await http.get(f"/api/games/{game_id}")).json()["turns"][0]
    assert turn["reactions"] == [{"seatId": bob_seat, "emoji": "heart"}]
    assert turn["reactionCounts"] == {"heart": 1, "wow": 1}
    [entry] = (await http.get(f"/api/users/{bob.id}/pins")).json()["pins"]
    assert entry["myReaction"] is None and entry["drawnByMe"] is True

    await sign_in_as(http, factory, cid.id)
    cleared = await http.delete(path)
    assert cleared.status_code == 200
    assert cleared.json()["reactionCounts"] == {"heart": 1}
    assert cleared.json()["myReaction"] is None


async def test_every_gallery_reaction_refusal_is_a_404(env):
    """Signed out, a guest, the drawer, a private game, a drawing never kept,
    an unknown code, an unknown turn: the gallery door never says which."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    guest = await users.create_anonymous(display_name="Guest")
    await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    public_turn = record_game.last_turn_id
    await record_game(
        history, users, winner=ann.id, loser=bob.id, index=1, drawing=_skch(), visibility="private"
    )
    private_turn = record_game.last_turn_id
    await record_game(history, users, winner=ann.id, loser=bob.id, index=2)
    unkept_turn = record_game.last_turn_id

    assert (await http.put(f"/api/gallery/{public_turn}/reaction", json={"emoji": "heart"})).status_code == 404
    assert (await http.delete(f"/api/gallery/{public_turn}/reaction")).status_code == 404
    for user, why in ((guest, "a guest"), (ann, "the drawer")):
        await sign_in_as(http, factory, user.id)
        assert (
            await http.put(f"/api/gallery/{public_turn}/reaction", json={"emoji": "heart"})
        ).status_code == 404, why
    await sign_in_as(http, factory, cid.id)
    for turn, why in (
        (private_turn, "a private game"),
        (unkept_turn, "no drawing kept"),
        (str(generate_uuid()), "no such turn"),
        ("not-an-id", "not an id"),
    ):
        assert (
            await http.put(f"/api/gallery/{turn}/reaction", json={"emoji": "heart"})
        ).status_code == 404, why
    assert (await http.put(f"/api/gallery/{public_turn}/reaction", json={"emoji": "thumbs_down"})).status_code == 404
    assert (await http.put(f"/api/gallery/{public_turn}/reaction", json={"emoji": 1})).status_code == 422


# ---- pinned drawings (#440)


async def _pins_in_store(factory, user_id: str) -> list[tuple[str, int]]:
    from sqlalchemy import select

    from app.db.models import ProfileDrawingPin

    async with factory() as session:
        rows = (
            await session.scalars(
                select(ProfileDrawingPin)
                .where(ProfileDrawingPin.user_id == UUID(user_id))
                .order_by(ProfileDrawingPin.position)
            )
        ).all()
    return [(str(row.turn_id), row.position) for row in rows]


async def test_a_participant_pins_reorders_and_unpins_with_one_write(env):
    """The list is the shelf: pinning another player's drawing, one's own,
    changing the order and taking one down are all the same request."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    anns_drawing = record_game.last_turn_id
    await record_game(history, users, winner=bob.id, loser=ann.id, index=1, drawing=_skch())
    bobs_drawing = record_game.last_turn_id
    await sign_in_as(http, factory, bob.id)

    put = await http.put("/api/me/pins", json={"turnIds": [anns_drawing, bobs_drawing]})
    assert put.status_code == 200
    assert put.json() == {"pins": [{"turnId": anns_drawing}, {"turnId": bobs_drawing}]}
    assert await _pins_in_store(factory, bob.id) == [(anns_drawing, 0), (bobs_drawing, 1)]

    reordered = await http.put("/api/me/pins", json={"turnIds": [bobs_drawing, anns_drawing]})
    assert reordered.json()["pins"] == [{"turnId": bobs_drawing}, {"turnId": anns_drawing}]
    assert await _pins_in_store(factory, bob.id) == [(bobs_drawing, 0), (anns_drawing, 1)]

    unpinned = await http.put("/api/me/pins", json={"turnIds": [anns_drawing]})
    assert unpinned.json() == {"pins": [{"turnId": anns_drawing}]}
    cleared = await http.put("/api/me/pins", json={"turnIds": []})
    assert cleared.json() == {"pins": []}
    assert await _pins_in_store(factory, bob.id) == []


async def test_every_pin_refusal_is_a_404_and_leaves_the_shelf_as_it_was(env):
    """Signed out, a guest, a stranger to the game, a private room's game, a
    drawing that was never kept, a turn that does not exist: none of them
    learns which applied (R-HIST-16), and a refused list writes nothing."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    guest = await users.create_anonymous(display_name="Guest")
    await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    public_turn = record_game.last_turn_id
    await record_game(
        history, users, winner=ann.id, loser=bob.id, index=1, drawing=_skch(), visibility="private"
    )
    private_turn = record_game.last_turn_id
    await record_game(history, users, winner=ann.id, loser=bob.id, index=2, drawing=None)
    unkept_turn = record_game.last_turn_id

    assert (await http.put("/api/me/pins", json={"turnIds": [public_turn]})).status_code == 404, "signed out"
    await sign_in_as(http, factory, guest.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [public_turn]})).status_code == 404, "a guest"
    assert (await http.put("/api/me/pins", json={"turnIds": []})).status_code == 404, "a guest, even clearing"
    await sign_in_as(http, factory, cid.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [public_turn]})).status_code == 404, "a stranger"
    assert (await http.put("/api/me/pins", json={"turnIds": []})).status_code == 200, "their own empty shelf"

    await sign_in_as(http, factory, bob.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [public_turn]})).status_code == 200
    for turn_id, why in (
        (private_turn, "a private room's game"),
        (unkept_turn, "a drawing the recap did not keep"),
        (str(generate_uuid()), "a turn that does not exist"),
        ("not-a-turn-id", "not an id at all"),
    ):
        response = await http.put("/api/me/pins", json={"turnIds": [public_turn, turn_id]})
        assert response.status_code == 404, why
        assert await _pins_in_store(factory, bob.id) == [(public_turn, 0)], why


async def test_a_seventh_pin_is_refused_as_full_and_a_repeat_as_malformed(env):
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    turns = []
    for index in range(7):
        await record_game(history, users, winner=ann.id, loser=bob.id, index=index, drawing=_skch())
        turns.append(record_game.last_turn_id)
    await sign_in_as(http, factory, bob.id)

    assert (await http.put("/api/me/pins", json={"turnIds": turns[:6]})).status_code == 200
    full = await http.put("/api/me/pins", json={"turnIds": turns})
    assert full.status_code == 409
    assert full.json()["errorCode"] == "pinned_drawings_full"
    assert full.json()["params"] == {"slots": 6}
    assert await _pins_in_store(factory, bob.id) == [(turn, i) for i, turn in enumerate(turns[:6])]

    assert (await http.put("/api/me/pins", json={"turnIds": [turns[0], turns[0]]})).status_code == 422
    assert (await http.put("/api/me/pins", json={"turnIds": turns * 2})).status_code == 422
    assert (await http.put("/api/me/pins", json={"turnIds": turns[0]})).status_code == 422
    assert (await http.put("/api/me/pins", json={})).status_code == 422


async def test_an_erased_drawing_keeps_its_pin_row_only_until_the_erasure_path_runs(env):
    """Erasure is a status change on the drawing, not a row deletion, so no
    cascade reaches the pin: the write path refuses the turn from then on,
    and the account-erasure path deletes the row (tests/test_account_data.py)."""
    from sqlalchemy import select

    from app.db.models import TurnDrawing

    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    turn_id = record_game.last_turn_id
    await sign_in_as(http, factory, bob.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [turn_id]})).status_code == 200

    async with factory() as session:
        async with session.begin():
            drawing = await session.scalar(
                select(TurnDrawing).where(TurnDrawing.turn_id == UUID(turn_id))
            )
            drawing.status = "deleted"
            drawing.payload = None
            drawing.checksum_sha256 = None
            drawing.byte_size = None
            drawing.format_magic = None
            drawing.format_version = None
            drawing.deleted_at = datetime.now(timezone.utc)
    assert await _pins_in_store(factory, bob.id) == [(turn_id, 0)]
    assert (await http.put("/api/me/pins", json={"turnIds": [turn_id]})).status_code == 404


# ---- the shelf and the pinned-drawing door (#808)


async def test_a_signed_in_non_participant_can_fetch_a_pinned_drawing_and_not_an_unpinned_one(env):
    """The required proof from #440: the pin is the only door, it opens the
    pinned turn to any session, and it leaves the participant route alone."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    guest = await users.create_anonymous(display_name="Guest")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    pinned_turn = record_game.last_turn_id
    other_game = await record_game(history, users, winner=ann.id, loser=bob.id, index=1, drawing=_skch())
    unpinned_turn = record_game.last_turn_id
    await sign_in_as(http, factory, bob.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [pinned_turn]})).status_code == 200
    expected = (await http.get(f"/api/games/{game_id}/turns/{pinned_turn}/drawing")).content

    shelf = f"/api/users/{bob.id}/pins"
    for viewer, why in ((cid, "a stranger to the game"), (guest, "a guest")):
        await sign_in_as(http, factory, viewer.id)
        listed = await http.get(shelf)
        assert listed.status_code == 200, why
        [entry] = listed.json()["pins"]
        assert entry["turnId"] == pinned_turn and entry["prompt"] == "jackpot", why
        assert entry["drawerDisplayName"] == "Ann" and "gameId" not in entry, why
        served = await http.get(f"{shelf}/{pinned_turn}/drawing")
        assert served.status_code == 200 and served.content == expected, why
        assert served.headers["cache-control"] == "private, no-cache"
        assert (await http.get(f"{shelf}/{unpinned_turn}/drawing")).status_code == 404, why
        # The participant route is not widened by the pin.
        assert (await http.get(f"/api/games/{game_id}/turns/{pinned_turn}/drawing")).status_code == 404, why
        assert (await http.get(f"/api/games/{other_game}/turns/{unpinned_turn}/drawing")).status_code == 404, why
        # Nor can the pinned turn be reached through somebody else's shelf.
        assert (await http.get(f"/api/users/{ann.id}/pins/{pinned_turn}/drawing")).status_code == 404, why

    http.cookies.clear()
    assert (await http.get(shelf)).status_code == 404, "signed out: no shelf"
    assert (await http.get(f"{shelf}/{pinned_turn}/drawing")).status_code == 404, "signed out: no bytes"
    await sign_in_as(http, factory, cid.id)
    assert (await http.get(f"/api/users/{generate_uuid()}/pins")).status_code == 404, "no such player"
    assert (await http.get(f"/api/users/{generate_uuid()}/pins/{pinned_turn}/drawing")).status_code == 404


async def test_unpinning_and_erasure_close_the_door_at_once_even_for_a_remembered_validator(env):
    from sqlalchemy import select

    from app.db.models import TurnDrawing

    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    cid = await _registered(users, "Cid")
    await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    first = record_game.last_turn_id
    await record_game(history, users, winner=ann.id, loser=bob.id, index=1, drawing=_skch())
    second = record_game.last_turn_id
    await sign_in_as(http, factory, bob.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [first, second]})).status_code == 200

    await sign_in_as(http, factory, cid.id)
    served = await http.get(f"/api/users/{bob.id}/pins/{first}/drawing")
    tag = served.headers["etag"]
    assert (
        await http.get(f"/api/users/{bob.id}/pins/{first}/drawing", headers={"If-None-Match": tag})
    ).status_code == 304

    await sign_in_as(http, factory, bob.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [second]})).status_code == 200
    await sign_in_as(http, factory, cid.id)
    assert (
        await http.get(f"/api/users/{bob.id}/pins/{first}/drawing", headers={"If-None-Match": tag})
    ).status_code == 404, "a remembered tag cannot see past an unpin"
    assert [p["turnId"] for p in (await http.get(f"/api/users/{bob.id}/pins")).json()["pins"]] == [second]

    async with factory() as session:
        async with session.begin():
            drawing = await session.scalar(select(TurnDrawing).where(TurnDrawing.turn_id == UUID(second)))
            drawing.status = "deleted"
            drawing.payload = None
            drawing.checksum_sha256 = None
            drawing.byte_size = None
            drawing.format_magic = None
            drawing.format_version = None
            drawing.deleted_at = datetime.now(timezone.utc)
    assert (await http.get(f"/api/users/{bob.id}/pins")).json()["pins"] == [], "an erased drawing is not a hole"
    assert (await http.get(f"/api/users/{bob.id}/pins/{second}/drawing")).status_code == 404


async def test_the_shelf_credits_the_drawer_as_they_were_and_carries_the_tally(env):
    """Attribution is the frozen snapshot (#387): a rename after the game
    changes nothing on the shelf. Reactions ride along read-only."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    turn_id = record_game.last_turn_id
    await sign_in_as(http, factory, bob.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [turn_id]})).status_code == 200
    reacted = await http.put(f"/api/games/{game_id}/turns/{turn_id}/reaction", json={"emoji": "fire"})
    assert reacted.status_code == 200
    await users.update_profile(ann.id, display_name="Annabel")

    [entry] = (await http.get(f"/api/users/{bob.id}/pins")).json()["pins"]
    assert entry == {
        "turnId": turn_id,
        "roundNumber": 1,
        "turnNumber": 1,
        "drawerDisplayName": "Ann",
        "drawerNameColor": None,
        # `record_game` writes the seat without an account state, so the
        # snapshot says guest: the shelf repeats the snapshot, not the account.
        "drawerIsAnonymous": True,
        "prompt": "jackpot",
        "strokeCount": 0,
        "reactions": [{"seatId": reacted.json()["seatId"], "emoji": "fire"}],
        "reactionCounts": {"fire": 1},
        "myReaction": "fire",
        "drawnByMe": False,
    }


# ---- conditional downloads (#604)


async def _drawing_url(users, history) -> tuple[str, object, object]:
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    return f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing", ann, bob


async def test_a_current_copy_is_answered_304_with_no_body(env):
    """#604: the browser revalidates on every open and is answered from the
    metadata alone while its copy is current; the validator names the wire
    version as well as the stored bytes, and is weak, since the same bytes
    go out with or without a content encoding."""
    from app.canvas_history import CANVAS_HISTORY_VERSION

    http, users, history, factory = env
    url, ann, _ = await _drawing_url(users, history)
    await sign_in_as(http, factory, ann.id)

    first = await http.get(url)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "private, no-cache"
    tag = first.headers["etag"]
    assert tag.startswith('W/"') and tag.endswith(f'-w{CANVAS_HISTORY_VERSION}"')

    again = await http.get(url, headers={"If-None-Match": tag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == tag
    assert again.headers["cache-control"] == "private, no-cache"

    # A list, the strong form of the same tag, and a wildcard all match;
    # another tag does not, and the drawing is sent again.
    assert (await http.get(url, headers={"If-None-Match": f'"other", {tag}'})).status_code == 304
    assert (await http.get(url, headers={"If-None-Match": tag[2:]})).status_code == 304
    assert (await http.get(url, headers={"If-None-Match": "*"})).status_code == 304
    stale = await http.get(url, headers={"If-None-Match": 'W/"deadbeef-w1"'})
    assert stale.status_code == 200 and stale.content == _skch()


async def test_a_new_wire_version_changes_the_validator_over_unchanged_stored_bytes(env, monkeypatch):
    """The stored checksum alone is not a validator for what is served: a
    decoder that answers in a newer wire format changes the bytes sent
    without touching the bytes stored."""
    from app.api import profiles as profiles_module

    http, users, history, factory = env
    url, ann, _ = await _drawing_url(users, history)
    await sign_in_as(http, factory, ann.id)
    tag = (await http.get(url)).headers["etag"]

    monkeypatch.setattr(profiles_module, "CANVAS_HISTORY_VERSION", 99)
    bumped = await http.get(url, headers={"If-None-Match": tag})
    assert bumped.status_code == 200, "the remembered tag no longer matches"
    assert bumped.headers["etag"] != tag and bumped.headers["etag"].endswith('-w99"')


async def test_a_remembered_validator_cannot_see_past_permission_or_erasure(env):
    """A 304 is a statement that the caller may still have the drawing. A
    stranger with a known tag, and a participant whose drawing was erased,
    are told it does not exist - the same 404 as without the tag."""
    from sqlalchemy import update

    from app.db.models import TurnDrawing

    http, users, history, factory = env
    url, ann, _ = await _drawing_url(users, history)
    outsider = await users.create_anonymous(display_name="Cid")
    await sign_in_as(http, factory, ann.id)
    tag = (await http.get(url)).headers["etag"]

    await sign_in_as(http, factory, outsider.id)
    assert (await http.get(url, headers={"If-None-Match": tag})).status_code == 404

    async with factory() as session:
        await session.execute(
            update(TurnDrawing).values(
                status="unavailable", unavailable_reason="erased",
                payload=None, byte_size=None, checksum_sha256=None,
            )
        )
        await session.commit()
    await sign_in_as(http, factory, ann.id)
    assert (await http.get(url, headers={"If-None-Match": tag})).status_code == 404
    assert (await http.get(url)).status_code == 404


async def test_the_validator_is_the_same_gzipped_and_a_gzipped_copy_revalidates(env):
    """Behind the compression middleware the drawing goes out gzipped to a
    client that accepts it; the weak validator is the same either way, and a
    conditional request from such a client is answered 304 all the same."""
    from starlette.middleware.gzip import GZipMiddleware

    http, users, history, factory = env
    url, ann, _ = await _drawing_url(users, history)
    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1)
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_profile_router(users, history))
    app.include_router(create_gallery_router(history))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as gz:
        await sign_in_as(gz, factory, ann.id)
        plain = await gz.get(url, headers={"Accept-Encoding": "identity"})
        gzipped = await gz.get(url, headers={"Accept-Encoding": "gzip"})
        assert plain.headers.get("content-encoding") is None
        assert gzipped.headers.get("content-encoding") == "gzip"
        assert gzipped.content == plain.content == _skch(), "httpx inflates it; the bytes are the drawing"
        assert plain.headers["etag"] == gzipped.headers["etag"]
        revalidated = await gz.get(url, headers={"Accept-Encoding": "gzip", "If-None-Match": gzipped.headers["etag"]})
        assert revalidated.status_code == 304 and revalidated.content == b""


async def test_a_drawing_fetched_again_is_neither_read_nor_decoded_again(env, monkeypatch):
    """#979: every fetch decoded the stored blob and gzipped it on the loop, for
    bytes that are the same for everybody who may see them."""
    import gzip

    import app.api.profiles as profiles

    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    blob = _large_frame()
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
    turn_id = record_game.last_turn_id
    decodes: list[int] = []
    real_decode = profiles.stored_drawing_wire_payload

    def counted(*args, **kwargs):
        decodes.append(1)
        return real_decode(*args, **kwargs)

    monkeypatch.setattr(profiles, "stored_drawing_wire_payload", counted)
    blob_reads: list[int] = []
    real_read = history.get_turn_drawing

    async def counted_read(*args, **kwargs):
        blob_reads.append(1)
        return await real_read(*args, **kwargs)

    monkeypatch.setattr(history, "get_turn_drawing", counted_read)
    url = f"/api/games/{game_id}/turns/{turn_id}/drawing"
    for signed_in in (ann.id, bob.id):
        await sign_in_as(http, factory, signed_in)
        response = await http.get(url, headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert response.content == blob
        assert response.headers["content-encoding"] == "gzip"
        assert response.headers["vary"] == "Accept-Encoding"
    assert decodes == [1] and blob_reads == [1]
    # And a client that takes no encoding gets the bytes as they are.
    plain = await http.get(url, headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers and plain.content == blob
    assert profiles.drawing_cache.bytes == len(blob) + len(gzip.compress(blob, 6, mtime=0))
    # Keyed by the wire version as well as the checksum, as the ETag is.
    [key] = list(profiles.drawing_cache._entries)
    assert key.endswith(f"-w{profiles.CANVAS_HISTORY_VERSION}")


async def test_a_warm_cache_answers_nobody_the_drawing_was_not_for(env):
    """Only the bytes are shared: who may have them is asked every time."""
    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    outsider = await users.create_anonymous(display_name="Cid")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_skch())
    url = f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing"
    await sign_in_as(http, factory, ann.id)
    assert (await http.get(url)).status_code == 200
    await sign_in_as(http, factory, outsider.id)
    assert (await http.get(url)).status_code == 404


def test_the_drawing_cache_is_bounded_in_bytes_and_forgets_the_least_recent():
    from app.api.profiles import WireDrawingCache

    cache = WireDrawingCache(max_bytes=100)
    cache.put("a", b"x" * 30, b"y" * 10)
    cache.put("b", b"x" * 30, b"y" * 10)
    assert cache.get("a") is not None  # a is now the most recent
    cache.put("c", b"x" * 30, b"y" * 10)
    assert (cache.get("a"), cache.get("b") is None, cache.get("c") is not None) == (
        (b"x" * 30, b"y" * 10), True, True,
    )
    assert cache.bytes == 80
    cache.put("huge", b"x" * 200, b"")
    assert cache.get("huge") is None and cache.bytes == 80



def _large_frame() -> bytes:
    """A drawing well past the 500-byte floor under which none is gzipped."""
    from app.canvas_history import PackedCanvasHistory

    history = PackedCanvasHistory()
    for stroke in range(6):
        history.append_path(
            [((step % 50) / 50, (step // 50 + stroke) / 10) for step in range(120)],
            color=0x223344,
            width=3,
        )
    return history.binary_payload()


async def test_a_small_drawing_goes_out_as_it_is_and_vary_rides_only_the_gzip(env):
    """Gzip framing costs more than it saves on a few hundred bytes; and a
    `Vary` on the identity answer was repeated by the response middleware."""
    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    small = _skch()
    assert len(small) < 500
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=small)
    await sign_in_as(http, factory, ann.id)
    response = await http.get(
        f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing",
        headers={"Accept-Encoding": "gzip"},
    )
    assert response.content == small
    assert "content-encoding" not in response.headers and "vary" not in response.headers


async def test_gzip_refused_with_q_zero_is_not_sent(env):
    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_large_frame())
    await sign_in_as(http, factory, ann.id)
    response = await http.get(
        f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing",
        headers={"Accept-Encoding": "gzip;q=0, identity"},
    )
    assert response.status_code == 200 and "content-encoding" not in response.headers


async def test_concurrent_misses_for_one_drawing_decode_it_once(env, monkeypatch):
    """The This week shelf right after a restart: everybody asks at once."""
    import asyncio

    import app.api.profiles as profiles

    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    blob = _large_frame()
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
    decodes: list[int] = []
    real_decode = profiles.stored_drawing_wire_payload

    def slow_decode(*args, **kwargs):
        decodes.append(1)
        import time

        time.sleep(0.05)  # on the worker thread, so the others arrive meanwhile
        return real_decode(*args, **kwargs)

    monkeypatch.setattr(profiles, "stored_drawing_wire_payload", slow_decode)
    await sign_in_as(http, factory, ann.id)
    url = f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing"
    responses = await asyncio.gather(*(http.get(url) for _ in range(5)))
    assert [response.status_code for response in responses] == [200] * 5
    assert all(response.content == blob for response in responses)
    assert decodes == [1]
    assert profiles._fills == {}


async def test_a_refusal_inside_a_shared_fill_is_not_handed_to_the_other_waiters(env, monkeypatch):
    """Only bytes are shared. A drawing hidden between one caller's access
    check and its read is that caller's 404; a participant may still have it
    (R-GAL-09, #979 review)."""
    import asyncio

    import app.api.profiles as profiles

    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    blob = _large_frame()
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
    turn_id = record_game.last_turn_id
    await sign_in_as(http, factory, ann.id)
    url = f"/api/games/{game_id}/turns/{turn_id}/drawing"

    reads = []
    real_read = history.get_turn_drawing

    async def refuse_the_first_read(*args, **kwargs):
        reads.append(1)
        if len(reads) == 1:
            await asyncio.sleep(0.05)  # the second request arrives meanwhile
            return None  # as if it had just been hidden
        return await real_read(*args, **kwargs)

    monkeypatch.setattr(history, "get_turn_drawing", refuse_the_first_read)
    first, second = await asyncio.gather(http.get(url), http.get(url))
    assert {first.status_code, second.status_code} == {404, 200}
    served = first if first.status_code == 200 else second
    assert served.content == blob
    assert profiles._fills == {}


async def test_a_fill_survives_the_caller_that_started_it_going_away(env):
    """The fill is a task of its own: the caller that started it going away -
    a shutdown, a timeout - must not cancel the read the other waiters are
    waiting on (#979 review).

    At `_decode_once` rather than through HTTP: cancelling a request with a
    query in flight tears down its database connection, which is a different
    story from this one.
    """
    import asyncio

    import app.api.profiles as profiles

    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    blob = _large_frame()
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
    turn_id = record_game.last_turn_id
    detail = await history.get_turn_drawing(game_id, turn_id, requesting_user_id=ann.id)
    release = asyncio.Event()

    async def slow_read():
        await release.wait()
        return detail

    checksum = detail.checksum_sha256
    owner = asyncio.create_task(profiles._decode_once(checksum, turn_id, slow_read))
    await asyncio.sleep(0.02)
    waiter = asyncio.create_task(profiles._decode_once(checksum, turn_id, slow_read))
    await asyncio.sleep(0.02)
    owner.cancel()
    release.set()

    wire, gzipped, served_checksum = await asyncio.wait_for(waiter, timeout=5)
    assert wire == blob and served_checksum == checksum
    assert profiles.drawing_cache.get(profiles._cache_key(checksum)) is not None
    assert profiles._fills == {}


async def test_one_decode_serves_every_door_to_the_same_drawing(env, monkeypatch):
    """The cache is keyed by the drawing's checksum, not by the route that
    asked: the participant page, a pinned shelf and the Gallery all serve the
    bytes the first of them decoded (#979 third review - no test outside the
    participant route touched the cache)."""
    import app.api.profiles as profiles

    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    blob = _large_frame()
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
    turn_id = record_game.last_turn_id
    await sign_in_as(http, factory, bob.id)
    assert (await http.put("/api/me/pins", json={"turnIds": [turn_id]})).status_code == 200

    decodes: list[int] = []
    real_decode = profiles.stored_drawing_wire_payload
    monkeypatch.setattr(
        profiles,
        "stored_drawing_wire_payload",
        lambda *args, **kwargs: (decodes.append(1), real_decode(*args, **kwargs))[1],
    )

    participant = await http.get(f"/api/games/{game_id}/turns/{turn_id}/drawing")
    pinned = await http.get(f"/api/users/{bob.id}/pins/{turn_id}/drawing")
    gallery = await http.get(f"/api/gallery/{turn_id}/drawing")

    assert [participant.status_code, pinned.status_code, gallery.status_code] == [200, 200, 200]
    assert participant.content == pinned.content == gallery.content == blob
    assert decodes == [1], "decoded once, served through three doors"


async def test_a_door_that_may_not_see_it_is_refused_while_the_others_are_served(
    env, monkeypatch
):
    """Sharing bytes is not sharing access. The Gallery's own query answers
    for the Gallery; a participant keeps a drawing the Gallery may not show
    (R-GAL-09)."""
    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    blob = _large_frame()
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
    turn_id = record_game.last_turn_id
    await sign_in_as(http, factory, bob.id)

    served = await http.get(f"/api/games/{game_id}/turns/{turn_id}/drawing")
    assert served.status_code == 200 and served.content == blob

    async def hidden_from_the_gallery(*_args, **_kwargs):
        return None

    # The gate is the checksum query, which every door runs before the cache
    # is consulted at all.
    monkeypatch.setattr(history, "get_gallery_drawing_checksum", hidden_from_the_gallery)
    monkeypatch.setattr(history, "get_gallery_drawing", hidden_from_the_gallery)
    assert (await http.get(f"/api/gallery/{turn_id}/drawing")).status_code == 404
    again = await http.get(f"/api/games/{game_id}/turns/{turn_id}/drawing")
    assert again.status_code == 200 and again.content == blob


async def test_the_starter_of_a_fill_the_cache_declined_still_gets_its_drawing(
    env, monkeypatch
):
    """The fill's own answer, not whatever the cache ended up holding: a
    decode the cache declined - too large for it, or a checksum that changed
    while it ran - was answered as a missing drawing (#979 third review)."""
    import app.api.profiles as profiles

    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    blob = _large_frame()
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
    turn_id = record_game.last_turn_id
    await sign_in_as(http, factory, bob.id)
    monkeypatch.setattr(profiles.drawing_cache, "put", lambda *args, **kwargs: None)

    served = await http.get(f"/api/games/{game_id}/turns/{turn_id}/drawing")

    assert served.status_code == 200
    assert served.content == blob


async def test_the_starter_of_a_refused_fill_is_refused_and_a_waiter_asks_again(env):
    """The refusal belongs to the query it came from: the caller whose own
    read found nothing is refused, and whoever was waiting behind it asks
    again with its own (R-GAL-09). At the seam, so which caller started the
    fill is not left to chance."""
    import asyncio

    import pytest

    import app.api.profiles as profiles
    from app.api.errors import Refusal

    http, users, history, factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    blob = _large_frame()
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
    turn_id = record_game.last_turn_id
    detail = await history.get_turn_drawing(game_id, turn_id, requesting_user_id=ann.id)
    checksum = detail.checksum_sha256
    release = asyncio.Event()

    async def hidden_from_the_starter():
        await release.wait()
        return None

    async def visible_to_the_waiter():
        return detail

    starter = asyncio.create_task(
        profiles._decode_once(checksum, turn_id, hidden_from_the_starter)
    )
    await asyncio.sleep(0.02)
    waiter = asyncio.create_task(
        profiles._decode_once(checksum, turn_id, visible_to_the_waiter)
    )
    await asyncio.sleep(0.02)
    release.set()

    with pytest.raises(Refusal) as refused:
        await asyncio.wait_for(starter, timeout=5)
    assert refused.value.status_code == 404
    wire, _gzipped, served = await asyncio.wait_for(waiter, timeout=5)
    assert wire == blob and served == checksum


async def test_the_cache_is_keyed_by_the_checksum_the_bytes_were_verified_against(env):
    """The row may have changed between the access query and the read, so the
    entry is keyed by the checksum the decode verified - not by the key the
    caller asked under, which would serve one drawing's bytes for another's
    checksum (#979 third review)."""
    import app.api.profiles as profiles

    _http, users, history, _factory = env
    ann = await _registered(users, "Ann")
    bob = await _registered(users, "Bob")
    blob = _large_frame()
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
    turn_id = record_game.last_turn_id
    detail = await history.get_turn_drawing(game_id, turn_id, requesting_user_id=ann.id)
    asked_under = "0" * 64  # what the checksum query answered a moment ago

    wire, _gzipped, served = await profiles._decode_once(
        asked_under, turn_id, lambda: _answer(detail)
    )

    assert wire == blob
    assert served == detail.checksum_sha256
    assert profiles.drawing_cache.get(profiles._cache_key(detail.checksum_sha256)) is not None
    assert profiles.drawing_cache.get(profiles._cache_key(asked_under)) is None


async def _answer(value):
    return value


def test_the_cached_copy_is_gzipped_at_the_documented_level():
    """Made once, off the loop, and kept - so it is worth more than the level
    the per-request middleware would use."""
    import gzip

    import app.api.profiles as profiles

    assert profiles.DRAWING_GZIP_LEVEL == 6
    blob = _skch()
    wire, gzipped = profiles._decoded_drawing(blob, None)
    assert gzipped == gzip.compress(wire, compresslevel=6, mtime=0)


def test_the_cache_size_is_exposed_to_the_scrape():
    """An in-memory cache with no gauge is a memory ceiling nobody can see:
    the wiring in `main` is what puts it in the scrape (#979 third review)."""
    import app.main  # noqa: F401 - imported for the wiring it performs
    import app.api.profiles as profiles
    from app.services.telemetry import telemetry

    assert telemetry.sources.drawing_cache_bytes is not None
    assert telemetry.sources.drawing_cache_bytes() == profiles.drawing_cache.bytes
    assert any(
        line.startswith("sketchy_drawing_cache_bytes")
        for line in telemetry.prometheus_lines()
    )


async def test_the_cache_counter_says_which_it_was(env):
    from app.services.telemetry import telemetry

    http, users, history, factory = env
    ann = await users.create_anonymous(display_name="Ann")
    bob = await users.create_anonymous(display_name="Bob")
    game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=_large_frame())
    await sign_in_as(http, factory, ann.id)
    url = f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing"
    misses = telemetry.drawing_cache_requests.get(("miss",))
    hits = telemetry.drawing_cache_requests.get(("hit",))
    assert (await http.get(url)).status_code == 200
    assert (await http.get(url)).status_code == 200
    assert telemetry.drawing_cache_requests.get(("miss",)) == misses + 1
    assert telemetry.drawing_cache_requests.get(("hit",)) == hits + 1


async def test_behind_the_real_middleware_the_answer_is_encoded_once(monkeypatch):
    """Mounted as production mounts it: the response middleware must leave a
    body that already carries `Content-Encoding` alone (a second pass would
    make the decoded bytes gzip, not the frame), and must not repeat `Vary`
    (#979 review)."""
    from app.compression import SelectiveGZipMiddleware

    monkeypatch.setenv("IP_HASH_SECRET", "profiles-middleware-secret")
    session_factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(session_factory)
    history = SqlAlchemyGameHistoryRepository(session_factory)
    app = FastAPI()
    install_refusal_handler(app)
    app.add_middleware(SessionAuthMiddleware, session_factory=session_factory)
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=500)
    app.include_router(create_profile_router(users, history))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            ann = await users.create_anonymous(display_name="Ann")
            bob = await users.create_anonymous(display_name="Bob")
            blob = _large_frame()
            game_id = await record_game(history, users, winner=ann.id, loser=bob.id, drawing=blob)
            await sign_in_as(http, session_factory, ann.id)
            url = f"/api/games/{game_id}/turns/{record_game.last_turn_id}/drawing"
            for _ in range(2):  # the miss and then the hit
                response = await http.get(url, headers={"Accept-Encoding": "gzip"})
                assert response.status_code == 200
                assert response.content == blob
                assert response.headers["content-encoding"] == "gzip"
                assert response.headers["vary"].lower().count("accept-encoding") == 1
            # The small-body floor is not asserted here: on `main` the session
            # middleware is still a `BaseHTTPMiddleware`, which streams every
            # response, and Starlette's gzip compresses a streamed body at any
            # size. #1026 makes that layer plain ASGI and the floor applies
            # again; `test_a_small_drawing_goes_out_as_it_is...` covers the
            # route's own half.
    finally:
        await engine.dispose()

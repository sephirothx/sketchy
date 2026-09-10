"""The public profile endpoints: stats, history pages, and who may see detail."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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
        "reactions": [],
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

"""Requester-only exports and history-safe account deletion."""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.auth.middleware import SessionAuthMiddleware
from tests.dbfixtures import create_test_db
import app.auth.account_data as account_data_module
from app.services.avatars import set_avatar
from tests.png_fixture import png_bytes
from app.auth.account_data import (
    EXPORT_INTERVAL,
    AccountDataError,
    anonymize_account,
    create_data_export,
    ExportNotYetAllowed,
    process_pending_data_exports,
)
from app.auth.routes import create_auth_router
from app.db.models import (
    AuditEvent,
    AuthSession,
    BugReport,
    DataExport,
    Friendship,
    GameParticipant,
    GameRecord,
    IdentityAlias,
    PlayerReport,
    PlayerReportMessageEvidence,
    PromptConcept,
    PromptContentReport,
    PromptList,
    RoomMessage,
    RoomPreset,
    ScoreEvent,
    TurnDrawing,
    TurnGuess,
    TurnRecord,
    User,
    UserBan,
    UserBlock,
    UserSettings,
    generate_uuid,
)
from app.domain_values import AccountState, DataExportStatus, FriendshipState
from app.services.friends import friendship_key
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    PromptOfferInput,
    ScoreEventInput,
    TurnDrawingInput,
    TurnGuessInput,
    TurnParticipantOutcomeInput,
    TurnRecordInput,
    PromptListEntryInput,
)
from app.repositories.sqlalchemy import (
    SqlAlchemyGameHistoryRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyPromptListRepository,
)


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"
STARTED = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "account-data-test-secret")
    # PostgreSQL when TEST_DATABASE_URL says so: the streamed build uses a
    # server-side cursor there, which SQLite only imitates.
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    deletion_hook = AsyncMock()
    # The router only writes the row and wakes the worker; the tests play the
    # worker themselves, so a build happens exactly where a test says it does.
    wake = Mock()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(
        create_auth_router(
            users, factory, on_account_deleted=deletion_hook, on_export_requested=wake
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        http._test_deletion_hook = deletion_hook
        http._test_factory = factory
        http._test_wake = wake
        yield http, users, history, factory
    await engine.dispose()


async def register(http: AsyncClient, username: str = "Exporter") -> dict:
    response = await http.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()


def _skch_drawing() -> bytes:
    fixtures = json.loads(
        (Path(__file__).parents[2] / "fixtures" / "canvas_protocol_v1.json").read_text()
    )
    entry = next(
        item for item in fixtures["histories"] if item["name"] == "representative"
    )
    return bytes.fromhex(entry["binary"])


async def record_private_game(history, *, owner_id: str, other_id: str) -> str:
    owner_seat = str(generate_uuid())
    other_seat = str(generate_uuid())
    owner_turn = str(generate_uuid())
    other_turn = str(generate_uuid())
    return await history.save_game(
        GameRecordInput(
            room_name="Export room",
            scoring_mode="default",
            scoring_version=1,
            score_ledger_version=1,
            rule_snapshot_version=1,
            hint_mode="checkpoints",
            drawing_seconds=90,
            total_rounds=1,
            player_count=2,
            started_at=STARTED,
            finished_at=STARTED + timedelta(minutes=5),
            prompt_source_mode="custom",
        ),
        [
            GameParticipantInput(
                user_id=owner_id,
                final_score=250,
                final_rank=1,
                turns_played=2,
                seat_id=owner_seat,
                display_name="Exporter",
            ),
            GameParticipantInput(
                user_id=other_id,
                final_score=250,
                final_rank=1,
                turns_played=2,
                seat_id=other_seat,
                display_name="Other player",
            ),
        ],
        [
            TurnRecordInput(
                id=owner_turn,
                round_number=1,
                turn_number=1,
                drawer_user_id=owner_id,
                drawer_seat_id=owner_seat,
                prompt="owner prompt",
                duration_seconds=25,
                prompt_source_kind="custom",
                guesser_count=1,
                prompt_offers=(
                    PromptOfferInput(0, "owner prompt", True, "custom"),
                    PromptOfferInput(1, "other option", False, "custom"),
                ),
                participant_outcomes=(
                    TurnParticipantOutcomeInput(
                        seat_id=other_seat,
                        user_id=other_id,
                        eligible=True,
                        eligibility_reason="eligible",
                        outcome="correct",
                        terminal_state="active",
                        correct_guess_time_seconds=10,
                    ),
                ),
            ),
            TurnRecordInput(
                id=other_turn,
                round_number=1,
                turn_number=2,
                drawer_user_id=other_id,
                drawer_seat_id=other_seat,
                prompt="requester guessed this",
                duration_seconds=30,
                prompt_source_kind="custom",
                guesser_count=1,
                participant_outcomes=(
                    TurnParticipantOutcomeInput(
                        seat_id=owner_seat,
                        user_id=owner_id,
                        eligible=True,
                        eligibility_reason="eligible",
                        outcome="correct",
                        terminal_state="active",
                        correct_guess_time_seconds=12,
                    ),
                ),
            ),
        ],
        [
            TurnGuessInput(
                turn_id=owner_turn,
                user_id=other_id,
                seat_id=other_seat,
                points_awarded=100,
                guess_time_seconds=10,
            ),
            TurnGuessInput(
                turn_id=other_turn,
                user_id=owner_id,
                seat_id=owner_seat,
                points_awarded=150,
                guess_time_seconds=12,
            ),
        ],
        [
            ScoreEventInput(
                id=str(generate_uuid()),
                participant_seat_id=other_seat,
                participant_user_id=other_id,
                turn_id=owner_turn,
                event_order=1,
                event_type="guess_award",
                points_delta=100,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            ScoreEventInput(
                id=str(generate_uuid()),
                participant_seat_id=owner_seat,
                participant_user_id=owner_id,
                turn_id=owner_turn,
                event_order=2,
                event_type="drawer_bonus",
                points_delta=100,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            ScoreEventInput(
                id=str(generate_uuid()),
                participant_seat_id=owner_seat,
                participant_user_id=owner_id,
                turn_id=other_turn,
                event_order=3,
                event_type="guess_award",
                points_delta=150,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
            ScoreEventInput(
                id=str(generate_uuid()),
                participant_seat_id=other_seat,
                participant_user_id=other_id,
                turn_id=other_turn,
                event_order=4,
                event_type="drawer_bonus",
                points_delta=150,
                scoring_version=1,
                rule_snapshot_version=1,
            ),
        ],
        [
            TurnDrawingInput(turn_id=owner_turn, payload=_skch_drawing()),
            TurnDrawingInput(turn_id=other_turn, payload=_skch_drawing()),
        ],
    )


async def request_ready_export(http: AsyncClient) -> tuple[dict, dict]:
    http._test_wake.reset_mock()
    requested = await http.post("/api/auth/data-exports")
    assert requested.status_code == 202
    assert requested.json()["status"] == DataExportStatus.PENDING.value
    http._test_wake.assert_called_once_with()
    assert await process_pending_data_exports(http._test_factory) == 1
    status = await http.get(f"/api/auth/data-exports/{requested.json()['id']}")
    assert status.status_code == 200
    assert status.json()["status"] == DataExportStatus.READY.value
    downloaded = await http.get(status.json()["downloadUrl"])
    assert downloaded.status_code == 200
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert "attachment" in downloaded.headers["content-disposition"]
    return status.json(), downloaded.json()


def artifact_field_paths(value, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths.update(artifact_field_paths(child, path))
    elif isinstance(value, list) and value:
        paths.update(artifact_field_paths(value[0], f"{prefix}[]"))
    return paths


async def test_export_is_versioned_durable_and_requester_only(env):
    http, users, history, factory = env
    owner = await register(http)
    # The picture is the player's own upload, so the export carries it (#573).
    await set_avatar(factory, user_id=owner["id"], payload=png_bytes(seed=5))
    linked_guest = await users.create_anonymous("Linked road guest")
    await users.merge_guest_into_account(linked_guest.id, owner["id"])
    other = await users.create_anonymous("Private Bob")
    submitted_report_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            owner_row = await session.get(User, UUID(owner["id"]))
            other_row = await session.get(User, UUID(other.id))
            assert owner_row is not None and other_row is not None
            owner_row.email = "owner@example.test"
            other_row.email = "private-bob@example.test"
            session.add(
                PlayerReport(
                    id=submitted_report_id,
                    reporter_user_id=owner_row.id,
                    reported_user_id=other_row.id,
                    reason="harassment",
                    details="Requester-authored report details",
                    context_snapshot={"schemaVersion": 1, "submitted": {}},
                )
            )
            session.add(
                BugReport(
                    id=generate_uuid(),
                    reporter_user_id=owner_row.id,
                    area="drawing_and_canvas",
                    severity="major",
                    summary="Requester-authored bug summary",
                    details="Requester-authored bug details",
                    build_sha="abc1234",
                    route="/room/BQ7F2K",
                    room_code="BQ7F2K",
                    client_context={"buildSha": "abc1234"},
                    server_context={"account": {"registered": True}},
                )
            )
            session.add(
                UserBan(
                    id=generate_uuid(),
                    user_id=UUID(linked_guest.id),
                    banned_by_user_id=other_row.id,
                    reason="Historic suspension",
                    is_active=False,
                )
            )
            session.add(
                UserBlock(
                    blocker_user_id=owner_row.id,
                    blocked_user_id=other_row.id,
                )
            )
            # A friendship the requester is half of, so the export's friend
            # fields are pinned by a row rather than by an empty list.
            low, high = friendship_key(owner_row.id, other_row.id)
            session.add(
                Friendship(
                    user_low_id=low,
                    user_high_id=high,
                    requested_by_id=owner_row.id,
                    status=FriendshipState.ACCEPTED.value,
                    responded_at=datetime.now(timezone.utc),
                )
            )
    game_id = await record_private_game(
        history, owner_id=owner["id"], other_id=other.id
    )
    async with factory() as session:
        async with session.begin():
            owner_turn = await session.scalar(
                select(TurnRecord).where(
                    TurnRecord.game_id == UUID(game_id),
                    TurnRecord.drawer_user_id == UUID(owner["id"]),
                )
            )
            owner_seat = await session.scalar(
                select(GameParticipant).where(
                    GameParticipant.game_id == UUID(game_id),
                    GameParticipant.user_id == UUID(owner["id"]),
                )
            )
            assert owner_turn is not None and owner_seat is not None
            session.add(
                RoomMessage(
                    id=generate_uuid(),
                    room_instance_id=generate_uuid(),
                    game_id=UUID(game_id),
                    turn_id=owner_turn.id,
                    sender_user_id=UUID(owner["id"]),
                    sender_player_id=generate_uuid(),
                    sender_seat_id=owner_seat.id,
                    sender_display_name_snapshot="Exporter",
                    sender_name_color_snapshot="#224466",
                    sender_is_anonymous_snapshot=False,
                    is_spectator=False,
                    message_kind="wrong_guess",
                    audience="room",
                    audience_user_ids=[owner["id"], other.id],
                    near_miss_kind="close",
                    text="Requester-authored retained guess",
                    created_at=STARTED + timedelta(minutes=1),
                    expires_at=STARTED + timedelta(days=30),
                )
            )
            # A line said in the lobby has no room and no seat; it is theirs
            # all the same, and their export says where it was said.
            session.add(
                RoomMessage(
                    id=generate_uuid(),
                    room_instance_id=None,
                    sender_user_id=UUID(owner["id"]),
                    sender_player_id=None,
                    sender_display_name_snapshot="Exporter",
                    sender_name_color_snapshot="#224466",
                    sender_is_anonymous_snapshot=False,
                    is_spectator=False,
                    message_kind="chat",
                    audience="lobby",
                    audience_user_ids=[],
                    text="Requester-authored lobby line",
                    created_at=STARTED + timedelta(minutes=2),
                    expires_at=STARTED + timedelta(days=30),
                )
            )
            session.add(
                PlayerReportMessageEvidence(
                    report_id=submitted_report_id,
                    position=0,
                    source_message_id=None,
                    source_message_snapshot_id=generate_uuid(),
                    game_id_snapshot=UUID(game_id),
                    turn_id_snapshot=owner_turn.id,
                    sender_user_id=UUID(other.id),
                    sender_display_name_snapshot="Reported player",
                    sender_name_color_snapshot=None,
                    sender_is_anonymous_snapshot=True,
                    message_kind="chat",
                    audience="room",
                    near_miss_kind=None,
                    text_snapshot="Message selected by the requester",
                    message_created_at=STARTED + timedelta(minutes=2),
                )
            )
    exported_list = await SqlAlchemyPromptListRepository(factory).create_owned(
        owner["id"],
        name="Exported prompts",
        description="Requester-authored content",
        language="en",
        visibility="unlisted",
        prompts=(PromptListEntryInput(answer="red panda"),),
    )
    async with factory() as session:
        async with session.begin():
            session.add(
                RoomPreset(
                    owner_user_id=UUID(owner["id"]),
                    name="Tournament night",
                    name_key="tournament night",
                    room_name="Friday finals",
                    is_public=False,
                    max_players=12,
                    rounds=5,
                    drawing_seconds=120,
                    hint_mode="none",
                    scoring_mode="pressure",
                    spectators_see_prompt=True,
                    hide_masked_prompt=False,
                    allowed_tools=["brush", "shapes"],
                    color_mode="colorblind_safe",
                    prompt_list_ids=[exported_list.id],
                )
            )
            session.add(
                PromptContentReport(
                    id=generate_uuid(),
                    reporter_user_id=UUID(owner["id"]),
                    reported_owner_user_id=UUID(other.id),
                    prompt_list_id=UUID(exported_list.id),
                    prompt_version_id=UUID(
                        exported_list.prompts[0].prompt_version_id
                    ),
                    target_type="prompt",
                    list_name_snapshot="Exported prompts",
                    prompt_snapshot="red panda",
                    reason="inappropriate",
                    details="Requester-authored prompt report",
                )
            )

    status, artifact = await request_ready_export(http)
    assert status["schemaVersion"] == 2
    assert artifact["schemaVersion"] == 2
    assert artifact["account"]["email"] == "owner@example.test"
    assert artifact["gameParticipations"][0]["game"]["id"] == game_id
    assert artifact["gameParticipations"][0]["game"]["scoringVersion"] == 1
    assert artifact["gameParticipations"][0]["game"]["scoreLedgerVersion"] == 1
    assert artifact["gameParticipations"][0]["game"]["ruleSnapshot"] == {}
    assert artifact["gameParticipations"][0]["game"]["promptSourceMode"] == "custom"
    assert artifact["drawnTurns"][0]["promptOffers"][0] == {
        "position": 0,
        "prompt": "owner prompt",
        "selected": True,
        "sourceKind": "custom",
        "promptVersionId": None,
        "sourceRevisionIds": [],
    }
    assert artifact["drawnTurns"][0]["promptVersionId"] is None
    assert artifact["drawnTurns"][0]["promptSourceKind"] == "custom"
    assert artifact["drawnTurns"][0]["prompt"] == "owner prompt"
    assert artifact["correctGuesses"][0]["prompt"] == "requester guessed this"
    assert artifact["turnOutcomes"][0]["participantSeatId"]
    assert [event["eventType"] for event in artifact["scoreEvents"]] == [
        "drawer_bonus",
        "guess_award",
    ]
    assert artifact["turnOutcomes"][0]["outcome"] == "correct"
    assert artifact["turnOutcomes"][0]["terminalState"] == "active"
    assert artifact["retainedMessages"][0]["text"] == (
        "Requester-authored retained guess"
    )
    assert artifact["retainedMessages"][0]["messageKind"] == "wrong_guess"
    assert artifact["retainedMessages"][1]["text"] == "Requester-authored lobby line"
    assert artifact["retainedMessages"][1]["audience"] == "lobby"
    assert artifact["retainedMessages"][1]["gameId"] is None
    assert artifact["retainedMessages"][1]["participantSeatId"] is None
    assert artifact["sessions"] and "tokenHash" not in artifact["sessions"][0]
    assert artifact["reportsSubmitted"][0]["details"] == (
        "Requester-authored report details"
    )
    assert artifact["reportsSubmitted"][0]["messageEvidence"][0]["text"] == (
        "Message selected by the requester"
    )
    assert "reportedUserId" not in artifact["reportsSubmitted"][0]
    assert artifact["suspensions"][0]["reason"] == "Historic suspension"
    assert "bannedByUserId" not in artifact["suspensions"][0]
    assert artifact["blocks"][0]["blockedUserId"] == other.id
    assert artifact["promptLists"][0]["name"] == "Exported prompts"
    assert artifact["promptLists"][0]["revisions"][0]["prompts"][0]["prompt"] == "red panda"
    assert artifact["roomPresets"][0]["name"] == "Tournament night"
    assert artifact["roomPresets"][0]["promptListIds"] == [exported_list.id]
    assert artifact["promptContentReportsSubmitted"][0]["details"] == (
        "Requester-authored prompt report"
    )
    assert "reportedOwnerUserId" not in artifact["promptContentReportsSubmitted"][0]

    encoded = json.dumps(artifact)
    assert "Private Bob" not in encoded
    assert "private-bob@example.test" not in encoded
    assert PASSWORD not in encoded
    assert "$argon2" not in encoded

    contract = json.loads(
        (REPO_ROOT / "fixtures" / "account_data_export_v2_fields.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["schemaVersion"] == artifact["schemaVersion"]
    assert artifact_field_paths(artifact) == set(contract["fieldPaths"])

    async with factory() as session:
        job = await session.get(DataExport, UUID(status["id"]))
        assert job is not None
        assert job.status == DataExportStatus.READY.value
        # Stored compressed, and the row says how to read itself.
        assert job.artifact_encoding == "gzip+json"
        assert json.loads(gzip.decompress(job.artifact)) == artifact
        assert len(job.artifact) < len(json.dumps(artifact).encode()), (
            "the stored document is smaller than the text it encodes"
        )


async def test_export_cannot_be_read_by_another_account(env):
    http, _, _, _ = env
    await register(http)
    status, _ = await request_ready_export(http)

    other = AsyncClient(transport=http._transport, base_url="http://test")
    async with other:
        await register(other, "OtherAccount")
        response = await other.get(f"/api/auth/data-exports/{status['id']}")
    assert response.status_code == 404


async def test_worker_recovers_a_job_orphaned_by_a_crashed_process(env):
    http, _, _, factory = env
    owner = await register(http)
    now = datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc)
    job = await create_data_export(factory, user_id=owner["id"], now=now)
    async with factory() as session:
        async with session.begin():
            stored = await session.get(DataExport, job.id)
            assert stored is not None
            stored.status = DataExportStatus.PROCESSING.value
            stored.started_at = now - timedelta(minutes=16)

    assert await process_pending_data_exports(factory, now=now, limit=1) == 1
    async with factory() as session:
        stored = await session.get(DataExport, job.id)
        assert stored is not None
        assert stored.status == DataExportStatus.READY.value
        assert stored.artifact is not None


async def test_deletion_requires_password_and_anonymizes_history(env):
    http, users, history, factory = env
    owner = await register(http)
    other = await users.create_anonymous("Other player")
    game_id = await record_private_game(
        history, owner_id=owner["id"], other_id=other.id
    )
    evidence_report_id = generate_uuid()
    retained_message_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            owner_turn = await session.scalar(
                select(TurnRecord).where(
                    TurnRecord.game_id == UUID(game_id),
                    TurnRecord.drawer_user_id == UUID(owner["id"]),
                )
            )
            owner_seat = await session.scalar(
                select(GameParticipant).where(
                    GameParticipant.game_id == UUID(game_id),
                    GameParticipant.user_id == UUID(owner["id"]),
                )
            )
            assert owner_turn is not None and owner_seat is not None
            session.add(
                RoomMessage(
                    id=retained_message_id,
                    room_instance_id=generate_uuid(),
                    game_id=UUID(game_id),
                    turn_id=owner_turn.id,
                    sender_user_id=UUID(owner["id"]),
                    sender_player_id=generate_uuid(),
                    sender_seat_id=owner_seat.id,
                    sender_display_name_snapshot="Exporter",
                    sender_name_color_snapshot="#224466",
                    sender_is_anonymous_snapshot=False,
                    is_spectator=False,
                    message_kind="chat",
                    audience="room",
                    audience_user_ids=[owner["id"], other.id],
                    near_miss_kind=None,
                    text="Erase this retained message",
                    created_at=STARTED,
                    expires_at=STARTED + timedelta(days=30),
                )
            )
            session.add(
                PlayerReport(
                    id=evidence_report_id,
                    reporter_user_id=UUID(other.id),
                    reported_user_id=UUID(owner["id"]),
                    game_id=UUID(game_id),
                    turn_id=owner_turn.id,
                    reason="harassment",
                    details="Pinned before account deletion",
                    context_snapshot={"schemaVersion": 1, "submitted": {}},
                )
            )
            session.add(
                PlayerReportMessageEvidence(
                    report_id=evidence_report_id,
                    position=0,
                    source_message_id=retained_message_id,
                    source_message_snapshot_id=retained_message_id,
                    game_id_snapshot=UUID(game_id),
                    turn_id_snapshot=owner_turn.id,
                    sender_user_id=UUID(owner["id"]),
                    sender_display_name_snapshot="Exporter",
                    sender_name_color_snapshot="#224466",
                    sender_is_anonymous_snapshot=False,
                    message_kind="chat",
                    audience="room",
                    near_miss_kind=None,
                    text_snapshot="Pinned evidence survives",
                    message_created_at=STARTED,
                )
            )
    export_status, _ = await request_ready_export(http)
    deleted_list = await SqlAlchemyPromptListRepository(factory).create_owned(
        owner["id"],
        name="Delete me",
        description="",
        language="en",
        visibility="private",
        prompts=(PromptListEntryInput(answer="private prompt"),),
    )
    async with factory() as session:
        async with session.begin():
            session.add(
                RoomPreset(
                    owner_user_id=UUID(owner["id"]),
                    name="Delete me",
                    name_key="delete me",
                    room_name="Private configuration",
                    is_public=False,
                    max_players=8,
                    rounds=3,
                    drawing_seconds=90,
                    hint_mode="checkpoints",
                    scoring_mode="default",
                    spectators_see_prompt=False,
                    hide_masked_prompt=False,
                    allowed_tools=["brush"],
                    color_mode="all",
                    prompt_list_ids=[deleted_list.id],
                )
            )

    missing = await http.request("DELETE", "/api/auth/account", json={})
    assert missing.status_code == 400
    wrong = await http.request(
        "DELETE", "/api/auth/account", json={"password": "wrong-password"}
    )
    assert wrong.status_code == 401

    deleted = await http.request(
        "DELETE", "/api/auth/account", json={"password": PASSWORD}
    )
    assert deleted.status_code == 200
    assert deleted.json()["identitiesAnonymized"] == 1
    assert "sketchy_session=" in deleted.headers["set-cookie"].lower()
    http._test_deletion_hook.assert_awaited_once_with(owner["id"])

    async with factory() as session:
        account = await session.get(User, UUID(owner["id"]))
        assert account is not None
        assert account.state == AccountState.DELETED.value
        assert account.username is None
        assert account.password_hash is None
        assert account.email is None
        assert account.display_name == "Deleted player"
        assert account.name_color is None
        assert account.avatar_key is None

        seats = list((await session.scalars(select(GameParticipant))).all())
        owner_seat = next(seat for seat in seats if seat.user_id == account.id)
        other_seat = next(seat for seat in seats if seat.user_id != account.id)
        assert owner_seat.display_name_snapshot == "Deleted player"
        assert owner_seat.final_score == 250
        assert other_seat.display_name_snapshot == "Other player"

        owner_turn = await session.scalar(
            select(TurnRecord).where(TurnRecord.drawer_user_id == account.id)
        )
        owner_guess = await session.scalar(
            select(TurnGuess).where(TurnGuess.user_id == account.id)
        )
        assert owner_turn is not None
        assert owner_turn.drawer_display_name_snapshot == "Deleted player"
        assert owner_turn.prompt == "owner prompt"
        assert owner_guess is not None
        assert owner_guess.display_name_snapshot == "Deleted player"
        assert owner_guess.points_awarded == 150
        assert await session.scalar(select(func.count(GameRecord.id))) == 1
        assert await session.scalar(select(func.count(ScoreEvent.id))) == 4
        assert await session.scalar(select(func.count(RoomMessage.id))) == 0
        evidence = await session.scalar(
            select(PlayerReportMessageEvidence).where(
                PlayerReportMessageEvidence.report_id == evidence_report_id
            )
        )
        assert evidence is not None
        assert evidence.text_snapshot == "Pinned evidence survives"
        assert evidence.sender_display_name_snapshot == "Deleted player"
        assert evidence.sender_name_color_snapshot is None
        assert evidence.sender_is_anonymous_snapshot is True
        assert await session.get(DataExport, UUID(export_status["id"])) is None
        assert await session.get(UserSettings, account.id) is None
        assert await session.scalar(select(func.count(UserBlock.blocked_user_id))) == 0
        assert await session.scalar(select(func.count(PromptList.id))) == 0
        assert await session.scalar(select(func.count(RoomPreset.id))) == 0
        assert await session.scalar(select(func.count(PromptConcept.id))) == 0
        assert not list(
            (
                await session.scalars(
                    select(AuthSession).where(
                        AuthSession.user_id == account.id,
                        AuthSession.revoked_at.is_(None),
                    )
                )
            ).all()
        )
        event = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "account.deleted")
        )
        assert event is not None

    assert (await http.get("/api/auth/sessions")).status_code == 401


async def test_guest_can_delete_auto_provisioned_account_without_password(env):
    http, _, _, factory = env
    guest = (
        await http.post("/api/auth/display-name", json={"displayName": "Visitor"})
    ).json()
    response = await http.request("DELETE", "/api/auth/account", json={})
    assert response.status_code == 200
    async with factory() as session:
        account = await session.get(User, UUID(guest["id"]))
        assert account is not None and account.state == AccountState.DELETED.value


async def test_deletion_anonymizes_linked_guest_seats_without_collapsing_them(env):
    http, users, history, factory = env
    owner = await register(http, "LinkedDeletion")
    linked_guest = await users.create_anonymous("Old guest name")
    await record_private_game(
        history, owner_id=linked_guest.id, other_id=owner["id"]
    )
    await users.merge_guest_into_account(linked_guest.id, owner["id"])

    response = await http.request(
        "DELETE", "/api/auth/account", json={"password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["identitiesAnonymized"] == 2

    async with factory() as session:
        account = await session.get(User, UUID(owner["id"]))
        source = await session.get(User, UUID(linked_guest.id))
        assert account is not None and account.state == AccountState.DELETED.value
        assert source is not None and source.state == AccountState.MERGED.value
        assert source.display_name == "Deleted player"
        seats = list((await session.scalars(select(GameParticipant))).all())
        assert len(seats) == 2
        assert {seat.user_id for seat in seats} == {account.id, source.id}
        assert all(seat.display_name_snapshot == "Deleted player" for seat in seats)


async def test_deletion_erases_the_drawings_that_account_made(env):
    """A drawing is authored content, so it goes where the turn around it stays."""

    http, users, history, factory = env
    owner = await register(http, "DrawingDeleter")
    other = await users.create_anonymous("Other player")
    game_id = await record_private_game(
        history, owner_id=owner["id"], other_id=other.id
    )

    response = await http.request(
        "DELETE", "/api/auth/account", json={"password": PASSWORD}
    )
    assert response.status_code == 200

    async with factory() as session:
        rows = (
            await session.scalars(
                select(TurnDrawing).where(TurnDrawing.game_id == UUID(game_id))
            )
        ).all()
        by_drawer = {}
        for row in rows:
            turn = await session.get(TurnRecord, row.turn_id)
            by_drawer[turn.drawer_user_id] = row

        erased = by_drawer[UUID(owner["id"])]
        assert erased.status == "deleted"
        assert erased.payload is None
        assert erased.checksum_sha256 is None
        assert erased.deleted_at is not None

        # The other player drew that one; deleting an account must not reach
        # into somebody else's work.
        kept = by_drawer[UUID(other.id)]
        assert kept.status == "ready"
        assert kept.payload is not None


async def test_deletion_erases_drawings_made_under_a_merged_identity(env):
    http, users, history, factory = env
    owner = await register(http, "MergedDrawer")
    guest = await users.create_anonymous("Guest identity")
    game_id = await record_private_game(
        history, owner_id=guest.id, other_id=owner["id"]
    )
    async with factory() as session:
        async with session.begin():
            session.add(
                IdentityAlias(
                    source_user_id=UUID(guest.id),
                    target_user_id=UUID(owner["id"]),
                )
            )

    response = await http.request(
        "DELETE", "/api/auth/account", json={"password": PASSWORD}
    )
    assert response.status_code == 200

    async with factory() as session:
        rows = (
            await session.scalars(
                select(TurnDrawing).where(TurnDrawing.game_id == UUID(game_id))
            )
        ).all()
        assert rows, "the game should still have its drawing rows"
        assert all(row.status == "deleted" for row in rows)
        assert all(row.payload is None for row in rows)


# --- the refusals on the privacy path ---------------------------------------
#
# Export and deletion have to be right the first time: there is no second
# chance at data that has already left, and none at a row already gone. The
# suite drove these through the HTTP surface, which never asks for an account
# that is not there - so the guards that make these functions safe to call with
# an unverified id had never been taken.


async def test_a_second_export_within_a_week_is_refused_with_the_date(env):
    """R-PRIV-12: a right to a copy is not a right to a fresh copy per click."""
    http, _, _, factory = env
    registered = await register(http, "Collector")
    first, _ = await request_ready_export(http)

    again = await http.post("/api/auth/data-exports")
    assert again.status_code == 429
    assert "request another on" in again.json()["detail"]
    assert int(again.headers["retry-after"]) > 6 * 24 * 3600

    listed = await http.get("/api/auth/data-exports")
    next_at = datetime.fromisoformat(listed.json()["nextRequestAt"])
    created = datetime.fromisoformat(first["createdAt"])
    assert next_at - created == EXPORT_INTERVAL

    # A week later the interval has passed and a new one is accepted.
    later = datetime.now(timezone.utc) + EXPORT_INTERVAL + timedelta(seconds=1)
    job = await create_data_export(factory, user_id=registered["id"], now=later)
    assert job.status == DataExportStatus.PENDING.value


async def test_an_export_still_being_built_blocks_another(env):
    http, _, _, factory = env
    registered = await register(http, "Impatient")
    await create_data_export(factory, user_id=registered["id"])
    with pytest.raises(ExportNotYetAllowed, match="already being prepared") as refused:
        await create_data_export(factory, user_id=registered["id"])
    assert refused.value.retry_at is None
    listed = await http.get("/api/auth/data-exports")
    assert listed.json()["nextRequestAt"] is None


async def test_two_live_exports_for_one_account_cannot_exist(env):
    """R-PRIV-12's "never two live at once" is held by the database, so two
    requests arriving in the same instant cannot both get past a check."""
    http, _, _, factory = env
    registered = await register(http, "Twice")
    first = await create_data_export(factory, user_id=registered["id"])
    async with factory() as session:
        session.add(
            DataExport(
                id=generate_uuid(),
                user_id=UUID(registered["id"]),
                status=DataExportStatus.PENDING.value,
                schema_version=first.schema_version,
                created_at=first.created_at,
                expires_at=first.expires_at,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_a_request_that_loses_the_race_is_refused_like_a_late_one(env, monkeypatch):
    """If the check saw nothing live but the insert collides, the caller is
    told the same thing as a caller who read the live job a moment earlier."""
    http, _, _, factory = env
    registered = await register(http, "Racer")
    await create_data_export(factory, user_id=registered["id"])

    async def nothing_live(session, db_user_id):
        return None

    monkeypatch.setattr(account_data_module, "latest_counted_export", nothing_live)
    with pytest.raises(ExportNotYetAllowed, match="already being prepared"):
        await create_data_export(factory, user_id=registered["id"])


async def test_a_failed_export_does_not_count_against_the_week(env):
    http, _, _, factory = env
    registered = await register(http, "Unlucky")
    job = await create_data_export(factory, user_id=registered["id"])
    async with factory() as session:
        stored = await session.get(DataExport, job.id)
        stored.status = DataExportStatus.FAILED.value
        await session.commit()
    retry = await http.post("/api/auth/data-exports")
    assert retry.status_code == 202


async def test_an_export_cannot_be_requested_for_an_account_that_is_not_there(env):
    _, _, _, factory = env
    with pytest.raises(AccountDataError, match="account not found"):
        await create_data_export(factory, user_id=generate_uuid())


async def test_an_export_cannot_be_requested_for_a_deleted_account(env):
    """A deleted account's data must not be re-assembled into a download."""
    http, _, _, factory = env
    registered = await register(http, "Departing")
    user_id = UUID(registered["id"])
    async with factory() as session:
        account = await session.get(User, user_id)
        account.state = AccountState.DELETED.value
        await session.commit()

    with pytest.raises(AccountDataError, match="account not found"):
        await create_data_export(factory, user_id=user_id)


async def test_anonymising_an_account_that_is_not_there_is_refused(env):
    _, _, _, factory = env
    with pytest.raises(AccountDataError, match="account not found"):
        await anonymize_account(factory, user_id=generate_uuid())


async def test_anonymising_an_already_deleted_account_is_refused(env):
    """Idempotent-looking, but a second pass would rewrite the tombstone."""
    http, _, _, factory = env
    registered = await register(http, "Gone")
    user_id = UUID(registered["id"])
    async with factory() as session:
        account = await session.get(User, user_id)
        account.state = AccountState.DELETED.value
        await session.commit()

    with pytest.raises(AccountDataError, match="account not found"):
        await anonymize_account(factory, user_id=user_id)


async def test_a_merged_identity_must_be_deleted_through_its_own_account(env):
    """Deleting the alias would leave the canonical account's data standing
    while telling the player it was erased."""
    http, _, _, factory = env
    registered = await register(http, "Merged")
    user_id = UUID(registered["id"])
    async with factory() as session:
        account = await session.get(User, user_id)
        account.state = AccountState.MERGED.value
        await session.commit()

    with pytest.raises(AccountDataError, match="merged identities"):
        await anonymize_account(factory, user_id=user_id)


@pytest.mark.parametrize("limit", [0, -1, -100])
async def test_a_non_positive_export_batch_is_refused(env, limit):
    """A batch of zero is a worker that runs for ever and processes nothing."""
    _, _, _, factory = env
    with pytest.raises(ValueError, match="limit must be positive"):
        await process_pending_data_exports(factory, limit=limit)


async def test_an_empty_queue_processes_nothing_without_error(env):
    _, _, _, factory = env
    assert await process_pending_data_exports(factory) == 0


async def test_a_stored_export_must_say_how_to_read_itself(env):
    """The encoding travels with the document so a later format needs no
    migration - which only works if an unreadable one is refused rather than
    guessed at."""
    from app.auth.account_data import decode_export_artifact

    http, _, _, factory = env
    await register(http)
    status, _ = await request_ready_export(http)

    async with factory() as session:
        job = await session.get(DataExport, UUID(status["id"]))
        assert decode_export_artifact(job), "the real document decodes"

        job.artifact_encoding = "brotli+cbor"
        with pytest.raises(AccountDataError, match="unreadable encoding"):
            decode_export_artifact(job)

        job.artifact = None
        with pytest.raises(AccountDataError, match="no stored document"):
            decode_export_artifact(job)


async def test_a_corrupt_export_document_is_refused_not_served(env):
    """Truncated bytes decompress to an exception, and an empty result is not
    the JSON the row claims to hold. Either way the download answers with a
    controlled error instead of crashing or serving a malformed body."""
    from app.auth.account_data import decode_export_artifact

    http, _, _, factory = env
    await register(http)
    status, _ = await request_ready_export(http)

    async with factory() as session:
        async with session.begin():
            job = await session.get(DataExport, UUID(status["id"]))
            job.artifact = job.artifact[:8]

    download = await http.get(f"/api/auth/data-exports/{status['id']}/download")
    assert download.status_code == 500
    assert "new export" in download.json()["detail"]

    async with factory() as session:
        job = await session.get(DataExport, UUID(status["id"]))
        with pytest.raises(AccountDataError, match="could not be decompressed"):
            decode_export_artifact(job)
        # gzip decompresses empty input without complaint; the decoder does not.
        job.artifact = gzip.compress(b"")
        with pytest.raises(AccountDataError, match="decoded to nothing"):
            decode_export_artifact(job)


async def test_the_writer_produces_the_same_bytes_as_a_whole_document_dump():
    """The streamed encoding is the stored encoding: byte for byte what
    `json.dumps(document, separators=(",", ":"))` would have produced, so
    nothing that reads a stored export can tell the build was paged."""
    from app.auth.account_data import _ExportWriter

    document = {
        "schemaVersion": 2,
        "empty": [],
        "nested": {"a": None, "b": [1, {"c": "dé\u2603"}], "d": {}},
        "rows": [{"x": 1}, {"x": 2}, {"x": 3}],
        "last": "value",
    }
    writer = _ExportWriter(max_bytes=10_000)
    writer.begin_object()
    writer.field("schemaVersion", 2)
    writer.key("empty")
    writer.begin_array()
    writer.end_array()
    writer.field("nested", document["nested"])
    writer.key("rows")
    writer.begin_array()
    for row in document["rows"]:
        writer.value(row)
    writer.end_array()
    writer.field("last", "value")
    writer.end_object()

    expected = json.dumps(document, separators=(",", ":")).encode("utf-8")
    assert gzip.decompress(writer.finish()) == expected
    assert writer.written == len(expected)


async def test_the_writer_refuses_at_the_ceiling_rather_than_after_it():
    """The ceiling is checked on every write, so a build that will be refused
    stops at the byte that crosses it instead of finishing first."""
    from app.auth.account_data import ExportTooLarge, _ExportWriter

    writer = _ExportWriter(max_bytes=40)
    writer.begin_object()
    writer.key("rows")
    writer.begin_array()
    written = 0
    with pytest.raises(ExportTooLarge) as refused:
        for _ in range(1000):
            writer.value({"x": 1})
            written += 1
    assert refused.value.limit == 40
    # A handful of rows, not a thousand: it stopped as soon as it knew.
    assert written < 10


async def test_a_document_past_the_ceiling_is_refused_not_built(env, monkeypatch):
    """Past `EXPORT_MAX_BYTES` the job fails as `too_large` with no document
    stored, the status says so, and - like any failed build - it does not
    count against the week (R-PRIV-13)."""
    http, _, _, factory = env
    await register(http, "Prolific")
    monkeypatch.setenv("EXPORT_MAX_BYTES", "256")

    requested = await http.post("/api/auth/data-exports")
    assert requested.status_code == 202
    assert await process_pending_data_exports(factory) == 0

    status = await http.get(f"/api/auth/data-exports/{requested.json()['id']}")
    assert status.json()["status"] == DataExportStatus.FAILED.value
    assert status.json()["failureCode"] == "too_large"
    assert status.json()["downloadUrl"] is None
    async with factory() as session:
        job = await session.get(DataExport, UUID(requested.json()["id"]))
        assert job.artifact is None
        assert job.artifact_encoding is None

    download = await http.get(f"/api/auth/data-exports/{requested.json()['id']}/download")
    assert download.status_code == 409

    # An operator raising the ceiling is the remedy; the account is not
    # locked out for a week by a build that stored nothing.
    monkeypatch.delenv("EXPORT_MAX_BYTES")
    again = await http.post("/api/auth/data-exports")
    assert again.status_code == 202
    assert await process_pending_data_exports(factory) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", 64 * 1024 * 1024), ("abc", 64 * 1024 * 1024), ("0", 64 * 1024 * 1024),
     ("-5", 64 * 1024 * 1024), ("1024", 1024)],
)
async def test_the_ceiling_is_read_from_the_environment(raw, expected):
    from app.auth.account_data import export_max_bytes

    assert export_max_bytes({"EXPORT_MAX_BYTES": raw}) == expected


async def test_the_build_pages_its_history_without_changing_the_document(env, monkeypatch):
    """More rows than one page in several sections, read two at a time:
    every row arrives, in order, and the bytes are the ones a single fetch
    would have produced."""
    from app.auth.account_data import _ExportWriter, _write_export_artifact

    http, _, _, factory = env
    owner = await register(http, "Paged")
    for _ in range(4):
        assert (
            await http.post(
                "/api/auth/login", json={"username": "Paged", "password": PASSWORD}
            )
        ).status_code == 200
    async with factory() as session:
        async with session.begin():
            for index in range(5):
                session.add(
                    UserBlock(
                        blocker_user_id=UUID(owner["id"]),
                        blocked_user_id=generate_uuid(),
                        created_at=STARTED + timedelta(minutes=index),
                    )
                )
                session.add(
                    RoomPreset(
                        id=generate_uuid(),
                        owner_user_id=UUID(owner["id"]),
                        name=f"Preset {index}",
                        name_key=f"preset {index}",
                        room_name=f"Room {index}",
                        is_public=False,
                        max_players=8,
                        rounds=3,
                        drawing_seconds=60,
                        hint_mode="none",
                        scoring_mode="default",
                        spectators_see_prompt=False,
                        hide_masked_prompt=False,
                        allowed_tools=["brush"],
                        color_mode="colorblind_safe",
                        prompt_list_ids=[],
                        created_at=STARTED + timedelta(minutes=index),
                        updated_at=STARTED + timedelta(minutes=index),
                    )
                )

    async def build() -> bytes:
        async with factory() as session:
            writer = _ExportWriter(max_bytes=10_000_000)
            await _write_export_artifact(
                session, writer, user_id=UUID(owner["id"]), generated_at=STARTED
            )
            return gzip.decompress(writer.finish())

    whole = await build()
    monkeypatch.setattr(account_data_module, "EXPORT_PAGE_SIZE", 2)
    paged = await build()

    assert paged == whole
    document = json.loads(paged)
    assert len(document["blocks"]) == 5
    assert len(document["roomPresets"]) == 5
    assert len(document["sessions"]) == 5
    assert [preset["name"] for preset in document["roomPresets"]] == [
        f"Preset {index}" for index in range(5)
    ]


async def test_the_download_is_the_stored_bytes_or_a_streamed_decode(env):
    """A client that accepts gzip gets the row's bytes untouched, with their
    own length; one that does not gets the document decompressed a chunk at a
    time with the length the gzip trailer records. Either way what arrives is
    the compact JSON the row holds (R-PRIV-14)."""
    from app.auth.account_data import decode_export_artifact, open_export_artifact

    http, _, _, factory = env
    await register(http)
    status, artifact = await request_ready_export(http)
    expected = json.dumps(artifact, separators=(",", ":")).encode("utf-8")
    async with factory() as session:
        job = await session.get(DataExport, UUID(status["id"]))
        stored = bytes(job.artifact)

    passthrough = await http.get(
        f"/api/auth/data-exports/{status['id']}/download",
        headers={"Accept-Encoding": "gzip"},
    )
    assert passthrough.status_code == 200
    assert passthrough.headers["content-encoding"] == "gzip"
    assert int(passthrough.headers["content-length"]) == len(stored)
    assert passthrough.headers["vary"] == "Accept-Encoding"
    # httpx decodes the transfer; the raw body is the row, byte for byte.
    assert gzip.decompress(stored) == expected
    assert passthrough.content == expected

    plain = await http.get(
        f"/api/auth/data-exports/{status['id']}/download",
        headers={"Accept-Encoding": "identity"},
    )
    assert plain.status_code == 200
    assert "content-encoding" not in plain.headers
    assert int(plain.headers["content-length"]) == len(plain.content)
    assert plain.content == expected

    async with factory() as session:
        job = await session.get(DataExport, UUID(status["id"]))
        opened = open_export_artifact(job)
        assert opened.stored == stored
        chunks = list(opened.chunks)
        assert b"".join(chunks) == decode_export_artifact(job)
        assert opened.size == len(expected)
        # A stored document that is not gzip at all is refused before a byte
        # of it is served, the same as a truncated one.
        job.artifact = b"{" + b"x" * 40
        with pytest.raises(AccountDataError, match="could not be decompressed"):
            open_export_artifact(job)
        job.artifact = gzip.compress(b"")
        with pytest.raises(AccountDataError, match="decoded to nothing"):
            open_export_artifact(job)


async def test_deleting_an_account_names_the_friends_it_takes_something_from(env):
    """Their lists lose a row, and they are still connected to hear it.

    Collected before the delete: afterwards there is nothing left to say who
    they were.
    """
    http, _, _, factory = env
    owner = await register(http)
    other_http = AsyncClient(transport=http._transport, base_url="http://test")
    async with other_http:
        friend = await register(other_http, "FriendOfOwner")
        async with factory() as session:
            async with session.begin():
                low, high = friendship_key(UUID(owner["id"]), UUID(friend["id"]))
                session.add(
                    Friendship(
                        user_low_id=low,
                        user_high_id=high,
                        requested_by_id=UUID(owner["id"]),
                        status=FriendshipState.ACCEPTED.value,
                    )
                )

        result = await anonymize_account(factory, user_id=UUID(owner["id"]))

    # The friend, and nobody else - certainly not the account being deleted.
    assert result.friends_notified == (friend["id"],)

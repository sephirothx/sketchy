"""Requester-only exports and history-safe account deletion."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.middleware import SessionAuthMiddleware
from app.auth.account_data import (
    create_data_export,
    process_pending_data_exports,
)
from app.auth.routes import create_auth_router
from app.db.models import (
    AuditEvent,
    AuthSession,
    Base,
    DataExport,
    GameParticipant,
    GameRecord,
    PlayerReport,
    PlayerReportMessageEvidence,
    PersistentRoom,
    PromptContentReport,
    ScoreEvent,
    TurnGuess,
    TurnRecord,
    User,
    UserBan,
    UserBlock,
    UserSettings,
    PromptConcept,
    PromptList,
    RoomMessage,
    RoomCodeReservation,
    generate_uuid,
)
from app.domain_values import AccountState, DataExportStatus
from app.repositories.interfaces import (
    GameParticipantInput,
    GameRecordInput,
    PromptOfferInput,
    ScoreEventInput,
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
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    history = SqlAlchemyGameHistoryRepository(factory)
    deletion_hook = AsyncMock()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(
        create_auth_router(users, factory, on_account_deleted=deletion_hook)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        http._test_deletion_hook = deletion_hook
        yield http, users, history, factory
    await engine.dispose()


async def register(http: AsyncClient, username: str = "Exporter") -> dict:
    response = await http.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()


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
    )


async def request_ready_export(http: AsyncClient) -> tuple[dict, dict]:
    requested = await http.post("/api/auth/data-exports")
    assert requested.status_code == 202
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
                    id=generate_uuid(),
                    blocker_user_id=owner_row.id,
                    blocked_user_id=other_row.id,
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
            session.add(RoomCodeReservation(code="EXPR01", kind="persistent"))
            session.add(
                PersistentRoom(
                    code="EXPR01",
                    owner_user_id=UUID(owner["id"]),
                    name="Exported room",
                    is_public=False,
                    max_players=8,
                    rounds=3,
                    drawing_seconds=90,
                    hint_mode="checkpoints",
                    scoring_mode="default",
                    spectators_see_prompt=False,
                    hide_masked_prompt=False,
                    allowed_tools=["brush", "shapes", "fill"],
                    color_mode="all",
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
    assert status["schemaVersion"] == 1
    assert artifact["schemaVersion"] == 1
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
    assert artifact["persistentRooms"][0]["code"] == "EXPR01"
    assert artifact["persistentRooms"][0]["promptListIds"] == [exported_list.id]
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
        (REPO_ROOT / "fixtures" / "account_data_export_v1_fields.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["schemaVersion"] == artifact["schemaVersion"]
    assert artifact_field_paths(artifact) == set(contract["fieldPaths"])

    async with factory() as session:
        job = await session.get(DataExport, UUID(status["id"]))
        assert job is not None
        assert job.status == DataExportStatus.READY.value
        assert job.artifact == artifact


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
    await SqlAlchemyPromptListRepository(factory).create_owned(
        owner["id"],
        name="Delete me",
        description="",
        language="en",
        visibility="private",
        prompts=(PromptListEntryInput(answer="private prompt"),),
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
        assert await session.scalar(select(func.count(UserBlock.id))) == 0
        assert await session.scalar(select(func.count(PromptList.id))) == 0
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
    guest = (await http.get("/api/auth/me")).json()
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

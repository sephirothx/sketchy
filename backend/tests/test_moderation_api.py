"""Reports, moderator actions, bans, and authentication enforcement."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from socketio.exceptions import ConnectionRefusedError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.moderation import create_moderation_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import (
    AuditEvent,
    AuthSession,
    Base,
    PlayerReport,
    PlayerReportMessageEvidence,
    RoomMessage,
    User,
    UserBan,
    generate_uuid,
)
from app.domain_values import ReportReason, ReportStatus, UserRole
from app.handlers.connection import connect as socket_connect
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.message_retention import purge_expired_room_messages


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "moderation-test-secret")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    banned_callback = AsyncMock()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(
        create_moderation_router(factory, on_user_banned=banned_callback)
    )

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        clients.append(client)
        return client

    try:
        yield new_client, factory, banned_callback
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()


async def set_role(factory, user_id: str, role: UserRole) -> None:
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(user_id))
            assert user is not None
            user.role = role.value


async def test_report_submission_is_bounded_private_and_audited(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    reporter = await register(reporter_http, "Reporter")
    target = await register(target_http, "ReportedPlayer")
    request_id = "019c1000-0000-7000-8000-000000000001"

    response = await reporter_http.post(
        "/api/reports",
        headers={"x-request-id": request_id},
        json={
            "reportedUserId": target["id"],
            "reason": "offensive_drawing",
            "details": "The drawing contained targeted abuse.",
            "contextSnapshot": {"strokeCount": 42, "canvasBytes": 1800},
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending"

    assert (
        await reporter_http.post(
            "/api/reports",
            json={
                "reportedUserId": reporter["id"],
                "reason": "spam",
                "details": "self",
            },
        )
    ).status_code == 422
    assert (await reporter_http.get("/api/moderation/reports")).status_code == 403

    async with factory() as session:
        report = await session.scalar(select(PlayerReport))
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "report.submitted")
        )
        assert report is not None
        assert report.reporter_user_id == UUID(reporter["id"])
        assert report.reported_user_id == UUID(target["id"])
        assert report.context_snapshot == {
            "schemaVersion": 1,
            "submitted": {"strokeCount": 42, "canvasBytes": 1800},
        }
        assert audit is not None
        assert audit.request_id == request_id
        assert len(audit.ip_hash or "") == 64
        assert "127.0.0.1" not in (audit.ip_hash or "")
        assert audit.details == {
            "report_id": str(report.id),
            "reason": "offensive_drawing",
        }


async def test_report_pins_only_messages_the_reporter_received(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    reporter = await register(reporter_http, "EvidenceReporter")
    target = await register(target_http, "EvidenceTarget")
    moderator = await register(moderator_http, "EvidenceMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    now = datetime.now(timezone.utc)
    visible_id = generate_uuid()
    hidden_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            common = {
                "room_instance_id": generate_uuid(),
                "sender_user_id": UUID(target["id"]),
                "sender_player_id": generate_uuid(),
                "sender_display_name_snapshot": "EvidenceTarget",
                "sender_is_anonymous_snapshot": False,
                "is_spectator": False,
                "message_kind": "chat",
                "audience": "prompt_aware",
                "near_miss_kind": None,
                "created_at": now,
                "expires_at": now + timedelta(days=30),
            }
            session.add_all(
                [
                    RoomMessage(
                        id=visible_id,
                        audience_user_ids=[reporter["id"], target["id"]],
                        text="Selected abusive message",
                        **common,
                    ),
                    RoomMessage(
                        id=hidden_id,
                        audience_user_ids=[target["id"]],
                        text="A message the reporter never received",
                        **common,
                    ),
                ]
            )

    submitted = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "Please review the selected line.",
            "messageIds": [str(visible_id)],
        },
    )
    assert submitted.status_code == 201

    forbidden = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "This line was not visible to me.",
            "messageIds": [str(hidden_id)],
        },
    )
    assert forbidden.status_code == 403

    listing = await moderator_http.get("/api/moderation/reports")
    evidence = listing.json()["reports"][0]["messageEvidence"]
    assert evidence == [
        {
            "sourceMessageId": str(visible_id),
            "sourceAvailable": True,
            "gameId": None,
            "turnId": None,
            "senderUserId": target["id"],
            "senderDisplayName": "EvidenceTarget",
            "senderNameColor": None,
            "senderWasAnonymous": False,
            "messageKind": "chat",
            "audience": "prompt_aware",
            "nearMissKind": None,
            "text": "Selected abusive message",
            "messageCreatedAt": now.isoformat(),
            "copiedAt": evidence[0]["copiedAt"],
        }
    ]

    assert await purge_expired_room_messages(
        factory, now=now + timedelta(days=31)
    ) == 2
    async with factory() as session:
        pinned = await session.scalar(select(PlayerReportMessageEvidence))
        assert pinned is not None
        assert pinned.text_snapshot == "Selected abusive message"


async def test_moderator_can_review_once_and_every_action_is_audited(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    await register(reporter_http, "ReviewReporter")
    target = await register(target_http, "ReviewTarget")
    moderator = await register(moderator_http, "Reviewer")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    submitted = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "Repeated harassment in chat.",
        },
    )
    report_id = submitted.json()["id"]
    listing = await moderator_http.get(
        "/api/moderation/reports", params={"status": "pending"}
    )
    assert listing.status_code == 200
    assert listing.json()["reports"][0]["details"] == "Repeated harassment in chat."

    reviewed = await moderator_http.patch(
        f"/api/moderation/reports/{report_id}",
        json={"status": "resolved", "note": "Evidence confirmed."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "resolved"
    assert reviewed.json()["reviewedByUserId"] == moderator["id"]
    assert reviewed.json()["reviewedAt"] is not None
    assert (
        await moderator_http.patch(
            f"/api/moderation/reports/{report_id}",
            json={"status": "dismissed", "note": "Try to overwrite."},
        )
    ).status_code == 409

    async with factory() as session:
        events = (
            await session.scalars(
                select(AuditEvent.event_type).order_by(AuditEvent.created_at)
            )
        ).all()
        assert events == ["report.submitted", "report.resolved"]


async def test_ban_revokes_sessions_and_rejects_http_login_and_socket(env):
    new_client, factory, banned_callback = env
    target_http = new_client()
    admin_http = new_client()
    target = await register(target_http, "SuspendedPlayer")
    admin = await register(admin_http, "BanAdmin")
    await set_role(factory, admin["id"], UserRole.ADMIN)
    raw_cookie = target_http.cookies.get("sketchy_session")
    assert raw_cookie

    banned = await admin_http.post(
        "/api/moderation/bans",
        headers={"x-request-id": "019c1000-0000-7000-8000-000000000002"},
        json={
            "userId": target["id"],
            "reason": "Confirmed repeated harassment",
        },
    )
    assert banned.status_code == 201
    assert banned.json()["isActive"] is True
    assert banned.json()["expiresAt"] is None
    banned_callback.assert_awaited_once_with(target["id"])

    async with factory() as session:
        sessions = (
            await session.scalars(
                select(AuthSession).where(AuthSession.user_id == UUID(target["id"]))
            )
        ).all()
        assert sessions and all(item.revoked_at is not None for item in sessions)

    # The revoked token remains attributable to the active ban, rather than
    # looking cookieless and provisioning a replacement guest.
    assert (await target_http.get("/api/auth/me")).status_code == 403
    assert (await target_http.get("/api/health")).status_code == 200
    # Suspension cannot erase the player's privacy rights. The same ban-time
    # credential remains valid only for export/delete/logout endpoints.
    assert (await target_http.post("/api/auth/data-exports")).status_code == 202

    fresh_login = new_client()
    assert (await fresh_login.get("/api/auth/me")).status_code == 200
    refused = await fresh_login.post(
        "/api/auth/login",
        json={"username": "SuspendedPlayer", "password": PASSWORD},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "This account is suspended."

    context = SimpleNamespace(
        sio=SimpleNamespace(save_session=AsyncMock()), session_factory=factory
    )
    with pytest.raises(ConnectionRefusedError, match="suspended"):
        await socket_connect(
            context,
            "banned-sid",
            {"HTTP_COOKIE": f"sketchy_session={raw_cookie}"},
            None,
        )

    async with factory() as session:
        event = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "ban.created")
        )
        assert event is not None
        assert event.request_id == "019c1000-0000-7000-8000-000000000002"
        assert len(event.ip_hash or "") == 64


async def test_revoke_and_expiry_restore_login_without_erasing_history(env):
    new_client, factory, _ = env
    target_http = new_client()
    admin_http = new_client()
    target = await register(target_http, "TemporaryTarget")
    admin = await register(admin_http, "RevokeAdmin")
    await set_role(factory, admin["id"], UserRole.ADMIN)
    expires = datetime.now(timezone.utc) + timedelta(hours=2)
    created = await admin_http.post(
        "/api/moderation/bans",
        json={
            "userId": target["id"],
            "reason": "Temporary suspension",
            "expiresAt": expires.isoformat(),
        },
    )
    ban_id = created.json()["id"]
    duplicate = await admin_http.post(
        "/api/moderation/bans",
        json={"userId": target["id"], "reason": "Duplicate"},
    )
    assert duplicate.status_code == 409

    revoked = await admin_http.post(
        f"/api/moderation/bans/{ban_id}/revoke",
        json={"reason": "Appeal accepted"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["isActive"] is False
    assert revoked.json()["revokeReason"] == "Appeal accepted"

    login_http = new_client()
    await login_http.get("/api/auth/me")
    assert (
        await login_http.post(
            "/api/auth/login",
            json={"username": "TemporaryTarget", "password": PASSWORD},
        )
    ).status_code == 200

    now = datetime.now(timezone.utc)
    async with factory() as session:
        async with session.begin():
            session.add(
                UserBan(
                    id=generate_uuid(),
                    user_id=UUID(target["id"]),
                    banned_by_user_id=UUID(admin["id"]),
                    reason="Already elapsed",
                    created_at=now - timedelta(days=2),
                    expires_at=now - timedelta(days=1),
                )
            )
    assert (await login_http.get("/api/auth/me")).status_code == 200

    active = await admin_http.get("/api/moderation/bans", params={"active": True})
    inactive = await admin_http.get(
        "/api/moderation/bans", params={"active": False}
    )
    assert active.json()["bans"] == []
    assert {item["reason"] for item in inactive.json()["bans"]} == {
        "Temporary suspension",
        "Already elapsed",
    }
    assert all(item["isActive"] is False for item in inactive.json()["bans"])
    async with factory() as session:
        assert await session.scalar(select(func.count(UserBan.id))) == 2
        event_types = set(await session.scalars(select(AuditEvent.event_type)))
        assert {"ban.created", "ban.revoked"}.issubset(event_types)


async def test_role_boundaries_and_database_checks(env):
    new_client, factory, _ = env
    moderator_http = new_client()
    peer_http = new_client()
    moderator = await register(moderator_http, "BoundModerator")
    peer = await register(peer_http, "BoundaryPeer")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    await set_role(factory, peer["id"], UserRole.MODERATOR)

    assert (
        await moderator_http.post(
            "/api/moderation/bans",
            json={"userId": moderator["id"], "reason": "Self"},
        )
    ).status_code == 422
    assert (
        await moderator_http.post(
            "/api/moderation/bans",
            json={"userId": peer["id"], "reason": "Peer"},
        )
    ).status_code == 403

    with pytest.raises(IntegrityError):
        async with factory() as session:
            async with session.begin():
                session.add(
                    PlayerReport(
                        id=generate_uuid(),
                        reporter_user_id=UUID(moderator["id"]),
                        reported_user_id=UUID(moderator["id"]),
                        reason=ReportReason.SPAM.value,
                        status=ReportStatus.PENDING.value,
                        details="self",
                    )
                )


async def test_a_timed_suspension_lifts_itself_and_a_lifted_one_is_still_recorded(env):
    """A suspension with an end date is over when it is over - nobody has to
    remember to lift it - and lifting one keeps the record of it."""
    new_client, factory, _ = env
    moderator_http, target_http = new_client(), new_client()
    moderator = await register(moderator_http, "TimedModerator")
    target = await register(target_http, "TimedTarget")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    created = await moderator_http.post(
        "/api/moderation/bans",
        json={
            "userId": target["id"],
            "reason": "Timed out for the evening",
            "expiresAt": expires_at.isoformat(),
        },
    )
    assert created.status_code == 201
    ban = created.json()
    assert ban["isActive"] is True
    # A moderator reading the list needs to know who, not a UUID.
    assert ban["displayName"] == "TimedTarget"

    listing = await moderator_http.get("/api/moderation/bans?active=true")
    assert [entry["id"] for entry in listing.json()["bans"]] == [ban["id"]]

    # Age the whole row into the past: nothing runs to expire a ban, so the
    # question is whether reading it reports the truth. Both timestamps move,
    # because ck_user_bans_expiry_after_creation refuses a ban that ends before
    # it began - which is the schema being right, not an obstacle.
    async with factory() as session:
        async with session.begin():
            stored = await session.get(UserBan, UUID(ban["id"]))
            stored.created_at = datetime.now(timezone.utc) - timedelta(days=2)
            stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    still_active = await moderator_http.get("/api/moderation/bans?active=true")
    assert still_active.json()["bans"] == []
    everything = await moderator_http.get("/api/moderation/bans")
    lapsed = everything.json()["bans"][0]
    assert lapsed["isActive"] is False
    # Expired, not lifted: nobody decided this, the clock did.
    assert lapsed["revokedAt"] is None


async def test_lifting_a_suspension_records_who_and_why(env):
    new_client, factory, _ = env
    moderator_http, target_http = new_client(), new_client()
    moderator = await register(moderator_http, "LiftingModerator")
    target = await register(target_http, "LiftedTarget")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    created = await moderator_http.post(
        "/api/moderation/bans",
        json={"userId": target["id"], "reason": "Suspended in error"},
    )
    ban_id = created.json()["id"]

    lifted = await moderator_http.post(
        f"/api/moderation/bans/{ban_id}/revoke",
        json={"reason": "Reviewed and reversed"},
    )

    assert lifted.status_code == 200
    body = lifted.json()
    assert body["isActive"] is False
    assert body["revokeReason"] == "Reviewed and reversed"
    assert body["revokedByUserId"] == moderator["id"]
    assert body["displayName"] == "LiftedTarget"
    # Lifting twice is a mistake worth naming rather than a no-op.
    again = await moderator_http.post(
        f"/api/moderation/bans/{ban_id}/revoke",
        json={"reason": "Again"},
    )
    assert again.status_code == 409


async def test_the_same_player_cannot_be_reported_twice_while_it_waits(env):
    """The REST path carries the rule too, and the index carries it under a
    race that both requests pass the check."""
    new_client, factory, _ = env
    reporter_http, target_http = new_client(), new_client()
    await register(reporter_http, "DoubleReporter")
    target = await register(target_http, "DoubleTarget")

    body = {
        "reportedUserId": target["id"],
        "reason": "harassment",
        "details": "Said the thing.",
    }
    first = await reporter_http.post("/api/reports", json=body)
    second = await reporter_http.post("/api/reports", json=body)

    assert first.status_code == 201
    assert second.status_code == 409
    assert "already reported" in second.json()["detail"]

    # The index is what decides, not the check - proved by inserting straight
    # past the endpoint, the way two simultaneous requests would.
    async with factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    PlayerReport(
                        id=generate_uuid(),
                        reporter_user_id=UUID(
                            (await reporter_http.get("/api/auth/me")).json()["id"]
                        ),
                        reported_user_id=UUID(target["id"]),
                        reason=ReportReason.SPAM.value,
                        details="A racing duplicate.",
                        context_snapshot={},
                    )
                )

    # Reviewed, so the same reporter may raise a new one.
    moderator_http = new_client()
    moderator = await register(moderator_http, "DoubleModerator")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    reviewed = await moderator_http.patch(
        f"/api/moderation/reports/{first.json()['id']}",
        json={"status": "dismissed", "note": "Not actionable"},
    )
    assert reviewed.status_code == 200

    third = await reporter_http.post("/api/reports", json=body)
    assert third.status_code == 201

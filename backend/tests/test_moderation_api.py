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

from app.api.moderation import create_moderation_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import (
    UserBlock,
    AuditEvent,
    AuthSession,
    PlayerReport,
    PlayerReportMessageEvidence,
    RoomMessage,
    User,
    UserBan,
    generate_uuid,
)
from app.domain_values import ReportReason, ReportStatus, UserRole
from app.handlers.connection import connect as socket_connect
from app.services.presence import PresenceRegistry
from app.services.room_quotas import RoomCapacityService
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.services.message_retention import purge_expired_room_messages

from tests.dbfixtures import create_test_db


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "moderation-test-secret")
    factory, engine = await create_test_db()
    users = SqlAlchemyUserRepository(factory)
    banned_callback = AsyncMock()
    warned_callback = AsyncMock()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(
        create_moderation_router(
            factory,
            on_user_banned=banned_callback,
            on_user_warned=warned_callback,
        )
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

    # Reachable from tests without widening the fixture's 3-tuple.
    new_client.warned_callback = warned_callback
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
            # A REST report has no live canvas to copy from.
            "has_drawing": False,
        }


async def test_report_pins_only_messages_the_reporter_received(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    reporter = await register(reporter_http, "EvidReporter")
    target = await register(target_http, "EvidTarget")
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
                "sender_display_name_snapshot": "EvidTarget",
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
            "senderDisplayName": "EvidTarget",
            "senderNameColor": None,
            "senderWasAnonymous": False,
            "messageKind": "chat",
            "audience": "prompt_aware",
            "nearMissKind": None,
            "role": "cited",
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
        sio=SimpleNamespace(save_session=AsyncMock()),
        session_factory=factory,
        room_capacity=RoomCapacityService(),
        presence=PresenceRegistry(),
    )
    with pytest.raises(ConnectionRefusedError, match="suspended"):
        await socket_connect(
            context,
            "banned-sid",
            {"HTTP_COOKIE": f"sketchy_session={raw_cookie}"},
            None,
        )
    # A refused handshake never reaches the disconnect handler - Socket.IO
    # answers it with CONNECT_ERROR and tears the session down itself - so a
    # socket counted on the way in and refused on the way out would sit in the
    # ledger for ever. Enough of those and the process refuses everybody.
    assert context.room_capacity.open_sockets == 0
    # The same property, for the ledger that says who is reachable: a
    # suspension refused here must not leave the account listed as online.
    assert context.presence.online_accounts == 0

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
    await login_http.post("/api/auth/display-name", json={"displayName": "Visitor"})
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


async def test_a_suspended_account_is_told_why_and_for_how_long(env):
    """Being signed out with no explanation is the experience this replaces."""
    new_client, factory, _ = env
    moderator_http, target_http = new_client(), new_client()
    moderator = await register(moderator_http, "TellingModerator")
    target = await register(target_http, "TellingTarget")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    created = await moderator_http.post(
        "/api/moderation/bans",
        json={
            "userId": target["id"],
            "reason": "Harassment in chat",
            "expiresAt": expires_at.isoformat(),
        },
    )
    assert created.status_code == 201

    refused = await target_http.get("/api/auth/me")

    assert refused.status_code == 403
    body = refused.json()
    assert body["suspended"] is True
    assert body["reason"] == "Harassment in chat"
    assert body["expiresAt"] is not None
    assert body["detail"] == "This account is suspended."


async def test_an_ordinary_refusal_is_not_mistaken_for_a_suspension(env):
    """The client raises a blocking notice on this flag, so nothing else may
    carry it."""
    new_client, factory, _ = env
    player_http = new_client()
    await register(player_http, "OrdinaryRefusal")

    refused = await player_http.get("/api/moderation/reports")

    assert refused.status_code == 403
    assert "suspended" not in refused.json()


async def test_a_suspended_account_can_still_sign_out(env):
    """The notice offers one way off the screen, so that way has to work.

    Signing out is one of the few paths a suspended account may reach - the
    others being its data export and its own deletion - because the alternative
    is a browser that can never be used again by anybody.
    """
    new_client, factory, _ = env
    moderator_http, target_http = new_client(), new_client()
    moderator = await register(moderator_http, "ExitModerator")
    target = await register(target_http, "ExitTarget")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    banned = await moderator_http.post(
        "/api/moderation/bans",
        json={"userId": target["id"], "reason": "Suspended for the test"},
    )
    assert banned.status_code == 201
    assert (await target_http.get("/api/auth/me")).status_code == 403

    signed_out = await target_http.post("/api/auth/logout")

    assert signed_out.status_code == 200
    # And the browser is usable again afterwards: the next visitor is a guest,
    # not the suspended account still being refused.
    fresh = await target_http.get("/api/auth/me")
    assert fresh.status_code == 200
    assert fresh.json() is None, "the suspended account is no longer the caller"
    # And it is usable: naming yourself provisions somebody new, not the
    # suspended account being refused again.
    visitor = await target_http.post(
        "/api/auth/display-name", json={"displayName": "Visitor"}
    )
    assert visitor.status_code == 200
    assert visitor.json()["id"] != target["id"]
    assert visitor.json()["isAnonymous"] is True


async def test_a_suspension_from_a_report_shows_the_messages_it_was_about(env):
    """A reason with nothing behind it is easy to dismiss. Their own words are
    what make it something they can weigh."""
    new_client, factory, _ = env
    reporter_http, target_http, moderator_http = (
        new_client(),
        new_client(),
        new_client(),
    )
    reporter = await register(reporter_http, "EvidReporter")
    target = await register(target_http, "EvidTarget")
    moderator = await register(moderator_http, "EvidMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    async with factory() as session:
        async with session.begin():
            now = datetime.now(timezone.utc)
            session.add(
                RoomMessage(
                    id=generate_uuid(),
                    room_instance_id=generate_uuid(),
                    sender_user_id=UUID(target["id"]),
                    sender_player_id=generate_uuid(),
                    sender_display_name_snapshot="EvidTarget",
                    sender_is_anonymous_snapshot=False,
                    message_kind="chat",
                    audience="room",
                    text="the thing that was reported",
                    audience_user_ids=[reporter["id"], target["id"]],
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                )
            )
            message_id = (
                await session.scalar(select(RoomMessage.id))
            )

    filed = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "Look at what they said.",
            "messageIds": [str(message_id)],
        },
    )
    assert filed.status_code == 201

    banned = await moderator_http.post(
        "/api/moderation/bans",
        json={
            "userId": target["id"],
            "reason": "Harassment in chat",
            "reportId": filed.json()["id"],
        },
    )
    assert banned.status_code == 201

    refused = await target_http.get("/api/auth/me")

    assert refused.status_code == 403
    body = refused.json()
    assert [line["text"] for line in body["messages"]] == [
        "the thing that was reported"
    ]
    # Their own message, and nothing about who reported it.
    assert "EvidReporter" not in str(body)
    assert reporter["id"] not in str(body)


async def test_a_ban_refuses_a_report_about_somebody_else(env):
    """Otherwise a suspension could be made to show one player another
    player's messages."""
    new_client, factory, _ = env
    reporter_http, target_http, other_http, moderator_http = (
        new_client(),
        new_client(),
        new_client(),
        new_client(),
    )
    await register(reporter_http, "MixReporter")
    target = await register(target_http, "MixTarget")
    other = await register(other_http, "MixOther")
    moderator = await register(moderator_http, "MixMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    filed = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": other["id"],
            "reason": "spam",
            "details": "About somebody else entirely.",
        },
    )
    assert filed.status_code == 201

    refused = await moderator_http.post(
        "/api/moderation/bans",
        json={
            "userId": target["id"],
            "reason": "Wrong report",
            "reportId": filed.json()["id"],
        },
    )

    assert refused.status_code == 422


async def test_a_warning_reaches_the_player_once_and_its_receipt_is_recorded(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    await register(reporter_http, "WarnReporter")
    target = await register(target_http, "WarnTarget")
    moderator = await register(moderator_http, "WarnModerator")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    submitted = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "Kept it up after being asked to stop.",
        },
    )
    report_id = submitted.json()["id"]
    async with factory() as session:
        async with session.begin():
            session.add(
                PlayerReportMessageEvidence(
                    report_id=UUID(report_id),
                    position=0,
                    source_message_snapshot_id=generate_uuid(),
                    sender_user_id=UUID(target["id"]),
                    sender_display_name_snapshot="WarnTarget",
                    sender_is_anonymous_snapshot=False,
                    message_kind="chat",
                    audience="room",
                    text_snapshot="nobody wants you in this room",
                    message_created_at=datetime.now(timezone.utc),
                )
            )

    issued = await moderator_http.post(
        "/api/moderation/warnings",
        json={
            "userId": target["id"],
            "reason": "Harassment in room chat - next time is a suspension.",
            "reportId": report_id,
        },
    )
    assert issued.status_code == 201
    warning_id = issued.json()["id"]
    # The live-push hook fired after commit, naming the warned account - this
    # is what tells a connected player without waiting for their next visit.
    new_client.warned_callback.assert_awaited_once_with(target["id"])

    # The warned player sees their own words behind the reason, exactly once.
    pending = await target_http.get("/api/warnings/pending")
    assert pending.status_code == 200
    body = pending.json()["warning"]
    assert body["id"] == warning_id
    assert body["reason"].startswith("Harassment in room chat")
    assert body["messages"] == [
        {
            "text": "nobody wants you in this room",
            "at": body["messages"][0]["at"],
        }
    ]

    # Nobody else can see it or acknowledge it away.
    assert (await reporter_http.get("/api/warnings/pending")).json()["warning"] is None
    assert (
        await reporter_http.post(f"/api/warnings/{warning_id}/acknowledge")
    ).status_code == 404

    assert (
        await target_http.post(f"/api/warnings/{warning_id}/acknowledge")
    ).status_code == 200
    assert (await target_http.get("/api/warnings/pending")).json()["warning"] is None

    async with factory() as session:
        events = (
            await session.scalars(
                select(AuditEvent.event_type).order_by(AuditEvent.created_at)
            )
        ).all()
        assert "warning.issued" in events


async def test_warning_role_boundaries_match_suspensions(env):
    new_client, factory, _ = env
    target_http = new_client()
    moderator_http = new_client()
    admin_http = new_client()
    other_http = new_client()
    target = await register(target_http, "BoundaryTarget")
    moderator = await register(moderator_http, "BoundaryMod")
    admin = await register(admin_http, "BoundaryAdmin")
    other = await register(other_http, "BoundaryOtherMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    await set_role(factory, admin["id"], UserRole.ADMIN)
    await set_role(factory, other["id"], UserRole.MODERATOR)

    async def warn(client, user_id, reason="A warning."):
        return await client.post(
            "/api/moderation/warnings", json={"userId": user_id, "reason": reason}
        )

    # An ordinary player is refused outright.
    assert (await warn(target_http, moderator["id"])).status_code == 403
    # Nobody warns an administrator; a moderator cannot warn a moderator.
    assert (await warn(moderator_http, admin["id"])).status_code == 403
    assert (await warn(moderator_http, other["id"])).status_code == 403
    # An admin can warn a moderator, and a moderator an ordinary player.
    assert (await warn(admin_http, other["id"])).status_code == 201
    assert (await warn(moderator_http, moderator["id"])).status_code == 422
    assert (await warn(moderator_http, target["id"])).status_code == 201

    # A report about somebody else cannot be attached.
    submitted = await target_http.post(
        "/api/reports",
        json={
            "reportedUserId": moderator["id"],
            "reason": "harassment",
            "details": "Unrelated report used as a link target.",
        },
    )
    assert (
        await admin_http.post(
            "/api/moderation/warnings",
            json={
                "userId": target["id"],
                "reason": "Mismatched report.",
                "reportId": submitted.json()["id"],
            },
        )
    ).status_code == 422


async def test_the_queue_shows_the_reported_players_standing(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    await register(reporter_http, "StandingReporter")
    target = await register(target_http, "StandingTarget")
    moderator = await register(moderator_http, "StandingMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    first = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "First incident.",
        },
    )
    await moderator_http.patch(
        f"/api/moderation/reports/{first.json()['id']}",
        json={"status": "dismissed", "note": "Not actionable."},
    )
    await moderator_http.post(
        "/api/moderation/warnings",
        json={"userId": target["id"], "reason": "A first warning."},
    )
    second = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "Second incident.",
        },
    )
    assert second.status_code == 201

    listing = await moderator_http.get(
        "/api/moderation/reports", params={"status": "pending"}
    )
    report = listing.json()["reports"][0]
    player = report["reportedPlayer"]
    assert player["displayName"] == "StandingTarget"
    assert player["registered"] is True
    assert player["createdAt"] is not None
    # The open report itself is not "prior"; the dismissed one is.
    assert player["priorReports"] == 1
    assert player["priorWarnings"] == 1
    assert player["activeSuspension"] is False


async def test_a_consequence_decides_its_report_in_one_transaction(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    await register(reporter_http, "AtomicReporter")
    target = await register(target_http, "AtomicTarget")
    moderator = await register(moderator_http, "AtomicMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    submitted = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "One incident, one decision.",
        },
    )
    report_id = submitted.json()["id"]

    issued = await moderator_http.post(
        "/api/moderation/warnings",
        json={
            "userId": target["id"],
            "reason": "Formal warning.",
            "reportId": report_id,
        },
    )
    assert issued.status_code == 201

    # The warning decided the report in the same transaction...
    listing = await moderator_http.get(
        "/api/moderation/reports", params={"status": "resolved"}
    )
    resolved = listing.json()["reports"][0]
    assert resolved["id"] == report_id
    assert resolved["resolutionNote"] == "Formal warning."
    assert resolved["reviewedByUserId"] == moderator["id"]

    # ...so a retry (or a racing moderator) is refused rather than issuing a
    # second consequence for the same complaint.
    retried = await moderator_http.post(
        "/api/moderation/warnings",
        json={
            "userId": target["id"],
            "reason": "Formal warning.",
            "reportId": report_id,
        },
    )
    assert retried.status_code == 409
    async with factory() as session:
        from app.db.models import UserWarning

        count = await session.scalar(
            select(func.count(UserWarning.id)).where(
                UserWarning.user_id == UUID(target["id"])
            )
        )
        assert count == 1

    # Suspending from an already-decided report is refused the same way.
    banned = await moderator_http.post(
        "/api/moderation/bans",
        json={
            "userId": target["id"],
            "reason": "Escalation attempt.",
            "reportId": report_id,
        },
    )
    assert banned.status_code == 409


async def test_a_lobby_line_is_evidence_on_its_own_terms(env):
    """Said to every lobby that was open, so it has no room to agree on and no
    recipient list to check the reporter against - public by construction.
    It is one conversation and not any room's, so it is never cited beside a
    room line, and it still has to be the reported player's own."""
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    reporter = await register(reporter_http, "LobbyReporter")
    target = await register(target_http, "LobbyTarget")
    moderator = await register(moderator_http, "LobbyMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    now = datetime.now(timezone.utc)
    lobby_id = generate_uuid()
    room_id = generate_uuid()
    reporters_own = generate_uuid()
    async with factory() as session:
        async with session.begin():
            common = {
                "sender_display_name_snapshot": "LobbyTarget",
                "sender_is_anonymous_snapshot": False,
                "is_spectator": False,
                "message_kind": "chat",
                "near_miss_kind": None,
                "created_at": now,
                "expires_at": now + timedelta(days=30),
            }
            session.add_all(
                [
                    RoomMessage(
                        id=lobby_id,
                        sender_user_id=UUID(target["id"]),
                        room_instance_id=None,
                        sender_player_id=None,
                        audience="lobby",
                        audience_user_ids=[],
                        text="Said to the whole lobby",
                        **common,
                    ),
                    RoomMessage(
                        id=room_id,
                        sender_user_id=UUID(target["id"]),
                        room_instance_id=generate_uuid(),
                        sender_player_id=generate_uuid(),
                        audience="room",
                        audience_user_ids=[reporter["id"], target["id"]],
                        text="Said in a room",
                        **common,
                    ),
                    RoomMessage(
                        id=reporters_own,
                        sender_user_id=UUID(reporter["id"]),
                        room_instance_id=None,
                        sender_player_id=None,
                        audience="lobby",
                        audience_user_ids=[],
                        text="The reporter's own lobby line",
                        **common,
                    ),
                ]
            )

    def report(message_ids, details):
        return reporter_http.post(
            "/api/reports",
            json={
                "reportedUserId": target["id"],
                "reason": "harassment",
                "details": details,
                "messageIds": [str(message_id) for message_id in message_ids],
            },
        )

    mixed = await report([lobby_id, room_id], "One from the lobby, one from a room.")
    assert mixed.status_code == 422
    assert "cannot be mixed" in mixed.json()["detail"]

    not_theirs = await report([reporters_own], "This one is mine, not theirs.")
    assert not_theirs.status_code == 422
    assert "authored by the reported player" in not_theirs.json()["detail"]

    accepted = await report([lobby_id], "Please review what they said in the lobby.")
    assert accepted.status_code == 201

    listing = await moderator_http.get("/api/moderation/reports")
    [pinned] = [
        item
        for item in listing.json()["reports"]
        if item["reportedUserId"] == target["id"]
    ]
    # The cited line, and around it the reporter's own lobby line as context:
    # the lobby is one conversation, so that is where the context comes from,
    # and the room line is nowhere in it.
    copied = pinned["messageEvidence"]
    assert [(line["role"], line["text"]) for line in copied] == [
        ("cited", "Said to the whole lobby"),
        ("context", "The reporter's own lobby line"),
    ]
    assert {line["audience"] for line in copied} == {"lobby"}
    assert copied[0]["sourceMessageId"] == str(lobby_id)
    assert copied[1]["sourceMessageId"] == str(reporters_own)


@pytest.mark.asyncio
async def test_a_report_carries_what_was_said_around_the_cited_line(env):
    """A line on its own is often unreadable, so the server copies the
    conversation around it: ten before and five after, within twelve hours,
    from anyone, but only what the reporter actually received, and never the
    cited line twice. The reported player is shown only their own words."""
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    other_http = new_client()
    moderator_http = new_client()
    reporter = await register(reporter_http, "CtxReporter")
    target = await register(target_http, "CtxTarget")
    other = await register(other_http, "CtxOther")
    moderator = await register(moderator_http, "CtxMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    anchor = datetime.now(timezone.utc) - timedelta(hours=1)
    room = generate_uuid()
    cited_id = generate_uuid()

    def row(text, *, at, sender, audience="room", received=True):
        return RoomMessage(
            id=generate_uuid(),
            room_instance_id=room,
            sender_user_id=UUID(sender["id"]),
            sender_player_id=generate_uuid(),
            sender_display_name_snapshot=sender["displayName"],
            sender_is_anonymous_snapshot=False,
            is_spectator=False,
            message_kind="chat",
            audience=audience,
            audience_user_ids=(
                [reporter["id"], target["id"], other["id"]]
                if received
                else [target["id"], other["id"]]
            ),
            near_miss_kind=None,
            text=text,
            created_at=at,
            expires_at=at + timedelta(days=30),
        )

    async with factory() as session:
        async with session.begin():
            rows = [
                # Twelve visible lines before: the ten nearest are kept.
                *[
                    row(f"before {index}", at=anchor - timedelta(minutes=12 - index), sender=other)
                    for index in range(12)
                ],
                # Not received by the reporter, so not theirs to have copied.
                row(
                    "prompt-aware and never delivered",
                    at=anchor - timedelta(seconds=30),
                    sender=other,
                    audience="prompt_aware",
                    received=False,
                ),
                # Outside the window on either side.
                row("thirteen hours before", at=anchor - timedelta(hours=13), sender=other),
                row("thirteen hours after", at=anchor + timedelta(hours=13), sender=other),
                # Six after: the five nearest are kept.
                *[
                    row(f"after {index}", at=anchor + timedelta(minutes=index + 1), sender=reporter)
                    for index in range(6)
                ],
            ]
            cited = row("the line itself", at=anchor, sender=target)
            cited.id = cited_id
            session.add_all([*rows, cited])

    submitted = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "Read it in context.",
            "messageIds": [str(cited_id)],
        },
    )
    assert submitted.status_code == 201, submitted.text

    listing = await moderator_http.get("/api/moderation/reports")
    [case] = [
        item
        for item in listing.json()["reports"]
        if item["reportedUserId"] == target["id"]
    ]
    copied = [(line["role"], line["text"]) for line in case["messageEvidence"]]
    assert copied == [
        *[("context", f"before {index}") for index in range(2, 12)],
        ("cited", "the line itself"),
        *[("context", f"after {index}") for index in range(5)],
    ]
    # Who said what survives the copy, so the thread reads as one.
    by_text = {line["text"]: line for line in case["messageEvidence"]}
    assert by_text["before 2"]["senderDisplayName"] == "CtxOther"
    assert by_text["after 0"]["senderDisplayName"] == "CtxReporter"
    assert by_text["the line itself"]["senderUserId"] == target["id"]

    # A warning and a suspension from this report show the player their own
    # reported words and nothing anybody else said (R-MOD-12).
    warned = await moderator_http.post(
        "/api/moderation/warnings",
        json={"userId": target["id"], "reason": "Mind the tone.", "reportId": case["id"]},
    )
    assert warned.status_code == 201, warned.text
    pending = await target_http.get("/api/warnings/pending")
    assert [line["text"] for line in pending.json()["warning"]["messages"]] == [
        "the line itself"
    ]


@pytest.mark.asyncio
async def test_a_report_with_nothing_cited_has_no_context(env):
    """No cited line means no place to look: a REST report with no
    messageIds copies nothing, rather than guessing a room."""
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    await register(reporter_http, "BareReporter")
    target = await register(target_http, "BareTarget")
    moderator = await register(moderator_http, "BareMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    now = datetime.now(timezone.utc)
    async with factory() as session:
        async with session.begin():
            session.add(
                RoomMessage(
                    id=generate_uuid(),
                    room_instance_id=None,
                    sender_user_id=UUID(target["id"]),
                    sender_player_id=None,
                    sender_display_name_snapshot="BareTarget",
                    sender_is_anonymous_snapshot=False,
                    is_spectator=False,
                    message_kind="chat",
                    audience="lobby",
                    audience_user_ids=[],
                    near_miss_kind=None,
                    text="A lobby line nobody cited",
                    created_at=now,
                    expires_at=now + timedelta(days=30),
                )
            )
    submitted = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "inappropriate_name",
            "details": "The name, not anything said.",
        },
    )
    assert submitted.status_code == 201, submitted.text
    listing = await moderator_http.get("/api/moderation/reports")
    [case] = [
        item
        for item in listing.json()["reports"]
        if item["reportedUserId"] == target["id"]
    ]
    assert case["messageEvidence"] == []


@pytest.mark.asyncio
async def test_lobby_context_omits_authors_the_reporter_blocked(env):
    """A lobby line by somebody the reporter muted was never delivered to
    them (R-LCHAT-03). The retained row records no recipients, so the block
    is re-applied when the context is chosen - otherwise a report about a
    neighbouring line would copy the muted text into evidence the reporter
    can export, which is exactly what the block withholds."""
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    muted_http = new_client()
    other_http = new_client()
    moderator_http = new_client()
    reporter = await register(reporter_http, "BlkReporter")
    target = await register(target_http, "BlkTarget")
    muted = await register(muted_http, "BlkMuted")
    other = await register(other_http, "BlkOther")
    moderator = await register(moderator_http, "BlkMod")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    anchor = datetime.now(timezone.utc) - timedelta(minutes=5)
    cited_id = generate_uuid()

    def lobby_line(text, *, at, sender):
        return RoomMessage(
            id=generate_uuid(),
            room_instance_id=None,
            sender_user_id=UUID(sender["id"]),
            sender_player_id=None,
            sender_display_name_snapshot=sender["displayName"],
            sender_is_anonymous_snapshot=False,
            is_spectator=False,
            message_kind="chat",
            audience="lobby",
            audience_user_ids=[],
            near_miss_kind=None,
            text=text,
            created_at=at,
            expires_at=at + timedelta(days=30),
        )

    async with factory() as session:
        async with session.begin():
            session.add(
                UserBlock(
                    blocker_user_id=UUID(reporter["id"]),
                    blocked_user_id=UUID(muted["id"]),
                )
            )
            cited = lobby_line("the reported line", at=anchor, sender=target)
            cited.id = cited_id
            session.add_all(
                [
                    lobby_line("seen, said before", at=anchor - timedelta(minutes=2), sender=other),
                    lobby_line("muted, said before", at=anchor - timedelta(minutes=1), sender=muted),
                    cited,
                    lobby_line("muted, said after", at=anchor + timedelta(minutes=1), sender=muted),
                    lobby_line("seen, said after", at=anchor + timedelta(minutes=2), sender=other),
                ]
            )

    submitted = await reporter_http.post(
        "/api/reports",
        json={
            "reportedUserId": target["id"],
            "reason": "harassment",
            "details": "Read it in context.",
            "messageIds": [str(cited_id)],
        },
    )
    assert submitted.status_code == 201, submitted.text

    listing = await moderator_http.get("/api/moderation/reports")
    [case] = [
        item
        for item in listing.json()["reports"]
        if item["reportedUserId"] == target["id"]
    ]
    assert [(line["role"], line["text"]) for line in case["messageEvidence"]] == [
        ("context", "seen, said before"),
        ("cited", "the reported line"),
        ("context", "seen, said after"),
    ]


async def _attach_drawing(factory, report_id: str, frame: bytes) -> None:
    """Pin a canvas frame to a report the way the socket path does."""
    from app.canvas_storage import stored_drawing_checksum
    from app.db.models import PlayerReportDrawingEvidence

    async with factory() as session:
        async with session.begin():
            session.add(
                PlayerReportDrawingEvidence(
                    report_id=UUID(report_id),
                    turn_id_snapshot=generate_uuid(),
                    round_number=2,
                    prompt_snapshot="lighthouse",
                    action_count=0,
                    format_magic="SKCH",
                    format_version=1,
                    payload=frame,
                    byte_size=len(frame),
                    checksum_sha256=stored_drawing_checksum(frame),
                )
            )


async def test_the_queue_carries_the_drawing_and_only_a_reviewer_reads_it(env):
    """The queue lists a drawing by its metadata; the bytes have their own
    route, answered in the wire format and only to a moderator. A report
    without one, or that does not exist, is a 404 either way."""
    from app.canvas_history import PackedCanvasHistory

    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    await register(reporter_http, "DrawingReporter")
    target = await register(target_http, "DrawingTarget")
    moderator = await register(moderator_http, "DrawingReviewer")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    with_drawing = (
        await reporter_http.post(
            "/api/reports",
            json={
                "reportedUserId": target["id"],
                "reason": "offensive_drawing",
                "details": "The lighthouse was not a lighthouse.",
            },
        )
    ).json()["id"]
    frame = PackedCanvasHistory().binary_payload()
    await _attach_drawing(factory, with_drawing, frame)

    listing = await moderator_http.get(
        "/api/moderation/reports", params={"status": "pending"}
    )
    assert listing.status_code == 200
    (report,) = listing.json()["reports"]
    assert report["id"] == with_drawing
    drawing = report["drawing"]
    assert drawing["prompt"] == "lighthouse"
    assert drawing["roundNumber"] == 2
    assert drawing["actionCount"] == 0
    assert drawing["byteSize"] == len(frame)
    assert drawing["capturedAt"] is not None
    assert "payload" not in drawing

    bytes_response = await moderator_http.get(
        f"/api/moderation/reports/{with_drawing}/drawing"
    )
    assert bytes_response.status_code == 200
    assert bytes_response.content == frame
    assert bytes_response.headers["content-type"] == "application/octet-stream"
    assert bytes_response.headers["cache-control"] == "private, no-store"

    # Evidence is for the reviewer: the reporter who asked for it cannot
    # read it back, and neither can anyone else.
    assert (
        await reporter_http.get(f"/api/moderation/reports/{with_drawing}/drawing")
    ).status_code == 403
    assert (
        await target_http.get(f"/api/moderation/reports/{with_drawing}/drawing")
    ).status_code == 403

    # Reviewing keeps the drawing with the report.
    reviewed = await moderator_http.patch(
        f"/api/moderation/reports/{with_drawing}",
        json={"status": "resolved", "note": "It was a lighthouse after all."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["drawing"]["prompt"] == "lighthouse"
    assert (
        await moderator_http.get(f"/api/moderation/reports/{with_drawing}/drawing")
    ).content == frame

    without_drawing = (
        await reporter_http.post(
            "/api/reports",
            json={
                "reportedUserId": target["id"],
                "reason": "spam",
                "details": "Same link, six times.",
            },
        )
    ).json()["id"]
    assert (
        await moderator_http.get(
            "/api/moderation/reports", params={"status": "pending"}
        )
    ).json()["reports"][0]["drawing"] is None
    assert (
        await moderator_http.get(f"/api/moderation/reports/{without_drawing}/drawing")
    ).status_code == 404
    assert (
        await moderator_http.get(f"/api/moderation/reports/{generate_uuid()}/drawing")
    ).status_code == 404


async def test_a_corrupt_report_drawing_is_refused_rather_than_served(env):
    """The checksum beside the bytes is checked on every read, as it is for
    a stored turn drawing."""
    from sqlalchemy import update

    from app.canvas_history import PackedCanvasHistory
    from app.db.models import PlayerReportDrawingEvidence

    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    moderator_http = new_client()
    await register(reporter_http, "CorruptReporter")
    target = await register(target_http, "CorruptTarget")
    moderator = await register(moderator_http, "CorruptReviewer")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    report_id = (
        await reporter_http.post(
            "/api/reports",
            json={
                "reportedUserId": target["id"],
                "reason": "offensive_drawing",
                "details": "See the drawing.",
            },
        )
    ).json()["id"]
    await _attach_drawing(factory, report_id, PackedCanvasHistory().binary_payload())
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(PlayerReportDrawingEvidence)
                .where(PlayerReportDrawingEvidence.report_id == UUID(report_id))
                .values(checksum_sha256="0" * 64)
            )

    assert (
        await moderator_http.get(f"/api/moderation/reports/{report_id}/drawing")
    ).status_code == 500


async def test_closed_cases_are_one_stream_newest_decision_first_and_paged(
    env, monkeypatch
):
    """Decided player and content reports are read together, ordered by when
    they were decided, under a page - the open queues can be held whole, but
    closed cases accumulate for as long as the service runs, and without a
    page the newest would be the ones nobody could reach."""
    from sqlalchemy import update

    from app.db.models import PromptContentReport

    new_client, factory, _ = env
    moderator_http = new_client()
    moderator = await register(moderator_http, "ClosedReviewer")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    target = await register(new_client(), "ClosedTarget")
    owner = await register(new_client(), "ClosedListOwner")

    async def player_report(name: str) -> str:
        http = new_client()
        await register(http, name)
        return (
            await http.post(
                "/api/reports",
                json={
                    "reportedUserId": target["id"],
                    "reason": "spam",
                    "details": f"Filed by {name}.",
                },
            )
        ).json()["id"]

    async def content_report(name: str) -> str:
        report = PromptContentReport(
            id=generate_uuid(),
            reporter_user_id=UUID(moderator["id"]),
            reported_owner_user_id=UUID(owner["id"]),
            target_type="list",
            list_name_snapshot=name,
            reason="inappropriate",
            details=f"About the list {name}.",
        )
        async with factory() as session:
            async with session.begin():
                session.add(report)
        return str(report.id)

    first = await player_report("ClosedFirst")
    second = await player_report("ClosedSecond")
    third = await player_report("ClosedThird")
    still_open = await player_report("ClosedStillOpen")
    list_a = await content_report("Alpha")
    list_b = await content_report("Beta")

    # Decided in an order that interleaves the two kinds, so the merge is
    # what is being tested rather than one table's own order.
    base = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    decided = [
        (PlayerReport, first, 1),
        (PromptContentReport, list_a, 2),
        (PlayerReport, second, 3),
        (PromptContentReport, list_b, 4),
        (PlayerReport, third, 5),
    ]
    async with factory() as session:
        async with session.begin():
            for model, row_id, minute in decided:
                await session.execute(
                    update(model)
                    .where(model.id == UUID(row_id))
                    .values(
                        status=ReportStatus.RESOLVED.value,
                        reviewed_by_user_id=UUID(moderator["id"]),
                        resolution_note="Decided.",
                        reviewed_at=base + timedelta(minutes=minute),
                    )
                )

    def ids(page: dict) -> list[str]:
        merged = sorted(
            [(report["reviewedAt"], report["id"]) for report in page["players"]]
            + [(report["reviewedAt"], report["id"]) for report in page["content"]],
            reverse=True,
        )
        return [row_id for _, row_id in merged]

    page_one = await moderator_http.get(
        "/api/moderation/closed-cases", params={"limit": 2, "offset": 0}
    )
    assert page_one.status_code == 200
    assert ids(page_one.json()) == [third, list_b]
    assert page_one.json()["hasMore"] is True
    # A player report on a closed page carries everything the open queue
    # does, standing included.
    assert page_one.json()["players"][0]["reportedPlayer"]["displayName"] == (
        "ClosedTarget"
    )

    page_two = await moderator_http.get(
        "/api/moderation/closed-cases", params={"limit": 2, "offset": 2}
    )
    assert ids(page_two.json()) == [second, list_a]
    assert page_two.json()["hasMore"] is True

    page_three = await moderator_http.get(
        "/api/moderation/closed-cases", params={"limit": 2, "offset": 4}
    )
    assert ids(page_three.json()) == [first]
    assert page_three.json()["hasMore"] is False
    assert page_three.json()["content"] == []

    # The one still waiting is not a closed case.
    everything = await moderator_http.get("/api/moderation/closed-cases")
    assert still_open not in ids(everything.json())
    assert len(ids(everything.json())) == 5

    # Bounded, and a reviewer's surface.
    assert (
        await moderator_http.get(
            "/api/moderation/closed-cases", params={"offset": 1001}
        )
    ).status_code == 422
    # At the cap the page stops offering an older one, even though older
    # rows exist: a page that pointed past the bound would only be refused.
    import app.api.moderation as moderation_module

    monkeypatch.setattr(moderation_module, "MAX_CLOSED_CASES_OFFSET", 3)
    capped = await moderator_http.get(
        "/api/moderation/closed-cases", params={"limit": 2, "offset": 2}
    )
    assert ids(capped.json()) == [second, list_a]
    assert capped.json()["hasMore"] is False
    assert (
        await new_client().get("/api/moderation/closed-cases")
    ).status_code == 401


async def test_a_rest_report_needs_no_words_of_its_own(env):
    """The cited line is the complaint, so a lobby report may say nothing
    beside it; blank is stored as empty rather than refused or padded."""
    new_client, factory, _ = env
    reporter_http = new_client()
    target_http = new_client()
    await register(reporter_http, "QuietReporter")
    target = await register(target_http, "QuietTarget")
    filed = await reporter_http.post(
        "/api/reports",
        json={"reportedUserId": target["id"], "reason": "spam", "details": "  "},
    )
    assert filed.status_code == 201
    async with factory() as session:
        report = await session.get(PlayerReport, UUID(filed.json()["id"]))
        assert report.details == ""


async def test_a_closed_case_says_what_was_done_and_by_whom(env):
    """A report's own status only says decided. The queue reads the outcome
    from what was done - a warning or suspension naming the report, the state
    a content decision set - and resolves the reviewer's name when read."""
    new_client, factory, _ = env
    moderator_http = new_client()
    moderator = await register(moderator_http, "OutcomeReviewer")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)

    # One reporter for every case: a reporter holds one open report per
    # target, and these are five targets. Fewer registrations, too, which
    # the fixture's rate limit counts.
    reporter_http = new_client()
    await register(reporter_http, "OutcomeReporter")

    async def report_about(name: str) -> tuple[str, str]:
        target_http = new_client()
        target = await register(target_http, f"{name}Tgt")
        filed = await reporter_http.post(
            "/api/reports",
            json={"reportedUserId": target["id"], "reason": "spam", "details": name},
        )
        return filed.json()["id"], target["id"]

    dismissed, _ = await report_about("Dismissed")
    warned, warned_target = await report_about("Warned")
    suspended, suspended_target = await report_about("Suspended")
    resolved, _ = await report_about("Resolved")
    still_open, _ = await report_about("Open")

    assert (
        await moderator_http.patch(
            f"/api/moderation/reports/{dismissed}",
            json={"status": "dismissed", "note": "Nothing there."},
        )
    ).json()["outcome"] == "dismissed"
    assert (
        await moderator_http.post(
            "/api/moderation/warnings",
            json={"userId": warned_target, "reason": "Tone it down.", "reportId": warned},
        )
    ).status_code == 201
    assert (
        await moderator_http.post(
            "/api/moderation/bans",
            json={"userId": suspended_target, "reason": "Enough.", "reportId": suspended},
        )
    ).status_code == 201
    reviewed = await moderator_http.patch(
        f"/api/moderation/reports/{resolved}",
        json={"status": "resolved", "note": "Handled elsewhere."},
    )
    assert reviewed.json()["outcome"] == "resolved"
    assert reviewed.json()["reviewedBy"] == "OutcomeReviewer"

    closed = (await moderator_http.get("/api/moderation/closed-cases")).json()
    by_id = {report["id"]: report for report in closed["players"]}
    assert {
        report_id: by_id[report_id]["outcome"]
        for report_id in (dismissed, warned, suspended, resolved)
    } == {
        dismissed: "dismissed",
        warned: "warned",
        suspended: "suspended",
        resolved: "resolved",
    }
    assert {report["reviewedBy"] for report in by_id.values()} == {"OutcomeReviewer"}
    assert still_open not in by_id
    pending = (
        await moderator_http.get("/api/moderation/reports", params={"status": "pending"})
    ).json()["reports"]
    assert [report["outcome"] for report in pending] == ["pending"]
    assert pending[0]["reviewedBy"] is None


async def test_a_warning_and_a_suspension_show_the_drawing_they_were_about(env):
    """The drawing the report carried is the player's own work, shown back
    for the reason their words are: by its metadata in the notice, and its
    bytes over a route only they can reach - the suspended one through the
    ban-time credential, since every other request of theirs is refused."""
    from app.canvas_history import PackedCanvasHistory

    new_client, factory, _ = env
    reporter_http = new_client()
    warned_http = new_client()
    suspended_http = new_client()
    moderator_http = new_client()
    await register(reporter_http, "PicReporter")
    warned = await register(warned_http, "PicWarned")
    suspended = await register(suspended_http, "PicSuspended")
    moderator = await register(moderator_http, "PicReviewer")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    frame = PackedCanvasHistory().binary_payload()

    async def report_with_drawing(target_id: str) -> str:
        filed = await reporter_http.post(
            "/api/reports",
            json={
                "reportedUserId": target_id,
                "reason": "offensive_drawing",
                "details": "See the drawing.",
            },
        )
        await _attach_drawing(factory, filed.json()["id"], frame)
        return filed.json()["id"]

    warning_report = await report_with_drawing(warned["id"])
    warning_id = (
        await moderator_http.post(
            "/api/moderation/warnings",
            json={"userId": warned["id"], "reason": "Not a lighthouse.", "reportId": warning_report},
        )
    ).json()["id"]
    pending = (await warned_http.get("/api/warnings/pending")).json()["warning"]
    assert pending["drawing"]["prompt"] == "lighthouse"
    assert "payload" not in pending["drawing"]
    assert (
        await warned_http.get(f"/api/warnings/{warning_id}/drawing")
    ).content == frame
    # Nobody else's to see: not the reporter's, and not a moderator's by
    # this route either.
    assert (
        await reporter_http.get(f"/api/warnings/{warning_id}/drawing")
    ).status_code == 404
    # A warning without a drawing behind it has none to give.
    assert (
        await suspended_http.get("/api/suspension/drawing")
    ).status_code == 404, "not suspended yet, so no suspension to ask about"

    suspension_report = await report_with_drawing(suspended["id"])
    assert (
        await moderator_http.post(
            "/api/moderation/bans",
            json={"userId": suspended["id"], "reason": "Still not a lighthouse.", "reportId": suspension_report},
        )
    ).status_code == 201
    refused = await suspended_http.get("/api/auth/me")
    assert refused.status_code == 403
    assert refused.json()["drawing"]["prompt"] == "lighthouse"
    picture = await suspended_http.get("/api/suspension/drawing")
    assert picture.status_code == 200
    assert picture.content == frame
    assert picture.headers["cache-control"] == "private, no-store"
    # The escape hatch opens that one path and nothing beside it.
    assert (await suspended_http.get("/api/warnings/pending")).status_code == 403

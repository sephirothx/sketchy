"""Filing a bug, what the server stamps on it, and who may triage it."""
from __future__ import annotations

import base64
import struct
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.bug_reports import create_bug_report_router
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AuditEvent, Base, BugReport, User, generate_uuid
from app.domain_values import UserRole
from app.game import Game
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.rooms import RoomManager


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"

PNG = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR"
    + struct.pack(">II", 4, 4)
    + b"\x08\x06\x00\x00\x00"
    + b"\x00" * 32
)
WEBP = b"RIFF" + struct.pack("<I", 32) + b"WEBP" + b"VP8 " + b"\x00" * 24


def encoded(payload: bytes) -> str:
    return base64.b64encode(payload).decode()


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "bug-report-test-secret")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(factory)
    room_manager = RoomManager()
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(users, factory))
    app.include_router(create_bug_report_router(factory, room_manager))

    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        )
        clients.append(client)
        return client

    try:
        yield new_client, factory, room_manager
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def guest(client: AsyncClient) -> dict:
    """Arrive with no account at all and be given the guest one."""
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    return response.json()


async def register(client: AsyncClient, username: str) -> dict:
    await guest(client)
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


def a_report(**overrides) -> dict:
    body = {
        "area": "drawing_and_canvas",
        "severity": "blocks_play",
        "summary": "Timer kept counting after everyone had guessed",
        "details": "Round 2, everyone had guessed but the timer ran to zero.",
        "clientContext": {"buildSha": "a299f80", "route": "/room/BQ7F2K"},
    }
    body.update(overrides)
    return body


async def test_a_guest_may_file_and_the_server_stamps_the_audit(env):
    new_client, factory, _ = env
    http = new_client()
    reporter = await guest(http)
    request_id = "019c1000-0000-7000-8000-0000000000b1"

    response = await http.post(
        "/api/bug-reports",
        headers={"x-request-id": request_id},
        json=a_report(),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    report_id = response.json()["id"]

    async with factory() as session:
        report = await session.get(BugReport, UUID(report_id))
        assert report is not None
        assert report.reporter_user_id == UUID(reporter["id"])
        # Lifted out of the context blob so a queue can group by them.
        assert report.build_sha == "a299f80"
        assert report.route == "/room/BQ7F2K"
        assert report.screenshot_status == "none"
        assert report.server_context["account"]["registered"] is False

        event = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "bug_report.submitted")
        )
        assert event is not None
        assert event.target_type == "bug_report"
        assert event.target_id == report_id
        assert event.request_id == request_id
        assert event.ip_hash
        # The ledger records that a bug was filed, never what it said.
        assert "Timer kept counting" not in str(event.details)


async def test_filing_needs_an_identity(env):
    new_client, _, _ = env
    http = new_client()
    response = await http.post("/api/bug-reports", json=a_report())
    assert response.status_code == 401


async def test_the_server_describes_the_seat_it_can_actually_see(env):
    """Room, game and turn come from live state, not from the client's claim."""
    new_client, factory, room_manager = env
    http = new_client()
    reporter = await guest(http)

    room = room_manager.create_room(name="Coffee break doodles", code="BQ7F2K")
    player = room_manager.add_player(room, "Sparrow-14")
    player.user_id = reporter["id"]
    room.state = "playing"
    room.game = Game(turn_order=[player.id], rounds_total=room.rounds)
    room.game.turn_index = 0
    room.game.current_turn_id = str(generate_uuid())
    room.game.current_drawer = player.id
    room.game.prompt = "lighthouse"

    response = await http.post(
        "/api/bug-reports", json=a_report(roomCode="BQ7F2K")
    )
    assert response.status_code == 201

    async with factory() as session:
        report = await session.get(BugReport, UUID(response.json()["id"]))
        assert report is not None
        assert report.room_code == "BQ7F2K"
        assert report.game_id is not None and report.turn_id is not None
        game = report.server_context["game"]
        assert game["roundNumber"] == 1
        assert game["roundsTotal"] == room.rounds
        assert game["phase"] == "choosing_prompt"
        assert report.server_context["room"]["playerCount"] == 1
        assert report.server_context["seat"]["isHost"] is True
        # A guesser filing a bug is still a guesser: the answer in play must
        # not come back to them in a report they can read.
        assert "lighthouse" not in str(report.server_context)
        assert "lighthouse" not in str(report.client_context)


async def test_a_room_you_are_not_in_tells_you_nothing(env):
    """Naming somebody else's room must not attach their room to your report."""
    new_client, factory, room_manager = env
    http = new_client()
    await guest(http)

    room = room_manager.create_room(name="Somebody else's room", code="ZZZZZZ")
    stranger = room_manager.add_player(room, "Stranger")
    stranger.user_id = str(generate_uuid())

    response = await http.post(
        "/api/bug-reports", json=a_report(roomCode="ZZZZZZ")
    )
    assert response.status_code == 201
    async with factory() as session:
        report = await session.get(BugReport, UUID(response.json()["id"]))
        assert report is not None
        assert report.room_code is None
        assert report.server_context.get("room") is None


async def test_the_error_tail_is_trimmed_rather_than_refused(env):
    """A page erroring in a loop is worth knowing about, not worth dropping."""
    new_client, factory, _ = env
    http = new_client()
    await guest(http)

    response = await http.post(
        "/api/bug-reports",
        json=a_report(
            clientContext={
                "buildSha": "a299f80",
                "recentErrors": [
                    {"at": f"09:41:{index:02d}", "message": "x" * 4000}
                    for index in range(60)
                ],
            }
        ),
    )
    assert response.status_code == 201
    async with factory() as session:
        report = await session.get(BugReport, UUID(response.json()["id"]))
        assert report is not None
        errors = report.client_context["recentErrors"]
        assert len(errors) == 20
        assert all(len(entry["message"]) == 500 for entry in errors)
        # The tail that survives is the newest one, which is the one that
        # actually preceded the failure.
        assert errors[-1]["at"] == "09:41:59"


@pytest.mark.parametrize(
    "sent, stored",
    [
        ("/room/BQ7F2K?invite=secret-code", "/room/BQ7F2K"),
        ("/profile#token=abc", "/profile"),
        ("/room/BQ7F2K?invite=a#b", "/room/BQ7F2K"),
        ("/", "/"),
        ("?only=query", None),
    ],
)
async def test_a_route_never_keeps_what_follows_the_path(env, sent, stored):
    """The client sends a bare pathname; the server makes sure of it.

    A query string is where invite codes and identifiers live. That a report
    never carries one has to hold against a client that is buggy or lying, so
    the cut is made server-side rather than trusted.
    """
    new_client, factory, _ = env
    http = new_client()
    await guest(http)

    response = await http.post(
        "/api/bug-reports",
        json=a_report(clientContext={"buildSha": "a299f80", "route": sent}),
    )
    assert response.status_code == 201
    async with factory() as session:
        report = await session.get(BugReport, UUID(response.json()["id"]))
        assert report is not None
        assert report.route == stored
        # And not left behind in the blob the column was lifted out of.
        assert report.client_context["route"] == stored
        assert "secret-code" not in str(report.client_context)


async def test_an_oversized_context_is_refused(env):
    new_client, _, _ = env
    http = new_client()
    await guest(http)
    response = await http.post(
        "/api/bug-reports",
        json=a_report(clientContext={"filler": "x" * 40_000}),
    )
    assert response.status_code == 422


async def test_rate_limit_bounds_how_many_one_client_may_file(env):
    new_client, _, _ = env
    http = new_client()
    await guest(http)
    for _ in range(5):
        assert (
            await http.post("/api/bug-reports", json=a_report())
        ).status_code == 201
    refused = await http.post("/api/bug-reports", json=a_report())
    assert refused.status_code == 429


@pytest.mark.parametrize("image", [PNG, WEBP])
async def test_a_screenshot_is_measured_by_the_server_not_the_sender(env, image):
    new_client, factory, _ = env
    http = new_client()
    await guest(http)

    response = await http.post(
        "/api/bug-reports",
        json=a_report(
            screenshot=encoded(image),
            clientContext={
                "buildSha": "a299f80",
                # Claims, all of them wrong on purpose.
                "screenshotWidth": 1440,
                "screenshotHeight": 900,
            },
        ),
    )
    assert response.status_code == 201

    async with factory() as session:
        report = await session.get(BugReport, UUID(response.json()["id"]))
        assert report is not None
        assert report.screenshot_status == "ready"
        assert report.screenshot_payload == image
        assert report.screenshot_byte_size == len(image)
        assert report.screenshot_content_type == (
            "image/png" if image is PNG else "image/webp"
        )
        import hashlib

        assert report.screenshot_checksum_sha256 == hashlib.sha256(image).hexdigest()


@pytest.mark.parametrize(
    "payload",
    [
        b"GIF89a" + b"\x00" * 32,
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        # RIFF alone is a container - it has to actually say WEBP.
        b"RIFF" + struct.pack("<I", 32) + b"WAVE" + b"\x00" * 24,
    ],
)
async def test_only_a_real_png_or_webp_is_taken(env, payload):
    new_client, _, _ = env
    http = new_client()
    await guest(http)
    response = await http.post(
        "/api/bug-reports", json=a_report(screenshot=encoded(payload))
    )
    assert response.status_code == 422


async def test_an_oversized_screenshot_is_refused(env):
    new_client, _, _ = env
    http = new_client()
    await guest(http)
    huge = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2_200_000
    response = await http.post(
        "/api/bug-reports", json=a_report(screenshot=encoded(huge))
    )
    assert response.status_code == 422


async def test_the_queue_is_for_administrators_only(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    await guest(reporter_http)
    assert (
        await reporter_http.post("/api/bug-reports", json=a_report())
    ).status_code == 201

    # A moderator is staff, and still gets the same answer as anybody else:
    # this queue is not a moderation surface.
    moderator_http = new_client()
    moderator = await register(moderator_http, "Moderator")
    await set_role(factory, moderator["id"], UserRole.MODERATOR)
    assert (await moderator_http.get("/api/admin/bug-reports")).status_code == 404

    assert (await reporter_http.get("/api/admin/bug-reports")).status_code == 404

    admin_http = new_client()
    admin = await register(admin_http, "Administrator")
    await set_role(factory, admin["id"], UserRole.ADMIN)
    listing = await admin_http.get("/api/admin/bug-reports")
    assert listing.status_code == 200
    assert len(listing.json()["reports"]) == 1
    assert listing.json()["reports"][0]["reporter"]["registered"] is False


async def test_deciding_is_one_way_and_erases_the_screenshot(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    await guest(reporter_http)
    filed = await reporter_http.post(
        "/api/bug-reports", json=a_report(screenshot=encoded(PNG))
    )
    report_id = filed.json()["id"]

    admin_http = new_client()
    admin = await register(admin_http, "Administrator")
    await set_role(factory, admin["id"], UserRole.ADMIN)

    assert (
        await admin_http.get(f"/api/admin/bug-reports/{report_id}/screenshot")
    ).status_code == 200

    decided = await admin_http.patch(
        f"/api/admin/bug-reports/{report_id}",
        json={"status": "resolved", "note": "Fixed in a299f80."},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "resolved"
    assert decided.json()["screenshot"]["status"] == "erased"
    # The metadata stays, so the record still says a picture existed.
    assert decided.json()["screenshot"]["byteSize"] == len(PNG)

    assert (
        await admin_http.get(f"/api/admin/bug-reports/{report_id}/screenshot")
    ).status_code == 404

    again = await admin_http.patch(
        f"/api/admin/bug-reports/{report_id}",
        json={"status": "dismissed", "note": "Changed my mind."},
    )
    assert again.status_code == 409

    async with factory() as session:
        report = await session.get(BugReport, UUID(report_id))
        assert report is not None
        assert report.screenshot_payload is None
        assert report.reviewed_by_user_id == UUID(admin["id"])


async def test_a_decision_needs_a_note(env):
    new_client, factory, _ = env
    reporter_http = new_client()
    await guest(reporter_http)
    report_id = (
        await reporter_http.post("/api/bug-reports", json=a_report())
    ).json()["id"]

    admin_http = new_client()
    admin = await register(admin_http, "Administrator")
    await set_role(factory, admin["id"], UserRole.ADMIN)
    response = await admin_http.patch(
        f"/api/admin/bug-reports/{report_id}",
        json={"status": "resolved", "note": "   "},
    )
    assert response.status_code == 422


async def test_erasure_is_structural_not_procedural(env):
    """The constraint is the guarantee, so the constraint is what is tested.

    A future code path that flips the status without dropping the bytes must
    fail at the database, not merely be absent from today's router.
    """
    _, factory, _ = env
    report_id = generate_uuid()
    async with factory() as session:
        async with session.begin():
            session.add(
                BugReport(
                    id=report_id,
                    area="performance",
                    severity="minor",
                    summary="Confetti keeps animating",
                    details="It runs behind the results card.",
                    screenshot_status="ready",
                    screenshot_payload=PNG,
                    screenshot_content_type="image/png",
                    screenshot_byte_size=len(PNG),
                    screenshot_checksum_sha256="0" * 64,
                )
            )

    with pytest.raises(IntegrityError):
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(BugReport)
                    .where(BugReport.id == report_id)
                    .values(screenshot_status="erased")
                )

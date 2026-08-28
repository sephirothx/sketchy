"""Administrative commands: pausing the server, ending rooms, granting a role.

These are the first administrative *commands* in the codebase - until now the
only mutating endpoint behind the administrator gate was the bug-report review
- so what is pinned here is as much the shape as the behaviour: the 404 for
anyone else, a reason recorded where the action is about a person, an audit
event in the same transaction, and refusals that leave nothing half-done.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
import pytest_asyncio
import socketio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.admin_controls import create_admin_controls_router, read_paused
from app.auth.middleware import SessionAuthMiddleware
from app.auth.routes import create_auth_router
from app.db.models import AuditEvent, Base, User
from app.domain_values import AccountState, UserRole
from app.game import Game, Phase
from app.handlers import register_all_handlers
from app.repositories.sqlalchemy import SqlAlchemyUserRepository
from app.rooms import RoomManager
from app.services.shutdown import ShutdownCoordinator


pytestmark = pytest.mark.asyncio
PASSWORD = "a-good-password"


@pytest_asyncio.fixture
async def env(monkeypatch):
    monkeypatch.setenv("IP_HASH_SECRET", "controls-test-secret")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    rooms = RoomManager()
    sio = socketio.AsyncServer(async_mode="asgi")
    sio.emit = AsyncMock()
    sio.leave_room = AsyncMock()
    sio.disconnect = AsyncMock()
    coordinator = ShutdownCoordinator(factory, rooms)
    coordinator.begin_startup(drain_seconds=0)
    coordinator.mark_ready()
    context = register_all_handlers(sio, rooms, shutdown=coordinator)

    # Recorded rather than performed: a test that actually signalled the
    # process would stop the test runner.
    exit_requests: list[int] = []

    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(
        create_admin_controls_router(
            factory,
            coordinator,
            rooms,
            context,
            request_process_exit=lambda: exit_requests.append(1),
        )
    )

    clients: list[AsyncClient] = []

    def new_client() -> AsyncClient:
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield new_client, factory, rooms, coordinator, context, exit_requests
    finally:
        await context.timers.close()
        for client in clients:
            await client.aclose()
        await engine.dispose()


async def register(client: AsyncClient, username: str) -> dict:
    assert (await client.get("/api/auth/me")).status_code == 200
    response = await client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()


async def set_role(factory, user_id: str, role: str) -> None:
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(user_id))
            user.role = role


async def an_admin(env, name="Operator") -> AsyncClient:
    new_client, factory, *_ = env
    client = new_client()
    account = await register(client, name)
    await set_role(factory, account["id"], UserRole.ADMIN.value)
    return client


async def audit_rows(factory) -> list[AuditEvent]:
    async with factory() as session:
        return list(
            (await session.scalars(select(AuditEvent).order_by(AuditEvent.id))).all()
        )


# --------------------------------------------------------------------- gating


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/admin/maintenance"),
        ("get", "/api/admin/rooms"),
        ("delete", "/api/admin/rooms/whatever"),
        ("delete", "/api/admin/rooms/whatever/players/somebody"),
        ("post", "/api/admin/rooms/whatever/end-turn"),
        ("post", "/api/admin/shutdown"),
    ],
)
async def test_an_ordinary_player_is_told_none_of_this_exists(env, method, path):
    new_client, *_ = env
    player = new_client()
    await register(player, "Player")
    response = await getattr(player, method)(path)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/admin/maintenance"),
        ("post", "/api/admin/shutdown"),
        ("patch", "/api/admin/players/00000000-0000-0000-0000-000000000000/role"),
    ],
)
async def test_a_malformed_body_does_not_reveal_that_the_endpoint_exists(
    env, method, path
):
    """422 before 404 would answer the question the 404 exists to refuse.

    FastAPI validates a request body before the handler runs, so a gate awaited
    inside one is reached only by requests that already parsed - and an
    ordinary player sending nonsense would be told their nonsense was
    unprocessable, which is a confirmation that there was something there to
    process. The gate is a dependency for exactly this reason.
    """
    new_client, *_ = env
    player = new_client()
    await register(player, f"Prober{method}{len(path)}")
    response = await getattr(player, method)(path, json={"nonsense": True})
    assert response.status_code == 404


async def test_a_moderator_is_not_an_administrator(env):
    """R-ROLE-01: the role is re-checked here, and moderation is a different tier."""
    new_client, factory, *_ = env
    client = new_client()
    account = await register(client, "Mod")
    await set_role(factory, account["id"], UserRole.MODERATOR.value)
    assert (await client.get("/api/admin/rooms")).status_code == 404


# ---------------------------------------------------------------- maintenance


async def test_pausing_refuses_new_rooms_while_live_games_play_on(env):
    _, _, rooms, coordinator, context, _ = env
    admin = await an_admin(env)

    await admin.post("/api/admin/maintenance", json={"paused": True})
    assert coordinator.refuses_new_work
    # The distinction the whole design rests on: this is not a drain.
    assert not coordinator.is_draining
    assert coordinator.is_ready

    refusal = coordinator.rejection_acknowledgement()
    assert refusal["serverPaused"] is True
    assert "serverDraining" not in refusal


async def test_a_pause_does_not_make_the_process_look_unready(env):
    """`/api/ready` answering 503 invites an orchestrator to replace the container.

    Which is the opposite of what pausing it is for.
    """
    _, _, _, coordinator, _, _ = env
    admin = await an_admin(env)
    await admin.post("/api/admin/maintenance", json={"paused": True})
    assert coordinator.is_ready
    assert coordinator.state == "ready"


async def test_resuming_puts_the_server_back_to_work(env):
    _, factory, _, coordinator, _, _ = env
    admin = await an_admin(env)
    await admin.post("/api/admin/maintenance", json={"paused": True})
    await admin.post("/api/admin/maintenance", json={"paused": False})
    assert not coordinator.refuses_new_work
    assert not await read_paused(factory)


async def test_a_pause_survives_the_restart_it_was_taken_for(env):
    _, factory, _, _, _, _ = env
    admin = await an_admin(env)
    await admin.post("/api/admin/maintenance", json={"paused": True})
    assert await read_paused(factory) is True


async def test_a_shutdown_still_drains_from_a_paused_process(env):
    """A deploy issued during a pause must not be refused by the pause."""
    _, _, rooms, coordinator, _, _ = env
    admin = await an_admin(env)
    await admin.post("/api/admin/maintenance", json={"paused": True})
    result = await coordinator.begin_shutdown(AsyncMock())
    assert coordinator.state == "stopped"
    assert result.abandoned_game_count == 0


async def test_pausing_records_who_paused_it_and_why(env):
    _, factory, _, _, _, _ = env
    admin = await an_admin(env)
    await admin.post(
        "/api/admin/maintenance", json={"paused": True, "reason": "database migration"}
    )
    (event,) = await audit_rows(factory)
    assert event.event_type == "maintenance.paused"
    assert event.details == {"reason": "database migration"}


async def test_pausing_an_already_paused_server_records_nothing(env):
    _, factory, _, _, _, _ = env
    admin = await an_admin(env)
    await admin.post("/api/admin/maintenance", json={"paused": True})
    await admin.post("/api/admin/maintenance", json={"paused": True})
    assert len(await audit_rows(factory)) == 1


# ----------------------------------------------------------------- room control


async def test_the_room_listing_says_what_each_room_is_doing_and_no_more(env):
    _, _, rooms, _, _, _ = env
    admin = await an_admin(env)
    room = rooms.create_room(name="Coffee break doodles")
    rooms.add_player(room, "Marta")

    (listed,) = (await admin.get("/api/admin/rooms")).json()["rooms"]
    assert listed["name"] == "Coffee break doodles"
    assert listed["players"] == 1
    assert listed["state"] == "waiting"
    # An operator finds a stuck or abused room here; reading what is being
    # said in one is what the moderation surfaces are for, with the evidence
    # trail that goes with them.
    assert not {"prompt", "chat", "canvas", "messages"} & set(listed)


async def test_the_listing_names_the_seats_so_one_can_be_removed(env):
    """A kick needs to say which player, so the listing has to name them.

    The panel had the endpoint and the client helper and no way to reach
    either, because the rows carried counts and nothing to act on.
    """
    _, _, rooms, _, _, _ = env
    admin = await an_admin(env)
    room = rooms.create_room(name="Studio")
    marta = rooms.add_player(room, "Marta")
    marta.sid = "marta-sid"

    (listed,) = (await admin.get("/api/admin/rooms")).json()["rooms"]
    assert listed["seats"] == [
        {
            "id": marta.id,
            "nickname": "Marta",
            "isSpectator": False,
            "connected": True,
        }
    ]
    # Enough to name a seat, and no more.
    assert set(listed["seats"][0]) == {"id", "nickname", "isSpectator", "connected"}


async def test_closing_a_room_tells_everyone_before_it_goes(env):
    _, _, rooms, _, context, _ = env
    admin = await an_admin(env)
    room = rooms.create_room(name="Doomed")
    player = rooms.add_player(room, "Marta")
    player.sid = "marta-sid"

    response = await admin.delete(f"/api/admin/rooms/{room.id}")
    assert response.status_code == 200
    assert room.id not in rooms.rooms
    told = [call.args for call in context.sio.emit.await_args_list]
    assert any(call[0] == "kicked" for call in told)


async def test_closing_a_room_that_is_not_there_is_a_404(env):
    admin = await an_admin(env)
    assert (await admin.delete("/api/admin/rooms/nope")).status_code == 404


async def test_kicking_removes_one_seat_and_leaves_the_room(env):
    _, _, rooms, _, _, _ = env
    admin = await an_admin(env)
    room = rooms.create_room(name="Studio")
    host = rooms.add_player(room, "Host")
    host.sid = "host-sid"
    guest = rooms.add_player(room, "Guest")
    guest.sid = "guest-sid"

    response = await admin.delete(f"/api/admin/rooms/{room.id}/players/{guest.id}")
    assert response.status_code == 200
    assert guest.id not in room.players
    assert host.id in room.players
    assert room.id in rooms.rooms


async def test_kicking_somebody_who_is_not_seated_is_a_404(env):
    _, _, rooms, _, _, _ = env
    admin = await an_admin(env)
    room = rooms.create_room(name="Studio")
    assert (
        await admin.delete(f"/api/admin/rooms/{room.id}/players/ghost")
    ).status_code == 404


async def test_ending_a_turn_leaves_the_game_running(env):
    """The ordinary ending, not a special one: the turn scores and play goes on."""
    _, _, rooms, _, _, _ = env
    admin = await an_admin(env)
    room = rooms.create_room(name="Studio")
    host = rooms.add_player(room, "Host")
    guest = rooms.add_player(room, "Guest")
    room.state = "playing"
    room.game = Game(turn_order=[host.id, guest.id], rounds_total=1)
    room.game.phase = Phase.DRAWING
    room.game.prompt = "lighthouse"
    room.game.current_drawer = host.id

    assert (await admin.post(f"/api/admin/rooms/{room.id}/end-turn")).status_code == 200
    assert room.game.phase != Phase.DRAWING
    assert room.id in rooms.rooms


async def test_ending_a_turn_is_recorded_before_the_turn_is_ended(env):
    """The room commands audit first, and ending a turn is no less final.

    It scores the turn and writes history, and none of that can share a
    transaction with the audit row - the state it changes lives in this
    process. So the entry goes down first: a ledger that can name an action
    which then failed is a smaller harm than one that can miss an
    irreversible action that happened.
    """
    _, factory, rooms, _, context, _ = env
    admin = await an_admin(env)
    room = rooms.create_room(name="Studio")
    host = rooms.add_player(room, "Host")
    guest = rooms.add_player(room, "Guest")
    room.state = "playing"
    room.game = Game(turn_order=[host.id, guest.id], rounds_total=1)
    room.game.phase = Phase.DRAWING
    room.game.prompt = "lighthouse"
    room.game.current_drawer = host.id

    async def fail_after_audit(_room):
        assert await audit_rows(factory), "the turn ended before it was recorded"
        raise RuntimeError("the turn could not be ended")

    with patch.object(context.game_flow, "end_turn_now", fail_after_audit):
        with pytest.raises(RuntimeError):
            await admin.post(f"/api/admin/rooms/{room.id}/end-turn")

    (event,) = await audit_rows(factory)
    assert event.event_type == "room.turn_ended_by_admin"


async def test_ending_a_turn_in_a_room_that_is_not_drawing_is_refused(env):
    _, _, rooms, _, _, _ = env
    admin = await an_admin(env)
    room = rooms.create_room(name="Waiting")
    response = await admin.post(f"/api/admin/rooms/{room.id}/end-turn")
    assert response.status_code == 409


async def test_every_room_command_names_the_room_in_the_ledger(env):
    _, factory, rooms, _, _, _ = env
    admin = await an_admin(env)
    room = rooms.create_room(name="Studio")
    rooms.add_player(room, "Marta")
    await admin.delete(f"/api/admin/rooms/{room.id}")

    (event,) = await audit_rows(factory)
    assert event.event_type == "room.closed_by_admin"
    assert event.target_type == "room"
    assert event.target_id == room.id
    assert event.request_id and event.ip_hash


# ----------------------------------------------------------------------- roles


async def test_an_administrator_may_make_somebody_a_moderator(env):
    new_client, factory, *_ = env
    admin = await an_admin(env)
    subject = await register(new_client(), "Helper")

    response = await admin.patch(
        f"/api/admin/players/{subject['id']}/role",
        json={"role": "moderator", "reason": "joining the safety rota"},
    )
    assert response.status_code == 200
    async with factory() as session:
        assert (await session.get(User, UUID(subject["id"]))).role == "moderator"


async def test_a_moderator_can_be_put_back_to_an_ordinary_player(env):
    new_client, factory, *_ = env
    admin = await an_admin(env)
    subject = await register(new_client(), "Former")
    await set_role(factory, subject["id"], UserRole.MODERATOR.value)

    await admin.patch(
        f"/api/admin/players/{subject['id']}/role",
        json={"role": "user", "reason": "stepped down"},
    )
    async with factory() as session:
        assert (await session.get(User, UUID(subject["id"]))).role == "user"


async def test_an_administrator_cannot_be_minted_over_the_network(env):
    """The guarded server-side command stays the only way in.

    One compromised administrator session should not be able to make more of
    them - the same reasoning R-AUTH-14 applies to a remote password reset.
    """
    new_client, factory, *_ = env
    admin = await an_admin(env)
    subject = await register(new_client(), "Ambitious")

    response = await admin.patch(
        f"/api/admin/players/{subject['id']}/role",
        json={"role": "admin", "reason": "why not"},
    )
    assert response.status_code == 400
    async with factory() as session:
        assert (await session.get(User, UUID(subject["id"]))).role == "user"


async def test_an_administrator_cannot_change_their_own_role(env):
    """The last one demoting themselves leaves nobody who can undo it."""
    admin = await an_admin(env)
    me = (await admin.get("/api/auth/me")).json()
    response = await admin.patch(
        f"/api/admin/players/{me['id']}/role",
        json={"role": "user", "reason": "stepping back"},
    )
    assert response.status_code == 400


async def test_another_administrator_cannot_be_demoted_here_either(env):
    new_client, factory, *_ = env
    admin = await an_admin(env)
    peer = await register(new_client(), "Peer")
    await set_role(factory, peer["id"], UserRole.ADMIN.value)

    response = await admin.patch(
        f"/api/admin/players/{peer['id']}/role",
        json={"role": "user", "reason": "not from here"},
    )
    assert response.status_code == 400


async def test_a_role_change_requires_a_reason(env):
    new_client, *_ = env
    admin = await an_admin(env)
    subject = await register(new_client(), "Nameless")
    for body in ({"role": "moderator"}, {"role": "moderator", "reason": "  "}):
        response = await admin.patch(
            f"/api/admin/players/{subject['id']}/role", json=body
        )
        assert response.status_code == 422, body


async def test_a_guest_cannot_hold_a_role(env):
    """A role belongs to an account somebody can be held to."""
    new_client, factory, *_ = env
    admin = await an_admin(env)
    subject = await register(new_client(), "Fleeting")
    async with factory() as session:
        async with session.begin():
            user = await session.get(User, UUID(subject["id"]))
            user.state = AccountState.ANONYMOUS.value

    response = await admin.patch(
        f"/api/admin/players/{subject['id']}/role",
        json={"role": "moderator", "reason": "should not stick"},
    )
    assert response.status_code == 400


async def test_a_role_change_records_the_move_and_the_reason(env):
    new_client, factory, *_ = env
    admin = await an_admin(env)
    subject = await register(new_client(), "Recorded")
    await admin.patch(
        f"/api/admin/players/{subject['id']}/role",
        json={"role": "moderator", "reason": "joining the safety rota"},
    )
    (event,) = await audit_rows(factory)
    assert event.event_type == "admin.role_changed"
    assert event.target_type == "user"
    assert event.details == {
        "from": "user",
        "to": "moderator",
        "reason": "joining the safety rota",
    }


# -------------------------------------------------------------------- shutdown


async def test_a_shutdown_asks_the_process_to_stop_rather_than_draining_here(env):
    """The drain must run where it runs for a real deploy, not in a request.

    `begin_shutdown` is one-way and ends with the coordinator `stopped`.
    Calling it from a handler would leave that state inside a process that is
    still listening, and the genuine shutdown afterwards would find the drain
    already spent and skip it - so the games it was supposed to protect would
    be cut off instead.
    """
    _, _, _, coordinator, _, exit_requests = env
    admin = await an_admin(env)

    response = await admin.post(
        "/api/admin/shutdown", json={"reason": "deploying 1.4.0"}
    )
    assert response.status_code == 200
    assert exit_requests == [1]
    # Untouched: the runner drains on the way out.
    assert coordinator.state == "ready"
    assert not coordinator.is_draining


async def test_the_drain_window_can_be_set_for_this_shutdown(env):
    """One shutdown's window, not a change to the configured one.

    The configured value is a tunable the panel can still change, so writing
    a one-shot window onto it would leave the shutdown's own window in reach
    of anyone editing the setting while it is pending.
    """
    _, _, _, coordinator, _, _ = env
    admin = await an_admin(env)
    coordinator.set_drain_seconds(30)

    response = await admin.post(
        "/api/admin/shutdown", json={"reason": "quick restart", "drainSeconds": 5}
    )
    assert response.json()["drainSeconds"] == 5
    assert coordinator.drain_seconds == 30, "the configured default is untouched"

    sio = AsyncMock()
    await coordinator.begin_shutdown(sio)
    (notice,) = [
        call.args[1] for call in sio.emit.await_args_list
        if call.args[0] == "server_shutdown"
    ]
    assert notice["drainSeconds"] == 5, "the drain ran on the window it was given"


async def test_tuning_the_default_cannot_move_a_shutdown_already_asked_for(env):
    """The window is fixed when the shutdown is claimed, and again when it starts.

    The notice is emitted and the deadline computed either side of an await, so
    a change landing between them could promise a minute and abandon the games
    a second later.
    """
    _, _, _, coordinator, _, _ = env
    admin = await an_admin(env)
    coordinator.set_drain_seconds(30)
    await admin.post(
        "/api/admin/shutdown", json={"reason": "deploying", "drainSeconds": 60}
    )

    # As a tuning change would, while the shutdown is pending.
    coordinator.set_drain_seconds(0)

    sio = AsyncMock()
    await coordinator.begin_shutdown(sio)
    (notice,) = [
        call.args[1] for call in sio.emit.await_args_list
        if call.args[0] == "server_shutdown"
    ]
    assert notice["drainSeconds"] == 60


async def test_omitting_the_window_freezes_the_configured_one(env):
    """"Use the configured window" has to mean the one that was configured *then*.

    The configured value is a tunable the panel can change, so resolving it
    and leaving the claim empty would let a change between the accepted
    request and the drain starting make the server wait a different length
    from the one the response and the audit both recorded.
    """
    _, factory, _, coordinator, _, _ = env
    admin = await an_admin(env)
    coordinator.set_drain_seconds(42)

    response = await admin.post("/api/admin/shutdown", json={"reason": "as configured"})
    assert response.json()["drainSeconds"] == 42

    # As a tuning change would, after the request was accepted.
    coordinator.set_drain_seconds(0)

    sio = AsyncMock()
    await coordinator.begin_shutdown(sio)
    (notice,) = [
        call.args[1] for call in sio.emit.await_args_list
        if call.args[0] == "server_shutdown"
    ]
    assert notice["drainSeconds"] == 42, "the drain ran on the window it promised"

    (event,) = await audit_rows(factory)
    assert event.details["drainSeconds"] == 42


async def test_the_notice_promises_exactly_what_will_be_waited(env):
    """Rounding up let a countdown still be running when the socket closed."""
    _, _, _, coordinator, _, _ = env
    admin = await an_admin(env)
    await admin.post(
        "/api/admin/shutdown", json={"reason": "precise", "drainSeconds": 1.25}
    )
    sio = AsyncMock()
    await coordinator.begin_shutdown(sio)
    (notice,) = [
        call.args[1] for call in sio.emit.await_args_list
        if call.args[0] == "server_shutdown"
    ]
    assert notice["drainSeconds"] == 1.25


@pytest.mark.parametrize("seconds", [-1, 301, 1000])
async def test_a_window_outside_the_documented_range_is_refused(env, seconds):
    """R-SHUT-03 fixes the range at 0-300 however the value arrives."""
    _, _, _, coordinator, _, exit_requests = env
    admin = await an_admin(env)
    coordinator.set_drain_seconds(30)

    response = await admin.post(
        "/api/admin/shutdown", json={"reason": "too long", "drainSeconds": seconds}
    )
    assert response.status_code == 400
    assert coordinator.drain_seconds == 30
    assert exit_requests == []


async def test_a_shutdown_requires_a_reason(env):
    _, _, _, _, _, exit_requests = env
    admin = await an_admin(env)
    for body in ({}, {"reason": "  "}, {"reason": "no"}):
        response = await admin.post("/api/admin/shutdown", json=body)
        assert response.status_code == 422, body
    assert exit_requests == []


async def test_a_second_shutdown_before_the_drain_starts_is_refused(env):
    """`is_draining` is false for the whole gap between asking and draining.

    Without a claim taken across that gap, two clicks a moment apart are two
    accepted requests: two audit events for one shutdown, and a second chance
    to move the drain window after the first was written down.
    """
    _, factory, _, _, _, exit_requests = env
    admin = await an_admin(env)

    first = await admin.post("/api/admin/shutdown", json={"reason": "deploying"})
    second = await admin.post(
        "/api/admin/shutdown", json={"reason": "deploying", "drainSeconds": 0}
    )
    assert first.status_code == 200
    assert second.status_code == 409
    assert exit_requests == [1]
    assert len(await audit_rows(factory)) == 1


async def test_concurrent_shutdowns_stop_the_process_once(env):
    _, factory, _, _, _, exit_requests = env
    admin = await an_admin(env)
    results = await asyncio.gather(
        *(
            admin.post("/api/admin/shutdown", json={"reason": "deploying"})
            for _ in range(4)
        )
    )
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409]
    assert exit_requests == [1]
    assert len(await audit_rows(factory)) == 1


async def test_a_failed_shutdown_leaves_the_drain_window_alone(env):
    """A one-shot window belongs to a shutdown that actually happens.

    Applying it before the audit meant a request that errored still changed
    what the *next* deploy would wait - a window set for a shutdown nobody
    ever started.
    """
    _, _, _, coordinator, _, exit_requests = env
    admin = await an_admin(env)
    coordinator.set_drain_seconds(30)

    with patch(
        "app.api.admin_controls.audit_coordinates",
        AsyncMock(side_effect=RuntimeError("the ledger is unavailable")),
    ):
        with pytest.raises(RuntimeError):
            await admin.post(
                "/api/admin/shutdown", json={"reason": "doomed", "drainSeconds": 1}
            )

    assert coordinator.drain_seconds == 30
    assert exit_requests == []
    # And the claim is given back, so a later attempt is not locked out by one
    # that never went through.
    assert not coordinator.shutdown_requested
    assert (
        await admin.post("/api/admin/shutdown", json={"reason": "retry"})
    ).status_code == 200


async def test_a_second_shutdown_during_a_drain_is_refused(env):
    _, _, _, coordinator, _, exit_requests = env
    admin = await an_admin(env)
    coordinator._state = "draining"

    response = await admin.post("/api/admin/shutdown", json={"reason": "again"})
    assert response.status_code == 409
    assert exit_requests == []


async def test_a_shutdown_is_recorded_before_anything_is_asked_to_stop(env):
    """A shutdown that works takes the chance to write it down with it."""
    _, factory, _, _, _, _ = env
    admin = await an_admin(env)
    await admin.post(
        "/api/admin/shutdown", json={"reason": "deploying 1.4.0", "drainSeconds": 12}
    )
    (event,) = await audit_rows(factory)
    assert event.event_type == "server.shutdown_requested"
    assert event.details == {"reason": "deploying 1.4.0", "drainSeconds": 12}
    assert event.request_id and event.ip_hash


async def test_a_deployment_that_cannot_stop_itself_says_so(env):
    """Served some other way, there is no signal for this router to send."""
    new_client, factory, rooms, coordinator, context, _ = env
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware, session_factory=factory)
    app.include_router(create_auth_router(SqlAlchemyUserRepository(factory), factory))
    app.include_router(
        create_admin_controls_router(factory, coordinator, rooms, context)
    )
    admin = await an_admin(env)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        client.cookies.update(admin.cookies)
        response = await client.post("/api/admin/shutdown", json={"reason": "no signal"})
    assert response.status_code == 503

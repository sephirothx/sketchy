"""Administrative commands: things done to a running server, not values set on it.

Kept apart from the tunables for a reason a panel should reflect too. A
tunable has a default, a range and a way back; pausing the process, closing
somebody's room or granting a role have none of those, and an irreversible
button among a row of sliders is a button pressed by accident.

Everything here is the first of its kind in this codebase - until now the only
mutating administrator endpoint anywhere was the bug-report review - so the
shape is deliberately uniform: the administrator gate, a required reason where
the action is about a person, an audit event in the same transaction, and a
plain JSON answer describing the new state.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.admin_auth import admin_gate
from app.auth.audit import audit_coordinates
from app.db.models import AuditEvent, RoleChangeNotice, generate_uuid
from app.domain_values import AuditTargetType
from app.db.models import User
from app.deployment import MAX_SHUTDOWN_DRAIN_SECONDS
from app.domain_values import AccountState, GRANTABLE_ROLES, UserRole
from app.game import Phase
from app.rooms import RoomManager
from app.services import config_store
from app.services.shutdown import ShutdownCoordinator

# The stored flag, so a pause survives the restart it was probably taken for.
MAINTENANCE_PAUSED_KEY = "maintenance.paused"

PAUSED_EVENT = "maintenance.paused"
RESUMED_EVENT = "maintenance.resumed"
ROOM_CLOSED_EVENT = "room.closed_by_admin"
PLAYER_KICKED_EVENT = "room.player_kicked"
TURN_ENDED_EVENT = "room.turn_ended_by_admin"
ROLE_CHANGED_EVENT = "admin.role_changed"
SHUTDOWN_REQUESTED_EVENT = "server.shutdown_requested"

# What an administrator may set a role to, from `domain_values` because the
# `role_change_notices` check constraint is the same statement: a notice can
# only ever be about a role this endpoint can set. Promotion to `admin` is
# deliberately absent: `auth/admin.py` bootstraps the first one from a guarded
# command that refuses to run once an administrator exists, and its own error
# message points at "an authorized moderation flow" - this is that flow, for the
# tier it can safely serve. Minting an administrator over the network would mean
# one compromised session could mint more, which is the reasoning R-AUTH-14
# applies to remote password reset.

# A list to scan rather than a page to read. The search exists to turn a name
# into the one account being promoted; an operator who cannot see their target
# in ten rows should type more of the name, not page through the players.
PLAYER_SEARCH_LIMIT = 10

# The widest term that can mean anything: `display_name` is 32 characters, and
# an account id is 36. Enforced by truncation rather than by a `Query`
# constraint, because FastAPI validates parameters *before* the handler runs -
# so a bound declared there would answer 422 to an ordinary player sending a
# long one, which is the confirmation the 404 in `admin_auth` exists to refuse.
MAX_SEARCH_TERM = 36


class ShutdownRequest(BaseModel):
    """Stop this process, giving live games a bounded window to finish."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Optional: absent means whatever the drain window is currently set to.
    # A value here is a one-shot override for this shutdown rather than a
    # change to the setting, because "let this one drain for ten seconds" is
    # not the same statement as "every deploy from now on gets ten seconds".
    drain_seconds: float | None = Field(default=None, alias="drainSeconds")
    reason: str = Field(min_length=3, max_length=200)


class RoleRequest(BaseModel):
    # Stripped before it is measured, so a reason of three spaces is no reason.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: str
    # Required, and required to say something. R-ACCT-07 makes the guarded
    # bootstrap record a reason; a promotion made from a web page should not
    # be held to less.
    reason: str = Field(min_length=3, max_length=200)


class MaintenanceRequest(BaseModel):
    # Stripped like the two above it. The reason is optional here, so without
    # this a handful of spaces counts as "given" and is written to the ledger
    # as a reason that says nothing - worse than the absence it is recorded
    # instead of, because it reads as though somebody explained themselves.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    paused: bool
    reason: str = Field(default="", max_length=200)


async def read_paused(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    """Whether this deployment was left paused."""
    return await config_store.read_one(session_factory, MAINTENANCE_PAUSED_KEY) == "1"


def create_admin_controls_router(
    session_factory: async_sessionmaker[AsyncSession],
    shutdown: ShutdownCoordinator,
    room_manager: RoomManager,
    context,
    *,
    on_change=None,
    on_role_changed=None,
    request_process_exit=None,
) -> APIRouter:
    """`context` is the live `HandlerContext`; rooms are process-owned.

    One worker owns every room, timer and socket session, so a request can
    reach them directly rather than through a message bus. That is a property
    of this deployment (N-01) rather than a shortcut, and it is what lets an
    administrator close a room from a web page at all.
    """
    router = APIRouter()
    # Taken as a dependency rather than awaited in the body, and that is not a
    # style choice: FastAPI validates the request body *before* the handler
    # runs, so a gate called inside one answers 422 to an ordinary player who
    # sends a malformed body - telling them the endpoint exists, which is the
    # single thing the 404 in `admin_auth` is there to avoid. A dependency is
    # resolved first, so they get the same 404 either way.
    require_admin = admin_gate(session_factory)

    async def _audit(request, admin, *, event, target_type, target_id, details):
        request_id, ip_hash = await audit_coordinates(request, session_factory)
        async with session_factory() as session:
            async with session.begin():
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type=event,
                        actor_user_id=admin.id,
                        target_type=target_type,
                        target_id=target_id,
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details=details,
                        created_at=datetime.now(timezone.utc),
                    )
                )

    def _room_or_404(room_id: str):
        room = room_manager.rooms.get(room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="No such room.")
        return room

    @router.get("/api/admin/maintenance")
    async def read_maintenance(request: Request):
        await require_admin(request)
        return _state(shutdown)

    @router.post("/api/admin/maintenance")
    async def set_maintenance(
        request: Request,
        body: MaintenanceRequest,
        admin: User = Depends(require_admin),
    ):
        """Stop or resume admitting new rooms, games and restart votes.

        Games already running are left alone, which is the whole difference
        between this and a shutdown: the point of pausing before a deploy is
        to stop the population growing while the rooms in flight finish by
        themselves.
        """
        if shutdown.is_draining:
            raise HTTPException(
                status_code=409,
                detail="A shutdown drain is already running.",
            )
        if shutdown.shutdown_requested:
            # `is_draining` is false until the signal lands, so without this
            # the moments after a shutdown is asked for are the one window
            # where this endpoint answers a question it refuses either side
            # of. Nothing good comes of the answer: the change cannot be
            # observed on a process that is stopping, its audit event
            # describes an effect this server never had, and the broadcast
            # goes to clients about to be disconnected - while the stored row
            # quietly decides what the *next* process starts as. Pausing
            # before a deploy is the supported order, and it still works.
            raise HTTPException(
                status_code=409,
                detail="A shutdown has been requested; this server is stopping.",
            )
        if body.paused == shutdown.is_paused:
            return _state(shutdown)

        request_id, ip_hash = await audit_coordinates(request, session_factory)
        async with session_factory() as session:
            async with session.begin():
                if body.paused:
                    await config_store.put(session, MAINTENANCE_PAUSED_KEY, "1")
                else:
                    await config_store.drop(session, MAINTENANCE_PAUSED_KEY)
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type=(
                            PAUSED_EVENT if body.paused else RESUMED_EVENT
                        ),
                        actor_user_id=admin.id,
                        target_type=AuditTargetType.APP_CONFIG.value,
                        target_id=MAINTENANCE_PAUSED_KEY,
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details=({"reason": body.reason} if body.reason else {}),
                        created_at=datetime.now(timezone.utc),
                    )
                )

        shutdown.pause(body.paused)
        if on_change is not None:
            await on_change(shutdown.pause_payload())
        return _state(shutdown)

    # ------------------------------------------------------------------ rooms

    @router.get("/api/admin/rooms")
    async def list_live_rooms(request: Request):
        """Every room this process is holding, and what it is doing.

        Seats are listed by id and nickname, which is the least that makes the
        kick control usable - there is no way to remove one player from a room
        without naming which. Nothing else about them: no prompts, no chat, no
        canvas. An operator needs to find a room that is stuck or being abused,
        not to read what is being said in it, and the moderation surfaces are
        where a report leads to content with the evidence trail that goes with
        it.
        """
        await require_admin(request)
        return {
            "rooms": [
                {
                    "id": room.id,
                    "code": room.code,
                    "name": room.name,
                    "isPublic": room.is_public,
                    "state": room.state,
                    "phase": room.game.phase.value if room.game else None,
                    "roundNumber": room.game.round_number if room.game else None,
                    "players": len(
                        [p for p in room.player_list() if not p.is_spectator]
                    ),
                    "spectators": len(
                        [p for p in room.player_list() if p.is_spectator]
                    ),
                    "connected": len(room.connected_players()),
                    "seats": [
                        {
                            "id": player.id,
                            "nickname": player.nickname,
                            "isSpectator": player.is_spectator,
                            "connected": player.sid is not None,
                        }
                        for player in room.player_list()
                    ],
                }
                for room in room_manager.rooms.values()
            ]
        }

    @router.delete("/api/admin/rooms/{room_id}")
    async def close_room(room_id: str, request: Request):
        """End a room now, telling everyone in it before their sockets close."""
        admin = await require_admin(request)
        room = _room_or_404(room_id)
        await _audit(
            request, admin,
            event=ROOM_CLOSED_EVENT,
            target_type=AuditTargetType.ROOM.value,
            target_id=room.id,
            details={"players": len(room.player_list())},
        )
        for player in list(room.player_list()):
            await context.evict_player(
                room,
                player.id,
                notice=(
                    "kicked",
                    {"reason": "An administrator closed this room."},
                ),
            )
        # Evicting the last player usually takes the room with them; this
        # covers a room that held nobody to begin with.
        await context.remove_room_if_empty(room.id)
        return {"closed": room.id}

    @router.delete("/api/admin/rooms/{room_id}/players/{player_id}")
    async def kick_player(room_id: str, player_id: str, request: Request):
        """Remove one seat, by the same sequence a room's own vote uses."""
        admin = await require_admin(request)
        room = _room_or_404(room_id)
        if player_id not in room.players:
            raise HTTPException(status_code=404, detail="No such player.")
        await _audit(
            request, admin,
            event=PLAYER_KICKED_EVENT,
            target_type=AuditTargetType.ROOM.value,
            target_id=room.id,
            details={"playerId": player_id},
        )
        await context.evict_player(
            room,
            player_id,
            notice=("kicked", {"reason": "An administrator removed you."}),
        )
        return {"kicked": player_id}

    @router.post("/api/admin/rooms/{room_id}/end-turn")
    async def end_turn(room_id: str, request: Request):
        """Finish the drawing phase now, as its own timer would have.

        Deliberately the ordinary ending rather than a special one: the turn
        scores, the results screen shows, and the game carries on. A room
        stuck behind a drawer who has stopped drawing wants the turn over, not
        the game.
        """
        admin = await require_admin(request)
        room = _room_or_404(room_id)
        if room.game is None or room.game.phase != Phase.DRAWING:
            raise HTTPException(
                status_code=409, detail="That room is not in a drawing turn."
            )
        # Recorded before the turn is ended, as the room commands above do.
        # Ending a turn scores it and writes history, and none of that can
        # share a transaction with the audit row - the state it changes lives
        # in this process, not the database. So the choice is between a ledger
        # that can name an action which then failed and a ledger that can miss
        # one that happened, and for an irreversible action the first is the
        # smaller harm.
        await _audit(
            request, admin,
            event=TURN_ENDED_EVENT,
            target_type=AuditTargetType.ROOM.value,
            target_id=room.id,
            details={},
        )
        if not await context.game_flow.end_turn_now(room):
            # The phase moved between the check and here - a guess landing, or
            # the timer. The entry stands: an administrator did ask.
            raise HTTPException(
                status_code=409, detail="That turn ended before the command ran."
            )
        return {"endedTurnIn": room.id}

    # --------------------------------------------------------------- shutdown

    @router.post("/api/admin/shutdown")
    async def initiate_shutdown(
        request: Request,
        body: ShutdownRequest,
        admin: User = Depends(require_admin),
    ):
        """Stop this process, draining live games first.

        This asks the process to terminate rather than draining here, and the
        difference matters. `begin_shutdown` is one-way and ends with the
        coordinator `stopped`; calling it from a request would leave that state
        inside a process that is still running and still listening, and the
        real shutdown later would find the drain already spent and skip it. So
        the signal goes to the process, and the drain happens where it always
        has - in the runner, on the way out.

        Whether anything comes back afterwards is not this server's business.
        Under a supervisor this is a restart; without one it is a stop, and the
        panel says so before the button is pressed.
        """
        if shutdown.is_draining:
            raise HTTPException(
                status_code=409, detail="A shutdown drain is already running."
            )
        if request_process_exit is None:
            raise HTTPException(
                status_code=503,
                detail="This process cannot stop itself; stop it from the host.",
            )

        drain = shutdown.drain_seconds
        if body.drain_seconds is not None:
            drain = body.drain_seconds
            if not 0 <= drain <= MAX_SHUTDOWN_DRAIN_SECONDS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "The drain window must be between 0 and "
                        f"{int(MAX_SHUTDOWN_DRAIN_SECONDS)} seconds."
                    ),
                )

        # Claimed before the first await, carrying this shutdown's window with
        # it. `is_draining` stays false from here until the signal lands and
        # the runner actually begins, so without the claim a second click
        # inside that gap is a second accepted request - two audit events for
        # one shutdown, and a second chance to move the window after the first
        # was written down. Carrying the window rather than writing it onto the
        # configured value keeps it out of reach of the tuning panel, which can
        # still change that value while this shutdown is pending.
        # `drain`, not `body.drain_seconds`: omitting a window means "use the
        # configured one", and that value is a tunable the panel can change
        # while this shutdown is pending. Resolving it here and freezing it on
        # the claim is what makes the number in the response and the audit the
        # number the drain actually runs on.
        if not shutdown.claim_shutdown(drain):
            raise HTTPException(
                status_code=409, detail="A shutdown has already been requested."
            )

        try:
            # Recorded before anything is asked to stop, because a shutdown
            # that succeeds takes the chance to write it down with it.
            await _audit(
                request, admin,
                event=SHUTDOWN_REQUESTED_EVENT,
                target_type=AuditTargetType.APP_CONFIG.value,
                target_id="server.shutdown",
                details={"reason": body.reason, "drainSeconds": drain},
            )
        except Exception:
            # The process is going to outlive this request after all, so it
            # must be left exactly as it was found - including the claim.
            shutdown.release_shutdown_claim()
            raise

        request_process_exit()
        return {"draining": True, "drainSeconds": drain}

    # ------------------------------------------------------------------ roles

    @router.get("/api/admin/players")
    async def search_players(
        request: Request,
        q: str = Query(default=""),
    ):
        """Find the account a role is about, by name rather than by pasted id.

        A read among the commands, for the reason `list_live_rooms` gives just
        above: it is the least that makes the control below usable. Granting a
        role used to mean pasting a UUID somebody had to already have, which is
        a lookup done by hand, badly, in another window.

        Registered accounts only - a guest cannot hold a role, so an
        unpromotable row is a refusal in waiting - most recently active first,
        and capped. An empty `q` answers with whoever holds a role now, which
        is the question the card opens on.

        **This writes nothing to the ledger, and that is deliberate.**
        R-AUDIT-05 records every use of the per-player activity view because
        that view answers *how has this account behaved*. This one answers
        *which account is called this*, and returns nothing a room does not
        already show every player seated in it - a display name and the colour
        its owner chose - plus the role that is about to change. An event per
        keystroke would also bury `admin.role_changed` under hundreds of rows
        in an append-only ledger that exists to make it findable.

        For the same reason nothing else is returned. No username, no dates,
        no game counts: two players who chose the same name are both listed and
        told apart by the id fragment beside them, and an operator who genuinely
        cannot tell which is which has the activity view - where that cost is
        recorded, which is where it belongs.
        """
        await require_admin(request)
        term = q.strip()[:MAX_SEARCH_TERM]
        statement = select(User).where(User.state == AccountState.REGISTERED.value)
        if term == "":
            statement = statement.where(User.role != UserRole.USER.value)
        else:
            matches = [User.display_name.ilike(_escaped_like(term), escape="\\")]
            # An operator arriving from the audit ledger or a report has an id
            # and not a name; the workflow this replaces still has to work.
            found = _maybe_uuid(term)
            if found is not None:
                matches.append(User.id == found)
            statement = statement.where(or_(*matches))
        async with session_factory() as session:
            rows = (
                await session.scalars(
                    statement.order_by(User.last_active_at.desc()).limit(
                        PLAYER_SEARCH_LIMIT
                    )
                )
            ).all()
        return {
            "players": [
                {
                    "id": str(row.id),
                    "displayName": row.display_name,
                    "nameColor": row.name_color,
                    "role": row.role,
                }
                for row in rows
            ]
        }

    @router.patch("/api/admin/players/{user_id}/role")
    async def set_role(
        user_id: str,
        request: Request,
        body: RoleRequest,
        admin: User = Depends(require_admin),
    ):
        """Grant or revoke the moderator role, with a reason on the record."""
        if body.role not in GRANTABLE_ROLES:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Role must be one of: "
                    f"{', '.join(GRANTABLE_ROLES)}. Administrators are created "
                    "by the guarded server-side command."
                ),
            )
        try:
            target_id = UUID(user_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="No such player.") from error
        if target_id == admin.id:
            # Not paternalism: the last administrator demoting themselves
            # leaves a deployment nobody can administer, and there is no
            # recovery for that short of the guarded command on the host.
            raise HTTPException(
                status_code=400, detail="You cannot change your own role."
            )

        request_id, ip_hash = await audit_coordinates(request, session_factory)
        async with session_factory() as session:
            async with session.begin():
                target = await session.get(User, target_id)
                if target is None:
                    raise HTTPException(status_code=404, detail="No such player.")
                if target.state != AccountState.REGISTERED.value:
                    raise HTTPException(
                        status_code=400,
                        detail="Only a registered account can hold a role.",
                    )
                if target.role == UserRole.ADMIN.value:
                    raise HTTPException(
                        status_code=400,
                        detail="An administrator's role cannot be changed here.",
                    )
                previous = target.role
                if previous == body.role:
                    return {"id": user_id, "role": previous}
                target.role = body.role
                session.add(
                    AuditEvent(
                        id=generate_uuid(),
                        event_type=ROLE_CHANGED_EVENT,
                        actor_user_id=admin.id,
                        target_user_id=target_id,
                        target_type=AuditTargetType.USER.value,
                        target_id=str(target_id),
                        request_id=request_id,
                        ip_hash=ip_hash,
                        details={
                            "from": previous,
                            "to": body.role,
                            "reason": body.reason,
                        },
                        created_at=datetime.now(timezone.utc),
                    )
                )
                # In the same transaction as the change it describes, so there
                # can be no role nobody was told about and no notice about a
                # role that was never granted. The reason stays in the ledger
                # above: it is text one administrator wrote for another.
                session.add(
                    RoleChangeNotice(
                        id=generate_uuid(),
                        user_id=target_id,
                        role=body.role,
                        created_at=datetime.now(timezone.utc),
                    )
                )
        # After the commit, so a socket can never announce a role a rolled-back
        # transaction never granted. The no-op above returns before reaching
        # here, so an administrator re-pressing the button tells nobody twice.
        #
        # The parsed id, not the path string: every socket joins its account's
        # broadcast room as `user:{id}` built from the session's canonical UUID,
        # so a request that spelled the id in upper case - which `UUID()` parses
        # perfectly well - would emit to a room nobody is in, and the push would
        # be lost with nothing to show for it.
        if on_role_changed is not None:
            await on_role_changed(str(target_id))
        # No session revocation: the gate loads the role fresh on every
        # request, so a demotion is in force on the target's very next call.
        return {"id": user_id, "role": body.role}

    return router


def _escaped_like(term: str) -> str:
    """A search term as a LIKE pattern, with its metacharacters neutralised.

    A `%` typed into a search box is a character somebody typed, not a pattern
    they wrote: without this, `?q=%` answers with ten arbitrary accounts, which
    is the difference between a lookup and a directory.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _maybe_uuid(term: str) -> UUID | None:
    """The term as an account id, when it is one."""
    try:
        return UUID(term)
    except ValueError:
        return None


def _state(shutdown: ShutdownCoordinator) -> dict:
    return {
        "paused": shutdown.is_paused,
        "draining": shutdown.is_draining,
        "readiness": shutdown.state,
        # What a shutdown started right now would give live games, so the
        # panel can show it rather than making an operator guess.
        "drainSeconds": shutdown.drain_seconds,
    }

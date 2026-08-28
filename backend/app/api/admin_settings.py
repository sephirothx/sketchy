"""Reading and changing the runtime tunables, on the record (#446).

Two endpoints over one registry. The read is what a panel draws its controls
from - every value with its default, its bounds and a line saying what it
trades off, so the page needs to know nothing about any particular setting.
The write is where a change becomes durable and accountable at the same moment:
the row and its audit event share one transaction, because a ledger that can
commit without the change it describes is a ledger that can lie.

A change takes effect on the next command rather than the next restart. That
is the whole point - the value that prompted this issue could only be settled
by looking at a running game, and a restart between attempts makes looking
expensive enough that nobody does it twice.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.admin_auth import admin_gate
from app.auth.audit import audit_coordinates
from app.db.models import AuditEvent, User, generate_uuid
from app.domain_values import AuditTargetType
from app.services import config_store
from app.services.runtime_settings import (
    CONFIG_PREFIX,
    RuntimeSettings,
    TunableError,
)

# One event type for every tunable, with the setting named in `target_id`.
# A type per setting would make the ledger's own filter useless for the
# question an operator actually asks: what has been changed lately.
CONFIG_CHANGED = "config.changed"


class TunableChanges(BaseModel):
    """One or more settings to change, and one or more to put back.

    Both in one request on purpose: a pair of values that only makes sense
    together - a faster client cadence and the larger budget that admits it -
    has to be validated as a set, and a panel that had to send them separately
    would be refused for a state neither half was asking for.
    """

    model_config = ConfigDict(extra="forbid")

    values: dict[str, float | str] = Field(default_factory=dict)
    reset: list[str] = Field(default_factory=list)


def _stored_form(number: float) -> str:
    """A number written the way it will be read back."""
    return str(int(number)) if float(number).is_integer() else str(number)


def _wire(described: dict) -> dict:
    """The registry's plain field names, in the camelCase the client reads."""
    return {
        "name": described["name"],
        "value": described["value"],
        "default": described["default"],
        "bootValue": described["boot_value"],
        "minimum": described["minimum"],
        "maximum": described["maximum"],
        "unit": described["unit"],
        "audience": described["audience"],
        "description": described["description"],
        "envVar": described["env_var"],
        "source": described["source"],
    }


def create_admin_settings_router(
    session_factory: async_sessionmaker[AsyncSession],
    settings: RuntimeSettings,
    *,
    on_change: Callable[[Collection[str]], Awaitable[None]] | None = None,
) -> APIRouter:
    """`on_change` is told which settings moved, once they are in force.

    Some of these are the *client's* cadences, and a client already connected
    has no reason to ask again - so somebody has to tell it. Passed in rather
    than reaching for the Socket.IO server here, because a router that can
    broadcast is a router that needs a live server to test.
    """
    router = APIRouter()
    # Taken as a dependency rather than awaited in the body, and that is not a
    # style choice: FastAPI validates the request body *before* the handler
    # runs, so a gate called inside one answers 422 to an ordinary player who
    # sends a malformed body - telling them the endpoint exists, which is the
    # single thing the 404 in `admin_auth` is there to avoid. A dependency is
    # resolved first, so they get the same 404 either way.
    require_admin = admin_gate(session_factory)

    @router.get("/api/admin/tunables")
    async def read_tunables(request: Request):
        """Every tunable, with what it is, what it was, and what it may be."""
        await require_admin(request)
        return {"tunables": [_wire(item) for item in settings.describe()]}

    @router.patch("/api/admin/tunables")
    async def change_tunables(
        request: Request,
        changes: TunableChanges,
        admin: User = Depends(require_admin),
    ):
        """Change settings as one set, persist them, and record who changed them."""
        if not changes.values and not changes.reset:
            raise HTTPException(status_code=400, detail="Nothing to change.")
        overlap = sorted(set(changes.values) & set(changes.reset))
        if overlap:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot set and reset the same setting: {', '.join(overlap)}",
            )
        try:
            wanted = settings.validate(changes.values, resets=changes.reset)
        except TunableError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        # Only what is actually moving. A panel that submits its whole form
        # would otherwise write a row and an audit event for every setting on
        # the page, and bury the one change an operator made.
        moving = {
            name: number
            for name, number in wanted.items()
            if number != settings.value(name)
        }
        if not moving:
            return {"tunables": [_wire(item) for item in settings.describe()]}

        request_id, ip_hash = await audit_coordinates(request, session_factory)
        previous = {name: settings.value(name) for name in moving}
        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            async with session.begin():
                for name, number in moving.items():
                    key = f"{CONFIG_PREFIX}{name}"
                    if number == settings.boot_value(name):
                        # Back to what this process booted with, so there is
                        # nothing left to override - and a row saying so would
                        # pin the setting against a later change to the
                        # environment that set it.
                        await config_store.drop(session, key)
                    else:
                        await config_store.put(session, key, _stored_form(number))
                    session.add(
                        AuditEvent(
                            id=generate_uuid(),
                            event_type=CONFIG_CHANGED,
                            actor_user_id=admin.id,
                            target_type=AuditTargetType.APP_CONFIG.value,
                            target_id=name,
                            request_id=request_id,
                            ip_hash=ip_hash,
                            details={"from": previous[name], "to": number},
                            created_at=now,
                        )
                    )

        # After the commit, so a process that failed to persist a change is not
        # also running it. The window is one request wide and single-worker.
        settings.apply(moving)
        if on_change is not None:
            await on_change(moving.keys())
        return {"tunables": [_wire(item) for item in settings.describe()]}

    return router

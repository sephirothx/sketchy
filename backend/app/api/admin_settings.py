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

import asyncio
from collections.abc import Awaitable, Callable, Collection
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt
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

    # Strict on the numbers so a JSON `true` stays a boolean rather than
    # arriving as 1.0: pydantic coerces it otherwise, and the registry's own
    # "that is not a number" check would never see one.
    values: dict[str, StrictInt | StrictFloat | str] = Field(default_factory=dict)
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
        "integral": described["integral"],
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
    # One change at a time. Validation reads the values in force, and there are
    # several awaits between it and the write, so two requests could each pass
    # against a state neither of them left behind: from a 80ms flush and a
    # budget of 400, one request lowering only the interval and another
    # lowering only the budget both validate, and together land on a pair the
    # validator exists to refuse. One worker is not one request at a time.
    changing = asyncio.Lock()
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

        async with changing:
            try:
                wanted = settings.validate(changes.values, resets=changes.reset)
            except TunableError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error

            # Two different questions, and conflating them was a bug. What is
            # *audited* is the values that move, so a panel posting its whole
            # form does not bury the one change an operator made. What is
            # *persisted* is which settings should have a row - which changes
            # even when the number does not, because resetting a setting whose
            # live value already equals the boot value must still take the row
            # away, or it comes back the next time the boot value moves.
            moving = {
                name: number
                for name, number in wanted.items()
                if number != settings.value(name)
            }
            persisted = {
                name: number
                for name, number in wanted.items()
                if number != settings.boot_value(name)
            }
            dropped = {
                name: number
                for name, number in wanted.items()
                if name not in persisted
            }
            # Whether each setting's *row* changes, kept per name rather than
            # as one flag: taking away a durable override is a change to how
            # this deployment will start, so it is recorded even when nothing
            # numeric moves (R-CONF-06). Only a submission that changes
            # neither the value nor the row is silent, which is what keeps a
            # panel posting its whole form from burying the one real change.
            override_change = {
                name: ("stored" if name in persisted else "cleared")
                for name in wanted
                if settings.is_stored(name) is not (name in persisted)
            }
            recorded = set(moving) | set(override_change)
            if not recorded:
                return {"tunables": [_wire(item) for item in settings.describe()]}

            request_id, ip_hash = await audit_coordinates(request, session_factory)
            previous = {name: settings.value(name) for name in recorded}
            now = datetime.now(timezone.utc)
            async with session_factory() as session:
                async with session.begin():
                    for name in dropped:
                        # Back to what this process booted with, so there is
                        # nothing left to override - and a row saying so would
                        # pin the setting against a later change to whatever
                        # supplies it.
                        await config_store.drop(session, f"{CONFIG_PREFIX}{name}")
                    for name, number in persisted.items():
                        await config_store.put(
                            session, f"{CONFIG_PREFIX}{name}", _stored_form(number)
                        )
                    for name in sorted(recorded):
                        details = {"from": previous[name], "to": wanted[name]}
                        if name in override_change:
                            # Says which way the durable override went, so a
                            # reset that moved no number is still legible as
                            # the change to future restarts that it is.
                            details["override"] = override_change[name]
                        session.add(
                            AuditEvent(
                                id=generate_uuid(),
                                event_type=CONFIG_CHANGED,
                                actor_user_id=admin.id,
                                target_type=AuditTargetType.APP_CONFIG.value,
                                target_id=name,
                                request_id=request_id,
                                ip_hash=ip_hash,
                                details=details,
                                created_at=now,
                            )
                        )

            # After the commit, so a process that failed to persist a change is
            # not also running it. The window is one request wide, and the lock
            # above means no other change is inside it.
            settings.apply(persisted, stored=True)
            settings.apply(dropped, stored=False)
        if on_change is not None:
            await on_change(moving.keys())
        return {"tunables": [_wire(item) for item in settings.describe()]}

    return router

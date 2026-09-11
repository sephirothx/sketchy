"""The gate a destructive staff action passes, having already passed a role.

R-AUTH-21: holding a moderator's cookie is not the same as being the
moderator. Every action that suspends an account, warns one, changes a role,
takes content down, or reconfigures a live server asks for the second factor
again, and the answer stands for fifteen minutes rather than for the session.

Why per action rather than once at sign-in: a staff session lasts a week
(#468), and a cookie stolen from a browser left open on a moderation queue
would otherwise carry the full role for the rest of that week. Fifteen minutes
is short enough that a stolen cookie is almost never already stepped up, and
long enough to work through a queue without being asked between two decisions
about the same report.

Reading, deliberately, is not gated. A moderator who has to step up before
they can look at the queue would step up as a matter of routine, at which
point the window is open whenever they are working and the gate protects
nothing. It is the actions that change something - and the ones that show a
reported drawing - that ask.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request

from app.api.errors import Refusal
from app.refusals import ErrorCode

from app.auth.sessions import SessionData


# The header a refusal carries, so the browser can tell "prove yourself again"
# from "you may not do this at all" without parsing the sentence.
STEP_UP_HEADER = "X-Sketchy-Step-Up"
STEP_UP_DETAIL = "Confirm with your authenticator app to continue."


class StepUpRequired(Refusal):
    """A 403 that means *not yet*, rather than *not you*."""

    def __init__(self) -> None:
        super().__init__(
            403,
            ErrorCode.STEP_UP_REQUIRED,
            STEP_UP_DETAIL,
            headers={STEP_UP_HEADER: "required"},
        )


def session_is_stepped_up(request: Request) -> bool:
    """Whether this request's session proved a second factor recently."""
    session: SessionData | None = getattr(request.state, "auth_session", None)
    return session is not None and session.is_stepped_up()


def require_step_up(request: Request) -> None:
    """Raise unless this session may perform a destructive action right now."""
    if not session_is_stepped_up(request):
        raise StepUpRequired()


def stepped_up(
    gate: Callable[[Request], Awaitable[object]],
) -> Callable[[Request], Awaitable[object]]:
    """Wrap a role gate so it also demands a live step-up.

    Composed rather than folded into each gate, so the two questions stay
    separate: the role decides whether this surface exists for you at all
    (and answers 404 or 403 accordingly), and this decides whether you may
    act on it right now. Wrapping preserves whichever answer the role gave.
    """

    async def gated(request: Request):
        actor = await gate(request)
        require_step_up(request)
        return actor

    return gated

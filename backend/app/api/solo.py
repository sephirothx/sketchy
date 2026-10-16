"""Solo's REST surface (#1434): runs, the drawings they serve, and what each came to.

Solo is played in the browser: the client replays a drawing, runs its clock
and judges each guess with the TypeScript port of `app/guess_judge.py`. The
server chooses what is served, hands over the drawing behind its own door
(the fourth, R-HIST-16) and the answer forms beside it, and records what
the player reports. Every refusal of a serve is the same 404 as every other
drawing door's; a run that is not the caller's is a 404 of its own.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import Refusal
from app.api.friends import ACCOUNT_REQUIRED_HEADER
from app.api.profiles import serve_drawing
from app.auth.rate_limit import RateLimiter
from app.db.models import User
from app.domain_values import AccountState
from app.refusals import ErrorCode
from app.repositories.solo import RunView, ServeView, SoloRefused, SoloRepository
from app.request_text import ControlFreeModel
from app.services.solo_access import free_run_door, solo_door_open
from app.solo_rules import CLOCK_SECONDS, MAX_OPEN_SERVES, OUTCOMES, date_is_open

# A human's pace: a run is a handful of requests a minute. Per account, since
# every route needs one.
run_limiter = RateLimiter(limit=30, window_seconds=60)
serve_limiter = RateLimiter(limit=120, window_seconds=60)
# The bytes: one per drawing, and a revalidation on every open (R-HIST-24).
drawing_limiter = RateLimiter(limit=240, window_seconds=60)


class FreeRunBody(ControlFreeModel):
    """A free run's length: 5, 10, or null for unlimited."""

    model_config = ConfigDict(strict=True, extra="forbid")

    length: Literal[5, 10] | None


class ResultBody(ControlFreeModel):
    """What a served drawing came to, by the client's own clock."""

    model_config = ConfigDict(strict=True, extra="forbid")

    outcome: Literal[OUTCOMES]
    seconds: float = Field(ge=0, le=CLOCK_SECONDS)


def serve_payload(serve: ServeView) -> dict:
    """A serve as the client holds it. No turn id, no drawer, and the prompt
    in plain words only once it is settled: before, only in the encoded forms
    the client judges guesses by."""
    return {
        "serveId": serve.serve_id,
        "position": serve.position,
        "forms": serve.forms or None,
        "outcome": serve.outcome,
        "points": serve.points,
        "prompt": serve.prompt,
        "promptLanguage": serve.prompt_language,
    }


def run_payload(run: RunView) -> dict:
    return {
        "runId": run.run_id,
        "mode": run.mode,
        "length": run.length,
        "state": run.state,
        "endReason": run.end_reason,
        "position": run.position,
        "solved": run.solved,
        "points": run.points,
        "dailyDate": run.daily_date,
        "serves": [serve_payload(serve) for serve in run.serves],
    }


def create_solo_router(session_factory: async_sessionmaker[AsyncSession]) -> APIRouter:
    router = APIRouter(prefix="/api/solo")
    solo = SoloRepository(session_factory)

    async def account(request: Request) -> User:
        """The registered account behind the request, or the refusal saying
        why: Solo is for registered players (#1434)."""
        value = getattr(request.state, "user_id", None)
        if not value:
            raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        async with session_factory() as session:
            user = await session.get(User, UUID(value))
        if user is None or user.state == AccountState.DELETED.value:
            raise Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        if user.is_anonymous:
            raise Refusal(
                403,
                ErrorCode.ACCOUNT_REQUIRED,
                "Create an account to play Solo.",
                params={"action": "solo"},
                headers={ACCOUNT_REQUIRED_HEADER: "1"},
            )
        return user

    def throttle(limiter: RateLimiter, user: User) -> None:
        if not limiter.check(str(user.id)):
            raise Refusal(
                429, ErrorCode.TOO_MANY_REQUESTS, "Too many requests. Please wait and try again."
            )

    def refused(error: SoloRefused, *, missing: ErrorCode = ErrorCode.NO_SUCH_SOLO_RUN) -> Refusal:
        if error.kind == "missing":
            return Refusal(404, missing, "Not found.")
        if error.kind == "empty":
            return Refusal(409, ErrorCode.SOLO_POOL_EMPTY, "Nothing left to serve right now.")
        return Refusal(409, ErrorCode.SOLO_CONFLICT, "That changed in the meantime.")

    def now() -> datetime:
        return datetime.now(timezone.utc)

    @router.post("/runs", status_code=201)
    async def start_free_run(body: FreeRunBody, request: Request):
        """Start a free run, abandoning the one in play."""
        user = await account(request)
        throttle(run_limiter, user)
        door = free_run_door(body.length)
        if not solo_door_open(state=user.state, is_anonymous=user.is_anonymous, door=door):
            raise Refusal(
                403, ErrorCode.ACCOUNT_REQUIRED, "Create an account to play Solo.",
                params={"action": "solo"},
            )
        try:
            run = await solo.start_free_run(str(user.id), length=body.length, now=now())
        except SoloRefused as error:
            raise refused(error) from error
        return run_payload(run)

    @router.get("/runs/active")
    async def active_free_run(request: Request):
        """The free run there is to continue, or null."""
        user = await account(request)
        throttle(serve_limiter, user)
        run = await solo.active_free_run(str(user.id))
        return {"run": run_payload(run) if run is not None else None}

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str, request: Request):
        user = await account(request)
        throttle(serve_limiter, user)
        try:
            return run_payload(await solo.get_run(str(user.id), run_id))
        except SoloRefused as error:
            raise refused(error) from error

    @router.post("/runs/{run_id}/serves")
    async def serve_next(
        run_id: str,
        request: Request,
        count: int = Query(default=1, ge=1, le=MAX_OPEN_SERVES),
    ):
        """The next drawings of a free run, with the answer forms each is
        judged by: one, or two to hold the next one ready."""
        user = await account(request)
        throttle(serve_limiter, user)
        try:
            served = await solo.serve_next(str(user.id), run_id, count=count, now=now())
        except SoloRefused as error:
            raise refused(error) from error
        return {"serves": [serve_payload(serve) for serve in served]}

    @router.post("/serves/{serve_id}/result")
    async def settle(serve_id: str, body: ResultBody, request: Request):
        """What a served drawing came to: solved after so many seconds, given
        up, or timed out. Recorded once; the server derives the points."""
        user = await account(request)
        throttle(serve_limiter, user)
        try:
            serve, run = await solo.settle(
                str(user.id), serve_id, outcome=body.outcome, seconds=body.seconds, now=now()
            )
        except SoloRefused as error:
            raise refused(error, missing=ErrorCode.NO_SUCH_DRAWING) from error
        return {"serve": serve_payload(serve), "run": run_payload(run)}

    def local_date(value: str) -> date:
        """A player's local date, accepted only while it is today somewhere
        (±14 h of UTC): the server cannot see the player's zone, and a date
        that is nobody's today is somebody asking for another day's Daily."""
        try:
            day = date.fromisoformat(value)
        except ValueError as error:
            raise Refusal(
                422, ErrorCode.SOLO_DATE_OUT_OF_RANGE, "That is not a date.", field="date"
            ) from error
        if not date_is_open(day, now()):
            raise Refusal(
                422, ErrorCode.SOLO_DATE_OUT_OF_RANGE, "That date is not today anywhere.",
                field="date",
            )
        return day

    @router.post("/daily/{day}")
    async def open_daily(day: str, request: Request):
        """Today's Daily (#1434): created with its five drawings the first
        time, resumed after, never restarted. The same five for everybody."""
        user = await account(request)
        throttle(run_limiter, user)
        local = local_date(day)
        if not solo_door_open(state=user.state, is_anonymous=user.is_anonymous, door="daily_today"):
            raise Refusal(
                403, ErrorCode.ACCOUNT_REQUIRED, "Create an account to play Solo.",
                params={"action": "solo"},
            )
        try:
            run = await solo.open_daily(str(user.id), local, now=now())
        except SoloRefused as error:
            raise refused(error, missing=ErrorCode.NO_SUCH_DAILY) from error
        return run_payload(run)

    @router.get("/me")
    async def summary(request: Request, today: str = Query()):
        """What Solo's page opens on: today's Daily, the free run there is to
        continue, the bests, the Daily history and the streak."""
        user = await account(request)
        throttle(serve_limiter, user)
        return await solo.summary(str(user.id), local_date(today), now=now())

    @router.get("/serves/{serve_id}/drawing")
    async def served_drawing(serve_id: str, request: Request):
        """A served drawing's bytes: the fourth door (R-HIST-16), its own
        route and query - the caller's serve, the drawing still servable -
        with the other doors' conditional handling (R-HIST-24). Every refusal
        is the same 404, signed out included."""
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        if not drawing_limiter.check(user_id):
            raise Refusal(
                429, ErrorCode.TOO_MANY_REQUESTS, "Too many requests. Please wait and try again."
            )
        return await serve_drawing(
            request,
            serve_id,
            checksum_of=lambda: solo.served_drawing_checksum(user_id, serve_id),
            drawing_of=lambda: solo.served_drawing(user_id, serve_id),
        )

    return router

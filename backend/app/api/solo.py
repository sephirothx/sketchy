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
from collections.abc import Awaitable, Callable
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
from app.repositories.sqlalchemy import SqlAlchemyGameHistoryRepository
from app.request_text import ControlFreeModel
from app.services.solo_access import SoloDoor, free_run_door, solo_door_open
from app.solo_rules import (
    CLOCK_SECONDS,
    MAX_OPEN_SERVES,
    OUTCOMES,
    daily_release_at,
    date_is_open,
)

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


class SoloReactionBody(ControlFreeModel):
    """Which emoji, by code: the Gallery's reaction body."""

    model_config = ConfigDict(strict=True, extra="forbid")

    emoji: str = Field(min_length=1, max_length=16)


def create_solo_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    game_history_repo=None,
    on_inbox_changed: Callable[[str], Awaitable[None]] | None = None,
    on_gallery_changed: Callable[[], None] | None = None,
) -> APIRouter:
    """`game_history_repo` writes reactions and shares, which are the
    drawing's own facts whoever makes them; `on_inbox_changed` tells a
    drawer's open tabs that somebody shared their drawing."""
    router = APIRouter(prefix="/api/solo")
    solo = SoloRepository(session_factory)
    history = game_history_repo or SqlAlchemyGameHistoryRepository(session_factory)

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
        if error.kind == "erased":
            # Deleted while the request was on its way: signed out, as every
            # other write answers an erased account (moderation, lists).
            return Refusal(401, ErrorCode.SIGN_IN_REQUIRED, "Sign in first.")
        return Refusal(409, ErrorCode.SOLO_CONFLICT, "That changed in the meantime.")

    def now() -> datetime:
        return datetime.now(timezone.utc)

    @router.post("/runs", status_code=201)
    async def start_free_run(body: FreeRunBody, request: Request):
        """Start a free run, abandoning the one of its length in play."""
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

    def parse_date(value: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise Refusal(
                422, ErrorCode.SOLO_DATE_OUT_OF_RANGE, "That is not a date.", field="date"
            ) from error

    def local_date(value: str) -> date:
        """A player's local date, accepted only while it is today somewhere
        (±14 h of UTC): the server cannot see the player's zone, and a date
        that is nobody's today is somebody asking for another day's Daily."""
        day = parse_date(value)
        if not date_is_open(day, now()):
            raise Refusal(
                422, ErrorCode.SOLO_DATE_OUT_OF_RANGE, "That date is not today anywhere.",
                field="date",
            )
        return day

    def past_date(value: str) -> date:
        """A date that has ended everywhere: the archive's (#1470). One still
        today somewhere is today's door's, and a later one nobody's yet."""
        day = parse_date(value)
        if now() < daily_release_at(day):
            raise Refusal(
                422, ErrorCode.SOLO_DATE_OUT_OF_RANGE, "That date has not ended everywhere yet.",
                field="date",
            )
        return day

    def open_door(user: User, door: SoloDoor) -> None:
        if not solo_door_open(state=user.state, is_anonymous=user.is_anonymous, door=door):
            raise Refusal(
                403, ErrorCode.ACCOUNT_REQUIRED, "Create an account to play Solo.",
                params={"action": "solo"},
            )

    @router.post("/daily/{day}")
    async def open_daily(day: str, request: Request):
        """A date's Daily (#1434): created with its five drawings the first
        time, resumed after, never restarted. The same five for everybody.
        Today's through today's door; a date that has ended everywhere
        through the archive's (#1470), where a Daily left unfinished is
        finished, its late drawings marked so, and one finished is opened
        as it stands, to review."""
        user = await account(request)
        throttle(run_limiter, user)
        local = parse_date(day)
        archived = not date_is_open(local, now())
        local = past_date(day) if archived else local
        # A Daily the player finished is only reviewed, and their own: no
        # gate stands in front of it, as none stands before their history
        # (#1496 review). Playing a past one late is the archive's.
        if not (archived and await solo.daily_finished(str(user.id), local)):
            open_door(user, "archive" if archived else "daily_today")
        try:
            run = await solo.open_daily(str(user.id), local, now=now(), archive=archived)
        except SoloRefused as error:
            raise refused(error, missing=ErrorCode.NO_SUCH_DAILY) from error
        return run_payload(run)

    @router.get("/me")
    async def summary(request: Request, today: str = Query()):
        """What Solo's page opens on: today's Daily, the free runs there are
        to continue, the bests, the streak and the Dailies' totals."""
        user = await account(request)
        throttle(serve_limiter, user)
        return await solo.summary(str(user.id), local_date(today), now=now())

    @router.get("/daily/month")
    async def month(request: Request, today: str = Query(), month: str = Query()):
        """One month of the caller's Dailies for the calendar, up to their
        `today` (validated as `/me`'s): a month after it is refused. Each date
        says whether the archive door would play it now (#1470)."""
        user = await account(request)
        throttle(serve_limiter, user)
        local = local_date(today)
        try:
            first = date.fromisoformat(f"{month}-01")
        except ValueError as error:
            raise Refusal(
                422, ErrorCode.SOLO_DATE_OUT_OF_RANGE, "That is not a month.", field="month"
            ) from error
        if len(month) != 7 or first > local:
            raise Refusal(
                422, ErrorCode.SOLO_DATE_OUT_OF_RANGE, "That month has not begun.", field="month"
            )
        archive = solo_door_open(state=user.state, is_anonymous=user.is_anonymous, door="archive")
        return await solo.month(str(user.id), first, local, now=now(), archive=archive)

    async def settled(serve_id: str, user: User) -> str:
        turn_id = await solo.settled_turn(str(user.id), serve_id)
        if turn_id is None:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        return str(turn_id)

    async def write_reaction(serve_id: str, request: Request, emoji: str | None) -> dict:
        """Solo's door for a reaction (R-SOLO-15): a drawing Solo served the
        caller and they settled, still servable. It counts like a Gallery
        reaction (R-REACT-05). The answer names nobody - only the counts and
        the caller's own pick."""
        user = await account(request)
        throttle(serve_limiter, user)
        turn_id = await settled(serve_id, user)
        result = await history.set_drawing_reaction(
            None, turn_id, requesting_user_id=str(user.id), emoji=emoji, from_solo=True
        )
        if result is None:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        if on_gallery_changed is not None:
            on_gallery_changed()
        return {"myReaction": result.emoji, "reactionCounts": dict(result.reaction_counts)}

    def share_payload(share) -> dict:
        return {
            "inGallery": share.in_gallery,
            "sharedByMe": share.shared_by_me,
            "heldUntil": share.held_until.isoformat() if share.held_until else None,
            "shareWithdrawn": share.withdrawn,
        }

    @router.get("/serves/{serve_id}/state")
    async def drawing_state(serve_id: str, request: Request):
        """A settled drawing as the caller left it (#1496 review): the
        reaction counts and their pick, and their share, for the card and
        the review to start from. Names nobody; the same 404 as the writes."""
        user = await account(request)
        throttle(serve_limiter, user)
        turn_id = await settled(serve_id, user)
        state = await history.solo_drawing_state(turn_id, requesting_user_id=str(user.id))
        if state is None:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        return {
            "myReaction": state.my_reaction,
            "reactionCounts": state.reaction_counts,
            **share_payload(state.share),
        }

    @router.put("/serves/{serve_id}/reaction")
    async def react(serve_id: str, body: SoloReactionBody, request: Request):
        return await write_reaction(serve_id, request, body.emoji)

    @router.delete("/serves/{serve_id}/reaction")
    async def unreact(serve_id: str, request: Request):
        return await write_reaction(serve_id, request, None)

    async def write_share(serve_id: str, request: Request, shared: bool) -> dict:
        """Share a drawing Solo served the caller to the Gallery, under its
        drawer's name, or take their share back (R-SOLO-15). A Daily's
        drawing waits until that date has ended everywhere (`heldUntil`)."""
        user = await account(request)
        throttle(serve_limiter, user)
        turn_id = await settled(serve_id, user)
        result = await history.set_solo_share(
            turn_id, requesting_user_id=str(user.id), shared=shared
        )
        if result is None:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        if result.notify_user_id is not None and on_inbox_changed is not None:
            await on_inbox_changed(result.notify_user_id)
        if on_gallery_changed is not None:
            on_gallery_changed()
        return share_payload(result)

    @router.put("/serves/{serve_id}/share")
    async def share(serve_id: str, request: Request):
        return await write_share(serve_id, request, True)

    @router.delete("/serves/{serve_id}/share")
    async def unshare(serve_id: str, request: Request):
        return await write_share(serve_id, request, False)

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

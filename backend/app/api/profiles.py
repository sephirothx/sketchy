"""Public profile endpoints: lifetime stats and browsable game history."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.serializers import (
    game_detail_payload,
    game_summary_payload,
    stats_payload,
    user_payload,
)
from app.auth.rate_limit import RateLimiter, client_key
from app.canvas_storage import (
    CorruptStoredDrawingError,
    UnsupportedStoredDrawingError,
    stored_drawing_wire_payload,
)
from app.domain_values import OFFERED_REACTION_EMOJI_CODES
from app.repositories.interfaces import (
    DrawingReactionResult,
    GameHistoryRepository,
    UserRepository,
)

# The largest page the client may ask for. Deliberately below the repository's
# own clamp so that asking for one row past the page (how `hasMore` is answered)
# is never itself clamped away.
MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 20

# These endpoints need no session. Statistics now read a bounded daily
# projection rather than scanning lifetime game/turn/guess facts, but the
# ceiling still makes automated account-id walking inconvenient.
profile_limiter = RateLimiter(limit=120, window_seconds=60)

logger = logging.getLogger("sketchy.api.profiles")


class ReactionBody(BaseModel):
    """The one field a reaction write carries: which emoji, by code."""

    model_config = ConfigDict(strict=True, extra="forbid")

    emoji: str = Field(min_length=1, max_length=16)


def reaction_payload(result: DrawingReactionResult) -> dict:
    return {
        "turnId": result.turn_id,
        "seatId": result.seat_id,
        "emoji": result.emoji,
        "reactions": [
            {"seatId": reaction.seat_id, "emoji": reaction.emoji}
            for reaction in result.reactions
        ],
    }


def create_profile_router(
    user_repo: UserRepository,
    game_history_repo: GameHistoryRepository,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    def throttle(request: Request) -> None:
        if not profile_limiter.check(client_key(request)):
            raise HTTPException(
                status_code=429, detail="Too many requests. Please wait and try again."
            )

    @router.get("/users/{user_id}/stats")
    async def user_stats(user_id: str, request: Request):
        """Lifetime metrics for a player, alongside who they are.

        The account travels with the numbers because a profile opened by id is
        the one view that has no other way to learn the player's name - and
        because `get_stats` answers with a zeroed record for an id that does not
        exist, so the lookup is also what makes a 404 possible.
        """
        throttle(request)
        user = await user_repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="No such player.")
        stats = await user_repo.get_stats(user_id)
        return {"user": user_payload(user), "stats": stats_payload(stats)}

    @router.get("/users/{user_id}/games")
    async def user_games(
        user_id: str,
        request: Request,
        limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
        offset: int = Query(default=0, ge=0),
        include_abandoned: bool = Query(default=False, alias="includeAbandoned"),
    ):
        """A page of games this player took part in, newest first.

        Games that stopped without ending are left out unless asked for: a
        history made mostly of rooms that collapsed is not what anyone came
        looking for, but a game somebody remembers should still be findable.
        """
        throttle(request)
        # One extra row answers "is there another page?" without a second COUNT
        # query, and without the client inferring it from a full-looking page.
        games = await game_history_repo.get_user_games(
            user_id,
            limit=limit + 1,
            offset=offset,
            include_abandoned=include_abandoned,
        )
        has_more = len(games) > limit
        return {
            "games": [game_summary_payload(g) for g in games[:limit]],
            "hasMore": has_more,
        }

    @router.get("/games/{game_id}")
    async def game_detail(game_id: str, request: Request):
        """Round-by-round detail, visible only to the players who were there.

        The prompts drawn, who guessed them and how fast are the substance of a
        game, and they belong to its participants rather than to anyone holding
        the id.
        """
        throttle(request)
        requesting_user_id = getattr(request.state, "user_id", None)
        if not requesting_user_id:
            raise HTTPException(status_code=404, detail="No such game.")
        detail = await game_history_repo.get_game_detail(
            game_id, requesting_user_id=requesting_user_id
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="No such game.")
        return game_detail_payload(detail)

    @router.get("/games/{game_id}/turns/{turn_id}/drawing")
    async def turn_drawing(game_id: str, turn_id: str, request: Request):
        """The drawing made during one turn, for the players who were there.

        Answered in the current wire format, so a client decodes a stored
        drawing with exactly the code it already uses for a live one.
        """
        throttle(request)
        requesting_user_id = getattr(request.state, "user_id", None)
        if not requesting_user_id:
            raise HTTPException(status_code=404, detail="No such drawing.")
        drawing = await game_history_repo.get_turn_drawing(
            game_id, turn_id, requesting_user_id=requesting_user_id
        )
        if drawing is None:
            raise HTTPException(status_code=404, detail="No such drawing.")
        try:
            payload = stored_drawing_wire_payload(
                drawing.payload, checksum=drawing.checksum_sha256 or None
            )
        except UnsupportedStoredDrawingError as error:
            # A build older than the row it is reading. Answer as though the
            # drawing is absent rather than claiming it is broken.
            logger.error("Cannot decode stored drawing %s: %s", turn_id, error)
            raise HTTPException(status_code=404, detail="No such drawing.") from error
        except CorruptStoredDrawingError as error:
            logger.error("Stored drawing %s failed its checksum", turn_id)
            raise HTTPException(
                status_code=500, detail="That drawing could not be read."
            ) from error
        return Response(
            content=payload,
            media_type="application/octet-stream",
            headers={
                # Participant-scoped bytes must never reach a shared cache.
                "Cache-Control": "private, max-age=3600, immutable",
                "ETag": f'"{drawing.checksum_sha256}"',
            },
        )

    async def _write_reaction(
        game_id: str, turn_id: str, request: Request, emoji: str | None
    ) -> dict:
        """The shared body of the reaction routes.

        Every refusal is a 404, the same rule as the drawing route above
        (R-HIST-16): a stranger, a guest, the drawer, an erased drawing and a
        game that does not exist all get the same answer, so the route never
        says which. The repository applies the rules; this only asks.
        """
        throttle(request)
        requesting_user_id = getattr(request.state, "user_id", None)
        if not requesting_user_id:
            raise HTTPException(status_code=404, detail="No such drawing.")
        if emoji is not None and emoji not in OFFERED_REACTION_EMOJI_CODES:
            raise HTTPException(status_code=404, detail="No such drawing.")
        result = await game_history_repo.set_drawing_reaction(
            game_id, turn_id, requesting_user_id=requesting_user_id, emoji=emoji
        )
        if result is None:
            raise HTTPException(status_code=404, detail="No such drawing.")
        return reaction_payload(result)

    @router.put("/games/{game_id}/turns/{turn_id}/reaction")
    async def set_turn_reaction(
        game_id: str, turn_id: str, body: ReactionBody, request: Request
    ):
        """Leave, or change, the signed-in player's reaction to a stored drawing."""
        return await _write_reaction(game_id, turn_id, request, body.emoji)

    @router.delete("/games/{game_id}/turns/{turn_id}/reaction")
    async def clear_turn_reaction(game_id: str, turn_id: str, request: Request):
        """Take the signed-in player's reaction back."""
        return await _write_reaction(game_id, turn_id, request, None)

    return router

"""Public profile endpoints: lifetime stats and browsable game history."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.serializers import (
    game_detail_payload,
    game_summary_payload,
    stats_payload,
    user_payload,
)
from app.auth.rate_limit import RateLimiter, client_key
from app.repositories.interfaces import GameHistoryRepository, UserRepository

# The largest page the client may ask for. Deliberately below the repository's
# own clamp so that asking for one row past the page (how `hasMore` is answered)
# is never itself clamped away.
MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 20

# These endpoints need no session. Statistics now read a bounded daily
# projection rather than scanning lifetime game/turn/guess facts, but the
# ceiling still makes automated account-id walking inconvenient.
profile_limiter = RateLimiter(limit=120, window_seconds=60)


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
    ):
        """A page of finished games this player took part in, newest first."""
        throttle(request)
        # One extra row answers "is there another page?" without a second COUNT
        # query, and without the client inferring it from a full-looking page.
        games = await game_history_repo.get_user_games(
            user_id, limit=limit + 1, offset=offset
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

    return router

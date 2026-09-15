"""The Gallery's REST surface (#524): reactions from outside the game."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import Refusal
from app.api.profiles import reaction_payload
from app.auth.rate_limit import RateLimiter, client_key
from app.domain_values import OFFERED_REACTION_EMOJI_CODES
from app.refusals import ErrorCode
from app.repositories.interfaces import GameHistoryRepository

# The same ceiling as the profile routes: a human's pace, and enough to make
# walking turn ids inconvenient.
gallery_limiter = RateLimiter(limit=120, window_seconds=60)


class GalleryReactionBody(BaseModel):
    """The one field a reaction write carries: which emoji, by code."""

    model_config = ConfigDict(strict=True, extra="forbid")

    emoji: str = Field(min_length=1, max_length=16)


def create_gallery_router(game_history_repo: GameHistoryRepository) -> APIRouter:
    router = APIRouter(prefix="/api/gallery")

    def throttle(request: Request) -> None:
        if not gallery_limiter.check(client_key(request)):
            raise Refusal(
                429,
                ErrorCode.TOO_MANY_REQUESTS,
                "Too many requests. Please wait and try again.",
            )

    async def _write_reaction(turn_id: str, request: Request, emoji: str | None) -> dict:
        """The gallery door for a reaction (R-GAL-06, R-REACT-08).

        Any registered account that is not the drawer may react to a drawing
        the Gallery shows - a public game, a kept drawing - whether or not
        they sat in it; their seat is written beside the account when they
        did. Every refusal is the same 404: signed out, a guest, the drawer, a
        private game, an erased drawing, an unknown turn, an unknown code.
        """
        throttle(request)
        requesting_user_id = getattr(request.state, "user_id", None)
        if not requesting_user_id:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        if emoji is not None and emoji not in OFFERED_REACTION_EMOJI_CODES:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        result = await game_history_repo.set_drawing_reaction(
            None,
            turn_id,
            requesting_user_id=requesting_user_id,
            emoji=emoji,
            from_gallery=True,
        )
        if result is None:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        return reaction_payload(result)

    @router.put("/{turn_id}/reaction")
    async def set_gallery_reaction(
        turn_id: str, body: GalleryReactionBody, request: Request
    ):
        """Leave, or change, the signed-in player's reaction to a gallery drawing."""
        return await _write_reaction(turn_id, request, body.emoji)

    @router.delete("/{turn_id}/reaction")
    async def clear_gallery_reaction(turn_id: str, request: Request):
        """Take the signed-in player's reaction back."""
        return await _write_reaction(turn_id, request, None)

    return router

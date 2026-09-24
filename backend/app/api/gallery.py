"""The Gallery's REST surface (#524): reactions from outside the game."""
from __future__ import annotations

from dataclasses import replace
import hashlib

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import Refusal
from app.api.profiles import reaction_payload, serve_drawing, validator_matches
from app.api.serializers import _timestamp as serialize_timestamp
from app.auth.rate_limit import RateLimiter, client_key
from app.domain_values import OFFERED_REACTION_EMOJI_CODES
from app.refusals import ErrorCode
from app.repositories.interfaces import GalleryEntry, GameHistoryRepository
from app.services.gallery_ranking import MAX_GALLERY_PAGE, TOP_WINDOWS
from app.services.gallery_shelf import SHELF_SIZE, GalleryShelfCache

GALLERY_SORTS = ("hot", "new", "top")


async def _read_shelf(game_history_repo: GameHistoryRepository):
    page = await game_history_repo.list_gallery(
        sort="top", window="week", limit=SHELF_SIZE
    )
    return page.entries

# The same ceiling as the profile routes: a human's pace, and enough to make
# walking turn ids inconvenient.
gallery_limiter = RateLimiter(limit=120, window_seconds=60)
# The bytes get a budget of their own: a page of the Gallery replays up to
# 24 thumbnails and a scroll adds 24 more, so at the listing's ceiling five
# pages in a minute would refuse the sixth thumbnail. Most of these are
# `304`s answered from the metadata (R-HIST-24).
drawing_limiter = RateLimiter(limit=600, window_seconds=60)


def gallery_entry_payload(entry: GalleryEntry) -> dict:
    """What an entry publishes (R-GAL-03): the pin's shape, the finish time,
    and the viewer's own facts. No `gameId`, no room, no reactor's name."""
    return {
        "turnId": entry.turn_id,
        "roundNumber": entry.round_number,
        "turnNumber": entry.turn_number,
        "drawerDisplayName": entry.drawer_display_name,
        "drawerNameColor": entry.drawer_name_color,
        "drawerIsAnonymous": entry.drawer_is_anonymous,
        "prompt": entry.prompt,
        "strokeCount": entry.stroke_count,
        "finishedAt": serialize_timestamp(entry.finished_at),
        "reactionCounts": dict(entry.reaction_counts),
        "myReaction": entry.my_reaction,
        "drawnByMe": entry.drawn_by_me,
    }


class GalleryReactionBody(BaseModel):
    """The one field a reaction write carries: which emoji, by code."""

    model_config = ConfigDict(strict=True, extra="forbid")

    emoji: str = Field(min_length=1, max_length=16)


def create_gallery_router(
    game_history_repo: GameHistoryRepository,
    *,
    shelf: GalleryShelfCache | None = None,
) -> APIRouter:
    """`shelf` is the process-wide cache of This week; a router built
    without one gets a cache of its own over the repository."""
    router = APIRouter(prefix="/api/gallery")
    shelf_cache = shelf or GalleryShelfCache(
        lambda: _read_shelf(game_history_repo)
    )

    def throttle(request: Request, limiter: RateLimiter = gallery_limiter) -> None:
        if not limiter.check(client_key(request)):
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

    @router.get("")
    async def gallery(
        request: Request,
        sort: str = Query(default="hot"),
        window: str = Query(default="all"),
        limit: int = Query(default=MAX_GALLERY_PAGE, ge=1, le=MAX_GALLERY_PAGE),
        cursor: str | None = Query(default=None, max_length=256),
    ):
        """One page of the **Gallery** (R-GAL-01..04): every kept drawing from
        a public game, for anyone with a session.

        No session is refused as `account_required` rather than answered
        with an empty page (R-GAL-02): the page is the one surface on which
        every public drawing is a query away, and signed-in is the line
        between a player and a scraper. Guests are signed in.
        """
        throttle(request)
        if not getattr(request.state, "user_id", None):
            raise Refusal(
                403,
                ErrorCode.ACCOUNT_REQUIRED,
                "Sign in to see the gallery.",
                params={"action": "gallery"},
            )
        if sort not in GALLERY_SORTS:
            raise Refusal(422, ErrorCode.UNKNOWN_SORT, "Unknown sort.", field="sort")
        if window not in TOP_WINDOWS:
            raise Refusal(422, ErrorCode.UNKNOWN_SORT, "Unknown window.", field="window")
        page = await game_history_repo.list_gallery(
            sort=sort,
            window=window,
            limit=limit,
            cursor=cursor,
            requesting_user_id=request.state.user_id,
        )
        return {
            "entries": [gallery_entry_payload(entry) for entry in page.entries],
            "nextCursor": page.next_cursor,
        }

    @router.get("/week")
    async def this_week(request: Request, response: Response):
        """**This week** (R-GAL-07): Top over the last seven
        days, the first six, from a snapshot recomputed at most once a minute
        and shared by every lobby. The viewer's own facts are added per
        request; the validator names the snapshot and those facts, so a
        remembered copy is answered `304` until either moves. No session is
        the page's `account_required`, so nothing renders a shelf at all.
        """
        throttle(request)
        viewer_id = getattr(request.state, "user_id", None)
        if not viewer_id:
            raise Refusal(
                403,
                ErrorCode.ACCOUNT_REQUIRED,
                "Sign in to see this week's drawings.",
                params={"action": "gallery"},
            )
        snapshot = await shelf_cache.get()
        facts = await game_history_repo.viewer_gallery_facts(
            [entry.turn_id for entry in snapshot.entries], viewer_user_id=viewer_id
        )
        entries = [
            gallery_entry_payload(
                replace(
                    entry,
                    my_reaction=facts.get(entry.turn_id, (None, False))[0],
                    drawn_by_me=facts.get(entry.turn_id, (None, False))[1],
                )
            )
            for entry in snapshot.entries
        ]
        validator = 'W/"' + snapshot.version + "-" + hashlib.sha256(
            repr(sorted(facts.items())).encode()
        ).hexdigest()[:12] + '"'
        headers = {"Cache-Control": "private, no-cache", "ETag": validator}
        if_none_match = request.headers.get("if-none-match")
        if if_none_match is not None and validator_matches(if_none_match, validator):
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return {"entries": entries}

    @router.get("/{turn_id}")
    async def gallery_entry(turn_id: str, request: Request):
        """One entry, for the drawing's own page (`/gallery/{turn_id}`): the
        listing's shape, under the listing's predicate, and its 404 for
        everything else - signed out included, since a stranger with a link
        must learn nothing from it (R-GAL-02, R-GAL-06)."""
        throttle(request)
        if not getattr(request.state, "user_id", None):
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        entry = await game_history_repo.get_gallery_entry(
            turn_id, requesting_user_id=request.state.user_id
        )
        if entry is None:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        return gallery_entry_payload(entry)

    @router.get("/{turn_id}/drawing")
    async def gallery_drawing(turn_id: str, request: Request):
        """A gallery drawing's bytes: the third door (R-GAL-06), with its own
        query over the gallery predicate, and the participant route's
        conditional handling (R-HIST-24). Every refusal is a 404, signed out
        included."""
        throttle(request, drawing_limiter)
        if not getattr(request.state, "user_id", None):
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        return await serve_drawing(
            request,
            turn_id,
            checksum_of=lambda: game_history_repo.get_gallery_drawing_checksum(turn_id),
            drawing_of=lambda: game_history_repo.get_gallery_drawing(turn_id),
        )

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

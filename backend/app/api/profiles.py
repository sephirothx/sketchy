"""Public profile endpoints: lifetime stats and browsable game history."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
import gzip
import logging

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.errors import Refusal
from app.refusals import ErrorCode
from app.api.serializers import (
    game_detail_payload,
    game_summary_payload,
    public_user_payload,
    stats_payload,
)
from app.auth.rate_limit import RateLimiter, client_key
from app.canvas_history import CANVAS_HISTORY_VERSION
from app.canvas_storage import (
    CorruptStoredDrawingError,
    UnsupportedStoredDrawingError,
    stored_drawing_wire_payload,
)
from app.domain_values import OFFERED_REACTION_EMOJI_CODES, PROFILE_PIN_SLOTS
from app.compression import accepted_encodings
from app.services.telemetry import telemetry
from app.repositories.interfaces import (
    DrawingReactionResult,
    GameHistoryRepository,
    ProfilePinEntry,
    ProfilePinsResult,
    TurnDrawingDetail,
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


class PinsBody(BaseModel):
    """The whole shelf, in order: the turn ids of the drawings to show (#440).

    Bounded to the slot count here, so a body twice the cap is refused before
    anything is looked up; the cap itself is answered as a `409` by the route,
    since "you have no room" is an answer, not a malformed request.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    turnIds: list[str] = Field(max_length=PROFILE_PIN_SLOTS * 2)

    @field_validator("turnIds")
    @classmethod
    def _distinct(cls, turn_ids: list[str]) -> list[str]:
        if len(set(turn_ids)) != len(turn_ids):
            raise ValueError("a drawing can be pinned once")
        if any(not 1 <= len(turn_id) <= 64 for turn_id in turn_ids):
            raise ValueError("not a turn id")
        return turn_ids


def pin_entry_payload(pin: ProfilePinEntry) -> dict:
    """The shelf's shape mirrors a game-detail turn where the two overlap, so
    the client's recap metadata is built the same way from either."""
    return {
        "turnId": pin.turn_id,
        "roundNumber": pin.round_number,
        "turnNumber": pin.turn_number,
        "drawerDisplayName": pin.drawer_display_name,
        "drawerNameColor": pin.drawer_name_color,
        "drawerIsAnonymous": pin.drawer_is_anonymous,
        "prompt": pin.prompt,
        "strokeCount": pin.stroke_count,
        "reactions": [
            {"seatId": reaction.seat_id, "emoji": reaction.emoji}
            for reaction in pin.reactions
        ],
        "reactionCounts": dict(pin.reaction_counts),
        "myReaction": pin.my_reaction,
        "drawnByMe": pin.drawn_by_me,
    }


def pins_payload(result: ProfilePinsResult) -> dict:
    return {"pins": [{"turnId": pin.turn_id} for pin in result.pins]}


def reaction_payload(result: DrawingReactionResult) -> dict:
    """A reaction write's answer: the seat rows as a list, every row as a
    count, and the caller's own pick (R-REACT-05). `seatId` is null when the
    caller reacted from outside the room."""
    return {
        "turnId": result.turn_id,
        "seatId": result.seat_id,
        "emoji": result.emoji,
        "myReaction": result.emoji,
        "reactions": [
            {"seatId": reaction.seat_id, "emoji": reaction.emoji}
            for reaction in result.reactions
        ],
        "reactionCounts": dict(result.reaction_counts),
    }


def drawing_validator(checksum: str) -> str:
    """The `ETag` of a served drawing: the stored checksum and the wire
    version it is decoded into (#604). Weak, since the identical bytes go
    out with or without a content encoding."""
    return f'W/"{checksum}-w{CANVAS_HISTORY_VERSION}"'


def validator_matches(if_none_match: str, validator: str) -> bool:
    """Weak comparison of an `If-None-Match` header against one validator:
    the `W/` prefix is ignored on both sides, a list matches on any member,
    and `*` matches any current representation."""
    if if_none_match.strip() == "*":
        return True

    def bare(tag: str) -> str:
        tag = tag.strip()
        return tag[2:] if tag.startswith("W/") else tag

    return any(bare(tag) == bare(validator) for tag in if_none_match.split(",") if tag.strip())


#: Bytes of decoded drawings kept in memory, both encodings counted (#979).
DRAWING_CACHE_BYTES = 32 * 1024 * 1024
#: The level the cached gzip copy is made at: once, off the loop, and kept.
#: The response middleware would compress the same bytes per request (at
#: `DYNAMIC_COMPRESSLEVEL`, 4 since #1030) on the loop instead.
DRAWING_GZIP_LEVEL = 6


class WireDrawingCache:
    """Decoded drawings by stored checksum, most recently served kept (#979).

    Every fetch used to decode the stored blob back to wire bytes (1 ms for an
    ordinary drawing, 8 ms for a heavy one) and gzip the result on the loop -
    ~2 ms and ~25 ms of event loop, back to back, for bytes that are the same
    for everybody: the lobby's This week shelf is six drawings fetched by
    every visitor. The checksum is the stored blob's SHA-256 and decoding is
    deterministic, so a checksum names exactly one wire payload. Only the
    bytes are shared: who may have them is asked on every request.
    """

    def __init__(self, max_bytes: int = DRAWING_CACHE_BYTES) -> None:
        self.max_bytes = max_bytes
        self.bytes = 0
        self._entries: OrderedDict[str, tuple[bytes, bytes]] = OrderedDict()

    def get(self, key: str) -> tuple[bytes, bytes] | None:
        entry = self._entries.get(key)
        if entry is not None:
            self._entries.move_to_end(key)
        return entry

    def clear(self) -> None:
        self._entries.clear()
        self.bytes = 0

    def put(self, key: str, wire: bytes, gzipped: bytes) -> None:
        size = len(wire) + len(gzipped)
        if not key or key.startswith("-") or key in self._entries or size > self.max_bytes:
            return
        self._entries[key] = (wire, gzipped)
        self.bytes += size
        while self.bytes > self.max_bytes:
            _, (old_wire, old_gzipped) = self._entries.popitem(last=False)
            self.bytes -= len(old_wire) + len(old_gzipped)


drawing_cache = WireDrawingCache()
#: Decodes in flight, by cache key: concurrent misses for one drawing - the
#: This week shelf right after a restart - share one decode (#979 review).
_fills: dict[str, asyncio.Future] = {}
#: Below this a drawing goes out as it is: the gzip framing costs more than it
#: saves, which is the response middleware's own floor.
GZIP_MINIMUM_BYTES = 500


def _cache_key(checksum: str) -> str:
    """The stored checksum and the wire version it decodes into, as the
    `ETag` does: a new wire version changes the bytes without the checksum."""
    return f"{checksum}-w{CANVAS_HISTORY_VERSION}"


def _decoded_drawing(blob: bytes, checksum: str | None) -> tuple[bytes, bytes]:
    """The wire payload and its gzip, for a worker thread."""
    wire = stored_drawing_wire_payload(blob, checksum=checksum)
    return wire, gzip.compress(wire, compresslevel=DRAWING_GZIP_LEVEL, mtime=0)


async def serve_drawing(
    request: Request,
    turn_id: str,
    *,
    checksum_of: Callable[[], Awaitable[str | None]],
    drawing_of: Callable[[], Awaitable[TurnDrawingDetail | None]],
) -> Response:
    """The body the drawing routes share: the conditional answer, the decode,
    and the refusals. They differ only in *which* query says the caller may
    have the bytes - the participant check, the pin (R-PIN-06) or the gallery
    predicate (R-GAL-06) - and each passes its own, so none can borrow another's.
    """
    cache_headers = {
        # Reader-scoped bytes must never reach a shared cache, and a
        # browser's own copy is revalidated on every open: an erased or
        # unpinned drawing stops being shown at once rather than when a
        # lifetime runs out.
        "Cache-Control": "private, no-cache",
    }
    # Asked first, every time: the checksum query carries the same access
    # predicate as the drawing's, reads no blob, and names the bytes.
    checksum = await checksum_of()
    if checksum is None:
        raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
    validator = drawing_validator(checksum)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None and validator_matches(if_none_match, validator):
        # A copy that is still current: neither read nor decoded.
        return Response(status_code=304, headers={**cache_headers, "ETag": validator})
    cached = drawing_cache.get(_cache_key(checksum))
    if cached is not None:
        telemetry.drawing_cache_requests.inc(("hit",))
        wire, gzipped = cached
    else:
        telemetry.drawing_cache_requests.inc(("miss",))
        wire, gzipped, stored_checksum = await _decode_once(checksum, turn_id, drawing_of)
        validator = drawing_validator(stored_checksum)
    encoded = len(wire) >= GZIP_MINIMUM_BYTES and "gzip" in accepted_encodings(
        request.headers.get("accept-encoding")
    )
    headers = {**cache_headers, "ETag": validator}
    if encoded:
        # Already compressed, so the response middleware leaves it be.
        headers["Content-Encoding"] = "gzip"
        headers["Vary"] = "Accept-Encoding"
    return Response(
        content=gzipped if encoded else wire,
        media_type="application/octet-stream",
        headers=headers,
    )


async def _decode_once(
    checksum: str,
    turn_id: str,
    drawing_of: Callable[[], Awaitable[TurnDrawingDetail | None]],
) -> tuple[bytes, bytes, str]:
    """Read and decode a drawing the cache does not hold, once however many
    ask at the same moment.

    Only *bytes* are shared. A refusal is not: the fill runs against one
    caller's own query, and a drawing hidden between another caller's access
    check and this read is a 404 for that caller alone - a participant may
    still have it when the Gallery may not (R-GAL-09). Everyone else that was
    waiting reads the cache, and asks its own query again if the fill left
    nothing there.

    The fill is a task of its own, so the caller that started it going away -
    a shutdown, a timeout - does not cancel the read every other waiter is
    waiting on (#979 review).
    """
    key = _cache_key(checksum)
    fill = _fills.get(key)
    started_it = fill is None
    if fill is None:
        fill = asyncio.ensure_future(_fill_cache(key, turn_id, drawing_of))
        # Retrieved even when every waiter has gone, so a refusal inside the
        # fill is not reported as an exception nobody looked at.
        fill.add_done_callback(lambda task: task.cancelled() or task.exception())
        _fills[key] = fill
    # Watched rather than awaited: `await fill` hands this caller's
    # cancellation straight to the fill, because `Task.cancel` cancels the
    # future the task is waiting on - so one caller's disconnect would cancel
    # the decode every other waiter is waiting on, which is the thing this
    # single-flight exists to prevent (#979 fourth review). `asyncio.wait`
    # watches it from the outside; our own cancellation leaves it running.
    await asyncio.wait({fill})
    try:
        # The fill's own answer, not whatever the cache ended up holding: a
        # decode the cache declined - too large for it, or a checksum that
        # changed while it ran - is still this caller's drawing.
        return fill.result()
    except asyncio.CancelledError:
        # The fill was cancelled from outside. This caller was not, and still
        # wants its bytes - whether or not it was the one that started it.
        pass
    except Exception:
        if started_it:
            raise
    # Somebody else's refusal, or a fill that was cancelled, says nothing
    # about this caller's access - a participant may still have a drawing the
    # Gallery may not (R-GAL-09). Read what it left, and ask again if it left
    # nothing.
    cached = drawing_cache.get(key)
    if cached is not None:
        return cached[0], cached[1], checksum
    return await _fill_cache(key, turn_id, drawing_of, store=False)


async def _fill_cache(
    key: str,
    turn_id: str,
    drawing_of: Callable[[], Awaitable[TurnDrawingDetail | None]],
    *,
    store: bool = True,
) -> tuple[bytes, bytes, str]:
    """Read the blob, decode and gzip it off the loop, and hold the result."""
    try:
        drawing = await drawing_of()
        if drawing is None:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        try:
            wire, gzipped = await asyncio.to_thread(
                _decoded_drawing, drawing.payload, drawing.checksum_sha256 or None
            )
        except UnsupportedStoredDrawingError as error:
            # A build older than the row it is reading. Answer as though the
            # drawing is absent rather than claiming it is broken.
            logger.error("Cannot decode stored drawing %s: %s", turn_id, error)
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.") from error
        except CorruptStoredDrawingError as error:
            logger.error("Stored drawing %s failed its checksum", turn_id)
            raise Refusal(
                500, ErrorCode.DRAWING_UNREADABLE, "That drawing could not be read."
            ) from error
        # Keyed by the checksum these bytes were verified against, which is
        # the row's own - it may have changed since the question above.
        drawing_cache.put(_cache_key(drawing.checksum_sha256), wire, gzipped)
        return wire, gzipped, drawing.checksum_sha256
    finally:
        if store:
            _fills.pop(key, None)


def create_profile_router(
    user_repo: UserRepository,
    game_history_repo: GameHistoryRepository,
    *,
    is_online: Callable[[str], bool] = lambda user_id: False,
) -> APIRouter:
    """`is_online` is the presence registry's answer for an account id; the
    default, for a router built without one, says nobody is."""
    router = APIRouter(prefix="/api")

    def throttle(request: Request) -> None:
        if not profile_limiter.check(client_key(request)):
            raise Refusal(
                429,
                ErrorCode.TOO_MANY_REQUESTS,
                "Too many requests. Please wait and try again.",
            )

    @router.get("/users/{user_id}/stats")
    async def user_stats(user_id: str, request: Request):
        """Lifetime metrics for a player, alongside who they are.

        The account travels with the numbers because a profile opened by id is
        the one view that has no other way to learn the player's name - and
        because `get_stats` answers with a zeroed record for an id that does not
        exist, so the lookup is also what makes a 404 possible. It is the
        public shape (#469): the caller's own richer account is `/auth/me`.

        The numbers are lifetime, private-room games included, for anyone.
        That a stranger can subtract the games they are shown from
        `gamesPlayed` and learn that private games exist is accepted: a
        count says nothing about who, when or where, and scoping it would
        put a visibility dimension on the daily projection (R-HIST-20) for
        a number the owner decided is not sensitive.
        """
        throttle(request)
        user = await user_repo.get_by_id(user_id)
        if user is None:
            raise Refusal(404, ErrorCode.NO_SUCH_PLAYER, "No such player.")
        stats = await user_repo.get_stats(user_id)
        return {
            # Presence is keyed by the canonical account, which is what
            # `get_by_id` resolved a merged guest's id to.
            "user": public_user_payload(user, online=is_online(user.id)),
            "stats": stats_payload(stats),
        }

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

        Which games are on the page depends on who is asking (#469): one from
        a public room is there for anyone, one from a private room only for
        the players who were in it. The repository applies the rule; this
        only says who the caller is, and a visitor with no session is nobody.
        """
        throttle(request)
        # One extra row answers "is there another page?" without a second COUNT
        # query, and without the client inferring it from a full-looking page.
        games = await game_history_repo.get_user_games(
            user_id,
            limit=limit + 1,
            offset=offset,
            include_abandoned=include_abandoned,
            requesting_user_id=getattr(request.state, "user_id", None) or None,
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
            raise Refusal(404, ErrorCode.NO_SUCH_GAME, "No such game.")
        detail = await game_history_repo.get_game_detail(
            game_id, requesting_user_id=requesting_user_id
        )
        if detail is None:
            raise Refusal(404, ErrorCode.NO_SUCH_GAME, "No such game.")
        return game_detail_payload(detail)

    @router.get("/games/{game_id}/turns/{turn_id}/drawing")
    async def turn_drawing(game_id: str, turn_id: str, request: Request):
        """The drawing made during one turn, for the players who were there.

        Answered in the current wire format, so a client decodes a stored
        drawing with exactly the code it already uses for a live one.

        Conditional (#604): the browser is told to revalidate on every open
        (`no-cache`) and is answered `304` without a body while its copy is
        current, which is nearly always - a drawing never changes, it can
        only stop being available. The validator names the *served*
        representation: the stored checksum together with the wire version
        the decoders answer in, since a new wire version changes the bytes
        served without touching the bytes stored (R-HIST-18). It is weak,
        because the same bytes go out gzipped or not, and it is checked only
        after the same authorization and availability query as the drawing
        itself, so a tag a browser remembers cannot see past a lost
        permission or an erased drawing: those are 404 as before.
        """
        throttle(request)
        requesting_user_id = getattr(request.state, "user_id", None)
        if not requesting_user_id:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        return await serve_drawing(
            request,
            turn_id,
            checksum_of=lambda: game_history_repo.get_turn_drawing_checksum(
                game_id, turn_id, requesting_user_id=requesting_user_id
            ),
            drawing_of=lambda: game_history_repo.get_turn_drawing(
                game_id, turn_id, requesting_user_id=requesting_user_id
            ),
        )

    @router.get("/users/{user_id}/pins")
    async def user_pins(user_id: str, request: Request):
        """The player's **Pinned drawings**, in their order, for anyone signed in.

        Any session will do, a guest's included (R-PIN-06): the shelf is a
        deliberate widening of who may see a drawing, by the explicit act of
        the account that pinned it, and the one thing it keeps out is
        unauthenticated scraping. A visitor with no session gets the same
        404 an unknown player does, so the route never says which - and the
        client renders no shelf at all for a signed-out viewer, not an empty
        one. Each entry credits the drawer through the turn's frozen snapshot
        (#387) and carries no game id: a viewer who was not in the game has
        no page to open, and a private game could not be pinned to begin
        with (R-PIN-03).
        """
        throttle(request)
        viewer_id = getattr(request.state, "user_id", None)
        if not viewer_id:
            raise Refusal(404, ErrorCode.NO_SUCH_PLAYER, "No such player.")
        user = await user_repo.get_by_id(user_id)
        if user is None:
            raise Refusal(404, ErrorCode.NO_SUCH_PLAYER, "No such player.")
        pins = await game_history_repo.get_profile_pins(
            user.id, viewer_user_id=viewer_id
        )
        return {"pins": [pin_entry_payload(pin) for pin in pins]}

    @router.get("/users/{user_id}/pins/{turn_id}/drawing")
    async def pinned_drawing(user_id: str, turn_id: str, request: Request):
        """A pinned drawing's bytes, for anyone signed in (R-PIN-06).

        The one other door beside the participant route above, and its own
        query rather than an `OR` in that one: the join to the pins table is
        the authorization. Same conditional handling (R-HIST-24) and the same
        404 for every refusal - signed out, not pinned any more, erased, or a
        player that does not exist.
        """
        throttle(request)
        if not getattr(request.state, "user_id", None):
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        return await serve_drawing(
            request,
            turn_id,
            checksum_of=lambda: game_history_repo.get_pinned_drawing_checksum(
                user_id, turn_id
            ),
            drawing_of=lambda: game_history_repo.get_pinned_drawing(user_id, turn_id),
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
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        if emoji is not None and emoji not in OFFERED_REACTION_EMOJI_CODES:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        result = await game_history_repo.set_drawing_reaction(
            game_id, turn_id, requesting_user_id=requesting_user_id, emoji=emoji
        )
        if result is None:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
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

    @router.put("/me/pins")
    async def set_my_pins(body: PinsBody, request: Request):
        """Replace the signed-in player's pinned drawings with the list given.

        Pinning, unpinning and reordering are the same request: the body is
        the whole shelf in order, so the six-slot cap and the order fall out
        of the list itself and the client never has to shuffle positions.
        Which drawings may be on it (#440): any turn with a ready drawing from
        a **public** game the caller sat in - their own or another player's,
        credited to the drawer's frozen name. The repository applies those
        rules; every refusal is the same 404 (R-HIST-16), so the route never
        says which of stranger, guest, private game or erased drawing applied.
        A seventh pin is the one refusal that is not a 404: nothing was
        hidden from the caller, they are simply out of room.
        """
        throttle(request)
        requesting_user_id = getattr(request.state, "user_id", None)
        if not requesting_user_id:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        if len(body.turnIds) > PROFILE_PIN_SLOTS:
            raise Refusal(
                409,
                ErrorCode.PINNED_DRAWINGS_FULL,
                "Your pinned drawings are full.",
                params={"slots": PROFILE_PIN_SLOTS},
            )
        result = await game_history_repo.set_profile_pins(
            requesting_user_id=requesting_user_id, turn_ids=body.turnIds
        )
        if result is None:
            raise Refusal(404, ErrorCode.NO_SUCH_DRAWING, "No such drawing.")
        return pins_payload(result)

    return router

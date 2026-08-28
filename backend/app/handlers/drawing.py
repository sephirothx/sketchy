"""Socket.IO handlers for the drawing domain."""
from __future__ import annotations

from functools import partial

from app.drawing_rules import packet_allowed
from app.game import Phase
from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    parse_draw_payload,
    parse_sync_request_payload,
    parse_undo_payload,
)

async def draw(ctx: HandlerContext, sid, data, action_identity=None):
    try:
        payload = parse_draw_payload(data, action_identity)
    except PayloadError as error:
        return error.acknowledgement()
    packet = payload.packet
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return
    room, player = current
    if player.id != room.game.current_drawer or room.game.phase != Phase.DRAWING:
        return
    if not packet_allowed(
        packet.event, packet.payload, room.allowed_tools, room.color_mode
    ):
        # A stale or modified client drawing with a tool or color the host took
        # away. Nothing is recorded and nothing is rebroadcast, so the room
        # never sees it - but the sender already drew it locally, so resync it
        # onto server truth rather than leaving the two canvases apart.
        #
        # Only the frame that opens an action is answered. The points and the
        # end frame trailing a refused path are dropped in silence, the way the
        # discard flag drops them after an out-of-date generation: one refusal
        # is one sync, however many frames the client keeps sending.
        if packet.event == "draw_start":
            room.game.canvas.discarding_draw_sequence = True
        elif packet.event not in {"draw_shape", "draw_fill"}:
            return
        await ctx.game_flow._emit_canvas_sync(room, sid)
        return
    starts_action = packet.event in {
        "draw_start",
        "draw_shape",
        "draw_fill",
        "clear_canvas",
    }
    identity = payload.action_identity if starts_action else None
    generation, sequence = identity if identity else (None, None)
    if starts_action:
        if generation is None or sequence is None:
            return
        if generation != room.game.canvas.generation:
            if packet.event == "draw_start":
                room.game.canvas.discarding_draw_sequence = True
            await ctx.game_flow._emit_canvas_sync(room, sid)
            return
        if room.game.canvas.active_draw_sequence is not None:
            if (
                packet.event == "draw_start"
                and sequence == room.game.canvas.active_draw_sequence
            ):
                room.game.canvas.restart_active_path()
            else:
                expected_sequence = room.game.canvas.sequence + 1
                await ctx.game_flow._request_canvas_actions(
                    room,
                    sid,
                    expected_sequence,
                    sequence,
                )
                return
        if sequence <= room.game.canvas.sequence:
            if packet.event == "draw_start":
                room.game.canvas.discarding_draw_sequence = True
            commit = room.game.canvas.get_commit(sequence)
            if commit and commit[2] == "action":
                await ctx.game_flow._emit_canvas_commit(room, sequence, to=sid)
            else:
                await ctx.game_flow._emit_canvas_sync(room, sid)
            return
        expected_sequence = room.game.canvas.sequence + 1
        if sequence != expected_sequence:
            if packet.event == "draw_start":
                room.game.canvas.discarding_draw_sequence = True
            await ctx.game_flow._request_canvas_actions(
                room,
                sid,
                expected_sequence,
                sequence,
            )
            return
    elif room.game.canvas.discarding_draw_sequence:
        if packet.event == "draw_end":
            room.game.canvas.discarding_draw_sequence = False
        return
    if packet.event == "clear_canvas":
        if not room.game.canvas.clear_canvas_stroke():
            return
        room.game.canvas.commit_sequence(sequence)
        await _rebroadcast(ctx, room, sid, payload.wire_data, committed=sequence)
        return
    if not room.game.canvas.record_stroke(packet.event, packet.payload):
        return
    if packet.event == "draw_start":
        room.game.canvas.discarding_draw_sequence = False
        room.game.canvas.active_draw_sequence = sequence
    # The action is committed before the frame goes out, so the frame can carry
    # the commit that closes it. Nothing observable is reordered: both used to
    # be decided inside this call, and the state a rebroadcast describes is now
    # settled before anyone is told about it.
    committed = None
    if packet.event == "draw_end":
        active_sequence = room.game.canvas.active_draw_sequence
        if active_sequence is not None:
            room.game.canvas.active_draw_sequence = None
            room.game.canvas.commit_sequence(active_sequence)
            committed = active_sequence
    elif packet.event in {"draw_shape", "draw_fill"}:
        room.game.canvas.commit_sequence(sequence)
        committed = sequence
    await _rebroadcast(ctx, room, sid, payload.wire_data, committed=committed)


async def _rebroadcast(
    ctx: HandlerContext,
    room,
    drawer_sid: str,
    wire_data: int | bytes,
    *,
    committed: int | None,
) -> None:
    """Push the drawer's frame to the rest of the room, commit included.

    A committed action used to cost the room a second event: the frame, then a
    `canvas_commit` carrying four integers the viewer needs only to advance its
    revision bookkeeping. Viewers now read those off the frame that committed
    the action, which also makes it impossible to see a commit for a frame that
    has not arrived.

    The drawer is skipped by the rebroadcast and so still needs the event of
    its own: their pending-mutation window is what the commit resolves, and
    they never receive their own frame back.
    """
    commit = (
        ctx.game_flow.canvas_commit_payload(room, committed)
        if committed is not None
        else None
    )
    await ctx.sio.emit(
        "draw",
        (wire_data, commit) if commit is not None else wire_data,
        room=room.id,
        skip_sid=drawer_sid,
    )
    if committed is not None:
        await ctx.game_flow._emit_canvas_commit(room, committed, to=drawer_sid)


async def undo_stroke(ctx: HandlerContext, sid, data=None):
    try:
        payload = parse_undo_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return
    room, player = current
    if player.id != room.game.current_drawer:
        return {"ok": False, "error": "Only the drawer can undo"}
    generation = payload.generation
    sequence = payload.sequence
    if generation != room.game.canvas.generation:
        await ctx.game_flow._emit_canvas_sync(room, sid)
        return {"ok": False, "error": "Canvas generation is out of date"}
    if sequence <= room.game.canvas.sequence:
        commit = room.game.canvas.get_commit(sequence)
        if commit and commit[2] == "undo":
            await ctx.game_flow._emit_canvas_commit(room, sequence, to=sid)
            return {"ok": True}
        return {"ok": False, "error": "Sequence already committed"}
    expected_sequence = room.game.canvas.sequence + 1
    if sequence != expected_sequence:
        await ctx.game_flow._request_canvas_actions(
            room,
            sid,
            expected_sequence,
            sequence,
        )
        return {"ok": False, "error": "Drawing actions are out of sequence"}
    if payload.revision != room.game.canvas.revision or payload.history_hash != room.game.canvas.hash:
        await ctx.game_flow._emit_canvas_sync(room, sid)
        return {"ok": False, "error": "Canvas history is out of sync"}
    if room.game.canvas.undo_last_stroke():
        room.game.canvas.commit_sequence(sequence, "undo")
        await ctx.game_flow._emit_canvas_commit(room, sequence)
        return {"ok": True}
    return {"ok": False, "error": "Nothing to undo"}

# ------------------------------------------------------------------
# Guessing / chat
# ------------------------------------------------------------------


async def request_sync_strokes(ctx: HandlerContext, sid, data=None):
    try:
        holds = parse_sync_request_payload(data)
    except PayloadError as error:
        return error.acknowledgement()
    current = await ctx.game_flow.require_current_player(sid)
    if current and current[0].game:
        room, _ = current
        await ctx.game_flow._emit_canvas_sync(room, sid, holds)


def register(ctx: HandlerContext) -> None:
    ctx.on("draw", handler=partial(draw, ctx))
    ctx.on("undo_stroke", handler=partial(undo_stroke, ctx))
    ctx.on("request_sync_strokes", handler=partial(request_sync_strokes, ctx))

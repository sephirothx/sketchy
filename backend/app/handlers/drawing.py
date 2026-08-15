"""Socket.IO handlers for the drawing domain."""
from __future__ import annotations

from functools import partial

from app.game import Phase
from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    parse_draw_payload,
    parse_empty_payload,
    parse_undo_payload,
)

async def draw(ctx: HandlerContext, sid, data, action_identity=None):
    try:
        payload = parse_draw_payload(data, action_identity)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    packet = payload.packet
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return
    room, player = current
    if player.id != room.game.current_drawer or room.game.phase != Phase.DRAWING:
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
        await ctx.sio.emit(
            "draw",
            payload.wire_data,
            room=room.id,
            skip_sid=sid,
        )
        room.game.canvas.commit_sequence(sequence)
        await ctx.game_flow._emit_canvas_commit(room, sequence)
        return
    if not room.game.canvas.record_stroke(packet.event, packet.payload):
        return
    if packet.event == "draw_start":
        room.game.canvas.discarding_draw_sequence = False
        room.game.canvas.active_draw_sequence = sequence
    await ctx.sio.emit(
        "draw",
        payload.wire_data,
        room=room.id,
        skip_sid=sid,
    )
    if packet.event == "draw_end":
        active_sequence = room.game.canvas.active_draw_sequence
        if active_sequence is None:
            return
        room.game.canvas.active_draw_sequence = None
        room.game.canvas.commit_sequence(active_sequence)
        await ctx.game_flow._emit_canvas_commit(room, active_sequence)
    elif packet.event in {"draw_shape", "draw_fill"}:
        room.game.canvas.commit_sequence(sequence)
        await ctx.game_flow._emit_canvas_commit(room, sequence)


async def undo_stroke(ctx: HandlerContext, sid, data=None):
    try:
        payload = parse_undo_payload(data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
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
        parse_empty_payload(data)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if current and current[0].game:
        room, _ = current
        await ctx.game_flow._emit_canvas_sync(room, sid)


def register(ctx: HandlerContext) -> None:
    ctx.sio.on("draw", handler=partial(draw, ctx))
    ctx.sio.on("undo_stroke", handler=partial(undo_stroke, ctx))
    ctx.sio.on("request_sync_strokes", handler=partial(request_sync_strokes, ctx))

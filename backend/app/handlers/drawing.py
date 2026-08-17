"""Socket.IO handlers for the drawing domain."""
from __future__ import annotations

import logging
from functools import partial

from app.game import Phase
from app.handlers.context import HandlerContext
from app.handlers.payloads import (
    PayloadError,
    parse_checkpoint_payload,
    parse_draw_payload,
    parse_empty_payload,
    parse_undo_payload,
)

logger = logging.getLogger("sketchy.canvas")


def _log_canvas(room, event: str, extra: str = "") -> None:
    canvas = room.game.canvas
    suffix = f" {extra}" if extra else ""
    logger.info(
        "canvas %s room=%s gen=%s seq=%s %s%s",
        event,
        room.code,
        canvas.generation,
        canvas.sequence,
        canvas.debug_summary(),
        suffix,
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
            elif commit and commit[2].startswith("reject:"):
                await ctx.game_flow._emit_canvas_rejected(
                    room, sequence, commit[2].split(":", 1)[1], to=sid
                )
            elif commit and commit[2] == "checkpoint":
                await ctx.game_flow._emit_canvas_sync(room, sid)
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
            reason = room.game.canvas.reject_reason or "invalid"
            if reason != "invalid":
                room.game.canvas.commit_sequence(sequence, f"reject:{reason}")
                _log_canvas(room, "reject", extra=f"reason={reason} event=clear")
                await ctx.game_flow._emit_canvas_rejected(room, sequence, reason, to=sid)
                await ctx.game_flow._emit_canvas_sync(room, sid)
            return
        await ctx.sio.emit(
            "draw",
            payload.wire_data,
            room=room.id,
            skip_sid=sid,
        )
        room.game.canvas.commit_sequence(sequence)
        _log_canvas(room, "window", extra="event=clear")
        await ctx.game_flow._emit_canvas_commit(room, sequence)
        return
    if not room.game.canvas.record_stroke(packet.event, packet.payload):
        reason = room.game.canvas.reject_reason or "invalid"
        if starts_action and reason != "invalid":
            if packet.event == "draw_start":
                room.game.canvas.discarding_draw_sequence = True
            room.game.canvas.commit_sequence(sequence, f"reject:{reason}")
            _log_canvas(room, "reject", extra=f"reason={reason} event={packet.event}")
            await ctx.game_flow._emit_canvas_rejected(room, sequence, reason, to=sid)
            await ctx.game_flow._emit_canvas_sync(room, sid)
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
        _log_canvas(room, "window", extra="event=stroke")
        await ctx.game_flow._emit_canvas_commit(room, active_sequence)
    elif packet.event in {"draw_shape", "draw_fill"}:
        room.game.canvas.commit_sequence(sequence)
        _log_canvas(room, "window", extra=f"event={packet.event}")
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
        _log_canvas(room, "window", extra="event=undo")
        await ctx.game_flow._emit_canvas_commit(room, sequence)
        return {"ok": True}
    return {"ok": False, "error": "Nothing to undo"}


async def canvas_checkpoint(ctx: HandlerContext, sid, data, identity=None):
    try:
        payload = parse_checkpoint_payload(data, identity)
    except PayloadError as error:
        return ctx.game_flow.validation_error(error)
    current = await ctx.game_flow.require_current_player(sid)
    if not current or not current[0].game:
        return
    room, player = current
    if player.id != room.game.current_drawer or room.game.phase != Phase.DRAWING:
        return
    canvas = room.game.canvas
    if payload.generation != canvas.generation:
        await ctx.game_flow._emit_canvas_sync(room, sid)
        return
    if canvas.active_draw_sequence is not None:
        await ctx.game_flow._request_canvas_actions(
            room,
            sid,
            canvas.sequence + 1,
            payload.sequence,
        )
        return
    if payload.sequence <= canvas.sequence:
        commit = canvas.get_commit(payload.sequence)
        if commit and commit[2] == "checkpoint":
            await ctx.game_flow._emit_canvas_sync(room, sid)
        elif commit and commit[2].startswith("reject:"):
            await ctx.game_flow._emit_canvas_rejected(
                room, payload.sequence, commit[2].split(":", 1)[1], to=sid
            )
        else:
            await ctx.game_flow._emit_canvas_sync(room, sid)
        return
    if payload.sequence != canvas.sequence + 1:
        await ctx.game_flow._request_canvas_actions(
            room,
            sid,
            canvas.sequence + 1,
            payload.sequence,
        )
        return
    before = canvas.debug_summary()
    reason = canvas.apply_checkpoint(
        payload.png, payload.folded_count, payload.prefix_hash
    )
    if reason:
        canvas.commit_sequence(payload.sequence, f"reject:{reason}")
        logger.info(
            "canvas compact-reject room=%s gen=%s seq=%s reason=%s folded=%s png=%sB before=[%s]",
            room.code,
            canvas.generation,
            canvas.sequence,
            reason,
            payload.folded_count,
            len(payload.png),
            before,
        )
        await ctx.game_flow._emit_canvas_rejected(room, payload.sequence, reason, to=sid)
        await ctx.game_flow._emit_canvas_sync(room, sid)
        return
    canvas.commit_sequence(payload.sequence, "checkpoint")
    logger.info(
        "canvas compact room=%s gen=%s seq=%s folded=%s png=%sB before=[%s] after=[%s]",
        room.code,
        canvas.generation,
        canvas.sequence,
        payload.folded_count,
        len(payload.png),
        before,
        canvas.debug_summary(),
    )
    await ctx.game_flow._emit_canvas_checkpoint(
        room,
        payload.sequence,
        payload.folded_count,
        payload.png,
    )


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
    ctx.sio.on("canvas_checkpoint", handler=partial(canvas_checkpoint, ctx))
    ctx.sio.on("request_sync_strokes", handler=partial(request_sync_strokes, ctx))

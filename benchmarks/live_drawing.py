#!/usr/bin/env python3
"""Measure what live drawing actually costs on the wire.

Socket.IO totals include Engine.IO packet markers and, for data-bearing binary
actions, the standard binary-placeholder envelope. WebSocket framing is
intentionally excluded.

Two views:

- Per action, the legacy all-JSON encoding against the #203 hybrid protocol.
  This is the historical record for that change.
- A sustained-drawing model, which is the number that matters for capacity.
  A drawer emits on a fixed timer while the pen is down and the server
  rebroadcasts every frame to everyone else, so room egress is the per-frame
  cost multiplied by the flush rate and again by the audience.

Usage:
  backend/.venv/bin/python benchmarks/live_drawing.py
  backend/.venv/bin/python benchmarks/live_drawing.py --flush-interval-ms 80
  backend/.venv/bin/python benchmarks/live_drawing.py --json-output out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.live_drawing import encode_live_drawing  # noqa: E402

# What the drawer's canvas actually does today, so the model is not invented:
# a point is queued on every pointermove (useCanvasPointerInput.ts) and the
# queue is flushed on a fixed timer. A modern pointer reports at roughly
# 120 Hz; the flush interval is the production constant under test.
DEFAULT_POINTER_HZ = 120
DEFAULT_FLUSH_INTERVAL_MS = 40
DEFAULT_ROOM_SIZE = 16

# Actions that open a semantic mutation carry [generation, sequence] alongside
# the frame. Only these four; path points and the end frame carry none.
IDENTITY_BEARING_EVENTS = frozenset(
    {"draw_start", "draw_shape", "draw_fill", "clear_canvas"}
)


def json_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def legacy_socketio_bytes(event: str, payload: dict) -> int:
    return len(b"42") + len(json_bytes([event, payload]))


def optimized_socketio_bytes(
    payload: bytes | int,
    identity: tuple[int, int] | None = None,
) -> int:
    """Bytes one `draw` emission puts on the wire, identity included.

    The identity argument is not decoration: an action-opening frame really
    does travel as `["draw", <frame>, [generation, sequence]]`, and leaving it
    out of the model understates every opening action by the length of that
    array. A benchmark that flatters the current protocol cannot show whether
    a change to it helped.
    """
    envelope: list = ["draw"]
    if isinstance(payload, int):
        envelope.append(payload)
        if identity is not None:
            envelope.append(list(identity))
        return len(b"42") + len(json_bytes(envelope))
    envelope.append({"_placeholder": True, "num": 0})
    if identity is not None:
        envelope.append(list(identity))
    envelope_bytes = len(b"451-") + len(json_bytes(envelope))
    attachment_bytes = 1 + len(payload)
    return envelope_bytes + attachment_bytes


def current_action_bytes(event: str, payload: dict, identity=(1, 1)) -> int:
    """Cost of one action under the protocol as it stands today."""
    return optimized_socketio_bytes(
        encode_live_drawing(event, payload),
        identity if event in IDENTITY_BEARING_EVENTS else None,
    )


def reduction(before: int, after: int) -> str:
    if not before:
        return "     -"
    return f"{(1 - after / before) * 100:6.1f}%"


def _sample_points(count: int) -> list[dict]:
    return [
        {"x": 0.1 + index / 800, "y": 0.2 + index / 600}
        for index in range(count)
    ]


def per_action_table() -> list[dict]:
    """Legacy JSON against the hybrid protocol, per action."""
    actions = [
        ("path start", "draw_start",
         {"x": 0.12375, "y": 0.45625, "color": "#aabbcc", "width": 6}),
        ("1 point", "draw_move", {"points": _sample_points(1)}),
        ("6 points", "draw_move", {"points": _sample_points(6)}),
        ("40 points", "draw_move", {"points": _sample_points(40)}),
        ("path end", "draw_end", {}),
        ("shape", "draw_shape",
         {"shape": "rectangle", "from": {"x": 0.1, "y": 0.2},
          "to": {"x": 0.8, "y": 0.9}, "color": "#123456", "width": 8}),
        ("fill", "draw_fill", {"x": 0.25, "y": 0.75, "color": "#fedcba"}),
        ("clear", "clear_canvas", {}),
    ]
    rows = []
    for label, event, payload in actions:
        rows.append({
            "action": label,
            "event": event,
            "legacy_bytes": legacy_socketio_bytes(event, payload),
            "current_bytes": current_action_bytes(event, payload),
        })
    return rows


def stroke_session(
    *,
    pointer_hz: int,
    flush_interval_ms: int,
    room_size: int,
    seconds: float = 1.0,
) -> dict:
    """Model one drawer holding the pen down for `seconds`.

    Reported both as what the drawer sends and as what the server pushes out,
    because the rebroadcast is where the cost really lives: one drawer frame
    becomes room_size - 1 outbound frames.
    """
    frames_per_second = 1000 / flush_interval_ms
    points_per_frame = max(1, round(pointer_hz * flush_interval_ms / 1000))
    frame_bytes = current_action_bytes(
        "draw_move", {"points": _sample_points(points_per_frame)}
    )
    frames = frames_per_second * seconds
    inbound = frame_bytes * frames
    audience = max(0, room_size - 1)
    return {
        "pointer_hz": pointer_hz,
        "flush_interval_ms": flush_interval_ms,
        "room_size": room_size,
        "seconds": seconds,
        "points_per_frame": points_per_frame,
        "frames_per_second": round(frames_per_second, 2),
        "bytes_per_frame": frame_bytes,
        "inbound_bytes_per_second": round(inbound / seconds),
        "egress_bytes_per_second": round(inbound * audience / seconds),
    }


def whole_stroke(points: int = 120, identity=(1, 1)) -> dict:
    """A complete 120-point stroke: start, coalesced points, end."""
    sampled = _sample_points(points)
    batch = 6
    legacy = (
        legacy_socketio_bytes(
            "draw_start", {"x": 0.1, "y": 0.2, "color": "#000000", "width": 6}
        )
        + sum(
            legacy_socketio_bytes("draw_move", {"points": sampled[i:i + batch]})
            for i in range(0, len(sampled), batch)
        )
        + legacy_socketio_bytes("draw_end", {})
    )
    current = (
        current_action_bytes(
            "draw_start",
            {"x": 0.1, "y": 0.2, "color": "#000000", "width": 6},
            identity,
        )
        + sum(
            current_action_bytes("draw_move", {"points": sampled[i:i + batch]})
            for i in range(0, len(sampled), batch)
        )
        + current_action_bytes("draw_end", {})
    )
    return {"points": points, "legacy_bytes": legacy, "current_bytes": current}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pointer-hz", type=int, default=DEFAULT_POINTER_HZ)
    parser.add_argument(
        "--flush-interval-ms", type=int, default=DEFAULT_FLUSH_INTERVAL_MS
    )
    parser.add_argument("--room-size", type=int, default=DEFAULT_ROOM_SIZE)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    rows = per_action_table()
    stroke = whole_stroke()
    session = stroke_session(
        pointer_hz=args.pointer_hz,
        flush_interval_ms=args.flush_interval_ms,
        room_size=args.room_size,
    )

    print("Live drawing Socket.IO payload benchmark")
    print("Action           JSON        Current    Reduction")
    print("-" * 52)
    for row in rows:
        print(
            f"{row['action']:<12} {row['legacy_bytes']:>8,} B "
            f"{row['current_bytes']:>10,} B "
            f"{reduction(row['legacy_bytes'], row['current_bytes']):>12}"
        )
    print("-" * 52)
    print(
        f"{stroke['points']}-point stroke {stroke['legacy_bytes']:>5,} B "
        f"{stroke['current_bytes']:>10,} B "
        f"{reduction(stroke['legacy_bytes'], stroke['current_bytes']):>12}"
    )

    print()
    print(
        f"Sustained drawing - {session['pointer_hz']} Hz pointer, "
        f"{session['flush_interval_ms']} ms flush, "
        f"{session['room_size']}-player room"
    )
    print("-" * 52)
    print(f"  points per frame        {session['points_per_frame']:>10,}")
    print(f"  frames per second       {session['frames_per_second']:>10,}")
    print(f"  bytes per frame         {session['bytes_per_frame']:>10,} B")
    print(f"  drawer sends            {session['inbound_bytes_per_second']:>10,} B/s")
    print(f"  server pushes out       {session['egress_bytes_per_second']:>10,} B/s")

    if args.json_output:
        args.json_output.write_text(
            json.dumps(
                {"actions": rows, "stroke": stroke, "session": session},
                indent=2,
            )
            + "\n"
        )
        print(f"\nWrote JSON results to {args.json_output}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""What a separate `canvas_commit` event costs a viewer (#418).

Every committed drawing action produces two room-wide emissions today: the
rebroadcast of the drawer's frame, and a `canvas_commit` carrying four small
integers the viewer uses only for its revision bookkeeping. #418 proposes
folding those four integers into the frame that commits the action, leaving the
drawer - who never receives their own rebroadcast - with a dedicated commit.

The uncompressed arithmetic makes that look obvious: a whole Socket.IO envelope
removed per action. But the deployment negotiates permessage-deflate with
context takeover, and consecutive commits differ only in their numbers, so a
warm compressor has seen nearly all of the next one. What is actually being
removed is one *message boundary* - about five bytes of `Z_SYNC_FLUSH` - plus
whatever the numbers themselves cost.

Measured over one viewer's downlink for a turn of drawing, since that is the
stream a viewer's compressor actually sees.

Usage:
  backend/.venv/bin/python benchmarks/canvas_commit.py
  backend/.venv/bin/python benchmarks/canvas_commit.py --players 16 --strokes 30
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import zlib

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.live_drawing import MAX_BASE64_FRAME_BYTES, encode_live_drawing

FLUSH_INTERVAL_MS = 40
POINTER_HZ = 120


def json_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def draw_messages(payload: bytes, commit: list[int] | None = None) -> list[bytes]:
    """The WebSocket messages one rebroadcast `draw` frame becomes.

    `commit` is #418's trailing argument: present only on the frame that
    commits an action, absent on every point frame.
    """
    if isinstance(payload, int):
        # `draw_end` and `clear_canvas` travel as a bare integer control, which
        # is cheaper than any binary envelope - and is also the shape #418
        # grows most, proportionally.
        envelope = ["draw", payload]
        if commit is not None:
            envelope.append(commit)
        return [b"42" + json_bytes(envelope)]
    if len(payload) <= MAX_BASE64_FRAME_BYTES:
        envelope = ["draw", base64.b64encode(payload).decode()]
        if commit is not None:
            envelope.append(commit)
        return [b"42" + json_bytes(envelope)]
    envelope = ["draw", {"_placeholder": True, "num": 0}]
    if commit is not None:
        envelope.append(commit)
    return [b"451-" + json_bytes(envelope), payload]


def commit_message(commit: list[int]) -> bytes:
    return b"42" + json_bytes(["canvas_commit", commit])


def deflated_stream_bytes(messages: list[bytes]) -> int:
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    return sum(
        len(compressor.compress(message) + compressor.flush(zlib.Z_SYNC_FLUSH))
        for message in messages
    )


def points(count: int, offset: int) -> list[dict]:
    return [
        {"x": 0.1 + (offset + index) / 800, "y": 0.2 + (offset + index) / 600}
        for index in range(count)
    ]


def turn_stream(strokes: int, frames_per_stroke: int, *, inline_commit: bool):
    """One viewer's downlink for a turn: strokes, their points, their commits."""
    points_per_frame = max(1, round(POINTER_HZ * FLUSH_INTERVAL_MS / 1000))
    messages: list[bytes] = []
    commits = 0
    generation, revision = 3, 41
    for stroke in range(strokes):
        sequence = stroke + 1
        start = encode_live_drawing(
            "draw_start",
            {"x": 0.1 + stroke / 90, "y": 0.2, "color": "#1b1b1b", "width": 6},
        )
        messages.extend(draw_messages(start))
        for frame in range(frames_per_stroke):
            move = encode_live_drawing(
                "draw_move",
                {"points": points(points_per_frame, stroke * 97 + frame * 5)},
            )
            messages.extend(draw_messages(move))
        commit = [generation, sequence, revision + sequence, 2_147_000_000 + sequence * 7919]
        end = encode_live_drawing("draw_end", {})
        if inline_commit:
            messages.extend(draw_messages(end, commit))
        else:
            messages.extend(draw_messages(end))
            messages.append(commit_message(commit))
        commits += 1
    return messages, commits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", type=int, default=16)
    parser.add_argument("--strokes", type=int, default=30,
                        help="committed actions in one turn")
    parser.add_argument("--frames-per-stroke", type=int, default=12,
                        help="point frames per stroke (12 = a ~half-second line)")
    args = parser.parse_args()

    today, commits = turn_stream(args.strokes, args.frames_per_stroke, inline_commit=False)
    inlined, _ = turn_stream(args.strokes, args.frames_per_stroke, inline_commit=True)

    today_raw = sum(len(m) for m in today)
    inlined_raw = sum(len(m) for m in inlined)
    today_wire = deflated_stream_bytes(today)
    inlined_wire = deflated_stream_bytes(inlined)

    # The commit message on its own, measured where it actually lives: warm
    # context, one commit every (frames_per_stroke + 2) messages.
    per_commit_raw = (today_raw - inlined_raw) / commits
    per_commit_wire = (today_wire - inlined_wire) / commits

    audience = max(0, args.players - 1)
    print(f"canvas_commit benchmark - {args.players} players, {args.strokes} committed "
          f"actions, {args.frames_per_stroke} point frames each\n")
    print(f"{'one viewer, a turn of drawing':<38}{'raw':>10}{'wire':>11}")
    print("-" * 59)
    print(f"{'  today (frame + canvas_commit)':<38}{today_raw:>9,}B{today_wire:>10,}B")
    print(f"{'  commit inlined on the frame':<38}{inlined_raw:>9,}B{inlined_wire:>10,}B")
    print(f"{'  saved':<38}{today_raw - inlined_raw:>9,}B{today_wire - inlined_wire:>10,}B")
    print(f"{'  saved, %':<38}{(1 - inlined_raw / today_raw) * 100:>9.1f}%"
          f"{(1 - inlined_wire / today_wire) * 100:>10.1f}%")
    print(f"\nper committed action, one viewer : "
          f"{per_commit_raw:5.1f} B raw, {per_commit_wire:5.1f} B on the wire")
    print(f"per committed action, {audience:2d} viewers : "
          f"{per_commit_raw * audience:5.0f} B raw, "
          f"{per_commit_wire * audience:5.0f} B on the wire")
    print(f"\nat 1 action/s that is {per_commit_wire * audience:,.0f} B/s of room egress; "
          f"at 2/s, {per_commit_wire * audience * 2:,.0f} B/s")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compare legacy JSON drawing events with the #203 binary wire protocol.

Socket.IO totals include Engine.IO text/binary packet markers and the standard
binary-placeholder envelope. WebSocket framing is intentionally excluded.

Usage:
  backend/.venv/bin/python benchmarks/live_drawing.py
"""
from __future__ import annotations

import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.live_drawing import encode_live_drawing  # noqa: E402


def json_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def legacy_socketio_bytes(event: str, payload: dict) -> int:
    return len(b"42") + len(json_bytes([event, payload]))


def binary_socketio_bytes(frame: bytes) -> int:
    placeholder = ["draw", {"_placeholder": True, "num": 0}]
    envelope_bytes = len(b"451-") + len(json_bytes(placeholder))
    attachment_bytes = 1 + len(frame)
    return envelope_bytes + attachment_bytes


def reduction(before: int, after: int) -> str:
    return f"{(1 - after / before) * 100:6.1f}%"


def main() -> None:
    actions = [
        (
            "path start",
            "draw_start",
            {"x": 0.12375, "y": 0.45625, "color": "#aabbcc", "width": 6},
        ),
        (
            "1 point",
            "draw_move",
            {"points": [{"x": 0.125, "y": 0.46}]},
        ),
        (
            "6 points",
            "draw_move",
            {
                "points": [
                    {"x": 0.125 + index / 800, "y": 0.46 + index / 600}
                    for index in range(6)
                ]
            },
        ),
        (
            "40 points",
            "draw_move",
            {
                "points": [
                    {"x": 0.125 + index / 800, "y": 0.46 + index / 600}
                    for index in range(40)
                ]
            },
        ),
        ("path end", "draw_end", {}),
        (
            "shape",
            "draw_shape",
            {
                "shape": "rectangle",
                "from": {"x": 0.1, "y": 0.2},
                "to": {"x": 0.8, "y": 0.9},
                "color": "#123456",
                "width": 8,
            },
        ),
        (
            "fill",
            "draw_fill",
            {"x": 0.25, "y": 0.75, "color": "#fedcba"},
        ),
        ("clear", "clear_canvas", {}),
    ]

    print("Live drawing Socket.IO payload benchmark (#203)")
    print("Action           JSON       Binary     Reduction")
    print("-" * 50)
    for label, event, payload in actions:
        before = legacy_socketio_bytes(event, payload)
        after = binary_socketio_bytes(encode_live_drawing(event, payload))
        print(f"{label:<12} {before:>8,} B {after:>10,} B {reduction(before, after):>12}")

    points = [
        {"x": 0.1 + index / 800, "y": 0.2 + index / 600}
        for index in range(120)
    ]
    legacy_total = (
        legacy_socketio_bytes(
            "draw_start",
            {"x": 0.1, "y": 0.2, "color": "#000000", "width": 6},
        )
        + sum(
            legacy_socketio_bytes("draw_move", {"points": points[index:index + 6]})
            for index in range(0, len(points), 6)
        )
        + legacy_socketio_bytes("draw_end", {})
    )
    binary_total = (
        binary_socketio_bytes(
            encode_live_drawing(
                "draw_start",
                {"x": 0.1, "y": 0.2, "color": "#000000", "width": 6},
            )
        )
        + sum(
            binary_socketio_bytes(
                encode_live_drawing(
                    "draw_move",
                    {"points": points[index:index + 6]},
                )
            )
            for index in range(0, len(points), 6)
        )
        + binary_socketio_bytes(encode_live_drawing("draw_end", {}))
    )
    print("-" * 50)
    print(
        f"120-point stroke {legacy_total:>5,} B {binary_total:>10,} B "
        f"{reduction(legacy_total, binary_total):>12}"
    )


if __name__ == "__main__":
    main()

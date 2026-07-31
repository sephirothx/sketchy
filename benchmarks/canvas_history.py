#!/usr/bin/env python3
"""Compare #197 semantic JSON history with the compact #198 representation.

Usage:
  backend/.venv/bin/python benchmarks/canvas_history.py
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
import json
import os
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.canvas_history import (  # noqa: E402
    ClearAction,
    FillAction,
    PackedCanvasHistory,
    PathAction,
    ShapeAction,
    color_to_hex,
    encode_canvas_history,
)


def deep_size(value, seen: set[int] | None = None) -> int:
    """Approximate recursively owned Python heap size without double-counting."""
    seen = seen or set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        return size + sum(
            deep_size(key, seen) + deep_size(item, seen)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return size + sum(deep_size(item, seen) for item in value)
    if is_dataclass(value):
        return size + sum(deep_size(getattr(value, field.name), seen) for field in fields(value))
    return size


def make_actions(path_count: int, points_per_path: int) -> list:
    actions = []
    for path_index in range(path_count):
        points = [
            (
                ((path_index * 17 + point_index * 3) % 800) / 800,
                ((path_index * 11 + point_index * 5) % 600) / 600,
            )
            for point_index in range(points_per_path)
        ]
        actions.append(
            PathAction(
                points=points,
                color=(path_index * 977) & 0xFFFFFF,
                width=path_index % 12 + 1,
            )
        )
    for index in range(max(1, path_count // 8)):
        actions.append(
            ShapeAction(
                shape=("rectangle", "ellipse", "triangle")[index % 3],
                start=(index / 100, index / 120),
                end=(0.8, 0.9),
                color=(index * 123_457) & 0xFFFFFF,
                width=4,
            )
        )
        actions.append(
            FillAction(
                x=(index * 37) % 800,
                y=(index * 29) % 600,
                color=(index * 654_319) & 0xFFFFFF,
            )
        )
    actions.append(ClearAction())
    return actions


def legacy_history(actions: list) -> dict:
    strokes = []
    for action in actions:
        if isinstance(action, PathAction):
            strokes.append(
                {
                    "event": "draw_path",
                    "payload": {
                        "points": [{"x": x, "y": y} for x, y in action.points],
                        "color": color_to_hex(action.color),
                        "width": action.width,
                    },
                }
            )
        elif isinstance(action, ShapeAction):
            strokes.append(
                {
                    "event": "draw_shape",
                    "payload": {
                        "shape": action.shape,
                        "from": {"x": action.start[0], "y": action.start[1]},
                        "to": {"x": action.end[0], "y": action.end[1]},
                        "color": color_to_hex(action.color),
                        "width": action.width,
                    },
                }
            )
        elif isinstance(action, FillAction):
            strokes.append(
                {
                    "event": "draw_fill",
                    "payload": {
                        "x": action.x / 800,
                        "y": action.y / 600,
                        "color": color_to_hex(action.color),
                    },
                }
            )
        else:
            strokes.append({"event": "clear_canvas", "payload": {}})
    return {"strokes": strokes}


def packed_history(actions: list) -> PackedCanvasHistory:
    history = PackedCanvasHistory()
    for action in actions:
        if isinstance(action, PathAction):
            history.append_path(
                action.points,
                color=action.color,
                width=action.width,
            )
        elif isinstance(action, ShapeAction):
            history.append_shape(
                shape=action.shape,
                start=action.start,
                end=action.end,
                color=action.color,
                width=action.width,
            )
        elif isinstance(action, FillAction):
            history.append_fill(x=action.x, y=action.y, color=action.color)
        else:
            history.append_clear()
    return history


def encoded_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def serialization_ms(value, iterations: int = 250) -> float:
    started = time.perf_counter()
    for _ in range(iterations):
        encoded_bytes(value)
    return (time.perf_counter() - started) * 1000 / iterations


def report(name: str, actions: list) -> None:
    legacy = legacy_history(actions)
    compact = encode_canvas_history(actions)
    legacy_bytes = len(encoded_bytes(legacy))
    compact_bytes = len(encoded_bytes(compact))
    binary_bytes = len(packed_history(actions).binary_payload())
    legacy_memory = deep_size(legacy)
    semantic_memory = deep_size(actions)
    packed_memory = deep_size(packed_history(actions))
    print(f"\n{name} ({len(actions)} actions)")
    print(
        f"  serialized: {legacy_bytes:>9,} -> {compact_bytes:>9,} bytes "
        f"({(1 - compact_bytes / legacy_bytes) * 100:5.1f}% smaller)"
    )
    print(
        f"  binary sync: {compact_bytes:>9,} -> {binary_bytes:>9,} bytes "
        f"({(1 - binary_bytes / compact_bytes) * 100:5.1f}% smaller than compact JSON)"
    )
    print(
        f"  room memory: {legacy_memory:>9,} -> {semantic_memory:>9,} -> "
        f"{packed_memory:>9,} bytes "
        f"({(1 - packed_memory / legacy_memory) * 100:5.1f}% smaller than legacy; "
        f"{(1 - packed_memory / semantic_memory) * 100:5.1f}% smaller than objects)"
    )
    print(
        f"  JSON encode: {serialization_ms(legacy):>8.3f} -> "
        f"{serialization_ms(compact):>8.3f} ms"
    )


def main() -> None:
    print("Canvas history encoding benchmark (#198)")
    report("Typical short history", make_actions(path_count=96, points_per_path=6))
    report("Long path-heavy history", make_actions(path_count=160, points_per_path=80))


if __name__ == "__main__":
    main()

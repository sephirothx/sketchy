#!/usr/bin/env python3
"""Measure representative and near-limit canvas history costs.

Usage:
  backend/.venv/bin/python benchmarks/canvas_history.py
  backend/.venv/bin/python benchmarks/canvas_history.py --near-limit \
    --json-output docs/performance-191-phase4-server.json
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, fields, is_dataclass
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.canvas_history import (  # noqa: E402
    ClearAction,
    FillAction,
    MAX_BINARY_CANVAS_HISTORY_BYTES,
    MAX_CANVAS_ACTIONS,
    MAX_CANVAS_POINTS,
    PackedCanvasHistory,
    PathAction,
    ShapeAction,
    decode_binary_canvas_history,
    color_to_hex,
    encode_canvas_history,
)
from app.canvas_session import CanvasSession, MAX_CANVAS_COMMITS  # noqa: E402


@dataclass(frozen=True)
class NearLimitResult:
    fixture: str
    actions: int
    points: int
    binary_bytes: int
    packed_history_bytes: int
    complete_session_bytes: int
    encode_median_ms: float
    decode_median_ms: float


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


def path_heavy_history() -> PackedCanvasHistory:
    """Use every action slot and point slot, distributed across paths."""
    history = PackedCanvasHistory()
    extra_points = MAX_CANVAS_POINTS - MAX_CANVAS_ACTIONS
    for index in range(MAX_CANVAS_ACTIONS):
        point_count = 2 if index < extra_points else 1
        history.append_path(
            [
                (
                    ((index * 17 + point * 3) % 800) / 800,
                    ((index * 11 + point * 5) % 600) / 600,
                )
                for point in range(point_count)
            ],
            color=(index * 977) & 0xFFFFFF,
            width=index % 12 + 1,
        )
    return history


def shape_heavy_history() -> PackedCanvasHistory:
    history = PackedCanvasHistory()
    shapes = tuple(("rectangle", "ellipse", "triangle"))
    for index in range(MAX_CANVAS_ACTIONS):
        x = (index % 100) / 100
        y = ((index // 100) % 100) / 100
        history.append_shape(
            shape=shapes[index % len(shapes)],
            start=(x, y),
            end=(min(1.0, x + 0.04), min(1.0, y + 0.04)),
            color=(index * 123_457) & 0xFFFFFF,
            width=index % 12 + 1,
        )
    return history


def fill_heavy_history(action_count: int = MAX_CANVAS_ACTIONS) -> PackedCanvasHistory:
    history = PackedCanvasHistory()
    for index in range(action_count):
        history.append_fill(
            x=(index * 37) % 800,
            y=(index * 29) % 600,
            color=(index * 654_319) & 0xFFFFFF,
        )
    return history


def mixed_history() -> PackedCanvasHistory:
    history = PackedCanvasHistory()
    path_actions = 6_250
    shape_actions = 6_250
    for index in range(path_actions):
        history.append_path(
            [
                (
                    ((index * 17 + point * 3) % 800) / 800,
                    ((index * 11 + point * 5) % 600) / 600,
                )
                for point in range(4)
            ],
            color=(index * 977) & 0xFFFFFF,
            width=index % 12 + 1,
        )
    shapes = tuple(("rectangle", "ellipse", "triangle"))
    for index in range(shape_actions):
        x = (index % 100) / 100
        y = ((index // 100) % 100) / 100
        history.append_shape(
            shape=shapes[index % len(shapes)],
            start=(x, y),
            end=(min(1.0, x + 0.04), min(1.0, y + 0.04)),
            color=(index * 123_457) & 0xFFFFFF,
            width=index % 12 + 1,
        )
    for index in range(MAX_CANVAS_ACTIONS - path_actions - shape_actions):
        history.append_fill(
            x=(index * 37) % 800,
            y=(index * 29) % 600,
            color=(index * 654_319) & 0xFFFFFF,
        )
    return history


def theoretical_max_history() -> PackedCanvasHistory:
    history = PackedCanvasHistory()
    history.append_path(
        [(0.0, 0.0)] * MAX_CANVAS_POINTS,
        color=0,
        width=1,
    )
    for _ in range(MAX_CANVAS_ACTIONS - 1):
        history.append_shape(
            shape="rectangle",
            start=(0.0, 0.0),
            end=(1.0, 1.0),
            color=0,
            width=1,
        )
    return history


def near_limit_histories() -> dict[str, PackedCanvasHistory]:
    return {
        "path-heavy": path_heavy_history(),
        "shape-heavy": shape_heavy_history(),
        "fill-heavy": fill_heavy_history(),
        "mixed": mixed_history(),
        "theoretical-max": theoretical_max_history(),
    }


def encoded_bytes(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def serialization_ms(value, iterations: int = 250) -> float:
    started = time.perf_counter()
    for _ in range(iterations):
        encoded_bytes(value)
    return (time.perf_counter() - started) * 1000 / iterations


def median_call_ms(callback, iterations: int = 9) -> float:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        callback()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples)


def history_point_count(history: PackedCanvasHistory) -> int:
    return sum(
        (len(history.record_bytes(index)) - 5) // 4
        for index in range(len(history))
        if history.data[history.offsets[index]] == 0
    )


def measured_session(history: PackedCanvasHistory) -> CanvasSession:
    hashes = [((index + 1) * 2_654_435_761) & 0xFFFFFFFF for index in range(len(history))]
    first_commit = max(1, len(history) - MAX_CANVAS_COMMITS + 1)
    commits = [
        (sequence, (sequence * 97_531) & 0xFFFFFFFF, "action")
        for sequence in range(first_commit, len(history) + 1)
    ]
    return CanvasSession(
        history=history,
        revision=len(history),
        generation=1,
        sequence=len(history),
        hashes=hashes,
        commits=commits,
        commit_base_sequence=first_commit,
        point_count=history_point_count(history),
    )


def measure_near_limit_fixture(
    name: str,
    history: PackedCanvasHistory,
) -> NearLimitResult:
    payload = history.binary_payload()
    return NearLimitResult(
        fixture=name,
        actions=len(history),
        points=history_point_count(history),
        binary_bytes=len(payload),
        packed_history_bytes=deep_size(history),
        complete_session_bytes=deep_size(measured_session(history)),
        encode_median_ms=median_call_ms(history.binary_payload),
        decode_median_ms=median_call_ms(
            lambda: decode_binary_canvas_history(payload)
        ),
    )


def report_near_limits() -> list[NearLimitResult]:
    results = [
        measure_near_limit_fixture(name, history)
        for name, history in near_limit_histories().items()
    ]
    print("\nNear-limit canvas history")
    print(
        "Fixture          Actions  Points  Binary payload  Packed history  "
        "Full session  Encode  Decode"
    )
    print("-" * 111)
    for result in results:
        print(
            f"{result.fixture:<16} {result.actions:>7,}  {result.points:>6,}  "
            f"{result.binary_bytes:>12,} B  {result.packed_history_bytes:>12,} B  "
            f"{result.complete_session_bytes:>10,} B  "
            f"{result.encode_median_ms:>6.2f}ms  {result.decode_median_ms:>6.2f}ms"
        )
    theoretical = next(
        result for result in results if result.fixture == "theoretical-max"
    )
    if theoretical.binary_bytes != MAX_BINARY_CANVAS_HISTORY_BYTES:
        raise RuntimeError("theoretical maximum fixture does not match layout bound")
    return results


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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--near-limit",
        action="store_true",
        help="also construct and measure histories at accepted limits",
    )
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    print("Canvas history encoding benchmark (#198)")
    report("Typical short history", make_actions(path_count=96, points_per_path=6))
    report("Long path-heavy history", make_actions(path_count=160, points_per_path=80))
    results = report_near_limits() if args.near_limit else []
    if args.json_output:
        args.json_output.write_text(
            json.dumps([asdict(result) for result in results], indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote JSON results to {args.json_output}")


if __name__ == "__main__":
    main()

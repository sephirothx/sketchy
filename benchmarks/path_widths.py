#!/usr/bin/env python3
"""Measure what a pen's changing width costs on the wire and in storage (#828).

A path's width can change part way along it: a pen's pressure, quantized to
whole pixels. This says what that costs, and what the ways it was *not* done
would have cost, because the choice was between designs and the design is only
right if the numbers say so.

The input is the recorded strokes under `fixtures/live_strokes/`. None of them
carries pressure - they were drawn with a mouse and a script - so a pressure
curve is laid over each stroke: a ramp up as the pen lands, a ramp down as it
lifts, and a slow wobble between, seeded so the run repeats. That is a model,
and says so; what it is a model *of* is the thing that decides the cost, which
is how often the quantized width steps. `--wobble` and `--brush` move it.

The width is quantized the way the client does (`frontend/src/lib/penPressure.ts`,
mirrored here constant for constant): the selected size is the ceiling, two
pixels the floor whatever the brush, a brush has at most `--levels` widths
spaced by ratio, and a new one is taken only when the target is three quarters
of the way to the next, so a pen held steady does not chatter between two.

Four ways to carry the changes, each through the same warm permessage-deflate
context as the drawer's uplink, with WebSocket frame headers counted:

- **in-band** - what is implemented: a two-byte record inside the frame that
  was being sent anyway. No message is added.
- **width per point** - one more byte on every point of every frame.
- **an event per change** - a `draw` frame of its own for each change, which
  also splits the batch it falls inside, since order has to hold.
- **a stroke per run** - no wire change at all: end the path and start
  another at the new width. Each start carries the action identity.

Storage is measured the same way: the `SKCH` frame and the stored `SKCD` blob
with and without the markers, and beside them what the frozen `SKCD` v1 walk
would have stored - it chains a marker into the differences - which is the
saving `SKCD` v2 was cut for.

Usage:
  backend/.venv/bin/python benchmarks/path_widths.py
  backend/.venv/bin/python benchmarks/path_widths.py --brush 6 12 32 --levels 0 6 --wobble 0.15
  backend/.venv/bin/python benchmarks/path_widths.py --json-output out.json
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import random
import sys
import zlib
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "benchmarks"))

from app.canvas_session import CanvasSession  # noqa: E402
from app.canvas_storage import _DELTA_HEADER, _recode_path_v1, _walk_frame, prepare_stored_drawing  # noqa: E402
from app.live_drawing import MAX_BASE64_FRAME_BYTES, encode_live_drawing  # noqa: E402
from live_drawing import Deflater, event_messages, stream_cost  # noqa: E402
from point_thinning import CANVAS_HEIGHT, CANVAS_WIDTH, TRACE_DIR, load_strokes, thin  # noqa: E402

TOLERANCE = 0.25
FLUSH_EVERY = 2  # the traces were recorded at 40 ms; the client flushes at 80
MIN_PEN_WIDTH = 2
FULL_PRESSURE = 0.7
PRESSURE_GAMMA = 0.8
HYSTERESIS = 0.75


# ---------------------------------------------------------------- pressure

def pressure_curve(count: int, rng: random.Random, wobble: float) -> list[float]:
    """Pressure per sample: lands, wobbles, lifts."""
    ramp = max(2, min(10, count // 4))
    phase = rng.uniform(0, math.tau)
    period = rng.uniform(40, 90)
    level = rng.uniform(0.55, 0.9)
    out = []
    for index in range(count):
        envelope = min(1.0, (index + 1) / ramp, (count - index) / ramp)
        value = level + wobble * math.sin(phase + index * math.tau / period) + rng.gauss(0, wobble / 6)
        out.append(max(0.0, min(1.0, value * envelope)))
    return out


def width_levels(brush: int, levels: int) -> tuple[int, list[int]]:
    """`widthLevels` in `frontend/src/lib/penPressure.ts`: the floor is two
    pixels whatever the brush, and the widths between are spaced by ratio.
    Zero levels = every pixel."""
    floor = min(brush, MIN_PEN_WIDTH)
    if not levels:
        return floor, list(range(floor, brush + 1))
    widths: list[int] = []
    for level in range(levels):
        # floor(x + 0.5), as Math.round does; Python's round() is banker's.
        width = math.floor(floor * (brush / floor) ** (level / (levels - 1)) + 0.5) if levels > 1 else brush
        if not widths or width != widths[-1]:
            widths.append(width)
    return floor, widths


def quantized_widths(pressure: list[float], brush: int, levels: int) -> list[int]:
    """The width of the segment ending at each sample: the client's quantizer.

    Pressure moves along the same ratio scale the levels sit on, the whole
    brush arrives at `FULL_PRESSURE` of the sensor's range, and a new width is
    taken once the target is three quarters of the way to the next level.
    """
    floor, widths = width_levels(brush, levels)
    span = math.log(brush / floor) if brush > floor else 0.0
    positions = [math.log(width / floor) / span if span else 0.0 for width in widths]
    nearest = lambda target: max(range(len(positions)), key=lambda i: (-abs(positions[i] - target), i))
    current = None
    out = []
    for value in pressure:
        target = min(1.0, max(0.0, value / FULL_PRESSURE)) ** PRESSURE_GAMMA
        if current is None:
            current = nearest(target)
        else:
            neighbour = current + (target > positions[current]) - (target < positions[current])
            if 0 <= neighbour < len(positions) and neighbour != current:
                if abs(target - positions[current]) >= abs(positions[neighbour] - positions[current]) * HYSTERESIS:
                    current = nearest(target)
        out.append(widths[current])
    return out


# ---------------------------------------------------------------- strokes

def pen_stroke(stroke: dict, brush: int, rng: random.Random, wobble: float, levels: int) -> dict:
    """Thin a stroke the way the client will: run boundaries are kept."""
    points, frame_of = stroke["points"], stroke["frame_of"]
    widths = quantized_widths(pressure_curve(len(points), rng, wobble), brush, levels)
    # Sample i starting a new width makes sample i-1 the point two runs share.
    cuts = [0] + [i - 1 for i in range(1, len(points)) if widths[i] != widths[i - 1] and i - 1 > 0]
    cuts = sorted(set(cuts)) + [len(points) - 1]
    kept: list = [points[0]]
    kept_frames = [frame_of[0]]
    kept_widths = [widths[0]]
    for start, end in zip(cuts, cuts[1:]):
        if end <= start:
            continue
        piece, piece_frames = thin(points[start:end + 1], frame_of[start:end + 1], TOLERANCE, True)
        for point, frame in zip(piece[1:], piece_frames[1:]):
            kept.append(point)
            kept_frames.append(frame)
            kept_widths.append(widths[end])
    plain, plain_frames = thin(points, frame_of, TOLERANCE, True)
    return {
        "color": stroke["color"],
        "start_width": widths[1] if len(widths) > 1 else widths[0],
        "points": kept, "frames": kept_frames, "widths": kept_widths,
        "plain_points": plain, "plain_frames": plain_frames, "brush": brush,
    }


def normalized(point) -> dict:
    return {"x": point[0] / CANVAS_WIDTH, "y": point[1] / CANVAS_HEIGHT}


def batches(points, frames, widths=None):
    """The flush batches after the start point: (points, widths) per flush."""
    out = []
    current = None
    for index in range(1, len(points)):
        flush = frames[index] // FLUSH_EVERY
        if flush != current:
            out.append(([], []))
            current = flush
        out[-1][0].append(points[index])
        out[-1][1].append(widths[index] if widths else None)
    return out


# ---------------------------------------------------------------- variants

def draw(frame, identity=None) -> list[bytes]:
    if isinstance(frame, int):
        argument = frame
    elif len(frame) <= MAX_BASE64_FRAME_BYTES:
        argument = base64.b64encode(frame).decode()
    else:
        argument = frame
    return event_messages("draw", argument, identity) if identity else event_messages("draw", argument)


def start_frame(stroke, point, width):
    return encode_live_drawing("draw_start", {**normalized(point), "color": stroke["color"], "width": width})


def move_frame(points, previous, *, widths=None, ends=False):
    payload = {"points": [normalized(p) for p in points], "previous": normalized(previous)}
    if widths:
        payload["widths"] = widths
    if ends:
        payload["ends"] = True
    return encode_live_drawing("draw_move", payload)


def variant_baseline(stroke, sequence) -> list[bytes]:
    points = stroke["plain_points"]
    out = draw(start_frame(stroke, points[0], stroke["brush"]), [1, sequence])
    previous = points[0]
    groups = batches(points, stroke["plain_frames"])
    for index, (batch, _) in enumerate(groups):
        out += draw(move_frame(batch, previous, ends=index == len(groups) - 1))
        previous = batch[-1]
    if not groups:
        out += draw(encode_live_drawing("draw_end"))
    return out


def _changes(batch_widths, current):
    changes = []
    for index, width in enumerate(batch_widths):
        if width != current:
            changes.append([index, width])
            current = width
    return changes, current


def variant_in_band(stroke, sequence) -> tuple[list[bytes], int]:
    points = stroke["points"]
    out = draw(start_frame(stroke, points[0], stroke["start_width"]), [1, sequence])
    previous, current, count = points[0], stroke["start_width"], 0
    groups = batches(points, stroke["frames"], stroke["widths"])
    for index, (batch, batch_widths) in enumerate(groups):
        changes, current = _changes(batch_widths, current)
        count += len(changes)
        out += draw(move_frame(batch, previous, widths=changes, ends=index == len(groups) - 1))
        previous = batch[-1]
    if not groups:
        out += draw(encode_live_drawing("draw_end"))
    return out, count


def variant_per_point(stroke, sequence) -> list[bytes]:
    """The in-band frames with no markers, and a width byte after every record."""
    points = stroke["points"]
    out = draw(start_frame(stroke, points[0], stroke["start_width"]), [1, sequence])
    previous = points[0]
    groups = batches(points, stroke["frames"], stroke["widths"])
    for index, (batch, batch_widths) in enumerate(groups):
        frame = bytearray((move_frame(batch, previous, ends=index == len(groups) - 1)[0],))
        for point, width in zip(batch, batch_widths):
            record = move_frame([point], previous)[1:]
            frame += record + bytes((width,))
            previous = point
        out += draw(bytes(frame))
    if not groups:
        out += draw(encode_live_drawing("draw_end"))
    return out


def variant_event_per_change(stroke, sequence) -> list[bytes]:
    points = stroke["points"]
    out = draw(start_frame(stroke, points[0], stroke["start_width"]), [1, sequence])
    previous, current = points[0], stroke["start_width"]
    groups = batches(points, stroke["frames"], stroke["widths"])
    for index, (batch, batch_widths) in enumerate(groups):
        run: list = []
        for point, width in zip(batch, batch_widths):
            if width != current:
                if run:
                    out += draw(move_frame(run, previous))
                    previous, run = run[-1], []
                out += draw(bytes((0x19, width)))  # a spare tag, and the width
                current = width
            run.append(point)
        out += draw(move_frame(run, previous, ends=index == len(groups) - 1))
        previous = batch[-1]
    if not groups:
        out += draw(encode_live_drawing("draw_end"))
    return out


def variant_stroke_per_run(stroke, sequence) -> tuple[list[bytes], int]:
    points = stroke["points"]
    out = draw(start_frame(stroke, points[0], stroke["start_width"]), [1, sequence])
    previous, current, used = points[0], stroke["start_width"], 1
    groups = batches(points, stroke["frames"], stroke["widths"])
    for index, (batch, batch_widths) in enumerate(groups):
        run: list = []
        for point, width in zip(batch, batch_widths):
            if width != current:
                if run:
                    out += draw(move_frame(run, previous, ends=True))
                    previous = run[-1]
                    run = []
                else:
                    out += draw(encode_live_drawing("draw_end"))
                out += draw(start_frame(stroke, previous, width), [1, sequence + used])
                used += 1
                current = width
            run.append(point)
        last = index == len(groups) - 1
        out += draw(move_frame(run, previous, ends=last))
        previous = batch[-1]
    if not groups:
        out += draw(encode_live_drawing("draw_end"))
    return out, used


# ---------------------------------------------------------------- storage

def history_of(strokes, *, markers: bool) -> bytes:
    canvas = CanvasSession(generation=1)
    for stroke in strokes:
        points = stroke["points"] if markers else stroke["plain_points"]
        width = stroke["start_width"] if markers else stroke["brush"]
        canvas.record_stroke("draw_start", {**normalized(points[0]), "color": stroke["color"], "width": width})
        if len(points) > 1:
            changes, _ = _changes(stroke["widths"][1:], width) if markers else ([], width)
            canvas.record_stroke("draw_move", {"points": [normalized(p) for p in points[1:]], "widths": changes})
        canvas.record_stroke("draw_end", {})
    return canvas.sync_payload()


def stored_as_v1(frame: bytes) -> int:
    """What the frozen SKCD v1 walk would have stored: it chains a marker into
    the differences, which is what SKCD v2 was cut to stop doing."""
    recoded = _walk_frame(frame, undo=False, recode=_recode_path_v1)
    return _DELTA_HEADER.size + len(zlib.compress(recoded, 6))


# ---------------------------------------------------------------- report

def cost(messages: list[bytes]) -> dict:
    return {
        "raw": sum(len(m) for m in messages),
        **stream_cost(messages, Deflater(15), masked=True),
    }


def measure(path: Path, brush: int, wobble: float, seed: int, levels: int) -> dict:
    rng = random.Random(seed)
    strokes = [pen_stroke(stroke, brush, rng, wobble, levels) for stroke in load_strokes(path) if len(stroke["points"]) > 1]
    variants: dict[str, list[bytes]] = {name: [] for name in (
        "baseline (no pressure)", "in-band (implemented)", "width per point", "an event per change", "a stroke per run",
    )}
    changes = 0
    actions = 0
    sequence = 1
    for stroke in strokes:
        variants["baseline (no pressure)"] += variant_baseline(stroke, sequence)
        in_band, count = variant_in_band(stroke, sequence)
        variants["in-band (implemented)"] += in_band
        changes += count
        variants["width per point"] += variant_per_point(stroke, sequence)
        variants["an event per change"] += variant_event_per_change(stroke, sequence)
        per_run, used = variant_stroke_per_run(stroke, sequence)
        variants["a stroke per run"] += per_run
        actions += used
        sequence += 1
    plain, marked = history_of(strokes, markers=False), history_of(strokes, markers=True)
    return {
        "trace": path.stem, "brush": brush, "levels": levels, "strokes": len(strokes),
        "points": sum(len(s["plain_points"]) for s in strokes),
        "points_with_boundaries": sum(len(s["points"]) for s in strokes),
        "changes": changes, "actions_as_strokes": actions,
        "wire": {name: cost(messages) for name, messages in variants.items()},
        "history": {
            "skch_plain": len(plain), "skch_marked": len(marked),
            "stored_plain": len(prepare_stored_drawing(plain)[0]),
            "stored_marked": len(prepare_stored_drawing(marked)[0]),
            "stored_marked_as_v1": stored_as_v1(marked),
        },
    }


def print_report(result: dict) -> None:
    levels = f"at most {result['levels']} widths" if result["levels"] else "1 px steps"
    print(f"\n{result['trace']}  brush {result['brush']}px, {levels}  {result['strokes']} strokes")
    print(f"  points {result['points']} -> {result['points_with_boundaries']} with run boundaries kept, "
          f"{result['changes']} width changes ({result['changes'] / max(1, result['points_with_boundaries']):.0%} of points)")
    base = result["wire"]["baseline (no pressure)"]
    print(f"  {'uplink':<26}{'messages':>9}{'packet B':>10}{'deflated+framed B':>19}{'vs baseline':>13}")
    for name, row in result["wire"].items():
        delta = row["framed"] / base["framed"] - 1
        print(f"  {name:<26}{row['messages']:>9}{row['raw']:>10}{row['framed']:>19}{delta:>+12.1%}")
    print(f"  as strokes: {result['actions_as_strokes']} actions for {result['strokes']} pen strokes")
    history = result["history"]
    print(f"  SKCH {history['skch_plain']} -> {history['skch_marked']} B "
          f"({history['skch_marked'] / history['skch_plain'] - 1:+.1%}); stored SKCD {history['stored_plain']} -> "
          f"{history['stored_marked']} B ({history['stored_marked'] / history['stored_plain'] - 1:+.1%}); "
          f"SKCD v1 would have stored {history['stored_marked_as_v1']} B")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", type=Path, default=TRACE_DIR)
    parser.add_argument("--brush", type=int, nargs="+", default=[6, 12, 32])
    parser.add_argument("--wobble", type=float, default=0.15)
    parser.add_argument("--levels", type=int, nargs="+", default=[6], help="widths per brush (the client's is 6); 0 = every pixel")
    parser.add_argument("--seed", type=int, default=828)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    paths = sorted(args.trace.glob("*.json")) if args.trace.is_dir() else [args.trace]
    results = [
        measure(path, brush, args.wobble, args.seed, levels)
        for path in paths for brush in args.brush for levels in args.levels
    ]
    for result in results:
        print_report(result)
    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Measure what a pen's changing width costs on the wire and in storage (#828).

A path's width can change along it: a pen's pressure. What travels is a few
**width keyframes** - "the path is this wide at this point", two bytes inside
the frame that was being sent anyway - and every painter ramps the width
between them. This says what that costs, and what the ways it was *not* done
would have cost, because the choice was between designs and the design is only
right if the numbers say so.

The input is the recorded strokes under `fixtures/live_strokes/`. None of them
carries pressure - they were drawn with a mouse and a script - so a pressure
curve is laid over each stroke: a ramp up as the pen lands, a ramp down as it
lifts, and a slow wobble with sensor noise between, seeded so the run repeats.
That is a model, and says so; what it is a model *of* is the thing that
decides the cost, which is how often the width has something new to say.
`--wobble` and `--brush` move it.

The client's own rules are mirrored here constant for constant
(`frontend/src/lib/penPressure.ts`, `widthKeyframes.ts`, `penStroke.ts`): the
selected size is the ceiling and two pixels the floor, pressure moves the width
by ratio with the whole brush at 70% of the sensor's range, a sample becomes a
the pressure is smoothed before it is mapped (`--smoothing`), a sample becomes a
keyframe when a straight ramp to the next one would miss a sample passed over
by more than the tolerance (a pixel at least, and 15% of the width widening to
25% on a fat line; `--tolerance` tries a flat share instead), a frame that goes out part way through a change says how far it got,
and a change after a quiet stretch gets a hold to ramp from.

Ways to carry it, each through the same warm permessage-deflate context as the
drawer's uplink, with WebSocket frame headers counted:

- **keyframes, in-band** - what is implemented. No message is added.
- **width per point** - one more byte on every point of every frame.
- **an event per keyframe** - a `draw` frame of its own for each, which also
  splits the batch it falls inside, since order has to hold.
- **six stepped levels, in-band** - what keyframes replaced: the width snapped
  to six levels per brush and sent when the level changes. Its cost is about
  the same; it is here because what it drew was a staircase.

Storage is measured the same way: the `SKCH` frame and the stored `SKCD` blob
with and without the markers, and beside them what the frozen `SKCD` v1 walk
would have stored - it chains a marker into the differences - which is the
saving `SKCD` v2 was cut for.

Usage:
  backend/.venv/bin/python benchmarks/path_widths.py
  backend/.venv/bin/python benchmarks/path_widths.py --brush 6 12 32 --tolerance 0.15 --smoothing 0   # as it was before both
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
from point_thinning import CANVAS_HEIGHT, CANVAS_WIDTH, TRACE_DIR, distance_to_segment, load_strokes, thin  # noqa: E402

TOLERANCE = 0.25
FLUSH_EVERY = 2  # the traces were recorded at 40 ms; the client flushes at 80
MIN_PEN_WIDTH = 2
FULL_PRESSURE = 0.7
PRESSURE_GAMMA = 0.8
WIDTH_TOLERANCE_PX = 1.0
EXACT_TOLERANCE_PX = 0.49
QUIET_FRAME_SHARE = 0.5
FINE_TOLERANCE_SHARE = 0.15
WIDE_TOLERANCE_SHARE = 0.25
TOLERANCE_WIDENS_BETWEEN = (8, 16)
SMOOTHING_WEIGHT = 0.4
HYSTERESIS = 0.75
STEPPED_LEVELS = 6


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


def target_width(pressure: float, brush: int) -> float:
    """`targetWidth` in `penPressure.ts`: by ratio between the floor and the brush."""
    floor = min(brush, MIN_PEN_WIDTH)
    if brush <= floor:
        return float(brush)
    share = min(1.0, max(0.0, pressure / FULL_PRESSURE)) ** PRESSURE_GAMMA
    return floor * (brush / floor) ** share


def width_tolerance(width: float, brush: int) -> float:
    """`widthTolerance` in `widthKeyframes.ts`: a pixel at least, a share of the
    width that loosens from 15% at 8 px to 25% at 16, and exact at the ends of
    the brush's range - full pressure draws the selected size."""
    to_end = max(0.0, min(brush - width, width - min(brush, MIN_PEN_WIDTH)))
    fine, wide = TOLERANCE_WIDENS_BETWEEN
    along = min(1.0, max(0.0, (width - fine) / (wide - fine)))
    loose = max(WIDTH_TOLERANCE_PX, width * (FINE_TOLERANCE_SHARE + (WIDE_TOLERANCE_SHARE - FINE_TOLERANCE_SHARE) * along))
    return min(loose, EXACT_TOLERANCE_PX + to_end)


def smoothed(pressure: list[float], weight: float) -> list[float]:
    """`createPressureSmoother` in `penPressure.ts`, at the 120 Hz the traces'
    pens are modelled at: a 16 ms time constant weighs a new reading at 0.4."""
    if not weight:
        return pressure
    out, value = [], pressure[0]
    for reading in pressure:
        value += (reading - value) * weight
        out.append(value)
    return out


def whole_width(width: float, brush: int) -> int:
    return min(brush, max(min(brush, MIN_PEN_WIDTH), math.floor(width + 0.5)))


def keyframed_stroke(stroke: dict, brush: int, pressure: list[float], share: float | None = None) -> dict:
    """One stroke through the client's bookkeeping: the point thinner, the
    keyframe thinner, and `PenStroke`'s two rules about frames."""
    points, frame_of = stroke["points"], stroke["frame_of"]
    targets = [target_width(value, brush) for value in pressure]
    tolerance = (lambda width: width_tolerance(width, brush)) if share is None else (lambda width: max(WIDTH_TOLERANCE_PX, share * width))
    start_width = whole_width(targets[0], brush)
    kept, kept_frames, keys = [points[0]], [frame_of[0]], {}
    key_width, reach, frame_first = start_width, "previous-frame-end", 1
    anchor, pending, pending_index, dropped, last_seen = points[0], None, None, [], points[0]
    arc, width_anchor, width_pending, width_passed = 0.0, (0.0, float(start_width)), None, []

    def keep(index):
        nonlocal anchor, pending, pending_index, dropped
        kept.append(points[index])
        kept_frames.append(frame_of[index])
        anchor, pending, pending_index, dropped = points[index], None, None, []

    def key_last(width) -> bool:
        """`PenStroke.keyLast`; True when the keyframe was placed as asked."""
        nonlocal key_width, reach
        last = len(kept) - 1
        if last < frame_first or last in keys:
            return False
        if width != key_width and reach == "earlier":
            if last == frame_first:
                keys[last], reach = key_width, "frame"
                return False
            keys[frame_first] = key_width
        keys[last], key_width, reach = width, width, "frame"
        return True

    for index in range(1, len(points)):
        if points[index] == last_seen:
            continue
        previous_arc = arc
        arc += math.dist(points[index], last_seen)
        last_seen = points[index]
        sample = (arc, targets[index])
        if width_pending is not None:
            (from_at, from_width), (to_at, to_width) = width_anchor, sample
            on_ramp = lambda at: from_width + (to_width - from_width) * ((at - from_at) / (to_at - from_at) if to_at > from_at else 1)
            if all(abs(width - on_ramp(at)) <= tolerance(width) for at, width in (*width_passed, width_pending)):
                width_passed.append(width_pending)
            else:
                width_anchor, width_passed = width_pending, []
                if pending is not None:
                    keep(pending_index)
                if not key_last(whole_width(width_anchor[1], brush)) and reach == "frame" and keys.get(len(kept) - 1) == key_width:
                    width_anchor = (previous_arc, float(key_width))
        width_pending = sample
        if pending is None:
            pending, pending_index = points[index], index
        elif all(distance_to_segment(q, anchor, points[index]) <= TOLERANCE for q in (*dropped, pending)):
            dropped.append(pending)
            pending, pending_index = points[index], index
        else:
            keep(pending_index)
            pending, pending_index = points[index], index
        following = index + 1
        if following < len(points) and frame_of[following] // FLUSH_EVERY != frame_of[index] // FLUSH_EVERY:
            if pending is not None:
                keep(index)
            if len(kept) > frame_first:
                if abs(targets[index] - key_width) > tolerance(targets[index]) * QUIET_FRAME_SHARE and key_last(whole_width(targets[index], brush)):
                    width_anchor, width_passed, width_pending = (arc, float(key_width)), [], None
                reach = "previous-frame-end" if (len(kept) - 1) in keys else "earlier"
                frame_first = len(kept)
    if pending is not None:
        keep(pending_index)
    if len(kept) > frame_first and whole_width(targets[-1], brush) != key_width:
        key_last(whole_width(targets[-1], brush))
    return {
        "color": stroke["color"], "brush": brush, "start_width": start_width,
        "points": kept, "frames": kept_frames, "keys": keys,
    }


# ---------------------------------------------------------------- strokes

def stepped_stroke(stroke: dict, brush: int, pressure: list[float]) -> dict:
    """What keyframes replaced: six levels, sent when the level changes, with
    the point two levels share kept by the thinner."""
    points, frame_of = stroke["points"], stroke["frame_of"]
    widths = quantized_widths(pressure, brush, STEPPED_LEVELS)
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
    keys, current = {}, (widths[1] if len(widths) > 1 else widths[0])
    start_width = current
    for index in range(1, len(kept)):
        if kept_widths[index] != current:
            keys[index] = current = kept_widths[index]
    return {
        "color": stroke["color"], "brush": brush, "start_width": start_width,
        "points": kept, "frames": kept_frames, "keys": keys,
    }


def plain_stroke(stroke: dict, brush: int) -> dict:
    kept, kept_frames = thin(stroke["points"], stroke["frame_of"], TOLERANCE, True)
    return {"color": stroke["color"], "brush": brush, "start_width": brush, "points": kept, "frames": kept_frames, "keys": {}}


def normalized(point) -> dict:
    return {"x": point[0] / CANVAS_WIDTH, "y": point[1] / CANVAS_HEIGHT}


def batches(stroke: dict) -> list[list[int]]:
    """The kept points after the start, by the flush each rides: indices into `points`."""
    out: list[list[int]] = []
    current = None
    for index in range(1, len(stroke["points"])):
        flush = stroke["frames"][index] // FLUSH_EVERY
        if flush != current:
            out.append([])
            current = flush
        out[-1].append(index)
    return out


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


def variant_in_band(stroke, sequence) -> list[bytes]:
    """The stroke's frames with its keyframes inside them: what the client sends."""
    points, keys = stroke["points"], stroke["keys"]
    out = draw(start_frame(stroke, points[0], stroke["start_width"]), [1, sequence])
    previous = points[0]
    groups = batches(stroke)
    for position, group in enumerate(groups):
        widths = [[offset, keys[index]] for offset, index in enumerate(group) if index in keys]
        out += draw(move_frame([points[i] for i in group], previous, widths=widths, ends=position == len(groups) - 1))
        previous = points[group[-1]]
    if not groups:
        out += draw(encode_live_drawing("draw_end"))
    return out


def variant_per_point(stroke, sequence) -> list[bytes]:
    """The same points with no keyframes, and a width byte after every record."""
    points = stroke["points"]
    out = draw(start_frame(stroke, points[0], stroke["start_width"]), [1, sequence])
    previous = points[0]
    groups = batches(stroke)
    width = stroke["start_width"]
    for position, group in enumerate(groups):
        frame = bytearray((move_frame([points[i] for i in group], previous, ends=position == len(groups) - 1)[0],))
        for index in group:
            width = stroke["keys"].get(index, width)
            frame += move_frame([points[index]], previous)[1:] + bytes((width,))
            previous = points[index]
        out += draw(bytes(frame))
    if not groups:
        out += draw(encode_live_drawing("draw_end"))
    return out


def variant_event_per_keyframe(stroke, sequence) -> list[bytes]:
    points, keys = stroke["points"], stroke["keys"]
    out = draw(start_frame(stroke, points[0], stroke["start_width"]), [1, sequence])
    previous = points[0]
    groups = batches(stroke)
    for position, group in enumerate(groups):
        run: list = []
        for index in group:
            run.append(points[index])
            if index in keys and index != group[-1]:
                out += draw(move_frame(run, previous))
                previous, run = run[-1], []
            if index in keys:
                out += draw(bytes((0x19, keys[index])))  # a spare tag, and the width
        if run:
            out += draw(move_frame(run, previous, ends=position == len(groups) - 1))
            previous = run[-1]
    if not groups:
        out += draw(encode_live_drawing("draw_end"))
    return out


# ---------------------------------------------------------------- storage

def history_of(strokes) -> bytes:
    canvas = CanvasSession(generation=1)
    for stroke in strokes:
        points = stroke["points"]
        canvas.record_stroke("draw_start", {**normalized(points[0]), "color": stroke["color"], "width": stroke["start_width"]})
        if len(points) > 1:
            widths = [(index - 1, width) for index, width in sorted(stroke["keys"].items())]
            canvas.record_stroke("draw_move", {"points": [normalized(p) for p in points[1:]], "widths": widths})
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


def measure(path: Path, brush: int, wobble: float, seed: int, share: float | None, weight: float) -> dict:
    rng = random.Random(seed)
    raw = [stroke for stroke in load_strokes(path) if len(stroke["points"]) > 1]
    hands = [pressure_curve(len(stroke["points"]), rng, wobble) for stroke in raw]
    plain = [plain_stroke(stroke, brush) for stroke in raw]
    keyed = [keyframed_stroke(stroke, brush, smoothed(hand, weight), share) for stroke, hand in zip(raw, hands)]
    stepped = [stepped_stroke(stroke, brush, hand) for stroke, hand in zip(raw, hands)]
    variants = {
        "baseline (no pressure)": [m for n, stroke in enumerate(plain, 1) for m in variant_in_band(stroke, n)],
        "keyframes, in-band (implemented)": [m for n, stroke in enumerate(keyed, 1) for m in variant_in_band(stroke, n)],
        "width per point": [m for n, stroke in enumerate(keyed, 1) for m in variant_per_point(stroke, n)],
        "an event per keyframe": [m for n, stroke in enumerate(keyed, 1) for m in variant_event_per_keyframe(stroke, n)],
        "six stepped levels, in-band": [m for n, stroke in enumerate(stepped, 1) for m in variant_in_band(stroke, n)],
    }
    plain_history, keyed_history = history_of(plain), history_of(keyed)
    return {
        "trace": path.stem, "brush": brush, "tolerance": share, "smoothing": weight, "strokes": len(raw),
        "points": sum(len(stroke["points"]) for stroke in plain),
        "points_keyed": sum(len(stroke["points"]) for stroke in keyed),
        "keyframes": sum(len(stroke["keys"]) for stroke in keyed),
        "level_changes": sum(len(stroke["keys"]) for stroke in stepped),
        "wire": {name: cost(messages) for name, messages in variants.items()},
        "history": {
            "skch_plain": len(plain_history), "skch_keyed": len(keyed_history),
            "stored_plain": len(prepare_stored_drawing(plain_history)[0]),
            "stored_keyed": len(prepare_stored_drawing(keyed_history)[0]),
            "stored_keyed_as_v1": stored_as_v1(keyed_history),
        },
    }


def print_report(result: dict) -> None:
    tolerance = "the client's tolerance" if result["tolerance"] is None else f"a flat {result['tolerance']:.0%} tolerance"
    smoothing = "smoothed" if result["smoothing"] else "unsmoothed"
    print(f"\n{result['trace']}  brush {result['brush']}px, {tolerance}, {smoothing}  {result['strokes']} strokes")
    print(f"  points {result['points']} -> {result['points_keyed']} with keyframes' points kept; "
          f"{result['keyframes']} keyframes ({result['keyframes'] / max(1, result['points_keyed']):.0%} of points), "
          f"against {result['level_changes']} changes of level")
    base = result["wire"]["baseline (no pressure)"]
    print(f"  {'uplink':<34}{'messages':>9}{'packet B':>10}{'deflated+framed B':>19}{'vs baseline':>13}")
    for name, row in result["wire"].items():
        print(f"  {name:<34}{row['messages']:>9}{row['raw']:>10}{row['framed']:>19}{row['framed'] / base['framed'] - 1:>+12.1%}")
    history = result["history"]
    print(f"  SKCH {history['skch_plain']} -> {history['skch_keyed']} B "
          f"({history['skch_keyed'] / history['skch_plain'] - 1:+.1%}); stored SKCD {history['stored_plain']} -> "
          f"{history['stored_keyed']} B ({history['stored_keyed'] / history['stored_plain'] - 1:+.1%}); "
          f"SKCD v1 would have stored {history['stored_keyed_as_v1']} B")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", type=Path, default=TRACE_DIR)
    parser.add_argument("--brush", type=int, nargs="+", default=[6, 12, 32])
    parser.add_argument("--wobble", type=float, default=0.15)
    parser.add_argument("--tolerance", type=float, nargs="+", default=[None],
                        help="a flat tolerance, as a share of the width, in place of the client's (15%% widening to 25%%)")
    parser.add_argument("--smoothing", type=float, default=SMOOTHING_WEIGHT,
                        help="the weight of a new pressure reading (the client's is 0.4 at 120 Hz); 0 turns smoothing off")
    parser.add_argument("--seed", type=int, default=828)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    paths = sorted(args.trace.glob("*.json")) if args.trace.is_dir() else [args.trace]
    results = [
        measure(path, brush, args.wobble, args.seed, share, args.smoothing)
        for path in paths for brush in args.brush for share in args.tolerance
    ]
    for result in results:
        print_report(result)
    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()

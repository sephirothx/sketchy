#!/usr/bin/env python3
"""What thinning pointer samples would save, and what it would change (#560).

The input is the recorded traces under `fixtures/live_strokes/`: every `draw`
frame the drawer's browser sent, so the points are the quantized samples the
client queued (a quarter of a canvas pixel), grouped into the frames its flush
timer sent them in. Each trace is replayed through the same streaming thinner
the client would run, at several tolerances, and two ways of handling the
flush: **forced**, where the sample still pending when the timer fires is
sent (a viewer never sees the stroke stall on a long straight line, and the
error bound is unchanged), and **unforced**, where it stays pending until a
corner or the pen lifts (fewer points, but a straight stroke reaches the
viewers only when it ends or bends).

The thinner keeps an anchor and one pending sample, and accepts a new sample
as the pending one only if every sample dropped since the anchor is within
the tolerance of the segment from the anchor to it. When that fails, the
pending sample is emitted and becomes the anchor. So every dropped sample is
within the tolerance of the segment that replaced it - the whole-stroke bound
the issue asks for, checked here again over the output rather than trusted.
Tolerance 0 keeps only what changes the drawn line at all: exact duplicates
and exactly collinear samples go.

Reported per trace and setting: points before and after, raw point bytes
(4 B each in history), live frame bytes and their deflated size through one
warm context, the measured maximum error, and the rasterization difference:
pixels that differ between the raw and the thinned strokes drawn with the
client's capsule rasterizer, and the number of 4-connected blank regions the
canvas is left with, which is what a flood fill sees.

Usage:
  backend/.venv/bin/python benchmarks/point_thinning.py
  backend/.venv/bin/python benchmarks/point_thinning.py --tolerance 0 0.25 0.5 1
  backend/.venv/bin/python benchmarks/point_thinning.py --json-output out.json
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import zlib
from collections import deque
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.live_drawing import decode_live_drawing, encode_live_drawing

TRACE_DIR = Path(ROOT_DIR) / "fixtures" / "live_strokes"
CANVAS_WIDTH = 800
CANVAS_HEIGHT = 600
DEFLATE_LEVEL = 6
WINDOW_BITS = 15


# ---------------------------------------------------------------- traces

def load_strokes(path: Path) -> list[dict]:
    """Each brush stroke as canvas-pixel points, with the frame each came in."""
    trace = json.loads(path.read_text())
    strokes = []
    for stroke in trace["strokes"]:
        points: list[tuple[float, float]] = []
        frame_of: list[int] = []
        color = "#000000"
        width = 4.0
        frame_index = 0
        for frame in stroke["frames"]:
            if isinstance(frame["frame"], int):
                continue  # a one-byte frame: `draw_end`, `clear`
            packet = decode_live_drawing(base64.b64decode(frame["frame"]))
            if packet.event == "draw_start":
                color = packet.payload["color"]
                width = int(packet.payload["width"])
                points.append((packet.payload["x"] * CANVAS_WIDTH, packet.payload["y"] * CANVAS_HEIGHT))
                frame_of.append(frame_index)
            elif packet.event == "draw_move":
                frame_index += 1
                for point in packet.payload["points"]:
                    points.append((point["x"] * CANVAS_WIDTH, point["y"] * CANVAS_HEIGHT))
                    frame_of.append(frame_index)
        if points:
            strokes.append({"points": points, "frame_of": frame_of, "color": color, "width": width})
    return strokes


# ---------------------------------------------------------------- thinning

def distance_to_segment(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def thin(points, frame_of, tolerance: float, forced: bool) -> tuple[list, list[int]]:
    """The streaming thinner. Returns the kept points and their frames."""
    kept = [points[0]]
    kept_frames = [frame_of[0]]
    anchor = points[0]
    pending = None
    pending_frame = 0
    dropped: list = []
    last_seen = points[0]

    def emit(point, frame):
        nonlocal anchor, dropped
        kept.append(point)
        kept_frames.append(frame)
        anchor = point
        dropped = []

    for index in range(1, len(points)):
        point = points[index]
        frame = frame_of[index]
        if point == last_seen:
            continue  # an exact duplicate changes nothing, at any tolerance
        last_seen = point
        if pending is None:
            pending, pending_frame = point, frame
        else:
            fits = all(distance_to_segment(q, anchor, point) <= tolerance for q in dropped)
            fits = fits and distance_to_segment(pending, anchor, point) <= tolerance
            if fits:
                dropped.append(pending)
                pending, pending_frame = point, frame
            else:
                emit(pending, pending_frame)
                pending, pending_frame = point, frame
        # The flush timer fires after this sample: force what is pending out.
        if forced and index + 1 < len(points) and frame_of[index + 1] != frame and pending is not None:
            emit(pending, pending_frame)
            pending = None
    if pending is not None and pending != kept[-1]:
        emit(pending, pending_frame)
    return kept, kept_frames


def max_error(points, kept) -> float:
    """Every original sample's distance to the nearest kept segment.

    Brute force on purpose: this is the check on the thinner's promise, and
    a cleverer search would be one more thing to trust."""
    if len(kept) == 1:
        return max(math.hypot(p[0] - kept[0][0], p[1] - kept[0][1]) for p in points)
    segments = list(zip(kept, kept[1:]))
    return max(min(distance_to_segment(p, a, b) for a, b in segments) for p in points)


# ---------------------------------------------------------------- bytes

def frames_for(stroke, points, frames, *, relative: bool = False, flush_every: int = 1, fold_end: bool = False) -> list[bytes | int]:
    """Re-encode the kept points into the flush frames they would ride.

    `flush_every` merges that many of the recording's flushes into one, which
    is what a longer flush interval does to the same stroke (#559): the
    traces were recorded at 40 ms, so 2 is 80 ms. `relative` encodes each
    frame against the point the previous one ended on (#559).
    """
    normalized = lambda point: {"x": point[0] / CANVAS_WIDTH, "y": point[1] / CANVAS_HEIGHT}
    out = [encode_live_drawing("draw_start", {
        **normalized(points[0]), "color": stroke["color"], "width": stroke["width"],
    })]
    previous = normalized(points[0])
    batch: list[dict] = []
    current = frames[1] // flush_every if len(frames) > 1 else None
    for point, frame in zip(points[1:], frames[1:]):
        if frame // flush_every != current and batch:
            out.append(encode_live_drawing("draw_move", {"points": batch, **({"previous": previous} if relative else {})}))
            previous = batch[-1]
            batch = []
        current = frame // flush_every
        batch.append(normalized(point))
    if batch and fold_end:
        # The final batch closes the path (#603): one frame, no end event.
        out.append(encode_live_drawing("draw_move", {"points": batch, "previous": previous, "ends": True}))
        return out
    if batch:
        out.append(encode_live_drawing("draw_move", {"points": batch, **({"previous": previous} if relative else {})}))
    out.append(encode_live_drawing("draw_end"))
    return out


def deflated_bytes(frames: list[bytes | int]) -> int:
    compressor = zlib.compressobj(DEFLATE_LEVEL, zlib.DEFLATED, -WINDOW_BITS)
    total = 0
    for frame in frames:
        raw = bytes((frame,)) if isinstance(frame, int) else frame
        total += len(compressor.compress(raw)) + len(compressor.flush(zlib.Z_SYNC_FLUSH)) - 4
    return total


def raw_bytes(frames: list[bytes | int]) -> int:
    return sum(1 if isinstance(frame, int) else len(frame) for frame in frames)


# ---------------------------------------------------------------- raster

def rasterize(strokes_points: list[tuple[list, float]]) -> bytearray:
    """The client's capsule rasterizer: a pixel is ink when its centre is
    within the radius of any segment. One byte per pixel."""
    ink = bytearray(CANVAS_WIDTH * CANVAS_HEIGHT)
    for points, width in strokes_points:
        radius = width / 2
        radius_squared = radius * radius
        segments = [(points[0], points[0])] if len(points) == 1 else list(zip(points, points[1:]))
        for a, b in segments:
            min_x = max(0, math.floor(min(a[0], b[0]) - radius))
            min_y = max(0, math.floor(min(a[1], b[1]) - radius))
            max_x = min(CANVAS_WIDTH - 1, math.ceil(max(a[0], b[0]) + radius))
            max_y = min(CANVAS_HEIGHT - 1, math.ceil(max(a[1], b[1]) + radius))
            ax, ay = a
            dx, dy = b[0] - ax, b[1] - ay
            length_squared = dx * dx + dy * dy
            for y in range(min_y, max_y + 1):
                cy = y + 0.5
                row = y * CANVAS_WIDTH
                for x in range(min_x, max_x + 1):
                    cx = x + 0.5
                    if length_squared == 0:
                        t = 0.0
                    else:
                        t = max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / length_squared))
                    ex, ey = cx - (ax + t * dx), cy - (ay + t * dy)
                    if ex * ex + ey * ey <= radius_squared:
                        ink[row + x] = 1
    return ink


# Blank regions smaller than this are specks between overlapping strokes,
# not places a player would ever aim a fill at.
MIN_REGION_PIXELS = 16


def blank_regions(ink: bytearray) -> int:
    """4-connected regions of blank canvas of a size a fill could be aimed
    at: what a flood fill can tell apart, and so what thinning must not
    change."""
    seen = bytearray(len(ink))
    regions = 0
    for start in range(len(ink)):
        if ink[start] or seen[start]:
            continue
        size = 1
        seen[start] = 1
        queue = deque([start])
        while queue:
            index = queue.popleft()
            x = index % CANVAS_WIDTH
            for neighbour in (index - CANVAS_WIDTH, index + CANVAS_WIDTH,
                              index - 1 if x > 0 else -1,
                              index + 1 if x < CANVAS_WIDTH - 1 else -1):
                if 0 <= neighbour < len(ink) and not ink[neighbour] and not seen[neighbour]:
                    seen[neighbour] = 1
                    size += 1
                    queue.append(neighbour)
        if size >= MIN_REGION_PIXELS:
            regions += 1
    return regions


# ---------------------------------------------------------------- main

def measure(path: Path, tolerances: list[float], with_raster: bool) -> dict:
    strokes = load_strokes(path)
    raw_points = sum(len(s["points"]) for s in strokes)
    raw_frames = [f for s in strokes for f in frames_for(s, s["points"], s["frame_of"])]
    baseline_ink = rasterize([(s["points"], s["width"]) for s in strokes]) if with_raster else None
    result = {
        "trace": path.name,
        "strokes": len(strokes),
        "points": raw_points,
        "pointBytes": raw_points * 4,
        "frames": len(raw_frames),
        "frameBytes": raw_bytes(raw_frames),
        "deflatedBytes": deflated_bytes(raw_frames),
        "blankRegions": blank_regions(baseline_ink) if with_raster else None,
        "settings": [],
    }
    for forced in (True, False):
        for tolerance in tolerances:
            kept_all = []
            frames_all = []
            worst = 0.0
            thinned = []
            for stroke in strokes:
                kept, kept_frames = thin(stroke["points"], stroke["frame_of"], tolerance, forced)
                kept_all.append((kept, stroke["width"]))
                thinned.append((stroke, kept, kept_frames))
                frames_all.extend(frames_for(stroke, kept, kept_frames))
                worst = max(worst, max_error(stroke["points"], kept))
            points = sum(len(k) for k, _ in kept_all)
            entry = {
                "tolerance": tolerance,
                "forced": forced,
                "points": points,
                "pointBytes": points * 4,
                "frames": len(frames_all),
                "frameBytes": raw_bytes(frames_all),
                "deflatedBytes": deflated_bytes(frames_all),
                "maxErrorPx": round(worst, 4),
                # The same kept points on the wire two more ways (#559): in
                # relative frames, and in relative frames at twice the flush
                # interval. Fewer, smaller messages; the points are the same.
                "wire": [],
            }
            for label, relative, flush_every, fold_end in (
                ("40ms", False, 1, False), ("40ms relative", True, 1, False),
                ("80ms relative", True, 2, False), ("80ms relative, folded end", True, 2, True),
            ):
                frames = [f for stroke, kept, kept_frames in thinned
                          for f in frames_for(stroke, kept, kept_frames, relative=relative, flush_every=flush_every, fold_end=fold_end)]
                entry["wire"].append({
                    "label": label,
                    "frames": len(frames),
                    "frameBytes": raw_bytes(frames),
                    "deflatedBytes": deflated_bytes(frames),
                })
            if with_raster:
                ink = rasterize(kept_all)
                entry["pixelsDiffering"] = sum(a != b for a, b in zip(ink, baseline_ink))
                entry["blankRegions"] = blank_regions(ink)
            result["settings"].append(entry)
    return result


def print_report(results: list[dict]) -> None:
    for result in results:
        print(f"\n{result['trace']}: {result['strokes']} strokes, {result['points']} points, "
              f"{result['pointBytes']} B of points, {result['frames']} frames, "
              f"{result['frameBytes']} B raw, {result['deflatedBytes']} B deflated"
              + (f", {result['blankRegions']} blank regions" if result["blankRegions"] is not None else ""))
        print(f"  {'flush':<9}{'tol px':>7}{'points':>8}{'kept':>7}{'frames':>8}{'raw B':>8}{'defl B':>8}"
              f"{'max err':>9}{'px diff':>9}{'regions':>9}")
        for s in result["settings"]:
            kept = f"{100 * s['points'] / result['points']:.0f}%"
            print(f"  {'forced' if s['forced'] else 'unforced':<9}{s['tolerance']:>7.2f}{s['points']:>8}{kept:>7}"
                  f"{s['frames']:>8}{s['frameBytes']:>8}{s['deflatedBytes']:>8}{s['maxErrorPx']:>9.3f}"
                  f"{s.get('pixelsDiffering', '-'):>9}{s.get('blankRegions', '-'):>9}")
        print("  on the wire (#559), same kept points, tolerance 0.25 forced:")
        chosen = next(s for s in result["settings"] if s["forced"] and s["tolerance"] == 0.25)
        for w in chosen["wire"]:
            print(f"    {w['label']:<28}{w['frames']:>6} events{w['frameBytes']:>8} B raw{w['deflatedBytes']:>8} B deflated")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", type=Path, action="append", help="a trace file; default: every trace in the fixture directory")
    parser.add_argument("--tolerance", type=float, nargs="+", default=[0.0, 0.25, 0.5, 1.0], help="tolerances in canvas pixels")
    parser.add_argument("--no-raster", action="store_true", help="skip the (slow) pixel comparison")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    traces = args.trace or sorted(TRACE_DIR.glob("*.json"))
    results = [measure(path, args.tolerance, not args.no_raster) for path in traces]
    print_report(results)
    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()

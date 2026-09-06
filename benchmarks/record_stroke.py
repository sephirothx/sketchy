#!/usr/bin/env python3
"""Record what real drawing puts on the wire, into a fixture.

`live_drawing.py` used to model a stroke as the same five-point batch
repeated twenty-five times a second. Through permessage-deflate that is the
best case there is - the compressor has seen every byte before - and #563
found the estimate it produced could not be trusted. This records the
frames the production client actually emits instead: pointer events through
`useCanvasPointerInput`, the flush timer, `encodeLiveDrawing`, the base64 /
binary shape decision, and the Socket.IO packet each becomes, with the
DevTools timestamp of every WebSocket frame.

Two ways to drive the pen:

- scripted (default): five strokes of different character - a long slow
  curve, a loop, a short tick, a fast zigzag, a slow crawl - sampled at a
  pointer cadence (120 Hz by default) with seeded hand tremor, so the trace
  is deterministic in shape but real in every encoding decision;
- `--manual`: a headed browser and a real hand. Draw, then press Enter here.

The fixture is a benchmark input, not a protocol golden: its frames are
whatever the client sent, decoded only to label them.

Usage:
  ./benchmarks/record_stroke.sh
  ./benchmarks/record_stroke.sh --manual
  ./benchmarks/record_stroke.sh --output /tmp/trace.json --pointer-hz 60
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import random
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(ROOT_DIR / "benchmarks"))

from app.live_drawing import decode_live_drawing  # noqa: E402
from canvas import (  # noqa: E402
    PROFILES,
    TimedWebSocketFrame,
    canvas_point,
    create_game,
    select_drawing_tool,
)

DEFAULT_OUTPUT = ROOT_DIR / "fixtures" / "live_stroke_trace_v1.json"
SCHEMA_VERSION = 1
RECORDING_COMMIT: str | None = None


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True, cwd=ROOT_DIR
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


# --- the scripted hand ------------------------------------------------------

def ease(t: float) -> float:
    """Slow-fast-slow, the way a hand starts and stops a stroke."""
    return t * t * (3 - 2 * t)


def s_curve(t: float) -> tuple[float, float]:
    return 0.12 + 0.76 * t, 0.5 + 0.28 * math.sin(t * math.pi * 2)


def loop(t: float) -> tuple[float, float]:
    angle = t * math.pi * 2.2
    return 0.5 + 0.18 * math.cos(angle), 0.45 + 0.24 * math.sin(angle)


def tick(t: float) -> tuple[float, float]:
    return 0.2 + 0.06 * t, 0.8 - 0.05 * t


def zigzag(t: float) -> tuple[float, float]:
    return 0.15 + 0.7 * t, 0.3 + 0.12 * (1 if int(t * 10) % 2 else -1) * (t * 10 % 1)


def crawl(t: float) -> tuple[float, float]:
    return 0.7 + 0.03 * t, 0.75 + 0.02 * math.sin(t * math.pi)


SCRIPTED_STROKES = [
    ("long s-curve", s_curve, 1.2),
    ("loop", loop, 0.8),
    ("short tick", tick, 0.15),
    ("fast zigzag", zigzag, 0.9),
    ("slow crawl", crawl, 0.5),
]
PAUSE_BETWEEN_STROKES = 0.3


async def draw_scripted(page, pointer_hz: int, seed: int) -> None:
    rng = random.Random(seed)
    interval = 1 / pointer_hz
    for _label, path, seconds in SCRIPTED_STROKES:
        samples = max(2, round(seconds * pointer_hz))
        points = []
        for index in range(samples):
            nx, ny = path(ease(index / (samples - 1)))
            x, y = await canvas_point(page, nx, ny)
            points.append((x + rng.gauss(0, 0.4), y + rng.gauss(0, 0.4)))
        await page.mouse.move(*points[0])
        await page.mouse.down()
        started = time.perf_counter()
        for index, (x, y) in enumerate(points[1:], start=1):
            await page.mouse.move(x, y)
            due = started + index * interval
            delay = due - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
        await page.mouse.up()
        await asyncio.sleep(PAUSE_BETWEEN_STROKES)


async def draw_by_hand(page) -> None:
    await page.bring_to_front()
    print("Draw in the browser window. Press Enter here when done.", flush=True)
    loop_ = asyncio.get_running_loop()
    await loop_.run_in_executor(None, sys.stdin.readline)


# --- reading the wire back --------------------------------------------------

def parse_draw_frames(frames: list[TimedWebSocketFrame]) -> list[dict]:
    """The `draw` events among the drawer's sent frames, decoded and timed."""
    out: list[dict] = []
    pending_binary: dict | None = None
    for timestamp, opcode, payload in frames:
        if opcode == 2 and pending_binary is not None:
            raw = base64.b64decode(payload)
            pending_binary["frame"] = base64.b64encode(raw).decode()
            pending_binary["shape"] = "binary"
            out.append(pending_binary)
            pending_binary = None
            continue
        if opcode != 1 or not payload.startswith("4"):
            continue
        body = payload.removeprefix("42")
        if payload.startswith("45"):
            body = payload[payload.index("[") :]
        elif not payload.startswith("42"):
            continue
        try:
            packet = json.loads(body)
        except json.JSONDecodeError:
            continue
        if not isinstance(packet, list) or not packet or packet[0] != "draw":
            continue
        frame = packet[1]
        identity = packet[2] if len(packet) > 2 else None
        record = {"atMs": timestamp, "identity": identity}
        if isinstance(frame, dict) and frame.get("_placeholder"):
            pending_binary = record
            continue
        if isinstance(frame, int):
            record["frame"] = frame
            record["shape"] = "int"
        else:
            record["frame"] = frame
            record["shape"] = "base64"
        out.append(record)
    if not out:
        return out
    origin = out[0]["atMs"]
    for record in out:
        record["atMs"] = round((record["atMs"] - origin) * 1000, 1)
        raw = record["frame"]
        decoded = decode_live_drawing(
            raw if isinstance(raw, int) else base64.b64decode(raw)
        )
        record["event"] = decoded.event
        points = decoded.payload.get("points") if decoded.payload else None
        if points is not None:
            record["points"] = len(points)
        if record["identity"] is None:
            del record["identity"]
    return out


def group_strokes(frames: list[dict], labels: list[str]) -> list[dict]:
    strokes: list[dict] = []
    current: list[dict] | None = None
    for frame in frames:
        if frame["event"] == "draw_start":
            current = []
            strokes.append({"frames": current})
        if current is None:
            strokes.append({"frames": [frame]})
            current = None
            continue
        current.append(frame)
        if frame["event"] == "draw_end":
            current = None
    for index, stroke in enumerate(strokes):
        stroke["label"] = labels[index] if index < len(labels) else f"stroke {index + 1}"
        stroke["points"] = sum(f.get("points", 0) for f in stroke["frames"])
        moves = [f for f in stroke["frames"] if f["event"] == "draw_move"]
        stroke["moveFrames"] = len(moves)
        if stroke["frames"]:
            stroke["durationMs"] = round(
                stroke["frames"][-1]["atMs"] - stroke["frames"][0]["atMs"], 1
            )
    return strokes


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pointer-hz", type=int, default=120)
    parser.add_argument("--seed", type=int, default=563)
    parser.add_argument("--manual", action="store_true", help="draw by hand in a headed browser")
    args = parser.parse_args()

    profile = PROFILES["desktop"]
    sent: list[TimedWebSocketFrame] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.manual, args=["--mute-audio"])
        try:
            drawer_context, guesser_context, drawer, _guesser, _ = await create_game(
                browser, profile, args.base_url, drawer_sent_frames=sent
            )
            await select_drawing_tool(drawer, "Brush")
            if args.manual:
                await draw_by_hand(drawer)
            else:
                await draw_scripted(drawer, args.pointer_hz, args.seed)
            await asyncio.sleep(0.5)
            viewport = await drawer.evaluate("({w: innerWidth, h: innerHeight})")
            canvas_box = await drawer.locator("canvas.drawing-canvas").bounding_box()
            await drawer_context.close()
            await guesser_context.close()
        finally:
            await browser.close()

    frames = parse_draw_frames(sent)
    labels = [] if args.manual else [label for label, _, _ in SCRIPTED_STROKES]
    strokes = group_strokes(frames, labels)
    document = {
        "schemaVersion": SCHEMA_VERSION,
        "recorded": {
            "how": "by hand" if args.manual else "scripted pointer path",
            "pointerHz": None if args.manual else args.pointer_hz,
            "seed": None if args.manual else args.seed,
            "browser": "chromium " + browser.version,
            "viewport": viewport,
            "canvasCssBox": canvas_box,
            "commit": RECORDING_COMMIT,
        },
        "frames": len(frames),
        "strokes": strokes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=1) + "\n")
    print(f"Recorded {len(strokes)} strokes, {len(frames)} draw frames -> {args.output}")
    for stroke in strokes:
        print(
            f"  {stroke['label']:<14} {stroke['points']:>4} points "
            f"{stroke['moveFrames']:>3} move frames {stroke.get('durationMs', 0):>7} ms"
        )


if __name__ == "__main__":
    RECORDING_COMMIT = git_commit()
    asyncio.run(main())

"""How long a player entering a running turn waits for the drawing, and what it costs (#877).

A drawer draws ``--strokes`` strokes; then, ``--runs`` times, a new player joins
the room mid-turn and a seated viewer's connection drops and comes back. For each
it reports the time until that canvas matches the drawer's pixel for pixel, the
Socket.IO bytes it received meanwhile, and how many full ``sync_strokes`` and
``sync_strokes_tail`` replies were among them. #654 is why the join latency is
measured at all: an earlier change to the same path made every entry wait out a
resync window.

Needs a diagnostics build (the reconnect is forced through the socket the build
exposes) and a server on ``http://localhost:8000``, where the E2E helpers it
borrows to name players and join rooms expect one:

    (cd frontend && VITE_RENDER_DIAGNOSTICS=true npm run build)
    (cd backend && HOST=:: PORT=8000 GUEST_PROVISION_LIMIT=1000 .venv/bin/python -m app.server) &
    backend/.venv/bin/python benchmarks/join_to_drawing.py --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from uuid import uuid4

from playwright.async_api import async_playwright

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from tests.e2e.lobby_helpers import (
    join_by_code,
    room_code,
    use_guest_name,
)

CANVAS_PNG = "() => document.querySelector('canvas.drawing-canvas').toDataURL()"


class Wire:
    """What one page receives on its sockets, from a mark."""

    def __init__(self, page) -> None:
        self.frames: list[tuple[float, int, str]] = []
        page.on("websocket", lambda ws: ws.on("framereceived", self._record))

    def _record(self, payload) -> None:
        text = payload if isinstance(payload, str) else ""
        size = len(payload.encode()) if isinstance(payload, str) else len(payload)
        self.frames.append((time.monotonic(), size, text))

    def since(self, index: int) -> dict:
        frames = self.frames[index:]
        texts = [text for _, _, text in frames]
        # A canvas reply is a binary event: its text frame ("45<n>-[...]")
        # announces n attachment frames that follow it.
        sync_bytes, attachments = 0, 0
        for _, size, text in frames:
            if attachments and not text:
                sync_bytes += size
                attachments -= 1
            elif '"sync_strokes' in text:
                sync_bytes += size
                head = text.split("-", 1)[0]
                attachments = int(head[2:]) if head.startswith("45") and head[2:].isdigit() else 0
        return {
            "bytes": sum(size for _, size, _ in frames),
            "sync_bytes": sync_bytes,
            "full_syncs": sum('"sync_strokes"' in t and '"sync_strokes_tail"' not in t for t in texts),
            "tails": sum('"sync_strokes_tail"' in t for t in texts),
        }


INK = """() => {
  const canvas = document.querySelector('canvas.drawing-canvas');
  const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  let ink = 0;
  for (let i = 0; i < data.length; i += 4) if (data[i] !== 255) ink += 1;
  return ink;
}"""


async def _converged(a, b, started: float) -> float:
    """Seconds from `started` until the two canvases match pixel for pixel."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if await a.evaluate(CANVAS_PNG) == await b.evaluate(CANVAS_PNG):
            return time.monotonic() - started
        await asyncio.sleep(0.02)
    raise SystemExit(
        f"never converged: {await a.evaluate(INK)} inked pixels against {await b.evaluate(INK)}"
    )


async def run(args) -> dict:
    base = args.base_url.rstrip("/")
    joins, reconnects = [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host = await (await browser.new_context()).new_page()
        viewer = await (await browser.new_context()).new_page()
        viewer_wire = Wire(viewer)
        await host.goto(base)
        await use_guest_name(host, f"ProbeHost{uuid4().hex[:5]}")
        await host.click('button:has-text("Create room")')
        await host.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
        await host.click('button:has-text("Create room")')
        await host.wait_for_selector('[data-testid="waiting-room"]')
        code = await room_code(host)
        await viewer.goto(base)
        await use_guest_name(viewer, f"ProbeView{uuid4().hex[:5]}")
        await join_by_code(viewer, code)
        await viewer.wait_for_selector('[data-testid="waiting-room"]')
        await host.click(".waiting-start-button")
        await host.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
        drawer = host if await host.query_selector(".prompt-choices") else viewer
        watcher = viewer if drawer is host else host
        watcher_wire = viewer_wire if watcher is viewer else Wire(host)
        await drawer.click(".prompt-choices button:first-child")
        await drawer.wait_for_selector("canvas.drawing-canvas")
        await watcher.wait_for_selector("canvas.drawing-canvas")
        box = await (await drawer.query_selector("canvas.drawing-canvas")).bounding_box()
        for index in range(args.strokes):
            x, y = box["x"] + 20 + (index * 37) % (box["width"] - 60), box["y"] + 20 + (index * 23) % (box["height"] - 60)
            await drawer.mouse.move(x, y)
            await drawer.mouse.down()
            for step in range(1, 25):
                await drawer.mouse.move(x + step * 1.7, y + (step % 7) * 3)
            await drawer.mouse.up()
        await _converged(drawer, watcher, time.monotonic())
        # Every run must land in this turn: a new turn is a new, empty canvas,
        # and a reconnect into it has nothing to claim - a full sync of
        # nothing, which says nothing about a tail.
        turn_canvas = await drawer.evaluate(CANVAS_PNG)
        turn_mark = time.monotonic()

        for _ in range(args.runs):
            late = await (await browser.new_context()).new_page()
            wire = Wire(late)
            await late.goto(base)
            await use_guest_name(late, f"ProbeLate{uuid4().hex[:5]}")
            mark = len(wire.frames)
            started = time.monotonic()
            await join_by_code(late, code)
            await late.wait_for_selector("canvas.drawing-canvas")
            seconds = await _converged(drawer, late, started)
            await asyncio.sleep(0.5)  # anything still in flight for this entry
            joins.append({"seconds": seconds, **wire.since(mark)})
            # Kept seated: a turn whose last eligible guesser leaves while the
            # viewer is reconnecting ends at once, and a new turn's empty canvas
            # has nothing to claim.

            mark = len(watcher_wire.frames)
            started = time.monotonic()
            await watcher.evaluate("() => window.__SKETCHY_SOCKET__.io.engine.close()")
            await watcher.wait_for_function("() => window.__SKETCHY_SOCKET__.connected")
            seconds = await _converged(drawer, watcher, started)
            await asyncio.sleep(0.5)
            reconnects.append({"seconds": seconds, **watcher_wire.since(mark)})
            if await drawer.evaluate(CANVAS_PNG) != turn_canvas:
                raise SystemExit(
                    f"the drawer's canvas changed {time.monotonic() - turn_mark:.0f} s after the strokes"
                    f" (run {len(reconnects)}, {await drawer.evaluate(INK)} inked pixels); the runs"
                    " must fit in one turn - lower --runs or --strokes"
                )
        await browser.close()

    def summary(rows: list[dict]) -> dict:
        return {
            "seconds_median": round(statistics.median(r["seconds"] for r in rows), 3),
            "seconds_max": round(max(r["seconds"] for r in rows), 3),
            "bytes_median": int(statistics.median(r["bytes"] for r in rows)),
            "sync_bytes_median": int(statistics.median(r["sync_bytes"] for r in rows)),
            "full_syncs": sorted({r["full_syncs"] for r in rows}),
            "tails": sorted({r["tails"] for r in rows}),
        }

    report = {"strokes": args.strokes, "runs": args.runs, "mid_turn_join": summary(joins), "reconnect": summary(reconnects)}
    if args.per_run:
        report["per_run"] = {"joins": joins, "reconnects": reconnects}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--strokes", type=int, default=20)
    parser.add_argument("--per-run", action="store_true", help="include every run, not only the summary")
    parser.add_argument("--runs", type=int, default=5, help="each is a join and a reconnect; all must fit in one 90 s turn")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args))))


if __name__ == "__main__":
    main()

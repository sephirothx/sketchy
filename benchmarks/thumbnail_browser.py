#!/usr/bin/env python3
"""What drawing thumbnails costs the page's main thread, in a real browser (#1282).

Replays `fixtures/fill_replay_100.json` - the costliest history the server
accepts to replay, 100 full-canvas fills - as ``--count`` thumbnails at once,
drawn the way `DrawingThumbnail` did before #1282 (on the page) and the way it
does now (on the thumbnail worker), and reports the main thread's long tasks
and the worst lateness of a 10 ms timer meanwhile. The same fixture is also
replayed onto a live canvas surface (`canvas-history.html`), which is what a
full canvas sync costs a player who joins such a turn, and through the canvas's
renderer both ways it replays: at once, as the drawer's does, and played out
live, as a viewer's does since #1347.

Desktop, then a 4x CPU-throttled profile standing in for a phone. Run through
`benchmarks/run_canvas_history_browser.sh`, which serves the pages:

    BENCHMARK=thumbnail_browser benchmarks/run_canvas_history_browser.sh --count 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
FIXTURE = ROOT_DIR / "fixtures" / "fill_replay_100.json"
PROFILES = {"desktop": 1, "mobile": 4}


async def run(args) -> dict:
    encoded = json.loads(FIXTURE.read_text())["base64"]
    results: dict = {}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            for profile, rate in PROFILES.items():
                context = await browser.new_context()
                page = await context.new_page()
                session = await context.new_cdp_session(page)
                await session.send("Emulation.setCPUThrottlingRate", {"rate": rate})
                await page.goto(f"{args.base_url}/benchmarks/thumbnail-replay.html")
                await page.wait_for_function("() => typeof window.runThumbnailBenchmark === 'function'")
                row = {}
                for mode in ("page", "worker"):
                    row[mode] = await page.evaluate(
                        "([payload, count, mode]) => window.runThumbnailBenchmark(payload, count, mode)",
                        [encoded, args.count, mode],
                    )
                await page.goto(f"{args.base_url}/benchmarks/canvas-history.html")
                await page.wait_for_function("() => typeof window.runCanvasHistoryBenchmark === 'function'")
                row["fullSync"] = await page.evaluate(
                    "(payload) => window.runCanvasHistoryBenchmark(payload)", encoded
                )
                # The same sync through the canvas's renderer: all at once, as
                # the drawer's is, and played out live, as a viewer's is (#1347).
                for mode, live in (("fullSyncImmediate", False), ("fullSyncLive", True)):
                    row[mode] = await page.evaluate(
                        "([payload, live]) => window.runFullSyncBenchmark(payload, live)", [encoded, live]
                    )
                results[profile] = row
                await context.close()
        finally:
            await browser.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:4174")
    parser.add_argument("--count", type=int, default=3, help="thumbnails of the fixture drawn at once")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    results = asyncio.run(run(args))
    text = json.dumps(results, indent=2)
    print(text)
    if args.json_output:
        args.json_output.write_text(text + "\n")


if __name__ == "__main__":
    main()

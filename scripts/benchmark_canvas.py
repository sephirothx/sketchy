#!/usr/bin/env python3
"""End-to-end browser benchmarks for Sketchy's real-time canvas pipeline.

The benchmark creates a two-player room and exercises the production UI and
Socket.IO path. It intentionally reports measurements instead of asserting
thresholds: this is a baseline tool for comparing performance changes across
machines and browser profiles, not a timing-sensitive CI test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

CANVAS_WIDTH = 800
CANVAS_HEIGHT = 600


@dataclass(frozen=True)
class BrowserProfile:
    name: str
    viewport: dict[str, int]
    cpu_throttle_rate: int
    is_mobile: bool = False
    has_touch: bool = False


@dataclass
class BenchmarkResult:
    profile: str
    cpu_throttle_rate: int
    stroke_samples: int
    stroke_latency_median_ms: float
    stroke_latency_p95_ms: float
    large_fill_latency_ms: float
    undo_replay_latency_ms: float
    sync_strokes_frame_bytes: int
    retained_logical_strokes: int


PROFILES = {
    "desktop": BrowserProfile(
        name="desktop",
        viewport={"width": 1280, "height": 900},
        cpu_throttle_rate=1,
    ),
    "mobile": BrowserProfile(
        name="mobile-throttled",
        viewport={"width": 390, "height": 844},
        cpu_throttle_rate=4,
        is_mobile=True,
        has_touch=True,
    ),
}


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


async def set_cpu_throttle(context: BrowserContext, page: Page, rate: int) -> None:
    session = await context.new_cdp_session(page)
    await session.send("Emulation.setCPUThrottlingRate", {"rate": rate})


async def wait_for_canvas_pixel(
    page: Page,
    x: int,
    y: int,
    expected: tuple[int, int, int],
) -> None:
    await page.wait_for_function(
        """([x, y, expected]) => {
          const canvas = document.querySelector("canvas.drawing-canvas");
          if (!(canvas instanceof HTMLCanvasElement)) return false;
          const ctx = canvas.getContext("2d");
          if (!ctx) return false;
          const pixel = ctx.getImageData(x, y, 1, 1).data;
          return pixel[0] === expected[0]
            && pixel[1] === expected[1]
            && pixel[2] === expected[2];
        }""",
        arg=[x, y, list(expected)],
    )


async def canvas_point(page: Page, normalized_x: float, normalized_y: float) -> tuple[float, float]:
    canvas = page.locator("canvas.drawing-canvas")
    await canvas.scroll_into_view_if_needed()
    box = await canvas.bounding_box()
    if not box:
        raise RuntimeError("Drawing canvas has no bounding box")
    return (
        box["x"] + box["width"] * normalized_x,
        box["y"] + box["height"] * normalized_y,
    )


async def draw_stroke(
    drawer: Page,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    steps: int = 5,
) -> None:
    await drawer.mouse.move(*start)
    await drawer.mouse.down()
    await drawer.mouse.move(*end, steps=steps)
    await drawer.mouse.up()


async def create_game(
    browser: Browser,
    profile: BrowserProfile,
    base_url: str,
) -> tuple[BrowserContext, BrowserContext, Page, Page, list[str]]:
    context_options: dict[str, Any] = {
        "viewport": profile.viewport,
        "is_mobile": profile.is_mobile,
        "has_touch": profile.has_touch,
    }
    drawer_context = await browser.new_context(**context_options)
    observer_context = await browser.new_context(**context_options)
    drawer = await drawer_context.new_page()
    observer = await observer_context.new_page()
    websocket_frames: list[str] = []

    await set_cpu_throttle(drawer_context, drawer, profile.cpu_throttle_rate)
    await set_cpu_throttle(observer_context, observer, profile.cpu_throttle_rate)
    observer_cdp = await observer_context.new_cdp_session(observer)
    await observer_cdp.send("Network.enable")
    observer_cdp.on(
        "Network.webSocketFrameReceived",
        lambda event: websocket_frames.append(
            str(event.get("response", {}).get("payloadData", ""))
        ),
    )

    await drawer.goto(base_url)
    await drawer.fill('input[placeholder="Your name"]', f"{profile.name}-drawer")
    await drawer.get_by_role("button", name="Create room", exact=True).click()
    await drawer.wait_for_url("**/create")
    await drawer.get_by_role("button", name="Create room", exact=True).click()
    await drawer.wait_for_url("**/room/**")
    await drawer.wait_for_selector('[data-testid="waiting-room"]')
    code = (await drawer.inner_text(".room-copy-button")).split("Code:")[1].strip()

    await observer.goto(base_url)
    await observer.fill('input[placeholder="Your name"]', f"{profile.name}-observer")
    await observer.fill('input[placeholder="ABC123"]', code)
    await observer.click('button:has-text("Join by code")')
    await observer.wait_for_selector('[data-testid="waiting-room"]')

    await drawer.wait_for_selector(".waiting-start-button:not([disabled])")
    await drawer.click(".waiting-start-button")
    await drawer.wait_for_selector(".word-choices button")
    await observer.wait_for_selector('[data-testid="choosing-word-status"]')
    await drawer.click(".word-choices button:first-child")
    await drawer.wait_for_selector(".toolbar")
    await observer.wait_for_selector("canvas.drawing-canvas")

    return drawer_context, observer_context, drawer, observer, websocket_frames


async def benchmark_profile(
    browser: Browser,
    profile: BrowserProfile,
    base_url: str,
    stroke_samples: int,
    replay_strokes: int,
) -> BenchmarkResult:
    (
        drawer_context,
        observer_context,
        drawer,
        observer,
        websocket_frames,
    ) = await create_game(
        browser,
        profile,
        base_url,
    )

    try:
        # A fill of the untouched white canvas exercises the worst common fill
        # region while using the same toolbar and pointer path as a player.
        await drawer.locator('button[aria-label^="Fill"]').click()
        fill_x, fill_y = await canvas_point(drawer, 0.5, 0.5)
        fill_started = time.perf_counter()
        await drawer.mouse.click(fill_x, fill_y)
        await wait_for_canvas_pixel(
            observer,
            CANVAS_WIDTH // 2,
            CANVAS_HEIGHT // 2,
            (0, 0, 0),
        )
        fill_latency_ms = (time.perf_counter() - fill_started) * 1000

        # Clear the fill and start a new pen stroke. record_stroke deliberately
        # discards pre-clear history when that next stroke begins.
        await drawer.locator("button.clear-button").click()
        await wait_for_canvas_pixel(
            observer,
            CANVAS_WIDTH // 2,
            CANVAS_HEIGHT // 2,
            (255, 255, 255),
        )
        await drawer.locator('button[aria-label^="Pen"]').click()

        stroke_latencies: list[float] = []
        for index in range(stroke_samples):
            normalized_y = 0.12 + (0.70 * index / max(1, stroke_samples - 1))
            start = await canvas_point(drawer, 0.10, normalized_y)
            end = await canvas_point(drawer, 0.28, normalized_y)
            pixel_x = round(CANVAS_WIDTH * 0.27)
            pixel_y = round(CANVAS_HEIGHT * normalized_y)
            started = time.perf_counter()
            await draw_stroke(drawer, start, end)
            await wait_for_canvas_pixel(observer, pixel_x, pixel_y, (0, 0, 0))
            stroke_latencies.append((time.perf_counter() - started) * 1000)

        # Add a denser history without waiting after every logical stroke. The
        # last pixel wait is an ordering barrier: Socket.IO delivers every
        # preceding stroke before it.
        last_pixel = (0, 0)
        for index in range(replay_strokes):
            column = index % 10
            row = index // 10
            normalized_x = 0.38 + column * 0.045
            normalized_y = 0.12 + row * 0.07
            start = await canvas_point(drawer, normalized_x, normalized_y)
            end = await canvas_point(drawer, normalized_x + 0.025, normalized_y)
            last_pixel = (
                round(CANVAS_WIDTH * (normalized_x + 0.02)),
                round(CANVAS_HEIGHT * normalized_y),
            )
            await draw_stroke(drawer, start, end, steps=2)
        await wait_for_canvas_pixel(observer, *last_pixel, (0, 0, 0))

        websocket_frames.clear()
        undo_started = time.perf_counter()
        await drawer.locator("button.undo-button").click()
        await wait_for_canvas_pixel(observer, *last_pixel, (255, 255, 255))
        undo_replay_ms = (time.perf_counter() - undo_started) * 1000

        sync_frames = [
            frame for frame in websocket_frames if '"sync_strokes"' in frame
        ]
        sync_frame_bytes = max(
            (len(frame.encode("utf-8")) for frame in sync_frames),
            default=0,
        )
        if sync_frame_bytes == 0:
            raise RuntimeError("Did not capture a sync_strokes WebSocket frame")

        return BenchmarkResult(
            profile=profile.name,
            cpu_throttle_rate=profile.cpu_throttle_rate,
            stroke_samples=stroke_samples,
            stroke_latency_median_ms=statistics.median(stroke_latencies),
            stroke_latency_p95_ms=percentile(stroke_latencies, 0.95),
            large_fill_latency_ms=fill_latency_ms,
            undo_replay_latency_ms=undo_replay_ms,
            sync_strokes_frame_bytes=sync_frame_bytes,
            retained_logical_strokes=stroke_samples + replay_strokes - 1,
        )
    finally:
        await drawer_context.close()
        await observer_context.close()


def print_results(results: list[BenchmarkResult]) -> None:
    print()
    print("Sketchy canvas browser benchmark")
    print(
        "Profile             CPU  Stroke p50  Stroke p95  Large fill  "
        "Undo/replay  History  sync_strokes"
    )
    print("-" * 104)
    for result in results:
        print(
            f"{result.profile:<19} "
            f"{result.cpu_throttle_rate:>2}x  "
            f"{result.stroke_latency_median_ms:>9.1f}ms  "
            f"{result.stroke_latency_p95_ms:>9.1f}ms  "
            f"{result.large_fill_latency_ms:>9.1f}ms  "
            f"{result.undo_replay_latency_ms:>9.1f}ms  "
            f"{result.retained_logical_strokes:>7}  "
            f"{result.sync_strokes_frame_bytes:>10,} B"
        )
    print()
    print(
        "Stroke measurements are drawer-to-observer end-to-end latency. "
        "Undo includes the server round trip and browser replay."
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=sorted(PROFILES),
        default=["desktop", "mobile"],
    )
    parser.add_argument("--stroke-samples", type=int, default=12)
    parser.add_argument("--replay-strokes", type=int, default=60)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    if args.stroke_samples < 2:
        parser.error("--stroke-samples must be at least 2")
    if not 1 <= args.replay_strokes <= 90:
        parser.error("--replay-strokes must be between 1 and 90")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--mute-audio"],
        )
        try:
            results = []
            for profile_name in args.profiles:
                profile = PROFILES[profile_name]
                print(f"Running {profile.name} profile…", flush=True)
                results.append(
                    await benchmark_profile(
                        browser,
                        profile,
                        args.base_url,
                        args.stroke_samples,
                        args.replay_strokes,
                    )
                )
        finally:
            await browser.close()

    print_results(results)
    if args.json_output:
        args.json_output.write_text(
            json.dumps([asdict(result) for result in results], indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote JSON results to {args.json_output}")


if __name__ == "__main__":
    asyncio.run(main())

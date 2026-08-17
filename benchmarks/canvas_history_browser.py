#!/usr/bin/env python3
"""Measure cold and repeated browser decode/replay for near-limit histories."""
from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR / "benchmarks") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "benchmarks"))

from canvas_history import near_limit_histories  # noqa: E402


@dataclass(frozen=True)
class BrowserReplayResult:
    profile: str
    cpu_throttle_rate: int
    fixture: str
    actions: int
    replayed_actions: int
    binary_bytes: int
    late_join_decode_ms: float
    late_join_replay_ms: float
    reconnect_decode_ms: float
    reconnect_replay_ms: float
    projected_full_replay_ms: float
    late_join_heap_delta_bytes: int
    reconnect_heap_delta_bytes: int


PROFILES = {
    "desktop": 1,
    "mobile": 4,
}

# Full replay of every accepted window fixture. Checkpoint histories replay
# drawImage plus the trailing window, not the folded prefix floods.
REPLAY_LIMITS = {
    "window-fill": None,
    "path-heavy": None,
    "shape-heavy": None,
    "checkpoint-fill-spam": None,
    "checkpoint-mixed": None,
    "realistic": None,
}


async def set_cpu_throttle(
    context: BrowserContext,
    page: Page,
    rate: int,
) -> None:
    session = await context.new_cdp_session(page)
    await session.send("Emulation.setCPUThrottlingRate", {"rate": rate})


async def run_once(
    page: Page,
    encoded: str,
    replay_limit: int | None,
) -> dict:
    return await page.evaluate(
        "([payload, limit]) => window.runCanvasHistoryBenchmark(payload, limit)",
        [encoded, replay_limit],
    )


async def benchmark_fixture(
    page: Page,
    base_url: str,
    profile: str,
    cpu_throttle_rate: int,
    fixture: str,
    payload: bytes,
    replay_limit: int | None,
) -> BrowserReplayResult:
    await page.goto(f"{base_url}/benchmarks/canvas-history.html")
    await page.wait_for_function("typeof window.runCanvasHistoryBenchmark === 'function'")
    encoded = base64.b64encode(payload).decode("ascii")
    late_join = await run_once(page, encoded, replay_limit)
    reconnect = await run_once(page, encoded, replay_limit)
    scale = late_join["actions"] / late_join["replayedActions"]
    return BrowserReplayResult(
        profile=profile,
        cpu_throttle_rate=cpu_throttle_rate,
        fixture=fixture,
        actions=late_join["actions"],
        replayed_actions=late_join["replayedActions"],
        binary_bytes=len(payload),
        late_join_decode_ms=late_join["decodeMs"],
        late_join_replay_ms=late_join["replayMs"],
        reconnect_decode_ms=reconnect["decodeMs"],
        reconnect_replay_ms=reconnect["replayMs"],
        projected_full_replay_ms=max(
            late_join["replayMs"],
            reconnect["replayMs"],
        ) * scale,
        late_join_heap_delta_bytes=late_join["heapDeltaBytes"],
        reconnect_heap_delta_bytes=reconnect["heapDeltaBytes"],
    )


def print_results(results: list[BrowserReplayResult]) -> None:
    print("\nNear-limit canvas browser replay")
    print(
        "Profile           Fixture          Replay       Decode  Late join  "
        "Reconnect  Projected full"
    )
    print("-" * 108)
    for result in results:
        replay = f"{result.replayed_actions:,}/{result.actions:,}"
        print(
            f"{result.profile:<17} {result.fixture:<16} {replay:>13}  "
            f"{result.late_join_decode_ms:>7.1f}ms  "
            f"{result.late_join_replay_ms:>8.1f}ms  "
            f"{result.reconnect_replay_ms:>8.1f}ms  "
            f"{result.projected_full_replay_ms:>12.1f}ms"
        )
    print(
        "\nEvery fixture replays in full. Checkpoint histories blit one PNG then "
        "the trailing window; they do not re-flood compacted fills."
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4174")
    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=sorted(PROFILES),
        default=["desktop", "mobile"],
    )
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    histories = near_limit_histories()
    payloads = {
        name: histories[name].binary_payload()
        for name in REPLAY_LIMITS
    }
    async with async_playwright() as playwright:
        browser: Browser = await playwright.chromium.launch(
            headless=True,
            args=["--enable-precise-memory-info"],
        )
        try:
            results = []
            for profile in args.profiles:
                rate = PROFILES[profile]
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                )
                page = await context.new_page()
                await set_cpu_throttle(context, page, rate)
                try:
                    for fixture, replay_limit in REPLAY_LIMITS.items():
                        print(
                            f"Running {profile} {fixture} replay…",
                            flush=True,
                        )
                        results.append(
                            await benchmark_fixture(
                                page,
                                args.base_url,
                                profile,
                                rate,
                                fixture,
                                payloads[fixture],
                                replay_limit,
                            )
                        )
                finally:
                    await context.close()
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

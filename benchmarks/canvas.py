#!/usr/bin/env python3
"""End-to-end browser benchmarks for Sketchy's real-time canvas pipeline.

The benchmark creates a two-player room and exercises the production UI and
Socket.IO path. It intentionally reports measurements instead of asserting
thresholds: this is a baseline tool for comparing performance changes across
machines and browser profiles, not a timing-sensitive CI test. Prefer running
it through ``benchmarks/run_canvas.sh``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import math
import re
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    CDPSession,
    Page,
    async_playwright,
)

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
    local_stroke_handler_median_ms: float
    local_stroke_handler_p95_ms: float
    local_stroke_readback_median_ms: float
    local_stroke_readback_calls_median: float
    local_stroke_get_image_data_median_ms: float
    local_stroke_get_image_data_calls_median: float
    local_stroke_put_image_data_median_ms: float
    local_stroke_put_image_data_calls_median: float
    local_stroke_heap_delta_median_bytes: float
    large_fill_latency_ms: float
    local_fill_duration_ms: float
    local_fill_handler_ms: float
    local_fill_readback_ms: float
    local_fill_readback_calls: int
    local_fill_get_image_data_ms: float
    local_fill_get_image_data_calls: int
    local_fill_put_image_data_ms: float
    local_fill_put_image_data_calls: int
    local_fill_pixels_read: int
    local_fill_long_task_ms: float
    local_fill_heap_delta_bytes: int
    complex_fill_latency_ms: float
    local_complex_fill_duration_ms: float
    local_complex_fill_handler_ms: float
    local_complex_fill_readback_ms: float
    local_complex_fill_readback_calls: int
    local_complex_fill_get_image_data_ms: float
    local_complex_fill_get_image_data_calls: int
    local_complex_fill_put_image_data_ms: float
    local_complex_fill_put_image_data_calls: int
    local_complex_fill_pixels_read: int
    local_complex_fill_long_task_ms: float
    local_complex_fill_heap_delta_bytes: int
    undo_samples: int
    undo_replay_latency_ms: float
    undo_replay_latency_p95_ms: float
    local_undo_duration_ms: float
    local_undo_handler_ms: float
    local_undo_readback_ms: float
    local_undo_readback_calls: float
    local_undo_get_image_data_ms: float
    local_undo_get_image_data_calls: float
    local_undo_put_image_data_ms: float
    local_undo_put_image_data_calls: float
    local_undo_canvas_create_ms: float
    local_undo_canvas_create_calls: float
    local_undo_heap_delta_bytes: float
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

WebSocketFrame = tuple[int, str]

CANVAS_METRICS_INIT_SCRIPT = """
(() => {
  const state = {
    getImageDataCalls: 0,
    getImageDataMs: 0,
    getImageDataPixels: 0,
    putImageDataCalls: 0,
    putImageDataMs: 0,
    putImageDataPixels: 0,
    longTaskCount: 0,
    longTaskMs: 0,
    interactionEventCalls: 0,
    interactionEventMs: 0,
    interactionEventMaxMs: 0,
    canvasCreateCalls: 0,
    canvasCreateMs: 0,
  };
  const reset = () => {
    for (const key of Object.keys(state)) state[key] = 0;
  };
  const snapshot = () => ({ ...state });
  Object.defineProperty(window, "__sketchyCanvasMetrics", {
    value: { reset, snapshot },
    configurable: false,
  });

  const originalCreateElement = Document.prototype.createElement;
  Document.prototype.createElement = function(...args) {
    const isCanvas = String(args[0]).toLowerCase() === "canvas";
    const started = isCanvas ? performance.now() : 0;
    try {
      return originalCreateElement.apply(this, args);
    } finally {
      if (isCanvas) {
        state.canvasCreateCalls += 1;
        state.canvasCreateMs += performance.now() - started;
      }
    }
  };

  const interactionStarts = new WeakMap();
  for (const eventName of ["pointerdown", "pointermove", "pointerup", "click"]) {
    window.addEventListener(eventName, (event) => {
      interactionStarts.set(event, performance.now());
    }, true);
    window.addEventListener(eventName, (event) => {
      const started = interactionStarts.get(event);
      if (started === undefined) return;
      const duration = performance.now() - started;
      state.interactionEventCalls += 1;
      state.interactionEventMs += duration;
      state.interactionEventMaxMs = Math.max(
        state.interactionEventMaxMs,
        duration,
      );
    });
  }

  const contextPrototype = CanvasRenderingContext2D.prototype;
  const originalGetImageData = contextPrototype.getImageData;
  contextPrototype.getImageData = function(...args) {
    const started = performance.now();
    try {
      return originalGetImageData.apply(this, args);
    } finally {
      state.getImageDataCalls += 1;
      state.getImageDataMs += performance.now() - started;
      state.getImageDataPixels += Math.max(0, Number(args[2]) * Number(args[3]));
    }
  };

  const originalPutImageData = contextPrototype.putImageData;
  contextPrototype.putImageData = function(...args) {
    const started = performance.now();
    try {
      return originalPutImageData.apply(this, args);
    } finally {
      state.putImageDataCalls += 1;
      state.putImageDataMs += performance.now() - started;
      const imageData = args[0];
      if (imageData instanceof ImageData) {
        state.putImageDataPixels += imageData.width * imageData.height;
      }
    }
  };

  try {
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        state.longTaskCount += 1;
        state.longTaskMs += entry.duration;
      }
    });
    observer.observe({ type: "longtask", buffered: true });
  } catch {
    // Long Task observation is optional; readback instrumentation still works.
  }
})();
"""


async def reset_canvas_metrics(page: Page) -> dict[str, float]:
    """Reset injected counters and return a page-clock action start time."""
    return await page.evaluate(
        """() => {
          window.__sketchyCanvasMetrics.reset();
          return {
            started: performance.now(),
            heapBytes: performance.memory?.usedJSHeapSize ?? 0,
          };
        }"""
    )


async def read_canvas_metrics(
    page: Page,
    baseline: dict[str, float],
) -> dict[str, float]:
    """Read instrumented canvas costs using the browser's monotonic clock."""
    return await page.evaluate(
        """async (baseline) => {
          const actionDurationMs = performance.now() - baseline.started;
          await new Promise((resolve) => setTimeout(resolve, 0));
          return {
            actionDurationMs,
            jsHeapDeltaBytes:
              (performance.memory?.usedJSHeapSize ?? baseline.heapBytes)
              - baseline.heapBytes,
            ...window.__sketchyCanvasMetrics.snapshot(),
          };
        }""",
        baseline,
    )


def socketio_event_name(opcode: int, payload: str) -> str | None:
    """Return the event name from a text Socket.IO frame, if it has one."""
    if opcode != 1:
        return None
    array_start = payload.find("[")
    if array_start < 0:
        return None
    try:
        packet = json.loads(payload[array_start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(packet, list) or not packet or not isinstance(packet[0], str):
        return None
    return packet[0]


def socketio_event_frame_bytes(
    frames: list[WebSocketFrame],
    event_name: str,
) -> int:
    """Return the largest wire payload for a captured Socket.IO event."""
    largest = 0
    for index, (opcode, payload) in enumerate(frames):
        if socketio_event_name(opcode, payload) != event_name:
            continue
        candidate_bytes = len(payload.encode("utf-8"))
        for attachment_opcode, attachment in frames[index + 1:]:
            if attachment_opcode == 2:
                try:
                    candidate_bytes += len(base64.b64decode(attachment, validate=True))
                except (binascii.Error, ValueError):
                    candidate_bytes += len(attachment.encode("utf-8"))
                continue
            if attachment_opcode == 1:
                break
        largest = max(largest, candidate_bytes)
    return largest


def captured_socketio_events(frames: list[WebSocketFrame]) -> list[str]:
    """List captured Socket.IO event names for actionable diagnostics."""
    return sorted(
        {
            event_name
            for opcode, payload in frames
            if (event_name := socketio_event_name(opcode, payload)) is not None
        }
    )


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


async def set_cpu_throttle(context: BrowserContext, page: Page, rate: int) -> None:
    session = await context.new_cdp_session(page)
    await session.send("Emulation.setCPUThrottlingRate", {"rate": rate})


async def start_performance_trace(
    context: BrowserContext,
    page: Page,
) -> CDPSession:
    """Start a Chrome DevTools timeline trace for the measured interactions."""
    session = await context.new_cdp_session(page)
    await session.send(
        "Tracing.start",
        {
            "categories": (
                "devtools.timeline,v8,disabled-by-default-v8.gc,"
                "disabled-by-default-devtools.timeline"
            ),
            "transferMode": "ReturnAsStream",
        },
    )
    await session.send("HeapProfiler.enable")
    await session.send(
        "HeapProfiler.startSampling",
        {"samplingInterval": 32768},
    )
    return session


async def save_performance_trace(session: CDPSession, output: Path) -> None:
    """Finish a DevTools trace and save its raw JSON stream."""
    heap_profile = await session.send("HeapProfiler.stopSampling")
    heap_output = output.with_name(
        output.name.replace(".trace.json", ".heapprofile.json")
    )
    heap_output.parent.mkdir(parents=True, exist_ok=True)
    heap_output.write_text(
        json.dumps(heap_profile, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    loop = asyncio.get_running_loop()
    completed = loop.create_future()

    def on_complete(event: dict[str, Any]) -> None:
        if not completed.done():
            completed.set_result(event)

    session.once("Tracing.tracingComplete", on_complete)
    await session.send("Tracing.end")
    event = await asyncio.wait_for(completed, timeout=30)
    stream = event.get("stream")
    if not stream:
        raise RuntimeError("Chrome trace completed without a result stream")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as trace_file:
        while True:
            chunk = await session.send("IO.read", {"handle": stream})
            trace_file.write(chunk.get("data", ""))
            if chunk.get("eof"):
                break
    await session.send("IO.close", {"handle": stream})


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


async def select_drawing_tool(page: Page, name: str) -> None:
    """Select a drawing tool through either desktop or mobile controls."""
    tool = page.get_by_role(
        "button",
        name=re.compile(rf"^{re.escape(name)}(?: \(|$)"),
    )
    if await tool.count() and await tool.first.is_visible():
        await tool.first.click()
        return

    await page.get_by_role("button", name=re.compile(r"^Choose tool, current:")).click()
    await page.get_by_role("dialog", name="Choose tool").get_by_role(
        "button",
        name=name,
        exact=True,
    ).click()


async def click_canvas_action(page: Page, action: str) -> None:
    """Click Undo or Clear through either desktop or mobile controls."""
    accessible_name = {
        "Undo": re.compile(r"^Undo(?: last stroke)?$"),
        "Clear": re.compile(r"^Clear(?: canvas)?$"),
    }[action]
    await page.get_by_role("button", name=accessible_name).click()


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
) -> tuple[BrowserContext, BrowserContext, Page, Page, list[WebSocketFrame]]:
    context_options: dict[str, Any] = {
        "viewport": profile.viewport,
        "is_mobile": profile.is_mobile,
        "has_touch": profile.has_touch,
    }
    drawer_context = await browser.new_context(**context_options)
    guesser_context = await browser.new_context(**context_options)
    await drawer_context.add_init_script(CANVAS_METRICS_INIT_SCRIPT)
    drawer = await drawer_context.new_page()
    guesser = await guesser_context.new_page()
    websocket_frames: list[WebSocketFrame] = []

    await set_cpu_throttle(drawer_context, drawer, profile.cpu_throttle_rate)
    await set_cpu_throttle(guesser_context, guesser, profile.cpu_throttle_rate)
    guesser_cdp = await guesser_context.new_cdp_session(guesser)
    await guesser_cdp.send("Network.enable")
    guesser_cdp.on(
        "Network.webSocketFrameReceived",
        lambda event: websocket_frames.append(
            (
                int(event.get("response", {}).get("opcode", 1)),
                str(event.get("response", {}).get("payloadData", "")),
            )
        ),
    )

    await drawer.goto(base_url)
    await drawer.fill('input[placeholder="Display name"]', f"{profile.name}-drawer")
    await drawer.get_by_role("button", name="Create room", exact=True).click()
    await drawer.wait_for_url("**/create")
    await drawer.get_by_role("button", name="Create room", exact=True).click()
    await drawer.wait_for_url("**/room/**")
    await drawer.wait_for_selector('[data-testid="waiting-room"]')
    code = (await drawer.inner_text(".room-copy-button")).split("Code:")[1].strip()

    await guesser.goto(base_url)
    await guesser.fill('input[placeholder="Display name"]', f"{profile.name}-guesser")
    await guesser.fill('input[placeholder="ABC123"]', code)
    await guesser.click('button:has-text("Join by code")')
    await guesser.wait_for_selector('[data-testid="waiting-room"]')

    await drawer.wait_for_selector(".waiting-start-button:not([disabled])")
    await drawer.click(".waiting-start-button")
    await drawer.wait_for_selector(".prompt-choices button")
    await guesser.wait_for_selector('[data-testid="choosing-prompt-status"]')
    await drawer.click(".prompt-choices button:first-child")
    await drawer.wait_for_selector(".toolbar")
    await guesser.wait_for_selector("canvas.drawing-canvas")

    return drawer_context, guesser_context, drawer, guesser, websocket_frames


async def benchmark_profile(
    browser: Browser,
    profile: BrowserProfile,
    base_url: str,
    stroke_samples: int,
    replay_strokes: int,
    undo_samples: int,
    trace_output: Path | None = None,
) -> BenchmarkResult:
    (
        drawer_context,
        guesser_context,
        drawer,
        guesser,
        websocket_frames,
    ) = await create_game(
        browser,
        profile,
        base_url,
    )
    trace_session = (
        await start_performance_trace(drawer_context, drawer)
        if trace_output
        else None
    )

    try:
        # A fill of the untouched white canvas exercises the worst common fill
        # region while using the same toolbar and pointer path as a player.
        await select_drawing_tool(drawer, "Fill")
        fill_x, fill_y = await canvas_point(drawer, 0.5, 0.5)
        fill_local_started = await reset_canvas_metrics(drawer)
        fill_started = time.perf_counter()
        await drawer.mouse.click(fill_x, fill_y)
        fill_metrics = await read_canvas_metrics(drawer, fill_local_started)
        await wait_for_canvas_pixel(
            guesser,
            CANVAS_WIDTH // 2,
            CANVAS_HEIGHT // 2,
            (0, 0, 0),
        )
        fill_latency_ms = (time.perf_counter() - fill_started) * 1000

        # Exercise a large bounded region with nested outlines. This captures a
        # different neighbour/stack pattern than an untouched full-canvas fill.
        await click_canvas_action(drawer, "Clear")
        await wait_for_canvas_pixel(
            guesser,
            CANVAS_WIDTH // 2,
            CANVAS_HEIGHT // 2,
            (255, 255, 255),
        )
        await select_drawing_tool(drawer, "Rectangle")
        outer_start = await canvas_point(drawer, 0.12, 0.12)
        outer_end = await canvas_point(drawer, 0.88, 0.88)
        await draw_stroke(drawer, outer_start, outer_end, steps=2)
        await wait_for_canvas_pixel(
            guesser,
            round(CANVAS_WIDTH * 0.12),
            CANVAS_HEIGHT // 2,
            (0, 0, 0),
        )
        inner_start = await canvas_point(drawer, 0.32, 0.32)
        inner_end = await canvas_point(drawer, 0.68, 0.68)
        await draw_stroke(drawer, inner_start, inner_end, steps=2)
        await wait_for_canvas_pixel(
            guesser,
            round(CANVAS_WIDTH * 0.32),
            CANVAS_HEIGHT // 2,
            (0, 0, 0),
        )
        await select_drawing_tool(drawer, "Fill")
        complex_fill_x, complex_fill_y = await canvas_point(drawer, 0.20, 0.50)
        complex_fill_local_started = await reset_canvas_metrics(drawer)
        complex_fill_started = time.perf_counter()
        await drawer.mouse.click(complex_fill_x, complex_fill_y)
        complex_fill_metrics = await read_canvas_metrics(
            drawer,
            complex_fill_local_started,
        )
        await wait_for_canvas_pixel(
            guesser,
            round(CANVAS_WIDTH * 0.20),
            CANVAS_HEIGHT // 2,
            (0, 0, 0),
        )
        complex_fill_latency_ms = (
            time.perf_counter() - complex_fill_started
        ) * 1000

        # Clear the bounded fill and start a new brush stroke. record_stroke
        # deliberately discards pre-clear history when that next stroke begins.
        await click_canvas_action(drawer, "Clear")
        await wait_for_canvas_pixel(
            guesser,
            round(CANVAS_WIDTH * 0.20),
            CANVAS_HEIGHT // 2,
            (255, 255, 255),
        )
        await select_drawing_tool(drawer, "Brush")

        stroke_latencies: list[float] = []
        local_stroke_handler_ms: list[float] = []
        local_stroke_readback_ms: list[float] = []
        local_stroke_readback_calls: list[float] = []
        local_stroke_get_image_data_ms: list[float] = []
        local_stroke_get_image_data_calls: list[float] = []
        local_stroke_put_image_data_ms: list[float] = []
        local_stroke_put_image_data_calls: list[float] = []
        local_stroke_heap_deltas: list[float] = []
        for index in range(stroke_samples):
            normalized_y = 0.12 + (0.70 * index / max(1, stroke_samples - 1))
            start = await canvas_point(drawer, 0.10, normalized_y)
            end = await canvas_point(drawer, 0.28, normalized_y)
            pixel_x = round(CANVAS_WIDTH * 0.27)
            pixel_y = round(CANVAS_HEIGHT * normalized_y)
            local_started = await reset_canvas_metrics(drawer)
            started = time.perf_counter()
            await draw_stroke(drawer, start, end)
            local_metrics = await read_canvas_metrics(drawer, local_started)
            await wait_for_canvas_pixel(guesser, pixel_x, pixel_y, (0, 0, 0))
            stroke_latencies.append((time.perf_counter() - started) * 1000)
            local_stroke_handler_ms.append(local_metrics["interactionEventMs"])
            local_stroke_readback_ms.append(
                local_metrics["getImageDataMs"] + local_metrics["putImageDataMs"]
            )
            local_stroke_readback_calls.append(
                local_metrics["getImageDataCalls"] + local_metrics["putImageDataCalls"]
            )
            local_stroke_get_image_data_ms.append(local_metrics["getImageDataMs"])
            local_stroke_get_image_data_calls.append(
                local_metrics["getImageDataCalls"]
            )
            local_stroke_put_image_data_ms.append(local_metrics["putImageDataMs"])
            local_stroke_put_image_data_calls.append(
                local_metrics["putImageDataCalls"]
            )
            local_stroke_heap_deltas.append(local_metrics["jsHeapDeltaBytes"])

        # Add a denser history without waiting after every logical stroke. The
        # last pixel wait is an ordering barrier: Socket.IO delivers every
        # preceding stroke before it.
        replay_pixels: list[tuple[int, int]] = []
        for index in range(replay_strokes):
            column = index % 10
            row = index // 10
            normalized_x = 0.38 + column * 0.045
            normalized_y = 0.12 + row * 0.07
            start = await canvas_point(drawer, normalized_x, normalized_y)
            end = await canvas_point(drawer, normalized_x + 0.025, normalized_y)
            replay_pixels.append((
                round(CANVAS_WIDTH * (normalized_x + 0.02)),
                round(CANVAS_HEIGHT * normalized_y),
            ))
            await draw_stroke(drawer, start, end, steps=2)
        last_pixel = replay_pixels[-1]
        await wait_for_canvas_pixel(guesser, *last_pixel, (0, 0, 0))

        # Reloading the guesser triggers the same authoritative full-history
        # synchronization used after reconnects. Keep this measurement separate
        # from Undo, which now uses the incremental canvas_undo protocol event.
        websocket_frames.clear()
        await guesser.reload()
        await guesser.wait_for_selector("canvas.drawing-canvas")
        await wait_for_canvas_pixel(guesser, *last_pixel, (0, 0, 0))
        sync_frame_bytes = socketio_event_frame_bytes(websocket_frames, "sync_strokes")
        if sync_frame_bytes == 0:
            observed = ", ".join(captured_socketio_events(websocket_frames)) or "none"
            raise RuntimeError(
                "Did not capture a sync_strokes WebSocket frame after guesser reload; "
                f"observed Socket.IO events: {observed}"
            )

        undo_latencies: list[float] = []
        undo_durations: list[float] = []
        undo_handler_ms: list[float] = []
        undo_readback_ms: list[float] = []
        undo_readback_calls: list[float] = []
        undo_get_image_data_ms: list[float] = []
        undo_get_image_data_calls: list[float] = []
        undo_put_image_data_ms: list[float] = []
        undo_put_image_data_calls: list[float] = []
        undo_canvas_create_ms: list[float] = []
        undo_canvas_create_calls: list[float] = []
        undo_heap_deltas: list[float] = []
        measured_undo_samples = min(undo_samples, len(replay_pixels))
        for pixel in reversed(replay_pixels[-measured_undo_samples:]):
            undo_local_started = await reset_canvas_metrics(drawer)
            undo_started = time.perf_counter()
            await click_canvas_action(drawer, "Undo")
            undo_metrics = await read_canvas_metrics(drawer, undo_local_started)
            await wait_for_canvas_pixel(guesser, *pixel, (255, 255, 255))
            undo_latencies.append((time.perf_counter() - undo_started) * 1000)
            undo_durations.append(undo_metrics["actionDurationMs"])
            undo_handler_ms.append(undo_metrics["interactionEventMs"])
            undo_readback_ms.append(
                undo_metrics["getImageDataMs"] + undo_metrics["putImageDataMs"]
            )
            undo_readback_calls.append(
                undo_metrics["getImageDataCalls"] + undo_metrics["putImageDataCalls"]
            )
            undo_get_image_data_ms.append(undo_metrics["getImageDataMs"])
            undo_get_image_data_calls.append(undo_metrics["getImageDataCalls"])
            undo_put_image_data_ms.append(undo_metrics["putImageDataMs"])
            undo_put_image_data_calls.append(undo_metrics["putImageDataCalls"])
            undo_canvas_create_ms.append(undo_metrics["canvasCreateMs"])
            undo_canvas_create_calls.append(undo_metrics["canvasCreateCalls"])
            undo_heap_deltas.append(undo_metrics["jsHeapDeltaBytes"])

        result = BenchmarkResult(
            profile=profile.name,
            cpu_throttle_rate=profile.cpu_throttle_rate,
            stroke_samples=stroke_samples,
            stroke_latency_median_ms=statistics.median(stroke_latencies),
            stroke_latency_p95_ms=percentile(stroke_latencies, 0.95),
            local_stroke_handler_median_ms=statistics.median(local_stroke_handler_ms),
            local_stroke_handler_p95_ms=percentile(local_stroke_handler_ms, 0.95),
            local_stroke_readback_median_ms=statistics.median(local_stroke_readback_ms),
            local_stroke_readback_calls_median=statistics.median(local_stroke_readback_calls),
            local_stroke_get_image_data_median_ms=statistics.median(
                local_stroke_get_image_data_ms
            ),
            local_stroke_get_image_data_calls_median=statistics.median(
                local_stroke_get_image_data_calls
            ),
            local_stroke_put_image_data_median_ms=statistics.median(
                local_stroke_put_image_data_ms
            ),
            local_stroke_put_image_data_calls_median=statistics.median(
                local_stroke_put_image_data_calls
            ),
            local_stroke_heap_delta_median_bytes=statistics.median(
                local_stroke_heap_deltas
            ),
            large_fill_latency_ms=fill_latency_ms,
            local_fill_duration_ms=fill_metrics["actionDurationMs"],
            local_fill_handler_ms=fill_metrics["interactionEventMs"],
            local_fill_readback_ms=(
                fill_metrics["getImageDataMs"] + fill_metrics["putImageDataMs"]
            ),
            local_fill_readback_calls=int(
                fill_metrics["getImageDataCalls"] + fill_metrics["putImageDataCalls"]
            ),
            local_fill_get_image_data_ms=fill_metrics["getImageDataMs"],
            local_fill_get_image_data_calls=int(fill_metrics["getImageDataCalls"]),
            local_fill_put_image_data_ms=fill_metrics["putImageDataMs"],
            local_fill_put_image_data_calls=int(fill_metrics["putImageDataCalls"]),
            local_fill_pixels_read=int(fill_metrics["getImageDataPixels"]),
            local_fill_long_task_ms=fill_metrics["longTaskMs"],
            local_fill_heap_delta_bytes=int(fill_metrics["jsHeapDeltaBytes"]),
            complex_fill_latency_ms=complex_fill_latency_ms,
            local_complex_fill_duration_ms=complex_fill_metrics["actionDurationMs"],
            local_complex_fill_handler_ms=complex_fill_metrics["interactionEventMs"],
            local_complex_fill_readback_ms=(
                complex_fill_metrics["getImageDataMs"]
                + complex_fill_metrics["putImageDataMs"]
            ),
            local_complex_fill_readback_calls=int(
                complex_fill_metrics["getImageDataCalls"]
                + complex_fill_metrics["putImageDataCalls"]
            ),
            local_complex_fill_get_image_data_ms=complex_fill_metrics[
                "getImageDataMs"
            ],
            local_complex_fill_get_image_data_calls=int(
                complex_fill_metrics["getImageDataCalls"]
            ),
            local_complex_fill_put_image_data_ms=complex_fill_metrics[
                "putImageDataMs"
            ],
            local_complex_fill_put_image_data_calls=int(
                complex_fill_metrics["putImageDataCalls"]
            ),
            local_complex_fill_pixels_read=int(
                complex_fill_metrics["getImageDataPixels"]
            ),
            local_complex_fill_long_task_ms=complex_fill_metrics["longTaskMs"],
            local_complex_fill_heap_delta_bytes=int(
                complex_fill_metrics["jsHeapDeltaBytes"]
            ),
            undo_samples=measured_undo_samples,
            undo_replay_latency_ms=statistics.median(undo_latencies),
            undo_replay_latency_p95_ms=percentile(undo_latencies, 0.95),
            local_undo_duration_ms=statistics.median(undo_durations),
            local_undo_handler_ms=statistics.median(undo_handler_ms),
            local_undo_readback_ms=statistics.median(undo_readback_ms),
            local_undo_readback_calls=statistics.median(undo_readback_calls),
            local_undo_get_image_data_ms=statistics.median(undo_get_image_data_ms),
            local_undo_get_image_data_calls=statistics.median(
                undo_get_image_data_calls
            ),
            local_undo_put_image_data_ms=statistics.median(undo_put_image_data_ms),
            local_undo_put_image_data_calls=statistics.median(
                undo_put_image_data_calls
            ),
            local_undo_canvas_create_ms=statistics.median(undo_canvas_create_ms),
            local_undo_canvas_create_calls=statistics.median(
                undo_canvas_create_calls
            ),
            local_undo_heap_delta_bytes=statistics.median(undo_heap_deltas),
            sync_strokes_frame_bytes=sync_frame_bytes,
            retained_logical_strokes=(
                stroke_samples + replay_strokes - measured_undo_samples
            ),
        )
        if trace_session and trace_output:
            await save_performance_trace(trace_session, trace_output)
        return result
    finally:
        await drawer_context.close()
        await guesser_context.close()


def print_results(results: list[BenchmarkResult]) -> None:
    print()
    print("Sketchy canvas browser benchmark")
    print(
        "Profile             CPU  Remote p50  Remote p95  Local p50  Local p95  "
        "Large fill  Undo/replay  History  sync_strokes"
    )
    print("-" * 130)
    for result in results:
        print(
            f"{result.profile:<19} "
            f"{result.cpu_throttle_rate:>2}x  "
            f"{result.stroke_latency_median_ms:>8.1f}ms  "
            f"{result.stroke_latency_p95_ms:>8.1f}ms  "
            f"{result.local_stroke_handler_median_ms:>8.1f}ms  "
            f"{result.local_stroke_handler_p95_ms:>8.1f}ms  "
            f"{result.large_fill_latency_ms:>9.1f}ms  "
            f"{result.undo_replay_latency_ms:>9.1f}ms  "
            f"{result.retained_logical_strokes:>7}  "
            f"{result.sync_strokes_frame_bytes:>10,} B"
        )
    print()
    print(
        "Remote stroke measurements are drawer-to-guesser end-to-end latency; "
        "local stroke measurements sum synchronous pointer-handler time, including "
        "drawer rendering. Undo includes the server round trip and browser replay."
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
    parser.add_argument("--undo-samples", type=int, default=5)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--trace-dir",
        type=Path,
        help="write one DevTools timeline trace and heap profile per profile",
    )
    args = parser.parse_args()

    if args.stroke_samples < 2:
        parser.error("--stroke-samples must be at least 2")
    if not 1 <= args.replay_strokes <= 90:
        parser.error("--replay-strokes must be between 1 and 90")
    if not 1 <= args.undo_samples <= args.replay_strokes:
        parser.error("--undo-samples must be between 1 and --replay-strokes")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--mute-audio", "--enable-precise-memory-info"],
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
                        args.undo_samples,
                        (
                            args.trace_dir / f"{profile.name}.trace.json"
                            if args.trace_dir
                            else None
                        ),
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

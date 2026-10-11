"""A player who joins a fill-heavy turn watches it redraw rather than wait on
a frozen page (#1347).

Entering mid-turn replays the whole history onto the canvas. At 4x CPU a turn
of full-canvas fills used to take over a second in one task, the page taking no
input and drawing no frame for as long. A viewer's replay is now played out a
piece at a time. This fills a turn, joins it at 4x, and holds the joining page
to no replay-sized task from the moment its canvas arrives - and its canvas to
the drawer's pixels, with a fill drawn while its replay may still be running.

"Replay-sized" is measured against the replay itself, not the clock: the
pieces are the renderer's to size, and are held to one fill past budget by
`frontend/tests/protocolRenderer.test.mjs`.
"""
import asyncio
from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import BASE_URL, join_by_code, open_create_room, room_code, use_guest_name

CANVAS_PNG = "() => document.querySelector('canvas.drawing-canvas').toDataURL()"
# Each a full-canvas flood: at 4x a fill replays in ~11 ms on a laptop, so
# sixty are well over half a second in one task the old way (forty measured
# 353 ms), and a few dozen short pieces now.
FILLS = 60
CPU_THROTTLE = 4
# A guard against the one-task replay, not the acceptance measurement: #1347's
# 100 ms at 4x is the reference machine's (`BENCHMARK=thumbnail_browser`,
# 43 ms). No fixed bound separates the two on every machine. A CI runner at 4x
# is slower still - a fill there outlasts a whole piece, so each piece is one
# fill - and how slow varies from run to run: its longest task has been 115 ms
# and 210 ms, the second failing a 200 ms bound (#1442). At 64x on a laptop
# every piece is one fill, 180-260 ms, and the test's own `toDataURL` polls of
# the page are long tasks too. The old replay, meanwhile, is as little as half
# a second on a laptop at 4x.
#
# So the bound scales with the machine, through the one thing that slows with
# it: the replay. One task per fill is a sixtieth of it; the old replay is all
# of it. A task under the floor is never replay-sized - the old replay of
# these fills is over twice it even on a laptop.
LONGEST_TASK_SHARE_OF_REPLAY = 0.1
LONGEST_TASK_FLOOR_MS = 200

# Long tasks from the moment the canvas history arrives. The page has its own
# long tasks while it loads at 4x; the one that handles the history contains
# the moment it arrived, so a task counts if it ends at or after it.
WATCH_THE_REPLAY = """
window.__longTasks = [];
new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) window.__longTasks.push([entry.startTime, entry.duration]);
}).observe({ type: 'longtask', buffered: true });
const hook = setInterval(() => {
  const socket = window.__SKETCHY_SOCKET__;
  if (!socket) return;
  clearInterval(hook);
  socket.onAny((event) => {
    if (event === 'sync_strokes' && window.__syncAt === undefined) window.__syncAt = performance.now();
  });
}, 5);
"""
LONGEST_SINCE_SYNC = """
() => Math.max(0, ...window.__longTasks
  .filter(([start, duration]) => start + duration >= window.__syncAt)
  .map(([, duration]) => duration))
"""


async def _same_canvas(a, b, attempts: int = 150) -> None:
    for _ in range(attempts):
        if await a.evaluate(CANVAS_PNG) == await b.evaluate(CANVAS_PNG):
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the two canvases never matched")


async def test_a_mid_turn_entry_replays_a_fill_heavy_canvas_without_holding_the_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_page, player_page = [await (await browser.new_context()).new_page() for _ in range(2)]
        late_context = await browser.new_context()
        await late_context.add_init_script(WATCH_THE_REPLAY)
        late_page = await late_context.new_page()
        session = await late_context.new_cdp_session(late_page)
        await session.send("Emulation.setCPUThrottlingRate", {"rate": CPU_THROTTLE})
        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, f"FillHost{uuid4().hex[:6]}")
            await open_create_room(host_page)
            await host_page.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, f"FillView{uuid4().hex[:6]}")
            await join_by_code(player_page, code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
            drawing = host_page if await host_page.query_selector('.prompt-choices') else player_page
            viewing = player_page if drawing is host_page else host_page
            await drawing.click('.prompt-choices button:first-child')
            await drawing.wait_for_selector('canvas.drawing-canvas.drawable')

            await drawing.click('.toolbar-tools .tool-button[aria-label^="Fill"]')
            swatches = drawing.locator('.toolbar-colors .color-swatch')
            box = await (await drawing.query_selector('canvas.drawing-canvas')).bounding_box()
            centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            for index in range(FILLS):
                await swatches.nth(index % 2).click()
                await drawing.mouse.click(*centre)
            await _same_canvas(drawing, viewing)

            await late_page.goto(BASE_URL)
            await use_guest_name(late_page, f"FillLate{uuid4().hex[:6]}")
            await join_by_code(late_page, code)
            await late_page.wait_for_selector('canvas.drawing-canvas')
            await late_page.wait_for_function("() => window.__syncAt !== undefined", timeout=30_000)
            # Drawn while the entry's replay may still be playing out: painted
            # in its place, from the history, once the replay reaches it.
            await swatches.nth(2).click()
            await drawing.mouse.click(*centre)

            await _same_canvas(drawing, late_page)
            # An upper bound on the replay - it is over by the time the canvas
            # matches - which can only make the allowance more generous.
            replay_ms = await late_page.evaluate("() => performance.now() - window.__syncAt")
            longest = await late_page.evaluate(LONGEST_SINCE_SYNC)
            allowed = max(LONGEST_TASK_FLOOR_MS, LONGEST_TASK_SHARE_OF_REPLAY * replay_ms)
            assert longest < allowed, (
                f"a {longest:.0f} ms task held the joining page, of a {replay_ms:.0f} ms"
                " replay; its replay belongs in pieces"
            )
        finally:
            await browser.close()

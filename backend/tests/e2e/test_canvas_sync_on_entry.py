"""A canvas is sent once on entry, and a reconnect resumes from what it holds (#877).

A join used to push the whole history before its acknowledgement. On a fresh
join the canvas had not mounted to receive it, so the mount's own request loaded
the drawing a second time; on a reconnect it was a full dump to a viewer that
already held a verified prefix. Now the canvas asks - on mount, and once a new
socket has rebound its seat - claiming the prefix it holds.

Read off the socket rather than the canvas: the waste was invisible in pixels.
"""
import asyncio
from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name
from tests.e2e.test_canvas_commit_fanout import FrameLog, _draw_stroke, _named

BASE_URL = "http://localhost:8000"
CANVAS_PNG = "() => document.querySelector('canvas.drawing-canvas').toDataURL()"


def _full_syncs(frames) -> list:
    # `sync_strokes_tail` contains `sync_strokes`; count the full reply alone.
    return [frame for frame in _named(frames, "sync_strokes") if '"sync_strokes_tail"' not in frame]


async def _same_canvas(a, b) -> None:
    for _ in range(50):
        if await a.evaluate(CANVAS_PNG) == await b.evaluate(CANVAS_PNG):
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the two canvases never matched")


async def test_a_mid_turn_entry_gets_one_canvas_and_a_reconnect_gets_a_tail():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        pages = [await (await browser.new_context()).new_page() for _ in range(3)]
        host_page, player_page, late_page = pages
        logs = {id(page): FrameLog(page) for page in pages}
        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, f"EntryHost{uuid4().hex[:6]}")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)

            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, f"EntryView{uuid4().hex[:6]}")
            await join_by_code(player_page, code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
            drawing = host_page if await host_page.query_selector('.prompt-choices') else player_page
            viewing = player_page if drawing is host_page else host_page
            await drawing.click('.prompt-choices button:first-child')
            await drawing.wait_for_selector('canvas.drawing-canvas')
            await viewing.wait_for_selector('canvas.drawing-canvas')
            box = await (await drawing.query_selector('canvas.drawing-canvas')).bounding_box()
            for offset in (40, 120, 200):
                await _draw_stroke(drawing, box, offset)
            await _same_canvas(drawing, viewing)

            # A third player enters mid-turn: one full canvas, the one it asked for.
            await late_page.goto(BASE_URL)
            await use_guest_name(late_page, f"EntryLate{uuid4().hex[:6]}")
            await join_by_code(late_page, code)
            await late_page.wait_for_selector('canvas.drawing-canvas')
            await _same_canvas(drawing, late_page)
            await asyncio.sleep(1)
            assert len(_full_syncs(logs[id(late_page)].frames)) == 1, (
                "a mid-turn entry was sent the canvas more than once"
            )

            # The viewer's connection drops and comes back on a new socket. It
            # holds a verified prefix, so the answer is a tail, never a dump.
            viewer_log = logs[id(viewing)]
            watch_from = viewer_log.mark()
            await viewing.evaluate("() => window.__SKETCHY_SOCKET__.io.engine.close()")
            await viewer_log.wait_for("sync_strokes_tail")
            after = viewer_log.frames[watch_from:]
            assert _full_syncs(after) == [], "a reconnect with a verified prefix got a full dump"
            await _same_canvas(drawing, viewing)

            # And it keeps up afterwards: the next stroke reaches it as usual.
            await _draw_stroke(drawing, box, 260)
            await _same_canvas(drawing, viewing)
        finally:
            await browser.close()

"""A viewer's commits ride the frames that cause them (#418).

The server used to answer every committed drawing action with two room-wide
events: the rebroadcast of the drawer's frame, then a `canvas_commit` carrying
the four integers a viewer needs to advance its revision bookkeeping. The
commit now travels on the committing frame itself.

Two things have to hold, and only one of them is visible on the canvas. The
first is that the viewer stops receiving `canvas_commit` at all. The second is
that it still *processes* the commits, which is invisible in pixels - a viewer
whose bookkeeping falls behind renders exactly the same strokes.

Nothing forces it to notice, either, until something arrives that is checked
against its sequence. That is what the undo at the end is for: `canvas_undo` is
still an event of its own and refuses a sequence that is not the next one
expected, so a viewer that ignored its commits asks for a full resync there.
This therefore watches the socket rather than the canvas: no commit events in,
an undo accepted, and no resync of either shape out.
"""
import asyncio

import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import room_code, use_guest_name


BASE_URL = "http://localhost:8000"


def _named(frames, event: str) -> list:
    return [
        frame for frame in frames
        if isinstance(frame, str) and f'"{event}"' in frame
    ]


class FrameLog:
    """Every Socket.IO frame one page receives, in order."""

    def __init__(self, page):
        self.frames: list = []
        self._arrived = asyncio.Event()
        page.on("websocket", self._watch)

    def _watch(self, websocket) -> None:
        websocket.on("framereceived", self._record)

    def _record(self, payload) -> None:
        self.frames.append(payload)
        self._arrived.set()

    def mark(self) -> int:
        """The point from which the next assertions read."""
        return len(self.frames)

    async def wait_for(self, event: str) -> None:
        async with asyncio.timeout(5):
            while not _named(self.frames, event):
                self._arrived.clear()
                await self._arrived.wait()


async def _draw_stroke(page, box, offset: int) -> None:
    await page.mouse.move(box["x"] + offset, box["y"] + offset)
    await page.mouse.down()
    await page.mouse.move(box["x"] + offset + 90, box["y"] + offset + 60)
    await page.mouse.move(box["x"] + offset + 140, box["y"] + offset + 30)
    await page.mouse.up()


@pytest.mark.asyncio
async def test_a_viewer_gets_its_commits_on_the_frame_and_never_resyncs():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        host_frames = FrameLog(host_page)
        player_frames = FrameLog(player_page)
        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "CommitHost")
            await host_page.click('button:has-text("Create room")')
            # Private: a public room would sit in the lobby list the other
            # tests read.
            await host_page.click(
                '[role="group"][aria-label="Visibility"] button:has-text("Private")'
            )
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)

            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "CommitViewer")
            await player_page.fill('input[placeholder="ABC123"]', code)
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector(
                '.prompt-choices, [data-testid="choosing-prompt-status"]'
            )
            drawing = host_page if await host_page.query_selector('.prompt-choices') else player_page
            viewing = player_page if drawing is host_page else host_page
            viewer_frames = player_frames if viewing is player_page else host_frames
            await drawing.click('.prompt-choices button:first-child')
            await drawing.wait_for_selector('canvas.drawing-canvas')
            await viewing.wait_for_selector('canvas.drawing-canvas')

            canvas = await drawing.query_selector('canvas.drawing-canvas')
            box = await canvas.bounding_box()
            assert box is not None

            # Everything the viewer received while joining - including the
            # `sync_strokes` every turn start sends it - belongs to the past.
            watch_from = viewer_frames.mark()

            await _draw_stroke(drawing, box, 60)
            await _draw_stroke(drawing, box, 180)

            has_ink = """
                () => {
                  const canvas = document.querySelector('canvas.drawing-canvas');
                  const data = canvas.getContext('2d').getImageData(
                    0, 0, canvas.width, canvas.height
                  ).data;
                  for (let index = 0; index < data.length; index += 4) {
                    if (data[index] !== 255 || data[index + 1] !== 255
                        || data[index + 2] !== 255) return true;
                  }
                  return false;
                }
            """
            await viewing.wait_for_function(has_ink)

            # The undo is what makes a viewer that *ignored* its commits give
            # itself away. `canvas_undo` is still an event of its own, and the
            # client refuses one whose sequence is not the next it expects - so
            # a viewer two commits behind refuses this and asks for a full
            # resync, while a viewer that read them off the frames accepts it.
            await drawing.click("button.undo-button")
            await viewer_frames.wait_for("canvas_undo")
            # A resync is requested the moment the undo is refused, so a short
            # settle is enough for one to show up if it is going to. Proving an
            # event *absent* needs a window; this is that window.
            await viewing.wait_for_timeout(750)

            watched = viewer_frames.frames[watch_from:]
            assert _named(watched, "canvas_undo"), (
                "the undo never reached the viewer, so nothing was proven"
            )
            assert _named(watched, "canvas_commit") == [], (
                "the viewer was still sent a separate commit event"
            )
            # Both shapes of resync, because they are not interchangeable here.
            # A viewer that drifts still holds a *correct* history - only its
            # sequence is stale - so its prefix claim is accepted and it is
            # answered with the incremental tail, not the full dump. Watching
            # only for `sync_strokes` misses exactly the case this guards.
            resyncs = _named(watched, "sync_strokes") + _named(watched, "sync_strokes_tail")
            assert resyncs == [], (
                "the viewer's bookkeeping fell behind and it asked for a resync"
            )
        finally:
            await browser.close()

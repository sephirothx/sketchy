"""What a tab costs when it goes away and comes back (#886).

Every return to a visible tab used to re-bind the seat: a `join_room` and a
`sync_game` per seat per alt-tab, however short and however quiet. A hidden
tab keeps its socket and keeps receiving, so what matters is whether anything
authoritative arrived while it was away - the rule the heartbeat already uses
(#564).

Visibility is shimmed rather than emulated: Playwright cannot hide a page, and
a headless tab reports itself visible throughout.
"""
import asyncio
from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name
from tests.e2e.test_canvas_commit_fanout import FrameLog

BASE_URL = "http://localhost:8000"

HIDE = """
() => {
  Object.defineProperty(document, "visibilityState", {
    configurable: true, get: () => "hidden",
  });
  document.dispatchEvent(new Event("visibilitychange"));
}
"""

SHOW = """
() => {
  Object.defineProperty(document, "visibilityState", {
    configurable: true, get: () => "visible",
  });
  document.dispatchEvent(new Event("visibilitychange"));
}
"""


def sent(log, event: str) -> list:
    return [frame for frame in log.sent if isinstance(frame, str) and f'"{event}"' in frame]


class SentLog(FrameLog):
    """`FrameLog` records what arrives; this also records what goes out."""

    def __init__(self, page):
        self.sent: list = []
        super().__init__(page)

    def _watch(self, websocket) -> None:
        super()._watch(websocket)
        websocket.on("framesent", lambda frame: self.sent.append(frame))


async def test_a_short_quiet_return_rebinds_nothing_and_a_silent_one_does():
    tag = uuid4().hex[:6]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        pages = [await (await browser.new_context()).new_page() for _ in range(3)]
        host, guest, late = pages
        guest_log = SentLog(guest)
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, f"VisHost{tag}")
            await host.click('button:has-text("Create room")')
            await host.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, f"VisSeat{tag}")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await host.click(".waiting-start-button")
            await host.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
            drawing = host if await host.query_selector(".prompt-choices") else guest
            await drawing.click(".prompt-choices button:first-child")
            await guest.wait_for_selector("canvas.drawing-canvas")

            # Away, and something authoritative lands meanwhile: a third
            # player arriving is a `room_state` for everyone in the room.
            await asyncio.sleep(0.5)
            before = len(sent(guest_log, "join_room"))
            await guest.evaluate(HIDE)
            await late.goto(BASE_URL)
            await use_guest_name(late, f"VisLate{tag}")
            await join_by_code(late, code)
            await late.wait_for_selector("canvas.drawing-canvas, [data-testid='waiting-room']")
            await guest_log.wait_for("room_state")
            await guest.evaluate(SHOW)
            await asyncio.sleep(1)
            assert len(sent(guest_log, "join_room")) == before, (
                "a short return with a phase event in it asked the server again"
            )

            # Away again, and nothing arrives this time: that is what the
            # forced probe exists for, so the seat is re-bound on return.
            await guest.evaluate(HIDE)
            await asyncio.sleep(0.5)
            await guest.evaluate(SHOW)
            for _ in range(50):
                if len(sent(guest_log, "join_room")) > before:
                    break
                await asyncio.sleep(0.1)
            assert len(sent(guest_log, "join_room")) == before + 1, (
                "a return after a quiet spell re-binds the seat, once"
            )
        finally:
            await browser.close()

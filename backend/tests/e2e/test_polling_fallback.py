"""A browser whose WebSocket upgrades are blocked still plays, over polling (#601).

The client lists both transports, and until #601 that was all it did: without
`tryAllTransports` a blocked WebSocket was retried for ever against a polling
fallback the client had been told about. Here the guest's WebSocket routes are
closed before they open, so only polling can work; the host is untouched and
must still be on WebSocket. The guest joins, receives the drawer's stroke (a
canvas history over the binary sync path, then live frames), and guesses.
"""
from __future__ import annotations

from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name

BASE_URL = "http://localhost:8000"
CANVAS_WIDTH = 800
CANVAS_HEIGHT = 600


async def _pixel_is_dark(page, x: int, y: int) -> bool:
    return await page.evaluate(
        """([x, y]) => {
          const canvas = document.querySelector("canvas.drawing-canvas");
          if (!(canvas instanceof HTMLCanvasElement)) return false;
          const p = canvas.getContext("2d").getImageData(x, y, 1, 1).data;
          return p[0] < 40 && p[1] < 40 && p[2] < 40;
        }""",
        [x, y],
    )


async def test_a_browser_that_cannot_open_websockets_plays_over_polling():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()

        # Every WebSocket the guest opens is routed to a mock that never
        # speaks: the socket opens and then nothing arrives, which is what a
        # dropped upgrade looks like from a browser. HTTP, and so polling, is
        # untouched. A hang is the harder case - only an *error* while
        # opening moves Engine.IO to the next transport on its own - so this
        # exercises the client's stall watchdog rather than the library.
        blocked = []

        async def swallow(ws_route):
            blocked.append(ws_route.url)

        await guest.route_web_socket("**/socket.io/**", swallow)
        polling = []
        guest.on(
            "request",
            lambda request: polling.append(request.url) if "transport=polling" in request.url else None,
        )
        host_sockets = []
        host.on("websocket", lambda ws: host_sockets.append(ws.url))

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "WsHost")
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.wait_for_url("**/create")
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.wait_for_url("**/room/**")
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "PollGuest")
            await join_by_code(guest, code)
            # Joining waits for the socket: a silently dropped upgrade costs
            # one connection timeout (10 s) before polling is tried.
            await guest.wait_for_selector('[data-testid="waiting-room"]', timeout=45_000)
            assert blocked, "the guest's WebSocket was never even attempted"
            assert polling, "the guest did not fall back to polling"

            await host.wait_for_selector(".waiting-start-button:not([disabled])")
            await host.click(".waiting-start-button")
            await host.wait_for_selector(".prompt-choices button")
            await host.click(".prompt-choices button:first-child")
            await host.wait_for_selector(".toolbar")
            await guest.wait_for_selector("canvas.drawing-canvas", timeout=30_000)

            # A stroke from the host reaches the polling guest: live frames,
            # and the history the guest asks for on mount, both over polling.
            canvas = host.locator("canvas.drawing-canvas")
            box = await canvas.bounding_box()
            await host.mouse.move(box["x"] + box["width"] * 0.1, box["y"] + box["height"] * 0.5)
            await host.mouse.down()
            await host.mouse.move(box["x"] + box["width"] * 0.9, box["y"] + box["height"] * 0.5, steps=20)
            await host.mouse.up()
            await guest.wait_for_function(
                """() => {
                  const canvas = document.querySelector("canvas.drawing-canvas");
                  if (!(canvas instanceof HTMLCanvasElement)) return false;
                  const p = canvas.getContext("2d").getImageData(400, 300, 1, 1).data;
                  return p[0] < 40 && p[1] < 40 && p[2] < 40;
                }""",
                timeout=30_000,
            )
            assert await _pixel_is_dark(guest, CANVAS_WIDTH // 2, CANVAS_HEIGHT // 2)

            # And the guest can speak: a guess goes out and comes back as a line.
            await guest.fill('input[placeholder="Type your guess..."]', "a polling guess")
            await guest.press('input[placeholder="Type your guess..."]', "Enter")
            await guest.wait_for_selector("text=a polling guess", timeout=30_000)
            await host.wait_for_selector("text=a polling guess", timeout=30_000)

            assert host_sockets, "the host still opened a WebSocket"
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()

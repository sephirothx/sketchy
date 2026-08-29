import asyncio

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import room_code, use_guest_name


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_room_list_failure_retry_and_connection_banner():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        attempts = 0
        refusing = True
        # Nothing is answered until the test has seen the loading state, and
        # then everything is refused until the test stops refusing. Both halves
        # are load-bearing, and neither was true before.
        #
        # Sleeping in the handler instead - "hold the first one 250ms" - reads
        # the loading state against a clock: `page.goto` returns on `load`,
        # which is after the fonts, while the lobby's first request goes out as
        # soon as React mounts. On a busy machine the refusal has landed and
        # the loading state is gone by the time the assertion runs.
        #
        # Refusing only the *first* request has a second failure of its own.
        # The lobby polls, and it re-polls immediately whenever the poll
        # interval the server ships differs from the client's built-in 4000 -
        # which is the state another test on this same server leaves it in
        # while it proves a tuned cadence reaches a running browser. A second
        # request answered 200 before the first refusal landed loads the list,
        # and the refusal then renders as the "a refresh failed" warning rather
        # than the "never loaded" error this test is about. Measured against
        # that other test running alongside: 21 failures out of 21.
        answering = asyncio.Event()

        async def handle_rooms(route):
            nonlocal attempts
            attempts += 1
            if refusing:
                await answering.wait()
                await route.fulfill(status=503, json={"error": "unavailable"})
            else:
                await route.fulfill(status=200, json=[])

        await page.route("**/api/rooms", handle_rooms)
        try:
            await page.goto(BASE_URL)
            await page.wait_for_selector("text=Loading public rooms…")
            answering.set()
            await page.wait_for_selector('.room-list-error:has-text("Could not load public rooms")')

            refusing = False
            await page.click('.room-list-error button:has-text("Retry")')
            await page.wait_for_selector('text=No public rooms yet. Create one!')
            assert attempts >= 2

            # Name the player before the connection drops: seeding it reloads
            # the page, which offline emulation would block.
            await use_guest_name(page, "OfflinePlayer")
            await page.wait_for_selector('text=No public rooms yet. Create one!')

            await context.set_offline(True)
            await page.wait_for_selector('.connection-status-banner.offline:has-text("You’re disconnected")')
            await page.fill('input[placeholder="ABC123"]', "ABC123")
            await page.click('button:has-text("Join by code")')
            await page.wait_for_selector('.lobby-action-error:has-text("Connection lost")')
            assert await page.is_enabled('button:has-text("Join by code")')
            await context.set_offline(False)
            await page.wait_for_selector('.connection-status-banner', state="hidden", timeout=10000)
        finally:
            await context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_page_load_and_reload_never_show_the_connection_banner():
    """The socket connects after the identity lookup - that gap is not an outage."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()

        # The banner is only up while the socket opens, so polling for it would
        # miss it. Watch the DOM from before the first script runs instead.
        await page.add_init_script(
            """
            window.__bannerSeen = false;
            const check = () => {
              if (document.querySelector('.connection-status-banner')) {
                window.__bannerSeen = true;
              }
            };
            new MutationObserver(check).observe(document, {
              childList: true,
              subtree: true,
            });
            """
        )

        # Slow the identity lookup the socket waits on, so the gap this test is
        # about is wide enough to be more than a timing coincidence.
        async def handle_me(route):
            await asyncio.sleep(0.5)
            await route.continue_()

        await page.route("**/api/auth/me", handle_me)

        async def assert_no_banner_during_load():
            await page.wait_for_selector(".lobby-page")
            await page.wait_for_timeout(1000)
            # `is False`, not falsy: an undefined flag means the watcher never
            # ran, which would make this test pass without checking anything.
            assert await page.evaluate("window.__bannerSeen") is False, (
                "the connection banner appeared while the page was loading"
            )

        try:
            await page.goto(BASE_URL)
            await assert_no_banner_during_load()
            await page.reload()
            await assert_no_banner_during_load()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_mid_session_socket_reconnects_to_room():
    """Transport reconnect must rebind the active room session without a reload."""
    async with async_playwright() as p:
        browser1 = await p.chromium.launch(headless=True, args=["--mute-audio"])
        browser2 = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context1 = await browser1.new_context()
        context2 = await browser2.new_context()
        host = await context1.new_page()
        guest = await context2.new_page()

        # Proxy the guest's Socket.IO transport so the test can sever it on
        # demand; each reconnect attempt routes through here too.
        live_sockets = []

        async def route_socket(ws):
            ws.connect_to_server()
            live_sockets.append(ws)

        await guest.route_web_socket("**/socket.io/**", route_socket)

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "HostReconnect")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector(".room-copy-button")
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "GuestReconnect")
            await guest.fill('input[placeholder="ABC123"]', code)
            await guest.click('button:has-text("Join by code")')
            await guest.wait_for_selector(".room-copy-button")

            # Drop the transport at the socket itself rather than via offline
            # emulation: the frontend is same-origin with the backend, and
            # Chromium keeps a same-origin WebSocket alive across an offline
            # toggle, so toggling would not actually sever anything here.
            for _ in range(50):
                if live_sockets:
                    break
                await asyncio.sleep(0.1)
            assert live_sockets, (
                "guest never opened a Socket.IO WebSocket, so there is no "
                "transport to sever - it may have fallen back to polling"
            )
            await live_sockets[-1].close()
            # The banner waits a beat before announcing a drop, so a reconnect
            # that beats it is a pass, not a miss - what matters is that the
            # session comes back, which the assertions below cover. The banner
            # appearing at all is covered by the offline test above.
            #
            # Short timeout for exactly that reason: this is an optional
            # sighting, and locally the reconnect always wins the race, so a
            # long one is time the suite spends never seeing anything.
            try:
                await guest.wait_for_selector(
                    '.connection-status-banner.offline, .connection-status-banner.reconnecting',
                    timeout=1500,
                )
            except PlaywrightTimeoutError:
                pass
            await guest.wait_for_selector(".connection-status-banner", state="hidden", timeout=15000)

            await host.wait_for_selector("text=GuestReconnect reconnected", timeout=10000)

            await guest.fill(".waiting-chat-form input", "still here after reconnect")
            await guest.click(".waiting-chat-form button")
            await host.wait_for_selector("text=still here after reconnect", timeout=10000)
        finally:
            await context1.close()
            await context2.close()
            await browser1.close()
            await browser2.close()


@pytest.mark.asyncio
async def test_room_refresh_failure_keeps_last_successful_list():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        attempts = 0
        room = {
            "id": "resilient-room",
            "code": "STABLE",
            "name": "Last known room",
            "isPublic": True,
            "playerCount": 1,
            "spectatorCount": 0,
            "maxPlayers": 8,
            "isFull": False,
            "rounds": 3,
            "customPromptCount": 0,
            "customPromptsOnly": False,
            "drawingSeconds": 80,
            "hintMode": "none",
            "scoringMode": "default",
            "spectatorsSeePrompt": False,
            "hideMaskedPrompt": False,
            "allowedTools": ["brush", "fill", "shapes"],
            "colorMode": "all",
            "state": "waiting",
        }

        async def handle_rooms(route):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                await route.fulfill(status=200, json=[room])
            else:
                await route.fulfill(status=503, json={"error": "unavailable"})

        await page.route("**/api/rooms", handle_rooms)
        try:
            # The lobby re-polls on a four-second interval, and this test needs
            # the second poll - the one that fails. Fast-forwarding the page's
            # own clock gets there without spending the four seconds, and keeps
            # the interval a production constant rather than a test setting.
            await page.clock.install()
            await page.goto(BASE_URL)
            await page.wait_for_selector('[data-testid="public-room-card"]:has-text("Last known room")')
            await page.clock.fast_forward(5000)
            await page.wait_for_selector('.room-list-warning:has-text("Could not load public rooms")', timeout=7000)
            assert await page.is_visible('[data-testid="public-room-card"]:has-text("Last known room")')
        finally:
            await browser.close()

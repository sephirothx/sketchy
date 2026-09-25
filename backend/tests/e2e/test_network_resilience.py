import asyncio

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name


BASE_URL = "http://localhost:8000"


async def test_going_offline_banners_and_refuses_a_join():
    """The lobby's failure mode, now that the room list is not fetched.

    There is nothing left to retry: the list arrives on the socket, and a
    socket that is down is what the banner is for. What still has to hold is
    that a command issued into that outage is refused and gives its control
    back, rather than spinning on a promise nothing will ever settle.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            # Name the player before the connection drops: seeding it reloads
            # the page, which offline emulation would block.
            await use_guest_name(page, "OfflinePlayer")
            await page.wait_for_selector(".lobby-rooms-panel")

            await context.set_offline(True)
            await page.wait_for_selector(
                '.connection-status-banner.offline:has-text("You\u2019re disconnected")'
            )
            await join_by_code(page, "ABC123")
            await page.wait_for_selector('.lobby-action-error:has-text("Connection lost")')
            # The control that was refused, not the one that opened the sheet:
            # the header button is always enabled, so asserting on it would
            # pass whether or not the failed attempt released anything.
            assert await page.is_enabled('button:has-text("Join the room")')
            await context.set_offline(False)
            await page.wait_for_selector(".connection-status-banner", state="hidden", timeout=10000)
        finally:
            await context.close()
            await browser.close()


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
            await host.wait_for_selector('[data-testid="room-header"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "GuestReconnect")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="room-header"]')

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
            #
            # In the waiting room it is a header chip rather than a banner
            # (#797): a room lays itself out to the viewport, and a banner sat
            # on top of its header.
            notice = '.room-notice-chip[data-notice="connection"]'
            try:
                await guest.wait_for_selector(notice, timeout=1500)
            except PlaywrightTimeoutError:
                pass
            await guest.wait_for_selector(notice, state="hidden", timeout=15000)
            assert await guest.locator(".connection-status-banner").count() == 0

            await host.wait_for_selector("text=GuestReconnect reconnected", timeout=10000)
            await guest.wait_for_selector(
                '[data-testid="room-stage-paused"]', state="hidden", timeout=10000
            )

            await guest.fill(".waiting-chat-form input", "still here after reconnect")
            await guest.click(".waiting-chat-form button")
            await host.wait_for_selector("text=still here after reconnect", timeout=10000)
        finally:
            await context1.close()
            await context2.close()
            await browser1.close()
            await browser2.close()


async def test_a_dropped_socket_keeps_the_rooms_it_last_knew():
    """Losing the server must not blank the lobby.

    The room list is pushed now, so a reconnect abandons the revision sequence
    it was numbered in - but not the rooms themselves, which are public and
    were true a moment ago. The poll this replaced kept its last answer on
    screen for up to four seconds; a transport bounce that emptied the lobby
    would be a regression in what the reader sees for the sake of a counter.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        watcher_context = await browser.new_context()
        host = await host_context.new_page()
        watcher = await watcher_context.new_page()
        try:
            await watcher.goto(BASE_URL)
            await use_guest_name(watcher, "ListWatcher")
            await watcher.wait_for_selector(".lobby-rooms-panel")

            await host.goto(BASE_URL)
            await use_guest_name(host, "ListHost")
            await host.click('button:has-text("Create room")')
            await host.fill(
                'input[placeholder="Leave blank for a random name!"]', "Last known room"
            )
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')

            # Arrived with no reload and no request of its own: the watcher had
            # already been given its snapshot before this room existed.
            card = '[data-testid="public-room-card"]:has-text("Last known room")'
            await watcher.wait_for_selector(card)

            await watcher_context.set_offline(True)
            await watcher.wait_for_selector(".connection-status-banner.offline")
            assert await watcher.is_visible(card)
            assert not await watcher.is_visible(".lobby-rooms-panel .loading-note")

            await watcher_context.set_offline(False)
            await watcher.wait_for_selector(
                ".connection-status-banner", state="hidden", timeout=10000
            )
            await watcher.wait_for_selector(card)
        finally:
            await host_context.close()
            await watcher_context.close()
            await browser.close()


async def test_a_banner_makes_room_for_itself_on_the_pinned_lobby():
    """A desktop lobby is pinned to the viewport, so a banner above it in flow
    pushed its bottom off the screen (#797). It makes room for the stack now."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "PinnedLobby")
            await page.wait_for_selector(".lobby-rooms-panel")

            await context.set_offline(True)
            await page.wait_for_selector(".connection-status-banner.offline")
            # Polled rather than read once: the stack's height is published by a
            # ResizeObserver, which reports after the frame the banner arrived in.
            await page.wait_for_function(
                """() => {
                  const box = document.querySelector('.lobby-page').getBoundingClientRect();
                  return box.top > 0 && box.bottom <= innerHeight + 1;
                }""",
                timeout=5000,
            )
            await context.set_offline(False)
            await page.wait_for_selector(".connection-status-banner", state="hidden", timeout=10000)
        finally:
            await context.close()
            await browser.close()


async def test_a_notice_never_covers_a_phone_room_header():
    """A phone room is sized to the viewport, and a banner sat on its header and
    took the taps meant for the room menu (#797). The notice is a header chip
    there now, with the full sentence a tap away."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "PhoneNotices")
            await page.click('button:has-text("Create a room")')
            await page.wait_for_selector(".create-room-page")
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')

            await context.set_offline(True)
            chip = page.locator('.room-notice-chip[data-notice="connection"]')
            await chip.wait_for()
            assert await page.locator(".connection-status-banner").count() == 0
            # An outage that lasts pauses the stage (#823): a card says why, and
            # nothing under it takes input - but the header above it still does.
            paused = page.locator('[data-testid="room-stage-paused"]')
            await paused.wait_for(timeout=5000)
            assert await paused.get_attribute("data-cause") == "offline"
            assert await page.locator(".room-shell-main[inert]").count() == 1
            menu = page.locator('[data-testid="open-room-menu"]')
            menu_box = await menu.bounding_box()
            assert menu_box is not None
            hit = await page.evaluate(
                "([x, y]) => document.elementFromPoint(x, y)?.closest('[data-testid=\"open-room-menu\"]') !== null",
                [menu_box["x"] + menu_box["width"] / 2, menu_box["y"] + menu_box["height"] / 2],
            )
            assert hit, "something covers the room menu"
            await chip.click()
            await page.wait_for_selector(
                '.room-notice-popover:has-text("You\u2019re disconnected")'
            )
            await context.set_offline(False)
            await chip.wait_for(state="detached", timeout=10000)
            await paused.wait_for(state="detached", timeout=10000)
            assert await page.locator(".room-shell-main[inert]").count() == 0
            assert await page.locator(".room-notice-popover").count() == 0
            # A notice that comes back starts closed: the card is opened by a
            # tap, never by the last outage's.
            await context.set_offline(True)
            await chip.wait_for()
            await asyncio.sleep(0.3)
            assert await page.locator(".room-notice-popover").count() == 0
            await context.set_offline(False)
            await chip.wait_for(state="detached", timeout=10000)
        finally:
            await context.close()
            await browser.close()

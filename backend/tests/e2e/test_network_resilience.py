import asyncio

import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import use_guest_name


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_room_list_failure_retry_and_connection_banner():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        attempts = 0

        async def handle_rooms(route):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                await asyncio.sleep(0.25)
                await route.fulfill(status=503, json={"error": "unavailable"})
            else:
                await route.fulfill(status=200, json=[])

        await page.route("**/api/rooms", handle_rooms)
        try:
            await page.goto(BASE_URL)
            assert await page.is_visible("text=Loading public rooms…")
            await page.wait_for_selector('.room-list-error:has-text("Could not load public rooms")')

            await page.click('.room-list-error button:has-text("Retry")')
            await page.wait_for_selector('text=No public rooms yet. Create one!')
            assert attempts >= 2

            # Name the player before the connection drops: seeding it reloads
            # the page, which offline emulation would block.
            await use_guest_name(page, "OfflinePlayer")
            await page.wait_for_selector('text=No public rooms yet. Create one!')

            await context.set_offline(True)
            await page.wait_for_selector('.connection-status-banner.offline:has-text("You’re offline")')
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
async def test_mid_session_socket_reconnect_rejoins_room():
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
            code = (await host.inner_text(".room-copy-button")).split("Code:")[1].strip()

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
            await guest.wait_for_selector(
                '.connection-status-banner.offline, .connection-status-banner.reconnecting'
            )
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
            "customWordCount": 0,
            "customWordsOnly": False,
            "drawingSeconds": 80,
            "hintMode": "none",
            "scoringMode": "default",
            "spectatorsSeeSolution": False,
            "hideMaskedPrompt": False,
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
            await page.goto(BASE_URL)
            await page.wait_for_selector('[data-testid="public-room-card"]:has-text("Last known room")')
            await page.wait_for_selector('.room-list-warning:has-text("Could not load public rooms")', timeout=7000)
            assert await page.is_visible('[data-testid="public-room-card"]:has-text("Last known room")')
        finally:
            await browser.close()

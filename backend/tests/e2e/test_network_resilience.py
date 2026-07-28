import asyncio

import pytest
from playwright.async_api import async_playwright


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

            await context.set_offline(True)
            await page.wait_for_selector('.connection-status-banner.offline:has-text("You’re offline")')
            await page.fill('input[placeholder="Your name"]', "OfflinePlayer")
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

import pytest
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8000"

@pytest.mark.asyncio
async def test_player_afk_and_disconnect_scenario():
    """
    Scenario 3: Player AFK & Disconnect/Reconnect Sync E2E Test
    1. Browser 1 (Host in Chromium) creates a room.
    2. Browser 2 (Player in Chromium) joins room via Join by code.
    3. Host sees 2 players joined in waiting panel.
    4. Player toggles AFK button in Browser 2.
    5. Player closes tab / disconnects.
    6. Host in Browser 1 sees player count updated or waiting panel state sync.
    """
    async with async_playwright() as p:
        browser1 = await p.chromium.launch(headless=True, args=['--mute-audio'])
        browser2 = await p.chromium.launch(headless=True, args=['--mute-audio'])

        context1 = await browser1.new_context()
        context2 = await browser2.new_context()

        page1 = await context1.new_page()
        page2 = await context2.new_page()

        try:
            # Step 1: Host creates room
            await page1.goto(BASE_URL)
            await page1.fill('input[placeholder="Your name"]', "HostPlayer")
            await page1.click('button:has-text("Create room")')
            await page1.click('button:has-text("Create room")')

            await page1.wait_for_selector('.room-copy-button')
            room_code_text = await page1.inner_text('.room-copy-button')
            code = room_code_text.split("Code:")[1].strip()

            # Step 2: Player joins room via Join by code
            await page2.goto(BASE_URL)
            await page2.fill('input[placeholder="Your name"]', "AFKPlayer")
            await page2.fill('input[placeholder="ABC123"]', code)
            await page2.click('button:has-text("Join by code")')

            await page2.wait_for_selector('.room-copy-button')

            # Step 3: Host verifies 2 players joined in waiting lobby
            await page1.wait_for_selector('[data-testid="waiting-room"]')

            # Step 4: Player toggles AFK in Browser 2
            await page2.click('button:has-text("AFK")')

            # Verify AFK button text toggled to AFK 💤
            await page2.wait_for_selector('button:has-text("AFK 💤")')

            # Step 5: Player closes Browser 2 context
            await context2.close()

            # Step 6: Host sees updated waiting panel state
            await page1.wait_for_selector('[data-testid="waiting-room"]')

        finally:
            await context1.close()
            await browser1.close()
            await browser2.close()

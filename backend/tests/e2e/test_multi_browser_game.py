import pytest
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8000"

@pytest.mark.asyncio
async def test_multi_browser_gameplay_scenario():
    """
    Multi-browser test scenario:
    1. Browser 1 (Host in Chromium) creates a room and enters waiting lobby.
    2. Browser 2 (Player in Firefox) joins using room code in a separate browser context.
    3. Host sees 2 players joined in waiting lobby, clicks Start Game.
    4. Round starts: Drawer receives word choices, picks a word.
    5. Drawer draws on canvas.
    6. Guesser submits guess in chat.
    7. Both browsers sync in real time over Socket.IO.
    """
    async with async_playwright() as p:
        browser1 = await p.chromium.launch(headless=True)
        browser2 = await p.firefox.launch(headless=True)

        context1 = await browser1.new_context()
        context2 = await browser2.new_context()

        page1 = await context1.new_page()
        page2 = await context2.new_page()

        try:
            # Step 1: Host creates a room
            await page1.goto(BASE_URL)
            await page1.fill('input[placeholder="Your name"]', "HostAlice")
            await page1.click('button:has-text("Create room")')

            # Wait for navigation to room waiting panel
            await page1.wait_for_selector('.room-code')
            room_code_text = await page1.inner_text('.room-code')
            code = room_code_text.split("Code:")[1].split("(")[0].strip()
            assert len(code) > 0

            # Step 2: Player joins using room code from Browser 2 (Firefox)
            await page2.goto(BASE_URL)
            await page2.fill('input[placeholder="Your name"]', "BobGuesser")
            await page2.fill('input[placeholder="ABC123"]', code)
            await page2.click('button:has-text("Join by code")')

            # Wait for Browser 2 to enter waiting panel
            await page2.wait_for_selector('.room-code')

            # Step 3: Host verifies 2 players joined in waiting panel
            await page1.wait_for_selector('text=Waiting for players... (2 joined)')

            # Step 4: Host starts the game
            await page1.click('button:has-text("Start game")')

            # Both pages enter round / playing phase
            await page1.wait_for_selector('.game-layout')
            await page2.wait_for_selector('.game-layout')

            # Verify PlayerList rendered on both browsers
            await page1.wait_for_selector('.player-list')
            await page2.wait_for_selector('.player-list')

            # Step 5: Identify who is drawer and choose word if prompt choice is present
            drawer_page = page1 if await page1.query_selector('.word-choices') else page2
            guesser_page = page2 if drawer_page == page1 else page1

            if await drawer_page.query_selector('.word-choices button'):
                await drawer_page.click('.word-choices button:first-child')

            # Wait for drawing phase
            await drawer_page.wait_for_selector('canvas.drawing-canvas')
            await guesser_page.wait_for_selector('canvas.drawing-canvas')

            # Step 6: Drawer draws on canvas
            canvas = await drawer_page.query_selector('canvas.drawing-canvas')
            box = await canvas.bounding_box()
            assert box is not None

            # Draw a stroke across the canvas
            await drawer_page.mouse.move(box["x"] + 100, box["y"] + 100)
            await drawer_page.mouse.down()
            await drawer_page.mouse.move(box["x"] + 200, box["y"] + 200)
            await drawer_page.mouse.up()

            # Step 7: Guesser submits a guess in chat
            await guesser_page.fill('.chat-input input', 'apple')
            await guesser_page.keyboard.press('Enter')

            # Verify chat message container is present
            await guesser_page.wait_for_selector('.chat-messages')

        finally:
            await context1.close()
            await context2.close()
            await browser1.close()
            await browser2.close()

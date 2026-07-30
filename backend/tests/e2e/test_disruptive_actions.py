import pytest
from playwright.async_api import async_playwright


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_invite_feedback_and_active_game_leave_confirmation():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context(
            permissions=["clipboard-read", "clipboard-write"]
        )
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        host_page.set_default_timeout(10000)
        player_page.set_default_timeout(10000)

        try:
            await host_page.goto(BASE_URL)
            await host_page.fill('input[placeholder="Your name"]', "SafeHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.click('.room-copy-button')
            await host_page.wait_for_selector(
                '.app-toast.success:has-text("Invite link copied.")'
            )

            await host_page.evaluate(
                """
                () => Object.defineProperty(navigator, "clipboard", {
                  configurable: true,
                  value: { writeText: async () => { throw new Error("denied"); } },
                })
                """
            )
            await host_page.click('.room-copy-button')
            await host_page.wait_for_selector(
                '.app-toast.error:has-text("Couldn’t copy the link")'
            )

            code_text = await host_page.inner_text('.room-copy-button')
            code = code_text.split("Code:")[1].strip()
            await player_page.goto(BASE_URL)
            await player_page.fill('input[placeholder="Your name"]', "SafePlayer")
            await player_page.fill('input[placeholder="ABC123"]', code)
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector('.game-layout')
            await player_page.wait_for_selector('.game-layout')

            drawer_page = host_page if await host_page.query_selector('.word-choices') else player_page
            guesser_page = player_page if drawer_page == host_page else host_page

            await drawer_page.click('.game-header-leave-button')
            dialog = drawer_page.locator('[role="alertdialog"]')
            assert await dialog.is_visible()
            assert "Leave during your turn?" in await dialog.inner_text()
            assert "advance the game for everyone" in await dialog.inner_text()
            assert await drawer_page.evaluate(
                "() => document.activeElement?.textContent?.trim()"
            ) == "Cancel"

            await drawer_page.keyboard.press("Shift+Tab")
            assert await drawer_page.evaluate(
                "() => document.activeElement?.textContent?.trim()"
            ) == "Leave game"
            await drawer_page.keyboard.press("Tab")
            assert await drawer_page.evaluate(
                "() => document.activeElement?.textContent?.trim()"
            ) == "Cancel"
            await drawer_page.keyboard.press("Escape")
            await drawer_page.wait_for_selector('[role="alertdialog"]', state="hidden")
            assert await drawer_page.evaluate(
                "() => document.activeElement?.classList.contains('game-header-leave-button')"
            )

            await guesser_page.click('.game-header-leave-button')
            generic_dialog = guesser_page.locator('[role="alertdialog"]')
            assert "Leave active game?" in await generic_dialog.inner_text()
            assert "give up your place" in await generic_dialog.inner_text()
            await generic_dialog.locator('button:has-text("Leave game")').click()
            await guesser_page.wait_for_url(f"{BASE_URL}/")
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_waiting_room_leave_remains_immediate():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        page.set_default_timeout(10000)
        await page.add_init_script(
            """
            window.__sentSocketFrames = [];
            const originalSend = WebSocket.prototype.send;
            WebSocket.prototype.send = function(data) {
              if (typeof data === "string") window.__sentSocketFrames.push(data);
              return originalSend.call(this, data);
            };
            """
        )

        try:
            await page.goto(BASE_URL)
            await page.fill('input[placeholder="Your name"]', "WaitingLeaver")
            await page.click('button:has-text("Create room")')
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')

            room_code = (await page.inner_text(".room-copy-button")).split("Code:")[1].strip()
            await page.evaluate("window.__sentSocketFrames = []")
            await page.click('.game-header-leave-button')
            await page.wait_for_url(f"{BASE_URL}/")
            assert not await page.is_visible('[role="alertdialog"]')
            await page.wait_for_timeout(100)
            sent_frames = await page.evaluate("window.__sentSocketFrames")
            assert sum('"leave_room"' in frame for frame in sent_frames) == 1
            assert not any('"join_room"' in frame for frame in sent_frames)
            assert await page.evaluate(
                "(code) => localStorage.getItem(`sketchy_token_${code}`)",
                room_code,
            ) is None
        finally:
            await browser.close()

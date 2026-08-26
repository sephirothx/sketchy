import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import close_room_settings, open_room_settings
from tests.e2e.lobby_helpers import room_code as get_room_code, use_guest_name


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_players_approve_restart_without_losing_room_context():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        third_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        third_page = await third_context.new_page()
        host_page.set_default_timeout(12_000)
        player_page.set_default_timeout(12_000)
        third_page.set_default_timeout(12_000)

        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "RestartHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')

            room_code = await get_room_code(host_page)
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "RestartPlayer")
            await player_page.fill('input[placeholder="ABC123"]', room_code)
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            await third_page.goto(BASE_URL)
            await use_guest_name(third_page, "RestartThird")
            await third_page.fill('input[placeholder="ABC123"]', room_code)
            await third_page.click('button:has-text("Join by code")')
            await third_page.wait_for_selector('[data-testid="waiting-room"]')

            # Settings save themselves, so a value the room refuses has to snap
            # back to what the room holds and say why - three players seated is
            # exactly what makes a max of two impossible.
            await open_room_settings(host_page)
            await host_page.fill(
                '.room-settings-editor label:has-text("Max players") input', "2"
            )
            await host_page.wait_for_selector(
                '.app-toast:has-text("Max players cannot be below the 3 players")'
            )
            assert await host_page.input_value(
                '.room-settings-editor label:has-text("Max players") input'
            ) != "2"

            await player_page.fill(".waiting-chat-form input", "Keep this message")
            await player_page.click(".waiting-chat-form button")
            await host_page.wait_for_selector("text=Keep this message")

            await close_room_settings(host_page)
            await host_page.click('button:has-text("Start game")')
            await host_page.wait_for_selector(".game-layout")
            await player_page.wait_for_selector(".game-layout")
            await third_page.wait_for_selector(".game-layout")

            await host_page.click(".game-header-restart-button")
            host_vote = host_page.get_by_test_id("restart-vote-banner")
            player_vote = player_page.get_by_test_id("restart-vote-banner")
            third_vote = third_page.get_by_test_id("restart-vote-banner")
            await host_vote.wait_for()
            await player_vote.wait_for()
            await third_vote.wait_for()
            assert "1 yes" in await player_vote.inner_text()
            assert "2 needed" in await player_vote.inner_text()
            assert await host_vote.locator('button:has-text("Restart")').get_attribute(
                "aria-pressed"
            ) == "true"

            await player_vote.locator('button:has-text("Keep playing")').click()
            await host_page.wait_for_function(
                "document.querySelector('[data-testid=restart-vote-banner]')?.textContent.includes('1 no')"
            )
            await player_vote.locator('button:has-text("Restart")').click()

            await host_page.wait_for_selector(
                '[data-testid="restart-vote-banner"]:has-text("Restart approved")'
            )
            await player_page.wait_for_selector(
                '[data-testid="restart-vote-banner"]:has-text("Restart approved")'
            )
            await host_page.wait_for_selector(
                '[data-testid="restart-vote-banner"]', state="detached"
            )
            await player_page.wait_for_selector(
                '[data-testid="restart-vote-banner"]', state="detached"
            )
            await third_page.wait_for_selector(
                '[data-testid="restart-vote-banner"]', state="detached"
            )

            assert await host_page.is_visible("text=Keep this message")
            assert await host_page.is_visible(".player-list >> text=RestartHost")
            assert await host_page.is_visible(".player-list >> text=RestartPlayer")
            assert await host_page.is_visible(".player-list >> text=RestartThird")
            await host_page.wait_for_selector(".prompt-choices, [data-testid=choosing-prompt-status]")
            await player_page.wait_for_selector(".prompt-choices, [data-testid=choosing-prompt-status]")
            await third_page.wait_for_selector(".prompt-choices, [data-testid=choosing-prompt-status]")
        finally:
            await host_context.close()
            await player_context.close()
            await third_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_players_see_a_rejected_restart_and_cooldown():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        host_page.set_default_timeout(10_000)
        player_page.set_default_timeout(10_000)

        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "RejectHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            room_code = await get_room_code(host_page)

            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "RejectPlayer")
            await player_page.fill('input[placeholder="ABC123"]', room_code)
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            await host_page.click('button:has-text("Start game")')
            await host_page.wait_for_selector(".game-layout")
            await player_page.wait_for_selector(".game-layout")

            await host_page.click(".game-header-restart-button")
            player_vote = player_page.get_by_test_id("restart-vote-banner")
            await player_vote.wait_for()
            await player_vote.locator('button:has-text("Keep playing")').click()

            await host_page.wait_for_selector(
                '.chat-message:has-text("The restart vote was rejected.")'
            )
            await player_page.wait_for_selector(
                '.chat-message:has-text("The restart vote was rejected.")'
            )
            await host_page.wait_for_selector(
                '[data-testid="restart-vote-banner"]', state="detached"
            )
            restart_button = host_page.locator(".game-header-restart-button")
            assert await restart_button.is_disabled()
            assert "Restart vote available in" in (
                await restart_button.get_attribute("aria-label") or ""
            )
            assert await host_page.is_visible(
                "canvas.drawing-canvas, .prompt-choices, [data-testid=choosing-prompt-status]"
            )
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()

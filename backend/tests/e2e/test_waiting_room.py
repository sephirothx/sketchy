import pytest
from playwright.async_api import async_playwright


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_waiting_room_explains_rules_and_start_eligibility():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        try:
            await host_page.goto(BASE_URL)
            await host_page.fill('input[placeholder="Your name"]', "LobbyHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.fill('input[placeholder="Leave blank for a random name!"]', "Lobby details")
            await host_page.fill('label:has-text("Rounds") input', "2")
            await host_page.fill('label:has-text("Drawing time") input', "90")
            await host_page.click('button:has-text("Create room")')

            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            assert await host_page.is_visible('text=Lobby details')
            assert await host_page.is_visible('text=Players (1/8)')
            assert await host_page.is_visible('text=LobbyHost (you)')
            assert await host_page.is_visible('text=Host')
            assert await host_page.is_visible('text=2 rounds each · 90s to draw')
            assert await host_page.is_disabled('.waiting-start-button')
            assert await host_page.is_visible('text=Spectators, AFK, and disconnected players do not count.')

            code_text = await host_page.inner_text('.room-copy-button')
            code = code_text.split('Code:')[1].strip()
            await player_page.goto(BASE_URL)
            await player_page.fill('input[placeholder="Your name"]', "LobbyPlayer")
            await player_page.fill('input[placeholder="ABC123"]', code)
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.wait_for_selector('text=LobbyPlayer')
            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            assert await host_page.is_visible('text=2 active players are ready to play.')

            # The host can revise settings inline before the game, and everyone sees the update.
            await host_page.click('text=Edit room settings')
            await host_page.wait_for_selector('.room-settings-editor')
            await host_page.fill('.room-settings-editor label:has-text("Rounds") input', "4")
            await host_page.click('.room-settings-editor button:has-text("Save settings")')
            await player_page.wait_for_selector('text=4 rounds each · 90s to draw')

            # Waiting-room chat is shared before the game starts.
            await player_page.fill('.waiting-chat-form input', "Hello from the lobby")
            await player_page.click('.waiting-chat-form button')
            await host_page.wait_for_selector('text=Hello from the lobby')

            await player_page.click('button:has-text("AFK")')
            await host_page.wait_for_selector('text=LobbyPlayer')
            await host_page.wait_for_selector('.waiting-player-badges >> text=AFK')
            assert await host_page.is_disabled('.waiting-start-button')
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()

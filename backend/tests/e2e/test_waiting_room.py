import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import use_guest_name


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_waiting_room_shows_host_and_guest_settings_and_start_eligibility(
    assert_input_contract,
):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "LobbyHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.fill('input[placeholder="Leave blank for a random name!"]', "Lobby details")
            await host_page.fill('label:has-text("Rounds") input', "2")
            await host_page.fill('label:has-text("Drawing time") input', "90")
            await host_page.click('button:has-text("Create room")')

            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            assert await host_page.is_visible('text=Lobby details')
            assert await host_page.get_by_role("heading", name="Players").is_visible()
            assert await host_page.get_by_label("1 of 8 players").is_visible()
            assert await host_page.locator(".player-row.is-self").get_by_text("LobbyHost").is_visible()
            assert await host_page.get_by_label("Host", exact=True).is_visible()
            await host_page.wait_for_selector('.room-settings-editor')
            await assert_input_contract(
                host_page.locator('.room-settings-editor label:has-text("Room name") input'),
                {
                    "type": "search",
                    "role": None,
                    "inputMode": "text",
                    "autoComplete": "off",
                    "autoCapitalize": "sentences",
                    "spellCheck": True,
                    "autoCorrect": None,
                    "enterKeyHint": "done",
                },
            )
            assert not await host_page.is_visible('text=How this game will play')
            assert await host_page.input_value(
                '.room-settings-editor label:has-text("Rounds") input'
            ) == "2"
            assert await host_page.input_value(
                '.room-settings-editor label:has-text("Drawing time") input'
            ) == "90"
            advanced_summary = host_page.locator(
                '.room-settings-editor details > summary'
            )
            save_status = host_page.locator(
                '.room-settings-editor .room-settings-status'
            )
            collapsed_summary_box = await advanced_summary.bounding_box()
            collapsed_status_box = await save_status.bounding_box()
            assert collapsed_summary_box is not None
            assert collapsed_status_box is not None
            assert (
                collapsed_status_box["y"]
                - collapsed_summary_box["y"]
                - collapsed_summary_box["height"]
            ) >= 16

            await advanced_summary.click()
            final_advanced_setting = host_page.locator(
                '.room-settings-editor label:has-text("Only use custom prompts")'
            )
            expanded_setting_box = await final_advanced_setting.bounding_box()
            expanded_status_box = await save_status.bounding_box()
            assert expanded_setting_box is not None
            assert expanded_status_box is not None
            assert (
                expanded_status_box["y"]
                - expanded_setting_box["y"]
                - expanded_setting_box["height"]
            ) >= 16
            await advanced_summary.click()
            assert await host_page.is_disabled('.waiting-start-button')
            assert await host_page.is_visible('text=Spectators, AFK, and disconnected players do not count.')

            code_text = await host_page.inner_text('.room-copy-button')
            code = code_text.split('Code:')[1].strip()
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "LobbyPlayer")
            room_code_input = player_page.locator('input[placeholder="ABC123"]')
            await room_code_input.fill(code.lower())
            assert await room_code_input.input_value() == code
            await player_page.evaluate(
                """() => {
                    window.__inviteLoaderSeen = false;
                    new MutationObserver(() => {
                        if (document.querySelector(".invite-loading-card")) {
                            window.__inviteLoaderSeen = true;
                        }
                    }).observe(document.body, { childList: true, subtree: true });
                }"""
            )
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            assert not await player_page.evaluate("window.__inviteLoaderSeen")
            assert await player_page.is_visible('text=How this game will play')
            assert await player_page.is_visible('text=2 rounds each · 90s to draw')
            assert not await player_page.is_visible('.room-settings-editor')

            await host_page.wait_for_selector('text=LobbyPlayer')
            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            assert await host_page.is_visible('text=2 active players are ready to play.')

            # The host revises settings inline before the game and everyone sees
            # the update - with no Save button to forget (#325).
            await host_page.fill('.room-settings-editor label:has-text("Rounds") input', "4")
            await player_page.wait_for_selector('text=4 rounds each · 90s to draw')

            # ...and the lobby chat is not narrating every one of those saves.
            assert not await player_page.is_visible('text=The host updated the room settings.')

            # Custom prompts are the one thing that still waits to be applied -
            # a half-typed prompt list must not be stored a keystroke at a time -
            # so the Apply button says whether there is anything unapplied, and
            # leaving the textarea applies it whether or not the host presses it.
            await advanced_summary.click()
            await host_page.fill('#custom-prompts', "artichoke\nzeppelin")
            assert await host_page.inner_text('.custom-prompts-apply') == "Apply prompts"
            await host_page.keyboard.press("Tab")
            await player_page.wait_for_selector('text=2 custom prompts + curated lists')
            await host_page.wait_for_selector('.custom-prompts-apply:disabled')
            assert await host_page.inner_text('.custom-prompts-apply') == "Prompts applied"
            await advanced_summary.click()

            # Waiting-room chat is shared before the game starts.
            waiting_chat_input = player_page.locator('.waiting-chat-form input')
            await assert_input_contract(waiting_chat_input, {
                "type": "search",
                "role": None,
                "inputMode": "text",
                "autoComplete": "off",
                "autoCapitalize": "sentences",
                "spellCheck": True,
                "autoCorrect": None,
                "enterKeyHint": "send",
            })
            await waiting_chat_input.fill("Hello from the lobby")
            await waiting_chat_input.press("Enter")
            await host_page.wait_for_selector('text=Hello from the lobby')

            await player_page.click(".game-header-afk-button")
            await host_page.wait_for_selector('.player-row.is-afk:has-text("LobbyPlayer")')
            assert await host_page.is_disabled('.waiting-start-button')
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()

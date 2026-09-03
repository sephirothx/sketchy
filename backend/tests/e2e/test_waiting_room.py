import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import (
    open_room_menu,
    close_room_settings,
    open_room_settings,
    open_settings_section,
    room_code,
    save_room_settings,
    use_guest_name,
)


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
            # The crown sits on the avatar (#574); the name line still says it.
            assert await host_page.locator(".player-row.is-self").get_by_text("Host", exact=True).count() == 1
            await open_room_settings(host_page)
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
            # The editor is the creation form: the same four sections, in the
            # same order, so a room is described the same way wherever it is
            # being set up.
            assert await host_page.locator(
                '.room-settings-editor .form-section h2'
            ).all_inner_texts() == ["Basics", "Prompts", "Drawing", "Scoring and hints"]

            # Nothing is sent until Save, so it starts with nothing to send.
            save_button = host_page.locator('.room-settings-save')
            assert await save_button.is_disabled()
            assert await save_button.inner_text() == "Saved"

            last_setting = host_page.locator(
                '.room-settings-editor label:has-text("Only use custom prompts")'
            )
            await open_settings_section(host_page, "Prompts")
            setting_box = await last_setting.bounding_box()
            actions_box = await host_page.locator(
                '.room-settings-editor .room-settings-actions'
            ).bounding_box()
            assert setting_box is not None
            assert actions_box is not None
            assert (
                actions_box["y"] - setting_box["y"] - setting_box["height"]
            ) >= 16
            await open_settings_section(host_page, "Prompts")
            await close_room_settings(host_page)
            assert await host_page.is_disabled('.waiting-start-button')
            # The button carries its own blocking reason; what counts as an
            # active player is on its tooltip rather than a paragraph beside it.
            assert await host_page.inner_text('.waiting-start-button') == "Need 1 more player"
            assert "Spectators, AFK, and disconnected players do not count" in (
                await host_page.get_attribute('.waiting-start-button', 'title') or ""
            )

            code = await room_code(host_page)
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "LobbyPlayer")
            await player_page.click('button:has-text("Join by code")')
            await player_page.wait_for_selector('[data-testid="lobby-code-sheet"]')
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
            await player_page.click('button:has-text("Join the room")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            assert not await player_page.evaluate("window.__inviteLoaderSeen")
            assert await player_page.is_visible(
                '.waiting-settings-row:has-text("2 rounds · 90s")'
            )
            assert not await player_page.is_visible('.room-settings-editor')
            # A guest gets the summary, not a way in.
            assert await player_page.locator(
                '.waiting-settings-edit-button'
            ).count() == 0

            await host_page.wait_for_selector('text=LobbyPlayer')
            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            assert await host_page.inner_text('.waiting-start-button') == "Start game"

            # The draft is the host's until they submit it. Rounds and a prompt
            # list go in together, and the room hears about them once.
            await open_room_settings(host_page)
            await host_page.fill('.room-settings-editor label:has-text("Rounds") input', "4")
            await open_settings_section(host_page, "Prompts")
            await host_page.fill('#custom-prompts', "artichoke\nzeppelin")
            assert await host_page.inner_text('.room-settings-save') == "Save settings"
            # Nothing has left the host's screen yet.
            assert await player_page.is_visible(
                '.waiting-settings-row:has-text("2 rounds")'
            )

            await save_room_settings(host_page)
            await player_page.wait_for_selector(
                '.waiting-settings-row:has-text("4 rounds")'
            )

            # ...and the lobby chat is not narrating the save.
            assert not await player_page.is_visible('text=The host updated the room settings.')

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

            await open_room_menu(player_page)
            await player_page.click(".game-header-afk-button")
            await host_page.wait_for_selector('.player-row.is-afk:has-text("LobbyPlayer")')
            assert await host_page.is_disabled('.waiting-start-button')
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()

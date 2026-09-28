from uuid import uuid4

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import (
    close_room_settings,
    join_by_code,
    open_new_room,
    open_create_room,
    open_room_settings,
    open_settings_section,
    room_code,
    room_menu_action,
    save_room_settings,
    use_guest_name,
)


BASE_URL = "http://localhost:8000"


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
            await open_create_room(host_page)
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

            # Nothing is sent until Save, so it starts with nothing to send -
            # and says what it would do, not "Saved", which nothing was (#1279).
            save_button = host_page.locator('.room-settings-save')
            assert await save_button.is_disabled()
            assert await save_button.inner_text() == "Save room rules"

            last_setting = host_page.locator(
                '.room-settings-editor label:has-text("Only use custom prompts")'
            )
            await open_settings_section(host_page, "Prompts")
            # The actions are the dialog's footer: the form scrolls above
            # them, so however far down the last setting is, Save stays on
            # screen and the setting never runs underneath it.
            await last_setting.scroll_into_view_if_needed()
            setting_box = await last_setting.bounding_box()
            save_box = await save_button.bounding_box()
            viewport = host_page.viewport_size
            assert setting_box is not None
            assert save_box is not None
            assert viewport is not None
            assert (
                save_box["y"] - setting_box["y"] - setting_box["height"]
            ) >= 12
            assert save_box["y"] + save_box["height"] <= viewport["height"]
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
            await player_page.click('[data-testid="lobby-code-sheet"] button:text-is("Join")')
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            assert not await player_page.evaluate("window.__inviteLoaderSeen")
            # The room's facts as cells (#580): two rounds of 90s here.
            facts = player_page.get_by_test_id("waiting-facts")
            assert await facts.locator('[data-fact="rounds"] .room-fact-text').inner_text() == "2"
            assert await facts.locator('[data-fact="drawing-time"] .room-fact-text').inner_text() == "90s"
            # What the room seats, not who is in it: the roster says that,
            # beside its heading (#1279).
            players = facts.locator('[data-fact="players"]')
            assert await players.locator(".room-fact-label").text_content() == "Max players"
            assert " of " not in await players.locator(".room-fact-text").inner_text()
            assert not await player_page.is_visible('.room-settings-editor')
            # A guest gets the facts, not a way in.
            assert await player_page.locator(".waiting-rules-edit").count() == 0

            await host_page.wait_for_selector('text=LobbyPlayer')
            await host_page.wait_for_selector('.waiting-start-button:not([disabled])')
            assert await host_page.inner_text('.waiting-start-button') == "Start game"

            # The draft is the host's until they submit it. Rounds and a prompt
            # list go in together, and the room hears about them once.
            await open_room_settings(host_page)
            await host_page.fill('.room-settings-editor label:has-text("Rounds") input', "4")
            await open_settings_section(host_page, "Prompts")
            await host_page.fill('#custom-prompts', "artichoke\nzeppelin")
            assert await host_page.inner_text('.room-settings-save') == "Save room rules"
            # Nothing has left the host's screen yet.
            assert await facts.locator('[data-fact="rounds"] .room-fact-text').inner_text() == "2"

            await save_room_settings(host_page)
            await player_page.wait_for_selector(
                '[data-fact="rounds"] .room-fact-text:text-is("4")'
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

            await room_menu_action(player_page, "Go AFK")
            await host_page.wait_for_selector('.player-row.is-afk:has-text("LobbyPlayer")')
            assert await host_page.is_disabled('.waiting-start-button')
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()


async def test_a_phone_spectator_sees_they_are_watching_and_takes_an_open_seat():
    """#1269: a phone hides the players panel in the waiting room, and the
    seat offer lived only there - a spectator on a phone could not take a free
    seat and was never told they were spectating. The roster says both now,
    and lists the spectators under the seats."""
    phone = {
        "viewport": {"width": 390, "height": 844},
        "is_mobile": True,
        "has_touch": True,
    }
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(**phone), await browser.new_context(**phone)]
        host, watcher = [await context.new_page() for context in contexts]
        try:
            tag = uuid4().hex[:5]
            await host.goto(BASE_URL)
            await use_guest_name(host, f"SeatHost{tag}")
            await open_new_room(host)
            code = await room_code(host)
            name = f"SeatWatch{tag}"
            await watcher.goto(BASE_URL)
            await use_guest_name(watcher, name)
            await join_by_code(watcher, code, spectate=True)
            roster = watcher.locator(".waiting-roster")
            await roster.wait_for(state="visible")

            offer = roster.get_by_test_id("spectator-promotion")
            await offer.wait_for(state="visible")
            assert "You're spectating." in await offer.inner_text()
            assert "A player seat is open." in await offer.inner_text()
            watching = roster.locator(".waiting-roster-spectators")
            await watching.get_by_text(name).wait_for()
            # The host's roster lists the spectator too, and offers them nothing.
            await host.locator(".waiting-roster-spectators").get_by_text(name).wait_for()
            assert await host.locator(".waiting-roster").get_by_test_id("spectator-promotion").count() == 0

            # One offer in the page at a phone's width, not a hidden second one.
            assert await watcher.get_by_test_id("spectator-promotion").count() == 1
            await offer.get_by_role("button", name="Join as player").click()
            await offer.wait_for(state="detached")
            await watching.wait_for(state="detached")
            await roster.locator(".waiting-roster-grid .waiting-roster-tile", has_text=name).wait_for()
            # The offer is gone with the focus it had; the roster's heading takes it.
            await watcher.wait_for_function(
                "() => document.activeElement?.id === 'waiting-roster-title'"
            )

        finally:
            for context in contexts:
                await context.close()
            await browser.close()

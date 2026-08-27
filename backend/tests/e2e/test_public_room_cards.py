import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import room_code, use_guest_name


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_public_room_cards_explain_status_settings_and_actions(
    assert_input_contract,
):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        visitor_context = await browser.new_context(viewport={"width": 390, "height": 844})
        spectator_context = await browser.new_context()
        host = await host_context.new_page()
        player = await player_context.new_page()
        visitor = await visitor_context.new_page()
        spectator = await spectator_context.new_page()
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "CardHost")
            await host.click('button:has-text("Create room")')
            await host.fill('input[placeholder="Leave blank for a random name!"]', "Room cards")
            await host.fill('label:has-text("Max players") input', "3")
            await host.fill('label:has-text("Rounds") input', "2")
            await host.fill('label:has-text("Drawing time") input', "90")
            await host.click('summary:has-text("Prompts")')
            await host.fill('#custom-prompts', "apple, pear")
            await host.check('label:has-text("Only use custom prompts") input')
            await host.click('summary:has-text("Scoring and hints")')
            await host.get_by_role("button", name="No scoring").click()
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await visitor.goto(BASE_URL)
            await use_guest_name(visitor, "CardVisitor")
            card = visitor.locator('[data-testid="public-room-card"]', has_text="Room cards")
            await card.wait_for()
            room_search = visitor.locator(
                'input[placeholder="Search rooms by name or code"]'
            )
            await assert_input_contract(room_search, {
                "type": "search",
                "autoComplete": "off",
                "enterKeyHint": "search",
            })
            await room_search.fill("no matching room")
            assert not await card.is_visible()
            await room_search.fill("Room cards")
            await card.wait_for()
            assert await card.get_by_text("Waiting", exact=True).is_visible()
            assert await card.get_by_text("1/3", exact=True).is_visible()
            assert await card.get_by_text("2 rounds", exact=True).is_visible()
            assert await card.get_by_text("90s", exact=True).is_visible()
            assert await card.get_by_text("No scoring", exact=True).is_visible()
            assert await card.get_by_text("Custom prompts only", exact=True).is_visible()
            assert await card.get_by_role("button", name="Join", exact=True).is_visible()

            await player.goto(BASE_URL)
            await use_guest_name(player, "CardPlayer")
            await player.fill('input[placeholder="ABC123"]', code)
            await player.click('button:has-text("Join by code")')
            await player.wait_for_selector('[data-testid="waiting-room"]')
            await player.click('summary:has-text("Inspect 2 custom prompts")')
            prompt_list = player.locator('.waiting-custom-prompts-list')
            await prompt_list.wait_for()
            custom_prompt_search = player.locator(
                'input[placeholder="Search custom prompts…"]'
            )
            await assert_input_contract(custom_prompt_search, {
                "type": "search",
                "autoComplete": "off",
            })
            assert await prompt_list.get_by_text("apple", exact=True).is_visible()
            assert await prompt_list.get_by_text("pear", exact=True).is_visible()
            await custom_prompt_search.fill("app")
            assert await prompt_list.get_by_text("apple", exact=True).is_visible()
            assert not await prompt_list.get_by_text("pear", exact=True).is_visible()
            await custom_prompt_search.fill("")
            await player.get_by_role("button", name="Short", exact=True).click()
            assert await player.get_by_text("2 of 2 prompts match", exact=True).is_visible()
            assert not await host.is_visible(
                'summary:has-text("Inspect 2 custom prompts")'
            )
            await host.wait_for_selector('.waiting-start-button:not([disabled])')
            await host.click('.waiting-start-button')
            await host.wait_for_selector('.game-layout')

            await card.get_by_text("In progress", exact=True).wait_for()
            assert await card.get_by_role("button", name="Join in progress", exact=True).is_visible()
            await card.get_by_role("button", name="Join in progress", exact=True).click()
            await visitor.wait_for_selector('.game-layout')

            await spectator.goto(BASE_URL)
            await use_guest_name(spectator, "CardSpectator")
            spectator_card = spectator.locator('[data-testid="public-room-card"]', has_text="Room cards")
            await spectator_card.wait_for()
            await spectator_card.get_by_text("Full", exact=True).wait_for()
            assert await spectator_card.get_by_role("button", name="Spectate", exact=True).is_visible()
            assert await spectator_card.get_by_role("button", name="Join", exact=True).count() == 0
            await spectator_card.get_by_role("button", name="Spectate", exact=True).click()
            await spectator.wait_for_selector('.game-layout')
        finally:
            await host_context.close()
            await player_context.close()
            await visitor_context.close()
            await spectator_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_a_typed_name_is_enough_to_join_without_pressing_play_as_guest():
    """Typing a name and pressing Join means what pressing the block's own
    button means. The name is what provisions the account, so a visitor who
    skipped that button used to arrive as nobody, with an empty nickname."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        visitor_context = await browser.new_context()
        host = await host_context.new_page()
        visitor = await visitor_context.new_page()
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "DraftHost")
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector(".create-room-page")
            await host.fill(
                'input[placeholder="Leave blank for a random name!"]', "Draft welcome"
            )
            await host.click(".create-room-submit")
            await host.wait_for_selector('[data-testid="waiting-room"]')

            # No use_guest_name here: the name is typed and left sitting in the
            # first-run block, exactly as a hurried visitor leaves it.
            await visitor.goto(BASE_URL)
            await visitor.wait_for_selector(".first-run-guest-row input")
            await visitor.fill(".first-run-guest-row input", "DraftVisitor")
            card = visitor.locator(
                '[data-testid="public-room-card"]', has_text="Draft welcome"
            )
            await card.get_by_role("button", name="Join", exact=True).click()

            await visitor.wait_for_selector('[data-testid="waiting-room"]')
            assert await visitor.get_by_text("DraftVisitor", exact=True).is_visible()
            await host.get_by_text("DraftVisitor", exact=True).wait_for()
        finally:
            await host_context.close()
            await visitor_context.close()
            await browser.close()

import pytest
from playwright.async_api import async_playwright

from tests.e2e.guest_nickname import submit_guest_nickname


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_public_room_cards_explain_status_rules_and_actions(
    assert_input_contract,
):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        visitor_context = await browser.new_context(viewport={"width": 390, "height": 844})
        observer_context = await browser.new_context()
        host = await host_context.new_page()
        player = await player_context.new_page()
        visitor = await visitor_context.new_page()
        observer = await observer_context.new_page()
        try:
            await host.goto(BASE_URL)
            await host.click('button:has-text("Create room")')
            await submit_guest_nickname(host, "CardHost")
            await host.fill('input[placeholder="Leave blank for a random name!"]', "Room cards")
            await host.fill('label:has-text("Max players") input', "3")
            await host.fill('label:has-text("Rounds") input', "2")
            await host.fill('label:has-text("Drawing time") input', "90")
            await host.click('text=Advanced settings')
            await host.fill('#custom-words', "apple, pear")
            await host.check('label:has-text("Only use custom words") input')
            await host.get_by_role("button", name="Just for fun").click()
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = (await host.inner_text('.room-copy-button')).split("Code:")[1].strip()

            await visitor.goto(BASE_URL)
            card = visitor.locator('[data-testid="public-room-card"]', has_text="Room cards")
            await card.wait_for()
            room_search = visitor.locator(
                'input[placeholder="🔍 Search rooms by name or code..."]'
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
            assert await card.get_by_text("1/3 players", exact=True).is_visible()
            assert await card.get_by_text("2 rounds", exact=True).is_visible()
            assert await card.get_by_text("90s draws", exact=True).is_visible()
            assert await card.get_by_text("No scoring", exact=True).is_visible()
            assert await card.get_by_text("Custom words only", exact=True).is_visible()
            assert await card.get_by_role("button", name="Join", exact=True).is_visible()
            await card.get_by_text("View rules", exact=True).click()
            assert await card.get_by_text("2 custom words only", exact=True).is_visible()

            await player.goto(BASE_URL)
            await player.fill('input[placeholder="ABC123"]', code)
            await player.click('button:has-text("Join by code")')
            await submit_guest_nickname(player, "CardPlayer")
            await player.wait_for_selector('[data-testid="waiting-room"]')
            await player.click('summary:has-text("Inspect 2 custom words")')
            word_list = player.locator('.waiting-custom-words-list')
            await word_list.wait_for()
            custom_word_search = player.locator(
                'input[placeholder="Search custom words…"]'
            )
            await assert_input_contract(custom_word_search, {
                "type": "search",
                "autoComplete": "off",
            })
            assert await word_list.get_by_text("apple", exact=True).is_visible()
            assert await word_list.get_by_text("pear", exact=True).is_visible()
            await custom_word_search.fill("app")
            assert await word_list.get_by_text("apple", exact=True).is_visible()
            assert not await word_list.get_by_text("pear", exact=True).is_visible()
            await custom_word_search.fill("")
            await player.get_by_role("button", name="Short", exact=True).click()
            assert await player.get_by_text("2 of 2 words match", exact=True).is_visible()
            assert await player.get_by_label("Words to display").count() == 0
            assert not await host.is_visible(
                'summary:has-text("Inspect 2 custom words")'
            )
            await host.wait_for_selector('.waiting-start-button:not([disabled])')
            await host.click('.waiting-start-button')
            await host.wait_for_selector('.game-layout')

            await card.get_by_text("In progress", exact=True).wait_for()
            assert await card.get_by_role("button", name="Join in progress", exact=True).is_visible()
            await card.get_by_role("button", name="Join in progress", exact=True).click()
            await submit_guest_nickname(visitor, "CardVisitor")
            await visitor.wait_for_selector('.game-layout')

            await observer.goto(BASE_URL)
            observer_card = observer.locator('[data-testid="public-room-card"]', has_text="Room cards")
            await observer_card.wait_for()
            await observer_card.get_by_text("Full", exact=True).wait_for()
            assert await observer_card.get_by_role("button", name="Spectate", exact=True).is_visible()
            assert await observer_card.get_by_role("button", name="Join", exact=True).count() == 0
            await observer_card.get_by_role("button", name="Spectate", exact=True).click()
            await submit_guest_nickname(observer, "CardObserver")
            await observer.wait_for_selector('.game-layout')
        finally:
            await host_context.close()
            await player_context.close()
            await visitor_context.close()
            await observer_context.close()
            await browser.close()

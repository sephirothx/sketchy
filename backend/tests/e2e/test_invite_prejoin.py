import pytest
from playwright.async_api import async_playwright


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_invite_preview_join_spectate_full_room_and_reconnect(
    assert_input_contract,
):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        spectator_context = await browser.new_context()
        player_context = await browser.new_context()
        full_room_context = await browser.new_context()

        host_page = await host_context.new_page()
        spectator_page = await spectator_context.new_page()
        player_page = await player_context.new_page()
        full_room_page = await full_room_context.new_page()

        try:
            await host_page.goto(BASE_URL)
            await host_page.fill('input[placeholder="Your name"]', "InviteHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.fill('input[placeholder="Leave blank for a random name!"]', "Invite Test Room")
            await host_page.get_by_role("button", name="Private").click()
            await host_page.fill('label:has-text("Max players") input', "3")
            await host_page.click('button:has-text("Create room")')

            room_button = await host_page.wait_for_selector(".room-copy-button")
            room_code_text = await room_button.inner_text()
            room_code = room_code_text.split("Code:")[1].strip()
            invite_url = f"{BASE_URL}/room/{room_code}"

            # Previewing a private invite does not join the room.
            await spectator_page.goto(invite_url)
            await spectator_page.wait_for_selector("#invite-nickname")
            await assert_input_contract(spectator_page.locator("#invite-nickname"), {
                "type": "text",
                "inputMode": "text",
                "autoComplete": "nickname",
                "autoCapitalize": "words",
                "spellCheck": False,
                "autoCorrect": "off",
            })
            assert await spectator_page.is_visible("text=Invite Test Room")
            assert await spectator_page.is_visible("text=Private invite")
            assert await spectator_page.is_visible("text=1/3")
            await host_page.wait_for_selector('[data-testid="waiting-room"]')

            # Visitors can explicitly spectate.
            await spectator_page.fill("#invite-nickname", "InviteSpectator")
            await spectator_page.click('button:has-text("Spectate")')
            await spectator_page.wait_for_selector(".room-copy-button")
            spectator_indicator = host_page.locator('[data-testid="spectator-indicator"]')
            await spectator_indicator.wait_for()
            assert await spectator_indicator.locator(
                ".room-spectator-count"
            ).inner_text() == "1"
            spectator_tooltip = host_page.locator('[data-testid="spectator-tooltip"]')
            assert not await spectator_tooltip.is_visible()
            await spectator_indicator.hover()
            await spectator_tooltip.wait_for(state="visible")
            assert await spectator_tooltip.locator("text=InviteSpectator").is_visible()
            assert not await host_page.locator(
                '[data-testid="room-active-players"]'
            ).locator("text=InviteSpectator").is_visible()
            spectator_promotion = spectator_page.locator(
                '[data-testid="spectator-promotion"]'
            )
            assert await spectator_promotion.is_visible()
            assert await spectator_promotion.locator(
                "text=A player slot is available."
            ).is_visible()
            await spectator_promotion.locator(
                'button:has-text("Join as player")'
            ).click()
            await spectator_page.wait_for_selector(
                '[data-testid="room-active-players"] >> text=InviteSpectator'
            )
            await host_page.wait_for_selector(
                '[data-testid="room-active-players"] >> text=InviteSpectator'
            )
            assert not await host_page.is_visible('[data-testid="spectator-indicator"]')

            # Visitors can join as a player, and valid stored tokens reconnect on reload.
            await player_page.goto(invite_url)
            await player_page.wait_for_selector("#invite-nickname")
            await player_page.fill("#invite-nickname", "InvitePlayer")
            await player_page.click('button:has-text("Join game")')
            await player_page.wait_for_selector(".room-copy-button")
            await player_page.reload()
            await player_page.wait_for_selector(".room-copy-button")
            assert not await player_page.is_visible(".invite-card")

            # Once active-player capacity is full, spectating remains available.
            await full_room_page.goto(invite_url)
            await full_room_page.wait_for_selector("#invite-nickname")
            assert await full_room_page.is_disabled('button:has-text("Room full")')
            assert await full_room_page.is_visible("text=Spectating is still open.")
            await full_room_page.fill("#invite-nickname", "LateSpectator")
            await full_room_page.click('button:has-text("Spectate")')
            await full_room_page.wait_for_selector(".room-copy-button")
        finally:
            await host_context.close()
            await spectator_context.close()
            await player_context.close()
            await full_room_context.close()
            await browser.close()

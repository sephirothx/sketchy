import pytest
from playwright.async_api import async_playwright


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_invite_preview_join_spectate_full_room_and_reconnect():
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
            await host_page.fill('input[placeholder="Leave blank for a random name!"]', "Invite Test Room")
            await host_page.uncheck('label:has-text("Public (listed below)") input')
            await host_page.fill('label:has-text("Max players") input', "2")
            await host_page.click('button:has-text("Create room")')

            room_button = await host_page.wait_for_selector(".room-copy-button")
            room_code_text = await room_button.inner_text()
            room_code = room_code_text.split("Code:")[1].strip()
            invite_url = f"{BASE_URL}/room/{room_code}"

            # Previewing a private invite does not join the room.
            await spectator_page.goto(invite_url)
            await spectator_page.wait_for_selector("#invite-nickname")
            assert await spectator_page.is_visible("text=Invite Test Room")
            assert await spectator_page.is_visible("text=Private invite")
            assert await spectator_page.is_visible("text=1/2")
            await host_page.wait_for_selector('[data-testid="waiting-room"]')

            # Visitors can explicitly spectate.
            await spectator_page.fill("#invite-nickname", "InviteSpectator")
            await spectator_page.click('button:has-text("Spectate")')
            await spectator_page.wait_for_selector(".room-copy-button")

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

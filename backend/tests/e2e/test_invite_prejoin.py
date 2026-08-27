import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import room_code as get_room_code, use_guest_name


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
            await use_guest_name(host_page, "InviteHost")
            await host_page.click('button:has-text("Create room")')
            await host_page.fill('input[placeholder="Leave blank for a random name!"]', "Invite Test Room")
            await host_page.get_by_role("button", name="Private").click()
            await host_page.fill('label:has-text("Max players") input', "3")
            await host_page.click('button:has-text("Create room")')

            room_code = await get_room_code(host_page)
            invite_url = f"{BASE_URL}/room/{room_code}"

            # Previewing a private invite does not join the room.
            await spectator_page.goto(invite_url)
            # No name field here any more: the account already carries a
            # name, shown and editable in the header.
            assert await spectator_page.locator("#invite-nickname").count() == 0
            await spectator_page.wait_for_selector(".first-run, .identity-chip")

            assert await spectator_page.is_visible("text=Invite Test Room")
            assert await spectator_page.is_visible("text=Private invite")
            assert await spectator_page.is_visible("text=1/3")
            await host_page.wait_for_selector('[data-testid="waiting-room"]')

            # Visitors can explicitly spectate.
            # The invite screen no longer asks for a name - the account has one.
            await use_guest_name(spectator_page, "InviteSpectator")
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
            # This one names itself through the first-run block on the invite
            # screen rather than through use_guest_name, because that is the
            # cold path an invite link actually lands on: the block ships its
            # own <form>, and putting it inside another one used to leave the
            # submit unhandled, so the browser navigated and the page reloaded
            # with the typed name thrown away.
            await player_page.goto(invite_url)
            await player_page.wait_for_selector(".first-run")
            await player_page.evaluate("() => { window.__notReloaded = true; }")
            await player_page.fill(".first-run-guest-row input", "InvitePlayer")
            await player_page.click(".first-run-guest-submit")
            await player_page.wait_for_selector(".identity-chip")
            assert await player_page.evaluate("() => window.__notReloaded === true")
            await player_page.click('button:has-text("Join game")')
            await player_page.wait_for_selector(".room-copy-button")
            await player_page.reload()
            await player_page.wait_for_selector(".room-copy-button")
            assert not await player_page.is_visible(".invite-card")

            # Once active-player capacity is full, spectating remains available.
            await full_room_page.goto(invite_url)
            await full_room_page.wait_for_selector(".first-run, .identity-chip")
            assert await full_room_page.is_disabled('button:has-text("Room full")')
            assert await full_room_page.is_visible("text=Spectating is still open.")
            await use_guest_name(full_room_page, "LateSpectator")
            await full_room_page.click('button:has-text("Spectate")')
            await full_room_page.wait_for_selector(".room-copy-button")
        finally:
            await host_context.close()
            await spectator_context.close()
            await player_context.close()
            await full_room_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_a_typed_name_is_enough_to_join_from_an_invite():
    """The invite screen has no nickname field of its own: the name goes into
    the first-run block, and pressing Join must mean what pressing that
    block's own button means."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        visitor_context = await browser.new_context()
        host = await host_context.new_page()
        visitor = await visitor_context.new_page()
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "InviteDraftHost")
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector(".create-room-page")
            await host.click(".create-room-submit")
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await get_room_code(host)

            # Typed and left sitting: no "Play as guest" press.
            await visitor.goto(f"{BASE_URL}/room/{code}")
            await visitor.wait_for_selector(".first-run-guest-row input")
            await visitor.fill(".first-run-guest-row input", "InviteDrafter")
            await visitor.click('button:has-text("Join game")')

            await visitor.wait_for_selector(".room-copy-button")
            await host.get_by_text("InviteDrafter", exact=True).wait_for()
        finally:
            await host_context.close()
            await visitor_context.close()
            await browser.close()

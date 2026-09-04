"""Account identity end to end: guests, claiming, and seat ownership."""
import asyncio

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright, expect

from tests.e2e.lobby_helpers import join_by_code, register_account, room_code, use_guest_name

BASE_URL = "http://localhost:8000"


async def _create_room(page, name):
    await page.goto(BASE_URL)
    await use_guest_name(page, name)
    await page.click('button:has-text("Create room")')
    await page.click('button:has-text("Create room")')
    await page.wait_for_selector('[data-testid="waiting-room"]')
    return await room_code(page)


@pytest.mark.asyncio
async def test_guest_session_survives_a_reload_without_any_stored_credential():
    """Identity lives in an HttpOnly cookie, unreadable from JavaScript."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        try:
            code = await _create_room(page, "ReloadGuest")

            exposure = await page.evaluate(
                """() => ({
                    cookie: document.cookie,
                    storage: Object.keys(localStorage),
                })"""
            )
            assert "sketchy_session" not in exposure["cookie"]
            assert not any(k.startswith("sketchy_reconnect") for k in exposure["storage"])

            await page.reload()
            await page.wait_for_selector('[data-testid="waiting-room"]')
            assert code in await page.inner_text(".room-copy-button")
            name = page.locator(".player-name .colored-player-name").first
            assert "is-guest" in (await name.get_attribute("class"))
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_registering_keeps_the_seat_and_drops_the_guest_styling():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        try:
            await _create_room(page, "ClaimMe")
            seats = page.locator(".player-name .colored-player-name")
            # `count()` samples once; `to_have_count` waits for it. The list
            # arrives with `room_state`, so reading it the instant the room
            # renders is a race that fails as "wrong number of seats".
            await expect(seats).to_have_count(1)
            assert "is-guest" in (await seats.first.get_attribute("class"))

            await register_account(page, "ClaimedUser")

            # Same seat, upgraded in place - not a second player.
            await page.wait_for_function(
                """() => {
                    const names = document.querySelectorAll('.player-name .colored-player-name');
                    return names.length === 1 && names[0].textContent === 'ClaimedUser';
                }"""
            )
            assert "is-guest" not in (await seats.first.get_attribute("class"))
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_first_run_offers_an_account_first_and_guest_play_second():
    """The lobby is never gated, and the account is the headline action."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        try:
            await page.goto(BASE_URL)
            await page.wait_for_selector(".first-run")

            # Nothing modal, and the lobby is fully usable behind it.
            assert await page.locator(".modal-overlay").count() == 0
            assert await page.is_visible('button:has-text("Create room")')

            # A returning registered player can reach Log in without ever being
            # asked to invent a guest name.
            assert await page.is_visible(".first-run-login")
            assert await page.is_visible(".first-run-signup")

            # Guest play is one field and one click.
            await page.fill(".first-run-guest-row input", "ab")
            await page.click(".first-run-guest-submit")
            await page.wait_for_selector(".auth-error")

            await page.fill(".first-run-guest-row input", "Marta")
            await page.click(".first-run-guest-submit")
            await page.wait_for_selector('.identity-name:has-text("Marta")')

            # Asked once: the block never comes back.
            assert await page.locator(".first-run").count() == 0
            await page.reload()
            await page.wait_for_selector('.identity-name:has-text("Marta")')
            assert await page.locator(".first-run").count() == 0

            # And it is the name they play under.
            await page.click('button:has-text("Create room")')
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')
            assert "Marta" == await page.inner_text(
                ".player-name .colored-player-name"
            )
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_guest_renames_from_settings_and_cannot_take_a_username():
    """Renaming has exactly one home, and it respects registered names."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        owner_context = await browser.new_context()
        guest_context = await browser.new_context()
        owner = await owner_context.new_page()
        guest = await guest_context.new_page()
        try:
            await _create_room(owner, "OwnerGuest")
            await register_account(owner, "TakenName")

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "Wanderer")

            await guest.click(".header-settings-button")
            await guest.wait_for_selector(".settings-you")
            # Guests are pinned to grey, so there is no palette and no chip on
            # the disc; the account-only rows below are locked with a reason.
            assert await guest.locator(".settings-swatch").count() == 0
            assert await guest.is_visible(".settings-locked")

            # Only a guest can change the name (a registered player always
            # plays as their username), and it is the one thing on the card
            # the server can refuse, so it keeps a Save button of its own
            # where everything else applies at once.
            await guest.click('.settings-you button:has-text("Change")')
            await guest.fill("#settings-display-name", "takenname")
            await guest.click('.settings-you button:has-text("Save")')
            await guest.wait_for_selector("#settings-name-error")
            assert "registered player" in (
                await guest.inner_text("#settings-name-error")
            )

            await guest.fill("#settings-display-name", "Marta")
            await guest.click('.settings-you button:has-text("Save")')
            await guest.wait_for_selector('.identity-name:has-text("Marta")')
        finally:
            await owner_context.close()
            await guest_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_opening_the_same_room_twice_moves_the_seat_and_tells_the_old_tab():
    """One seat per account: the second tab takes it, the first is told why."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        first = await context.new_page()
        try:
            code = await _create_room(first, "TwoTabs")

            # Same context means the same cookie, so the same account.
            second = await context.new_page()
            await second.goto(f"{BASE_URL}/room/{code}")
            await second.wait_for_selector('[data-testid="waiting-room"]')

            await first.wait_for_url(f"{BASE_URL}/", timeout=15000)
            assert "another tab" in await first.inner_text('[role="dialog"], .modal-card')

            # Exactly one seat survives, held by the newer tab.
            seats = second.locator(".player-name .colored-player-name")
            await expect(seats).to_have_count(1)
        finally:
            await context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_game_end_asks_a_guest_to_claim_and_holds_the_countdown():
    """The strongest ask lands where there is something to lose.

    The overlay dismisses itself after ten seconds, so the countdown has to stop
    while the claim form is open or it would vanish mid-password.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        host.set_default_timeout(20000)
        guest.set_default_timeout(20000)
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "EndHost")
            await host.click('button:has-text("Create room")')
            rounds = int(await host.get_by_label("Rounds", exact=True).input_value())
            while rounds > 1:
                await host.get_by_role("button", name="Decrease Rounds").click()
                rounds -= 1
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "EndGuest")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')

            await host.click('button:has-text("Start game")')
            await host.wait_for_selector(".game-layout")
            await guest.wait_for_selector(".game-layout")

            # Play the turns out: the drawer takes the first prompt, the other
            # guesses it, until the game ends.
            #
            # Waits on the next phase actually arriving rather than on a fixed
            # sleep. The turn-results pause is configurable and E2E runs it at
            # half a second, so a sleep long enough to be safe here would be
            # several times the thing it is waiting for.
            for _ in range(6):
                if await host.query_selector('[data-testid="game-end-overlay"]'):
                    break
                drawer = host if await host.query_selector(".prompt-choices button") else guest
                other = guest if drawer is host else host
                choice = drawer.locator(".prompt-choices button").first
                try:
                    # Read and clicked with their own short deadline rather
                    # than checked and then clicked. The choosing phase has a
                    # deadline of its own, and the server picks for a drawer
                    # who runs out of time - so between finding this button
                    # and pressing it, it can stop existing. Under the suite's
                    # eight workers that is a real gap, and the default
                    # twenty-second click timeout turned it into a failure of
                    # this test rather than the tick it actually is.
                    prompt = (await choice.inner_text(timeout=2000)).strip()
                    await choice.click(timeout=2000)
                except PlaywrightTimeoutError:
                    prompt = None
                if prompt:
                    await drawer.wait_for_selector("canvas.drawing-canvas")
                    guess_input = other.locator(".chat-input input")
                    await guess_input.fill(prompt)
                    await guess_input.press("Enter")
                for _ in range(150):
                    if await host.query_selector('[data-testid="game-end-overlay"]'):
                        break
                    if await host.query_selector(".prompt-choices button") or (
                        await guest.query_selector(".prompt-choices button")
                    ):
                        break
                    await asyncio.sleep(0.1)

            await host.wait_for_selector('[data-testid="game-end-overlay"]', timeout=90000)
            assert await host.is_visible(".game-end-claim")
            assert "EndHost" in await host.inner_text(".game-end-claim-copy")

            await host.click(".game-end-claim-action")
            await host.wait_for_selector(".modal-card")
            assert "EndHost" == await host.input_value(".auth-form input")

            # Well past the ten-second dismissal had it kept running.
            await host.wait_for_timeout(4000)
            assert await host.is_visible('[data-testid="game-end-overlay"]')
            assert "s" not in (
                await host.inner_text(".game-end-actions button:last-child")
            ).split("room")[-1]
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_identity_controls_wait_for_provisioning_to_settle():
    """No identity UI while GET /api/auth/me is still in flight.

    A null user means "not known yet" as well as "nobody". Offering the
    controls in that window lets a submission race provisioning: both requests
    are cookieless, both create an account, and the later cookie discards the
    name that was just chosen.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()

        async def slow_provisioning(route):
            await asyncio.sleep(1.5)
            await route.continue_()

        await page.route("**/api/auth/me", slow_provisioning)
        try:
            await page.goto(BASE_URL)
            await page.wait_for_timeout(600)
            assert await page.locator(".first-run").count() == 0
            assert await page.locator(".identity-chip").count() == 0

            await page.wait_for_selector(".first-run", timeout=10000)
            await page.fill(".first-run-guest-row input", "RaceProof")
            await page.click(".first-run-guest-submit")
            await page.wait_for_selector('.identity-name:has-text("RaceProof")')

            # The name must not be clobbered by a late provisioning response.
            await page.wait_for_timeout(1500)
            assert await page.inner_text(".identity-name") == "RaceProof"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_player_can_download_then_delete_account_from_settings():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        try:
            await page.goto(BASE_URL)
            await register_account(page, "AccountDataE2E")
            # Both live in Settings > Account now: the identity menu is
            # navigation, and deleting an account is not navigation.
            await page.click("button.header-settings-button")
            await page.wait_for_selector('[data-testid="settings"]')
            await page.locator('.settings-row button:has-text("Request export")').click()
            dialog = page.locator(".account-data-dialog")
            await dialog.wait_for(state="visible")

            await dialog.get_by_role("button", name="Request export").click()
            download_link = dialog.get_by_role("link", name="Download")
            await download_link.wait_for(state="visible")
            async with page.expect_download() as pending_download:
                await download_link.click()
            download = await pending_download.value
            assert download.suggested_filename.startswith("sketchy-data-export-")
            assert download.suggested_filename.endswith(".json")

            await dialog.get_by_role("button", name="Close").click()
            await dialog.wait_for(state="hidden")

            # Deletion has a row and a dialog of its own now: it is not the
            # bottom of a panel called "Your data".
            await page.locator('.settings-row button:has-text("Delete…")').click()
            confirm = page.get_by_role("dialog", name="Delete your account")
            await confirm.wait_for(state="visible")
            await confirm.get_by_label("Password").fill("a-good-password")
            await confirm.get_by_label("Type DELETE to confirm").fill("DELETE")
            await confirm.get_by_role("button", name="Delete for good").click()

            await confirm.wait_for(state="hidden")
            await page.wait_for_selector(".first-run")
            current = await page.evaluate(
                """async () => {
                    const response = await fetch('/api/auth/me');
                    return response.json();
                }"""
            )
            # Deleting the account leaves the browser holding none at all,
            # and the first-run block above is what offers a new one. It used
            # to be handed a fresh guest by the act of asking.
            assert current is None
        finally:
            await browser.close()

"""Account identity end to end: guests, claiming, and seat ownership."""
import pytest
from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import register_account, use_guest_name

BASE_URL = "http://localhost:8000"


async def _create_room(page, name):
    await page.goto(BASE_URL)
    await use_guest_name(page, name)
    await page.click('button:has-text("Create room")')
    await page.click('button:has-text("Create room")')
    await page.wait_for_selector('[data-testid="waiting-room"]')
    code_text = await page.inner_text(".room-copy-button")
    return code_text.split("Code:")[1].strip()


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
            assert await seats.count() == 1
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
            await guest.wait_for_selector("#settings-display-name")
            # Guests are pinned to grey, so no colour picker is offered here.
            assert await guest.locator("#name-color-input").count() == 0
            assert await guest.is_visible(".settings-locked-hint")

            await guest.fill("#settings-display-name", "takenname")
            await guest.click('.settings-modal-footer button:has-text("Save")')
            await guest.wait_for_selector("#settings-name-error")
            assert "registered player" in (
                await guest.inner_text("#settings-name-error")
            )

            await guest.fill("#settings-display-name", "Marta")
            await guest.click('.settings-modal-footer button:has-text("Save")')
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
            assert await seats.count() == 1
        finally:
            await context.close()
            await browser.close()

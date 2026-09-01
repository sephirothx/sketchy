"""The page a URL with nothing behind it gets, and the status that comes with it."""
import pytest
from playwright.async_api import async_playwright, expect
from tests.e2e.a11y import assert_no_axe_violations
from tests.e2e.lobby_helpers import register_account, use_guest_name

BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_an_unknown_url_answers_404_and_offers_the_way_back():
    """R-UX-05. The status matters as much as the page.

    Before this existed the shell was served with a 200 and no route matched,
    so a mistyped link was a header over empty space - and a crawler or an
    uptime probe was told the page was fine.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, args=["--mute-audio"]
        )
        page = await browser.new_page()
        page.set_default_timeout(10000)

        try:
            response = await page.goto(f"{BASE_URL}/lobbyy")
            assert response is not None
            assert response.status == 404

            await expect(
                page.get_by_role("heading", name="Nobody drew this page")
            ).to_be_visible()
            await assert_no_axe_violations(page, "not found")

            await page.get_by_role("button", name="Back to lobby").click()
            await page.wait_for_url(f"{BASE_URL}/")
            await expect(
                page.get_by_role("button", name="Create room")
            ).to_be_visible()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_a_staff_route_shows_the_same_page_to_everyone_else():
    """R-ROLE-01, on the client side of the door.

    The endpoints behind these entries answer 404 rather than 403 so they never
    confirm the surface exists. A page that names the surface and refuses it
    gives that away, so it says exactly what a mistyped URL says. The route is
    real, so the status stays 200 - it is the account that is refused, and the
    API is what refuses it.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, args=["--mute-audio"]
        )
        page = await browser.new_page()
        page.set_default_timeout(10000)

        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "OrdinaryPlayer")
            await register_account(page, "OrdinaryPlayer")

            for route in ("/moderation", "/admin/operations", "/admin/bug-reports"):
                response = await page.goto(f"{BASE_URL}{route}")
                assert response is not None
                assert response.status == 200, route
                await expect(
                    page.get_by_role("heading", name="Nobody drew this page")
                ).to_be_visible()
        finally:
            await browser.close()

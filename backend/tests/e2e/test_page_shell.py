"""One header on every page (R-UX-11): the wordmark and the identity chip sit
in the same place whatever width the page's own content keeps."""
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import use_guest_name
from tests.e2e.test_friends import unique

BASE_URL = "http://localhost:8000"


async def test_the_lobby_header_is_whole_and_where_every_page_has_it():
    """At a laptop's 1280 x 800 the lobby is pinned to the window, and the
    header reaches out of its 928px column to the shell. The pinned page used
    to clip everything outside the column, which cut the wordmark and the chip
    off entirely - a lobby with no way to Settings or the account menu."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        try:
            await use_guest_name(page, unique("Shell"))
            await page.goto(BASE_URL)
            chip = page.locator(".lobby-header .identity-chip")
            home = page.locator(".lobby-header .header-home-link")
            await chip.wait_for()

            # Whole, and inside the window.
            for control in (chip, home):
                box = await control.bounding_box()
                assert box is not None
                assert box["x"] >= 0 and box["x"] + box["width"] <= 1280, box

            # And answering: a click reaches it rather than a clipped nothing.
            await chip.click()
            await expect(page.locator(".account-dropdown")).to_be_visible()
            await page.keyboard.press("Escape")
            lobby_chip = await chip.bounding_box()
            lobby_home = await home.bounding_box()

            # The same place on a page with a column of another width.
            await page.goto(f"{BASE_URL}/rules")
            await page.get_by_role("heading", name="Rules", exact=True).wait_for()
            rules_chip = await chip.bounding_box()
            rules_home = await home.bounding_box()
            assert abs(rules_chip["x"] - lobby_chip["x"]) <= 1, (rules_chip, lobby_chip)
            assert abs(rules_home["x"] - lobby_home["x"]) <= 1, (rules_home, lobby_home)
        finally:
            await context.close()
            await browser.close()

"""The community catalogue, opened by a reader with no account (#757).

Browsing is open on purpose: a published list is public by its owner's
deliberate act (R-LIST-14), and a link somebody shares has to work for
whoever opens it. The empty state is what a fresh deployment shows, so it is
the first thing anyone sees and worth having drawn rather than defaulted.
"""
from playwright.async_api import async_playwright, expect

BASE_URL = "http://localhost:8000"


async def test_the_catalogue_opens_for_a_reader_with_no_account():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(10000)
        try:
            await page.goto(f"{BASE_URL}/community-lists")

            await expect(
                page.get_by_role("heading", name="Community catalogue")
            ).to_be_visible()
            # Nothing is published on a fresh server, and the page says so
            # rather than showing an empty frame somebody has to interpret.
            await expect(
                page.get_by_text("Nobody has published a list yet.")
            ).to_be_visible()
            # The tag vocabulary is served to a signed-out reader too, so the
            # filters are usable before anybody has an account. Fifteen chips
            # would outweigh every other filter on the bar, so they are folded
            # behind a count and opening them is part of the check.
            tags = page.get_by_role("button", name="Tags", exact=True)
            await expect(tags).to_be_visible()
            await tags.click()
            await expect(
                page.get_by_role("button", name="Animals", exact=True)
            ).to_be_visible()
        finally:
            await context.close()
            await browser.close()

"""The prompt stats page: reachable, sortable, and honest about thin data."""
import pytest
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_prompt_stats_page_loads_sorts_and_is_linked_from_the_picker():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()

        try:
            # Reached the way a player would: from the prompt list picker.
            await page.goto(f"{BASE_URL}/create")
            link = page.get_by_role("link", name="English — Standard")
            await link.wait_for()
            assert await link.get_attribute("href") == "/prompt-lists/english_standard"

            await page.goto(f"{BASE_URL}/prompt-lists/english_standard")
            await page.get_by_role("heading", name="English — Standard").wait_for()

            # How much has been recorded is not ours to assume: the suite shares
            # one server, and tests running alongside this one are playing games
            # into the same database. So assert the guarantee rather than the
            # contents - whatever the page ranks, it ranked on a real sample.
            await page.locator(".prompt-stats-note, .prompt-stats-table").first.wait_for()
            rows = page.locator(".prompt-stats-table tbody tr")
            for index in range(await rows.count()):
                guessers = await rows.nth(index).locator("td").last.inner_text()
                assert int(guessers) >= 5, f"ranked a prompt with {guessers} guessers"

            # The sort is in the URL, so a chosen view can be linked to.
            await page.select_option("#prompt-stats-sort", "most-picked")
            await page.wait_for_url("**/prompt-lists/english_standard?sort=most-picked")
            assert await page.locator("#prompt-stats-sort").input_value() == "most-picked"

            # An unknown list says so rather than showing an empty table.
            await page.goto(f"{BASE_URL}/prompt-lists/not-a-real-list")
            await page.get_by_text("There is no prompt list with that name.").wait_for()
        finally:
            await browser.close()

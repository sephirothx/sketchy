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

            # Either the table or the note explaining why there is not one, but
            # never a bare empty page: which of the two shows depends on how
            # much has been played on this server, and both are correct.
            table = page.locator(".prompt-stats-table")
            note = page.locator(".prompt-stats-note")
            await page.wait_for_function(
                """() => document.querySelector('.prompt-stats-table')
                       || [...document.querySelectorAll('.prompt-stats-note')]
                            .some(n => !n.textContent.includes('Loading'))"""
            )
            assert await table.count() or await note.count()

            # The sort is in the URL, so a chosen view can be linked to.
            await page.select_option("#prompt-stats-sort", "most-picked")
            await page.wait_for_url("**/prompt-lists/english_standard?sort=most-picked")
            assert await page.locator("#prompt-stats-sort").input_value() == "most-picked"

            # An unknown list says so rather than showing an empty table.
            await page.goto(f"{BASE_URL}/prompt-lists/not-a-real-list")
            await page.get_by_text("There is no prompt list with that name.").wait_for()
        finally:
            await browser.close()

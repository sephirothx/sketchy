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
            # Reached the way a player would: from the lobby.
            await page.goto(BASE_URL)
            await page.get_by_role("link", name="Prompt stats").click()
            await page.wait_for_url("**/prompt-lists")
            await page.get_by_role("heading", name="Prompt stats").wait_for()

            # Every prompt in the list is listed, not just the ranked ones.
            table = page.locator(".prompt-stats-table")
            await table.wait_for()
            rows = page.locator(".prompt-stats-table tbody tr")
            listed = await rows.count()
            selected = await page.locator("#prompt-stats-list").input_value()
            expected = 592 if selected == "english_extended" else 260
            assert listed == expected, f"listed {listed} of {expected} prompts"

            # A ranked row is ranked on a real sample; the suite shares one
            # server with tests playing games, so which rows those are is not
            # ours to predict - only that nothing thin is ranked.
            for index in range(listed):
                row = rows.nth(index)
                if "is-unrated" in (await row.get_attribute("class") or ""):
                    continue
                guessers = await row.locator("td").last.inner_text()
                assert int(guessers) >= 5, f"ranked a prompt with {guessers} guessers"

            # Search narrows the list without leaving the page.
            await page.fill("#prompt-stats-search", "zzzz-no-such-prompt")
            await page.get_by_text("No prompt matches").wait_for()
            await page.fill("#prompt-stats-search", "")
            await table.wait_for()

            # The sort is in the URL, so a chosen view can be linked to.
            await page.select_option("#prompt-stats-sort", "most-picked")
            await page.wait_for_url("**sort=most-picked")
            assert await page.locator("#prompt-stats-sort").input_value() == "most-picked"

            # An unknown list says so rather than showing an empty table.
            await page.goto(f"{BASE_URL}/prompt-lists/not-a-real-list")
            await page.get_by_text("There is no prompt list with that name.").wait_for()

            # Room setup offers the stats from the chip itself, not as a link row.
            await page.goto(f"{BASE_URL}/create")
            info = page.get_by_role("link", name="How English — Standard prompts play")
            await info.wait_for()
            assert await info.get_attribute("href") == "/prompt-lists/english_standard"
            assert await page.locator(".prompt-list-stats-links").count() == 0
        finally:
            await browser.close()

"""The prompt stats page: reachable, sortable, and honest about thin data."""
import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import use_guest_name

BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_prompt_stats_page_loads_sorts_and_is_linked_from_the_picker():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()

        try:
            # Reached the way a player would: from the account menu.
            await page.goto(BASE_URL)
            await use_guest_name(page, "StatsReader")
            await page.click(".identity-chip")
            await page.get_by_role("menuitem", name="Prompt stats").click()
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

            # Which rows are ranked is not ours to predict - the suite shares
            # one server with tests playing games - but a ranked row must show
            # a measurement and an unranked one must not pretend to.
            for index in range(listed):
                row = rows.nth(index)
                cells = await row.locator("td").all_inner_texts()
                band, guessed = cells[0], cells[1]
                if "is-unrated" in (await row.get_attribute("class") or ""):
                    assert guessed == "—", f"unranked row shows a figure: {cells}"
                    assert band == "Not played enough", f"unranked row banded: {cells}"
                else:
                    assert guessed.endswith("%"), f"ranked row shows no figure: {cells}"

            # Search narrows the list without leaving the page.
            await page.fill("#prompt-stats-search", "zzzz-no-such-prompt")
            await page.get_by_text("No prompt matches").wait_for()
            await page.fill("#prompt-stats-search", "")
            await table.wait_for()

            # The sort is in the URL, so a chosen view can be linked to.
            await page.select_option("#prompt-stats-sort", "most-picked")
            await page.wait_for_url("**sort=most-picked")
            assert await page.locator("#prompt-stats-sort").input_value() == "most-picked"

            # Facts can be sliced without resetting or rewriting them. The
            # chosen period and rule dimensions remain linkable in the URL.
            await page.select_option("#prompt-stats-window", "30d")
            await page.wait_for_url("**window=30d*")
            await page.select_option("#prompt-stats-scoring", "pressure")
            await page.wait_for_url("**scoringMode=pressure*")
            await page.select_option("#prompt-stats-hints", "wheel")
            await page.wait_for_url("**hintMode=wheel*")
            await table.wait_for()

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

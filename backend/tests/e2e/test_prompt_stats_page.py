"""The prompt stats page: reachable, sortable, and honest about thin data."""
import re

from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import use_guest_name

BASE_URL = "http://localhost:8000"


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

            # It opens on the Standard list of the language this reader plays
            # in, not on whichever list sorts first by name ("Deutsch -
            # Erweitert" for an English guest, before).
            selected = await page.locator("#prompt-stats-list").input_value()
            assert selected == "english_standard", f"opened on {selected}"

            # Every prompt in the list is reachable, not just the ranked ones.
            # The list is paged - rendering hundreds of rows is thirty screens
            # of scroll on a phone - so the count is asserted by paging to the
            # end, which also proves nothing is silently dropped. How many to
            # expect is read off the picker's own option rather than written
            # down here: the catalogue holds two lists per supported language
            # and each one's size is content, not a constant this test knows.
            #
            # Two shapes, and which one is not ours to predict - the suite
            # shares one server with tests playing games: a table when
            # anything is ranked, and the bare names when nothing is.
            listing = page.locator(".prompt-stats-table, .prompt-stats-plain")
            await listing.first.wait_for()
            plain = await page.locator(".prompt-stats-plain").count() > 0
            rows = page.locator(
                ".prompt-stats-plain li" if plain else ".prompt-stats-table tbody tr"
            )
            label = await page.locator(
                f"#prompt-stats-list option[value='{selected}']"
            ).inner_text()
            expected = int(re.search(r"\((\d+)\)\s*$", label).group(1))

            more = page.locator(".prompt-stats-more button")
            while await more.count() > 0:
                await more.click()
            listed = await rows.count()
            assert listed == expected, f"listed {listed} of {expected} prompts"

            # With nothing ranked, the page says so once instead of in every
            # row. Otherwise a ranked row must show a measurement and an
            # unranked one must not pretend to.
            if plain:
                await page.get_by_text("so none of them is ranked").wait_for()
                assert await page.get_by_text("Not played enough").count() == 0
            for index in range(listed if not plain else 0):
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
            await listing.first.wait_for()

            # The sort is in the URL, so a chosen view can be linked to.
            #
            # `expect` rather than a bare `input_value`, because the URL leads
            # the control rather than following it: react-router writes history
            # synchronously and commits the re-render in a transition, so for a
            # frame or more `location` already says `most-picked` while the
            # controlled select is still held at the old value. `wait_for_url`
            # returns at the *start* of that window. It is one frame on an idle
            # machine and eight under load, which is why this only ever failed
            # on CI.
            await page.select_option("#prompt-stats-sort", "most-picked")
            await page.wait_for_url("**sort=most-picked")
            await expect(page.locator("#prompt-stats-sort")).to_have_value("most-picked")

            # Facts can be sliced without resetting or rewriting them. The
            # chosen period and rule dimensions remain linkable in the URL.
            await page.select_option("#prompt-stats-window", "30d")
            await page.wait_for_url("**window=30d*")
            await page.select_option("#prompt-stats-scoring", "pressure")
            await page.wait_for_url("**scoringMode=pressure*")
            await page.select_option("#prompt-stats-hints", "wheel")
            await page.wait_for_url("**hintMode=wheel*")
            await listing.first.wait_for()

            # An unknown list says so rather than showing an empty table.
            await page.goto(f"{BASE_URL}/prompt-lists/not-a-real-list")
            await page.get_by_text("There is no prompt list with that name.").wait_for()

            # Room setup offers the stats from the chip itself, not as a link row.
            await page.goto(f"{BASE_URL}/create")
            await page.click('summary:has-text("Prompts")')
            info = page.get_by_role("link", name="How English — Standard prompts play")
            await info.wait_for()
            assert await info.get_attribute("href") == "/prompt-lists/english_standard"
            assert await page.locator(".prompt-list-stats-links").count() == 0
        finally:
            await browser.close()

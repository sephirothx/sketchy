"""The prompt stats page: reachable, sortable, and honest about thin data."""
import re

from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import pick, use_guest_name

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
            list_picker = page.locator("#prompt-stats-list")
            selected = await list_picker.get_attribute("data-value")
            assert selected == "english_standard", f"opened on {selected}"

            # Every prompt in the list is reachable, not just the ranked ones.
            # The list is paged - rendering hundreds of rows is thirty screens
            # of scroll on a phone - so the count is asserted by paging to the
            # end, which also proves nothing is silently dropped. How many to
            # expect is read off the picker's own option rather than written
            # down here: the catalogue holds three lists per supported language
            # and each one's size is content, not a constant this test knows.
            #
            # Two shapes, and which one is not ours to predict - the suite
            # shares one server with tests playing games: a table once
            # anything has been drawn, and the bare names until then.
            listing = page.locator(".prompt-stats-table, .prompt-stats-plain")
            await listing.first.wait_for()
            plain = await page.locator(".prompt-stats-plain").count() > 0
            rows = page.locator(
                ".prompt-stats-plain li" if plain else ".prompt-stats-table tbody tr"
            )
            label = await list_picker.inner_text()
            # Locale-formatted since #1424: "1,036".
            expected = int(re.search(r"\(([\d,]+)\)\s*$", label).group(1).replace(",", ""))

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
            # `expect` rather than a bare `inner_text`, because the URL leads
            # the control rather than following it: react-router writes history
            # synchronously and commits the re-render in a transition, so for a
            # frame or more `location` already says `most-picked` while the
            # controlled picker is still held at the old value. `wait_for_url`
            # returns at the *start* of that window. It is one frame on an idle
            # machine and eight under load, which is why this only ever failed
            # on CI.
            # The list picker groups the lists by language, the reader's
            # first (#1424): 136 options in one column was no way to find one.
            await list_picker.click()
            first_group = page.get_by_role("listbox").get_by_role("group").first
            await expect(first_group).to_have_attribute("aria-label", "English")
            await page.keyboard.press("Escape")
            asked: list[str] = []
            page.on("request", lambda request: asked.append(request.url) if "/prompt-stats" in request.url else None)

            await pick(page, "#prompt-stats-sort", "most-picked")
            await page.wait_for_url("**sort=most-picked")
            await expect(page.locator("#prompt-stats-sort")).to_contain_text("Most picked")
            # Sorted here: the same counts in another order are not a request.
            await page.wait_for_timeout(300)
            assert asked == [], asked

            # Facts can be sliced without resetting or rewriting them. The
            # chosen period and rule dimensions remain linkable in the URL.
            await pick(page, "#prompt-stats-window", "30d")
            await page.wait_for_url("**window=30d*")
            # The period by name, which the server caches by - not a timestamp.
            for _ in range(50):
                if any("window=30d" in url for url in asked):
                    break
                await page.wait_for_timeout(100)
            assert any("window=30d" in url for url in asked), asked
            assert not any("from=" in url for url in asked), asked
            await pick(page, "#prompt-stats-scoring", "pressure")
            await page.wait_for_url("**scoringMode=pressure*")
            await pick(page, "#prompt-stats-hints", "wheel")
            await page.wait_for_url("**hintMode=wheel*")
            await listing.first.wait_for()

            # An unknown list says so rather than showing an empty table.
            await page.goto(f"{BASE_URL}/prompt-lists/not-a-real-list")
            await page.get_by_text("There is no prompt list with that name.").wait_for()

            # Room setup offers the stats from the list's own row, not as a link row.
            await page.goto(f"{BASE_URL}/create")
            await page.click('summary:has-text("Prompts")')
            info = page.get_by_role("link", name="How English — Standard prompts play")
            await info.wait_for()
            assert await info.get_attribute("href") == "/prompt-lists/english_standard"
            assert await page.locator(".prompt-list-stats-links").count() == 0
        finally:
            await browser.close()


async def test_the_language_headings_follow_the_interface_language():
    """Review of #1449: the headings were remembered by list and play
    language only, so switching the interface to German left them English
    while everything around them changed."""
    from uuid import uuid4

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, f"Heads{uuid4().hex[:6]}")
            await page.goto(f"{BASE_URL}/prompt-lists")
            list_picker = page.locator("#prompt-stats-list")
            first_group = page.get_by_role("listbox").get_by_role("group").first
            await list_picker.click()
            await expect(first_group).to_have_attribute("aria-label", "English")
            await page.keyboard.press("Escape")
            await page.locator(".language-picker .picker-trigger").first.click()
            await page.get_by_role("listbox").get_by_role("option", name=re.compile("Deutsch")).click()
            await page.wait_for_function("() => document.documentElement.lang === 'de'")
            await list_picker.click()
            await expect(first_group).to_have_attribute("aria-label", "Englisch")
        finally:
            await browser.close()

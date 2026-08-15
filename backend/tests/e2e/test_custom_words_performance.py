from time import perf_counter

import pytest
from playwright.async_api import async_playwright

from tests.e2e.custom_words_fixture import maximum_custom_words, set_textarea_value


BASE_URL = "http://localhost:8000"
MAX_INTERACTION_SECONDS = 5


@pytest.mark.asyncio
async def test_maximum_custom_word_editing_search_and_all_view_remain_bounded():
    words = maximum_custom_words()
    raw = "\n".join(words)
    assert len(words) == 10_000
    assert len(raw) < 400_000

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        try:
            await host.goto(BASE_URL)
            await host.fill('input[placeholder="Your name"]', "MaximumHost")
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.wait_for_selector(".create-room-page")
            await host.get_by_text("Advanced settings", exact=False).click()

            started = perf_counter()
            await set_textarea_value(host, "#custom-words", raw)
            await host.get_by_text("10000 usable custom words", exact=True).wait_for()
            assert perf_counter() - started < MAX_INTERACTION_SECONDS

            custom_only = host.get_by_label("Only use custom words")
            await custom_only.check()
            await set_textarea_value(
                host,
                "#custom-words",
                "this entry is deliberately longer than thirty two characters",
            )
            assert await custom_only.is_disabled()
            assert not await custom_only.is_checked()
            await set_textarea_value(host, "#custom-words", "")
            assert await custom_only.is_disabled()
            await set_textarea_value(host, "#custom-words", raw)
            assert await custom_only.is_enabled()
            await custom_only.check()

            await host.locator(".create-room-submit").click()
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = (await host.inner_text(".room-copy-button")).split("Code:")[1].strip()

            await guest.goto(BASE_URL)
            await guest.fill('input[placeholder="Your name"]', "MaximumGuest")
            await guest.fill('input[placeholder="ABC123"]', code)
            await guest.get_by_role("button", name="Join by code", exact=True).click()
            await guest.wait_for_selector('[data-testid="waiting-room"]')

            started = perf_counter()
            await guest.get_by_text("Inspect 10000 custom words", exact=False).click()
            word_list = guest.locator(".waiting-custom-words-list")
            await word_list.wait_for()
            assert perf_counter() - started < MAX_INTERACTION_SECONDS
            items = word_list.locator('[role="listitem"]')
            assert await items.count() < 100
            assert await guest.get_by_text("10000 words", exact=True).is_visible()

            expected_filter_counts = {
                "Short": 3334,
                "Medium": 3333,
                "Long": 3333,
            }
            for label, count in expected_filter_counts.items():
                await guest.get_by_role("button", name=label, exact=True).click()
                await guest.get_by_text(
                    f"{count} of 10000 words match",
                    exact=True,
                ).wait_for()

            await guest.get_by_role("button", name="All", exact=True).click()
            search = guest.locator('input[placeholder="Search custom words…"]')
            for word in (words[0], words[len(words) // 2], words[-1]):
                await search.fill(word)
                await guest.get_by_text("1 of 10000 words match", exact=True).wait_for()
                assert await word_list.get_by_text(word, exact=True).is_visible()

            started = perf_counter()
            await search.fill("")
            await guest.get_by_text("10000 words", exact=True).wait_for()
            assert perf_counter() - started < MAX_INTERACTION_SECONDS
            assert await guest.get_by_label("Words to display").count() == 0
            assert await items.count() < 100
            assert await items.first.get_attribute("aria-posinset") == "1"
            assert await items.first.get_attribute("aria-setsize") == "10000"

            long_word = word_list.get_by_text(words[2], exact=True)
            await long_word.hover()
            tooltip = guest.get_by_role("tooltip")
            await tooltip.get_by_text(words[2], exact=True).wait_for()
            assert await long_word.get_attribute(
                "aria-describedby"
            ) == await tooltip.get_attribute("id")
            await long_word.focus()
            await long_word.press("Escape")
            assert await tooltip.count() == 0
            await long_word.click()
            await tooltip.wait_for()
            await guest.get_by_text("10000 words", exact=True).click()
            assert await tooltip.count() == 0
            await items.first.hover()
            assert await tooltip.count() == 0

            await search.fill("skeleton")
            await guest.get_by_text("1 of 10000 words match", exact=True).wait_for()
            fully_visible_word = word_list.get_by_text(words[2], exact=True)
            await fully_visible_word.hover()
            assert await tooltip.count() == 0
            assert await fully_visible_word.evaluate(
                "element => element.scrollWidth <= element.clientWidth"
            )
            await search.fill("")
            await guest.get_by_text("10000 words", exact=True).wait_for()

            await word_list.focus()
            await word_list.press("End")
            await guest.get_by_text(words[-1], exact=True).wait_for()
            assert await word_list.evaluate("element => element.scrollTop > 0")
            assert await word_list.get_by_text(words[-1], exact=True).get_attribute(
                "aria-posinset"
            ) == "10000"
            await word_list.press("Home")
            await guest.get_by_text(words[0], exact=True).wait_for()

            started = perf_counter()
            await search.fill("long-custom-")
            await guest.get_by_text("3332 of 10000 words match", exact=True).wait_for()
            assert perf_counter() - started < MAX_INTERACTION_SECONDS
            assert await items.count() < 100
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()

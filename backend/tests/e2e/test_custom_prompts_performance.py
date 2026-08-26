from time import perf_counter

import pytest
from playwright.async_api import async_playwright

from tests.e2e.custom_prompts_fixture import maximum_custom_prompts, set_textarea_value
from tests.e2e.lobby_helpers import room_code, use_guest_name


BASE_URL = "http://localhost:8000"
MAX_INTERACTION_SECONDS = 5


@pytest.mark.asyncio
async def test_maximum_custom_prompt_editing_search_and_all_view_remain_bounded():
    prompts = maximum_custom_prompts()
    raw = "\n".join(prompts)
    assert len(prompts) == 10_000
    assert len(raw) < 400_000

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "MaximumHost")
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.wait_for_selector(".create-room-page")
            await host.click('summary:has-text("Prompts")')

            started = perf_counter()
            await set_textarea_value(host, "#custom-prompts", raw)
            await host.get_by_text("10000 usable custom prompts", exact=True).wait_for()
            assert perf_counter() - started < MAX_INTERACTION_SECONDS

            custom_only = host.get_by_label("Only use custom prompts")
            await custom_only.check()
            await set_textarea_value(
                host,
                "#custom-prompts",
                "this entry is deliberately longer than thirty two characters",
            )
            assert await custom_only.is_disabled()
            assert not await custom_only.is_checked()
            await set_textarea_value(host, "#custom-prompts", "")
            assert await custom_only.is_disabled()
            await set_textarea_value(host, "#custom-prompts", raw)
            assert await custom_only.is_enabled()
            await custom_only.check()

            await host.locator(".create-room-submit").click()
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "MaximumGuest")
            await guest.fill('input[placeholder="ABC123"]', code)
            await guest.get_by_role("button", name="Join by code", exact=True).click()
            await guest.wait_for_selector('[data-testid="waiting-room"]')

            started = perf_counter()
            await guest.get_by_text("Inspect 10000 custom prompts", exact=False).click()
            prompt_list = guest.locator(".waiting-custom-prompts-list")
            await prompt_list.wait_for()
            assert perf_counter() - started < MAX_INTERACTION_SECONDS
            items = prompt_list.locator('[role="listitem"]')
            assert await items.count() < 100
            assert await guest.get_by_text("10000 prompts", exact=True).is_visible()

            expected_filter_counts = {
                "Short": 3334,
                "Medium": 3333,
                "Long": 3333,
            }
            for label, count in expected_filter_counts.items():
                await guest.get_by_role("button", name=label, exact=True).click()
                await guest.get_by_text(
                    f"{count} of 10000 prompts match",
                    exact=True,
                ).wait_for()

            await guest.get_by_role("button", name="All", exact=True).click()
            search = guest.locator('input[placeholder="Search custom prompts…"]')
            for prompt in (prompts[0], prompts[len(prompts) // 2], prompts[-1]):
                await search.fill(prompt)
                await guest.get_by_text("1 of 10000 prompts match", exact=True).wait_for()
                assert await prompt_list.get_by_text(prompt, exact=True).is_visible()

            started = perf_counter()
            await search.fill("")
            await guest.get_by_text("10000 prompts", exact=True).wait_for()
            assert perf_counter() - started < MAX_INTERACTION_SECONDS
            # No display cap survives: every entry is reachable, and the list
            # says so through aria-setsize while only rendering a window of it.
            assert await items.count() < 100
            assert await items.first.get_attribute("aria-posinset") == "1"
            assert await items.first.get_attribute("aria-setsize") == "10000"

            long_prompt = prompt_list.get_by_text(prompts[2], exact=True)
            await long_prompt.hover()
            tooltip = guest.get_by_role("tooltip")
            await tooltip.get_by_text(prompts[2], exact=True).wait_for()
            assert await long_prompt.get_attribute(
                "aria-describedby"
            ) == await tooltip.get_attribute("id")
            await long_prompt.focus()
            await long_prompt.press("Escape")
            assert await tooltip.count() == 0
            await long_prompt.click()
            await tooltip.wait_for()
            await guest.get_by_text("10000 prompts", exact=True).click()
            assert await tooltip.count() == 0
            await items.first.hover()
            assert await tooltip.count() == 0

            await search.fill("skeleton")
            await guest.get_by_text("1 of 10000 prompts match", exact=True).wait_for()
            fully_visible_word = prompt_list.get_by_text(prompts[2], exact=True)
            await fully_visible_word.hover()
            assert await tooltip.count() == 0
            assert await fully_visible_word.evaluate(
                "element => element.scrollWidth <= element.clientWidth"
            )
            await search.fill("")
            await guest.get_by_text("10000 prompts", exact=True).wait_for()

            await prompt_list.focus()
            await prompt_list.press("End")
            await guest.get_by_text(prompts[-1], exact=True).wait_for()
            assert await prompt_list.evaluate("element => element.scrollTop > 0")
            assert await prompt_list.get_by_text(prompts[-1], exact=True).get_attribute(
                "aria-posinset"
            ) == "10000"
            await prompt_list.press("Home")
            await guest.get_by_text(prompts[0], exact=True).wait_for()

            started = perf_counter()
            await search.fill("long-custom-")
            await guest.get_by_text("3332 of 10000 prompts match", exact=True).wait_for()
            assert perf_counter() - started < MAX_INTERACTION_SECONDS
            assert await items.count() < 100
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()

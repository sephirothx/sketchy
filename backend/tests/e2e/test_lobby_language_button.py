"""The language you read in, changed from the lobby itself.

Settings is one more screen to find in a language you cannot read; the lobby
is where you arrive. So the lobby header carries the interface language as a
flag - at every width, because a phone is where it is needed most and where
the header's other page actions are hidden.
"""
from __future__ import annotations

import re

import pytest
from playwright.async_api import async_playwright


BASE_URL = "http://localhost:8000"


@pytest.mark.parametrize(
    "viewport",
    [{"width": 390, "height": 844}, {"width": 1280, "height": 800}],
    ids=lambda v: f"{v['width']}px",
)
async def test_the_lobby_changes_the_language_you_read_in(viewport):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport=viewport, locale="en-US")
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            trigger = page.locator(".lobby-header .language-picker-trigger")
            await trigger.wait_for()
            assert await page.evaluate("document.documentElement.lang") == "en"

            await trigger.click()
            await page.get_by_role("option", name=re.compile("Deutsch")).click()
            await page.wait_for_function("() => document.documentElement.lang === 'de'")
            # The flag says what it is set to, in the language it is now set to.
            assert "Deutsch" in (await trigger.get_attribute("aria-label") or "")

            # A choice, not a visit: it is still German after a reload.
            await page.reload()
            await page.locator(".lobby-header .language-picker-trigger").wait_for()
            assert await page.evaluate("document.documentElement.lang") == "de"
        finally:
            await context.close()
            await browser.close()

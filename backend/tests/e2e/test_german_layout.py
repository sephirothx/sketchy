"""The longest locale on the real screens, at the sizes people use.

German runs materially longer than English - a third more on a label, more
than that on a button - and the layout had never been asked the question,
because until #764 there was only one language to ask it in. A truncated
button is a translation bug even when every word in it is right.

What this checks is the one thing a machine can check honestly: that no
screen scrolls sideways. A person still has to look at it - that is the
native review gate (R-I18N-07) - but horizontal overflow is objective, it is
what long words actually cause, and it is invisible to every other test in
the suite because they all run in English.

Three widths, because the failure is width-dependent: a phone, the tablet
breakpoint where the room layout changes, and a laptop.
"""
from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import use_guest_name


BASE_URL = "http://localhost:8000"

# The sizes the layout actually changes at, not a sweep.
VIEWPORTS = [
    {"width": 390, "height": 844},   # a phone
    {"width": 768, "height": 1024},  # the tablet breakpoint
    {"width": 1280, "height": 800},  # a laptop
]


async def _overflow(page) -> int:
    """How far the page scrolls sideways, in pixels. Zero is the only pass.

    Measured on the document rather than on a component: a label that bursts
    its own box only matters when it pushes the page, and anything that does
    push the page is a break somebody will see.
    """
    return await page.evaluate(
        "Math.max(0, document.documentElement.scrollWidth"
        " - document.documentElement.clientWidth)"
    )


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=lambda v: f"{v['width']}px")
async def test_german_does_not_push_any_screen_sideways(viewport):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport=viewport)
        # Before the first paint, the way a returning German reader arrives.
        await context.add_init_script("localStorage.setItem('sketchy_locale', 'de')")
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "LangeWorte")

            # The lobby, which is the widest thing a visitor sees first.
            assert await page.evaluate("document.documentElement.lang") == "de"
            assert await _overflow(page) == 0, "the lobby scrolls sideways in German"

            # Settings: the densest screen in the app, and the one whose rows
            # are all label-plus-hint - the shape German lengthens most. Its
            # four sections are separate panels, so each is its own answer.
            await page.get_by_role("button", name="Spielereinstellungen").click()
            await page.get_by_test_id("settings").wait_for()
            for tab in await page.get_by_role("tab").all():
                await tab.click()
                assert await _overflow(page) == 0, (
                    f"the {await tab.inner_text()} settings scroll sideways in German"
                )

            await page.keyboard.press("Escape")

            # Room setup: every control has a German label beside a German hint.
            await page.get_by_role("button", name="Raum erstellen").first.click()
            await page.wait_for_selector(".create-room-page")
            assert await _overflow(page) == 0, "room setup scrolls sideways in German"
        finally:
            await context.close()
            await browser.close()

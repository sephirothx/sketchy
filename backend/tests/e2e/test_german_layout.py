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
from playwright.async_api import async_playwright, expect

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
            # One name per viewport: both run at once, and a guest name is
            # unique among the people online (R-ACCT-09).
            await use_guest_name(page, f"LangeWorte{viewport['width']}")

            # The lobby, which is the widest thing a visitor sees first.
            assert await page.evaluate("document.documentElement.lang") == "de"
            assert await _overflow(page) == 0, "the lobby scrolls sideways in German"

            # Settings: the densest screen in the app, and the one whose rows
            # are all label-plus-hint - the shape German lengthens most. Its
            # four sections are separate panels, so each is its own answer.
            #
            # Opened by its route rather than by its button: the header packs
            # differently at 390px, and this test is about what the panel does
            # to the layout, not about how you get to it.
            await page.goto(f"{BASE_URL}/settings")
            await page.get_by_test_id("settings").wait_for()
            for tab in await page.get_by_role("tab").all():
                await tab.click()
                assert await _overflow(page) == 0, (
                    f"the {await tab.inner_text()} settings scroll sideways in German"
                )

            # Room setup: every control has a German label beside a German hint.
            await page.goto(f"{BASE_URL}/create")
            await page.wait_for_selector(".create-room-page")
            assert await _overflow(page) == 0, "room setup scrolls sideways in German"
        finally:
            await context.close()
            await browser.close()


# Every word of the room's fact values, and how many lines each is laid over:
# a word on two lines is a word broken inside itself ("Zeitgesteu|erte").
# Values only: they are the text allowed to wrap (overflow-wrap), and the
# labels under them never break inside a word.
_BROKEN_FACT_WORDS = """() => {
  const broken = [];
  for (const el of document.querySelectorAll('.room-fact-text')) {
    const node = el.firstChild;
    if (!node) continue;
    let at = 0;
    for (const part of node.textContent.split(/(\\s+)/)) {
      if (part.trim()) {
        const range = document.createRange();
        range.setStart(node, at);
        range.setEnd(node, at + part.length);
        if (range.getClientRects().length > 1) broken.push(part);
      }
      at += part.length;
    }
  }
  return broken;
}"""


async def test_german_room_facts_keep_their_words_whole_on_a_phone():
    """The waiting room's six facts on a 390px phone, in German (R-UX-11).

    Three to a row broke "Zeitgesteuerte" (the default hints, "Timed") inside
    itself; RoomFacts measures the widest word and takes two to a row instead.
    English keeps three at this width, so the answer is the language's - which
    is why it is asked here.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 390, "height": 844})
        await context.add_init_script("localStorage.setItem('sketchy_locale', 'de')")
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "LangeFakten390")
            await page.goto(f"{BASE_URL}/create")
            await page.wait_for_selector(".create-room-page")
            await page.click(".create-room-submit")
            await page.wait_for_selector('[data-testid="waiting-room"]')

            facts = page.get_by_test_id("waiting-facts")
            await expect(facts).to_have_attribute("data-columns", "2")
            # After the fonts: the count is measured again once they load.
            await page.evaluate("document.fonts.ready")
            await expect(facts).to_have_attribute("data-columns", "2")
            assert await page.evaluate(_BROKEN_FACT_WORDS) == [], "a room fact's value breaks inside a word"
        finally:
            await context.close()
            await browser.close()

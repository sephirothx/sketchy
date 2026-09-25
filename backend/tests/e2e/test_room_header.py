"""The room's bar at the widths it gives way at (#580)."""

import random

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import use_guest_name


BASE_URL = "http://localhost:8000"

BAR = """() => {
  const box = (selector) => {
    const element = document.querySelector(`[data-testid="room-header"] ${selector}`);
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return rect.width ? { left: rect.left, right: rect.right, width: rect.width, height: rect.height } : null;
  };
  return {
    page: document.documentElement.scrollWidth,
    mark: box('.game-header-home'),
    chip: box('.identity-chip'),
    menu: box('[data-testid="open-room-menu"]'),
  };
}"""


async def test_the_wordmark_and_a_round_avatar_stay_in_the_bar_down_to_a_phone():
    """The wordmark went at 950px and the avatar chip was not on a phone's bar at
    all; where the chip gave up its name it kept a pill's padding round the
    avatar and came out oval."""
    tag = random.randint(1000, 9999)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            for width, mobile in ((950, False), (495, True), (320, True)):
                context = await browser.new_context(
                    viewport={"width": width, "height": 800}, is_mobile=mobile, has_touch=mobile
                )
                page = await context.new_page()
                await page.goto(BASE_URL)
                await use_guest_name(page, f"Bar{tag}w{width}")
                await page.click('button:has-text("Create room")')
                await page.wait_for_selector(".create-room-page")
                await page.click('button:has-text("Create room")')
                await page.wait_for_selector('[data-testid="waiting-room"]')

                bar = await page.evaluate(BAR)
                assert bar["page"] <= width, (width, bar)
                assert bar["mark"], (width, bar)
                assert bar["chip"], (width, bar)
                assert abs(bar["chip"]["width"] - bar["chip"]["height"]) < 1, (width, bar)
                # In order and apart: the wordmark, the Room menu, the avatar.
                assert bar["mark"]["right"] <= bar["menu"]["left"], (width, bar)
                assert bar["menu"]["right"] <= bar["chip"]["left"], (width, bar)
                assert bar["chip"]["right"] <= width, (width, bar)
                await context.close()
        finally:
            await browser.close()


async def test_a_notice_takes_the_wordmark_s_room_on_a_narrow_phone_and_gives_it_back():
    tag = random.randint(1000, 9999)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(
            viewport={"width": 320, "height": 640}, is_mobile=True, has_touch=True
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, f"Notice{tag}")
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector(".create-room-page")
            await page.click('button:has-text("Create room")')
            await page.wait_for_selector('[data-testid="waiting-room"]')

            await context.set_offline(True)
            await page.wait_for_selector(".room-notice-chip")
            bar = await page.evaluate(BAR)
            assert bar["mark"] is None, bar
            assert bar["page"] <= 320, bar
            notice = await page.locator(".room-notice-chip").bounding_box()
            assert notice and notice["x"] + notice["width"] <= bar["menu"]["left"], (notice, bar)

            await context.set_offline(False)
            await page.wait_for_selector(".room-notice-chip", state="detached", timeout=10000)
            assert (await page.evaluate(BAR))["mark"]
        finally:
            await context.close()
            await browser.close()

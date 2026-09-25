"""The room's bar at the widths it gives way at (#580)."""

import random

from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name


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


ROUND = """() => {
  const box = (selector) => {
    const element = document.querySelector(`[data-testid="room-header"] ${selector}`);
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return rect.width ? { left: rect.left, right: rect.right } : null;
  };
  const full = document.querySelector('.game-header-round-long');
  return {
    page: document.documentElement.scrollWidth,
    inner: window.innerWidth,
    mark: box('.game-header-home'),
    round: box('.game-header-round'),
    menu: box('[data-testid="open-room-menu"]'),
    full: !!full && getComputedStyle(full).visibility === 'visible'
      && getComputedStyle(full).position !== 'absolute',
    text: document.querySelector('.game-header-round')?.innerText ?? null,
  };
}"""


# A function, not an expression: the page's CSP refuses the eval Playwright
# polls an expression with.
FULL_ROUND_SHOWN = """() => {
  const full = document.querySelector('.game-header-round-long');
  return !!full && getComputedStyle(full).visibility === 'visible'
    && getComputedStyle(full).position !== 'absolute';
}"""


SHORT_ROUND_SHOWN = """() => {
  const short = document.querySelector('.game-header-round-short');
  return !!short && getComputedStyle(short).display !== 'none'
    && short.getBoundingClientRect().width > 0;
}"""


async def test_a_phone_s_round_says_round_when_it_fits_and_never_pushes_the_bar():
    """The phone's round read "R1/1" (C16). It says "Round 1/3" where the bar
    has room and "1/3" where it does not, chosen by measuring the bar, so it
    never pushes the wordmark or the menu off it."""
    tag = random.randint(1000, 9999)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context(viewport={"width": 1280, "height": 800})
        guest_context = await browser.new_context(viewport={"width": 1280, "height": 800})
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, f"RoundHost{tag}")
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector(".create-room-page")
            await host.click('button:has-text("Create room")')
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, f"RoundGuest{tag}")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')

            await host.click('button:has-text("Start game")')
            await guest.wait_for_selector(".game-header-round")

            for width in (375, 390, 412):
                await guest.set_viewport_size({"width": width, "height": 800})
                # The phone's chip is a React render off a media query, and
                # the label is chosen from a ResizeObserver after it.
                await guest.wait_for_selector(".game-header-round-short", state="attached")
                if width >= 390:
                    # "Round 1/3" needs about 340px of a 370px bar in English.
                    await guest.wait_for_function(FULL_ROUND_SHOWN)
                else:
                    await guest.wait_for_timeout(300)
                bar = await guest.evaluate(ROUND)
                assert bar["page"] <= bar["inner"], (width, bar)
                assert bar["mark"] and bar["round"] and bar["menu"], (width, bar)
                # In order and apart: the wordmark, the round, the Room menu.
                assert bar["mark"]["right"] <= bar["round"]["left"], (width, bar)
                assert bar["round"]["right"] <= bar["menu"]["left"], (width, bar)
                assert "R1/" not in bar["text"], (width, bar)

            # Too narrow for the word: "Round 1/3" needs about 340px and a
            # 340px phone's bar has 320. The numbers alone, nothing pushed.
            await guest.set_viewport_size({"width": 340, "height": 800})
            await guest.wait_for_function(SHORT_ROUND_SHOWN)
            bar = await guest.evaluate(ROUND)
            assert bar["page"] <= bar["inner"], bar
            assert bar["mark"]["right"] <= bar["round"]["left"], bar
            assert bar["round"]["right"] <= bar["menu"]["left"], bar

            # A notice beside the round: measured with it, so still nothing
            # pushed off the bar, whichever label that leaves room for.
            await guest.set_viewport_size({"width": 360, "height": 800})
            await guest_context.set_offline(True)
            await guest.wait_for_selector(".room-notice-chip")
            await guest.wait_for_timeout(300)
            bar = await guest.evaluate(ROUND)
            notice = await guest.locator(".room-notice-chip").bounding_box()
            assert bar["page"] <= bar["inner"], bar
            assert notice and bar["round"]["right"] <= notice["x"], (notice, bar)
            assert notice["x"] + notice["width"] <= bar["menu"]["left"], (notice, bar)
            await guest_context.set_offline(False)
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()

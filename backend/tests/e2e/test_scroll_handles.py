"""No scroll area keeps a lane for its scrollbar (#1222): where the platform's
scrollbars take one, the native ones are hidden and an overlay handle is drawn
over the edge of whatever is scrolling (lib/scrollHandles.ts).

Headless Chromium hides its scrollbars unless told not to; on Linux, as on
CI, they are then classic 15px ones, and the handles take over. macOS draws
overlay scrollbars unless set to always show them, which leave nothing to
replace - those runs skip."""
import sys

import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import open_player_settings, use_guest_name
from tests.e2e.test_friends import unique

BASE_URL = "http://localhost:8000"

HANDLES = """() => [...document.querySelectorAll('.scroll-handle.is-visible')].map((handle) => {
  const box = handle.getBoundingClientRect();
  return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, height: box.height };
})"""

# The page's own: at the window's right edge, where no panel's handle is.
PAGE_HANDLES = f"() => ({HANDLES})().filter((handle) => handle.right >= innerWidth - 4)"


async def classic_scrollbars(p):
    return await p.chromium.launch(
        headless=True, args=["--mute-audio"], ignore_default_args=["--hide-scrollbars"]
    )


async def require_handles(page) -> None:
    if await page.evaluate("() => document.documentElement.classList.contains('scroll-handles')"):
        return
    assert sys.platform != "linux", "Chromium on Linux drew classic scrollbars, and no handles replaced them"
    pytest.skip("this platform's scrollbars take no lane")


async def test_the_banner_reaches_the_window_edge_whether_the_page_scrolls_or_not():
    """The banner stopped 15px short of the window's right edge: that was the
    root's scrollbar lane, kept on every page, and nothing but the page's own
    colour can be painted in an empty one. With no lane it reaches the edge on
    the pinned lobby, which fits, and on a window short enough to scroll."""
    async with async_playwright() as p:
        browser = await classic_scrollbars(p)
        context = await browser.new_context(viewport={"width": 1200, "height": 800})
        page = await context.new_page()
        try:
            await use_guest_name(page, unique("Edge"))
            await page.goto(BASE_URL)
            await page.locator(".lobby-header .identity-chip").wait_for()
            await require_handles(page)
            header = await page.locator(".lobby-header").bounding_box()

            await context.set_offline(True)
            banner = page.locator(".connection-status-banner.offline")
            await banner.wait_for()
            for height, scrolls in ((800, False), (560, True)):
                await page.set_viewport_size({"width": 1200, "height": height})
                # Polled: the lobby makes room for the stack a frame later (#797).
                await page.wait_for_function(
                    """(scrolls) => (document.documentElement.scrollHeight
                        > document.documentElement.clientHeight) === scrolls""",
                    arg=scrolls,
                    timeout=5000,
                )
                box = await banner.bounding_box()
                assert box is not None and box["x"] == 0, (height, box)
                assert abs(box["x"] + box["width"] - 1200) <= 1, (height, box)
                assert await page.evaluate("() => innerWidth === document.documentElement.clientWidth"), (
                    f"the window kept a scrollbar's lane at {height}px"
                )
                # And the page under it did not move sideways for it.
                moved = await page.locator(".lobby-header").bounding_box()
                assert moved is not None and header is not None
                assert (moved["x"], moved["width"]) == (header["x"], header["width"]), (height, header, moved)
            await context.set_offline(False)
        finally:
            await context.close()
            await browser.close()


async def test_no_scroll_area_keeps_a_lane():
    """A panel's classic scrollbar took its lane off the panel's content: the
    lists, the chat, and a dialog's body were 15px narrower than on a
    trackpad. Every scroll area on the lobby and in Settings keeps its whole
    width now."""
    lanes = """() => [...document.querySelectorAll('*')].filter((area) => {
      const style = getComputedStyle(area);
      return /auto|scroll/.test(style.overflowY + style.overflowX) && area.getClientRects().length > 0;
    }).map((area) => {
      const style = getComputedStyle(area);
      const across = area.offsetWidth - area.clientWidth
        - parseFloat(style.borderLeftWidth) - parseFloat(style.borderRightWidth);
      const down = area.offsetHeight - area.clientHeight
        - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth);
      return { area: area.className, across: Math.round(across), down: Math.round(down),
               scrolls: area.scrollHeight > area.clientHeight };
    })"""
    async with async_playwright() as p:
        browser = await classic_scrollbars(p)
        context = await browser.new_context(viewport={"width": 1200, "height": 560})
        page = await context.new_page()
        try:
            await use_guest_name(page, unique("Lanes"))
            await page.goto(BASE_URL)
            await page.locator(".lobby-header .identity-chip").wait_for()
            await require_handles(page)
            await open_player_settings(page)
            await page.locator(".settings-tab-content").wait_for()

            areas = await page.evaluate(lanes)
            assert any(area["scrolls"] for area in areas), "nothing here scrolls, so nothing was tested"
            kept = [area for area in areas if area["across"] or area["down"]]
            assert kept == [], kept
        finally:
            await context.close()
            await browser.close()


async def test_the_handle_shows_while_the_page_scrolls_fades_and_drags():
    async with async_playwright() as p:
        browser = await classic_scrollbars(p)
        context = await browser.new_context(viewport={"width": 1200, "height": 560})
        page = await context.new_page()
        try:
            await use_guest_name(page, unique("Handle"))
            await page.goto(BASE_URL)
            await page.locator(".lobby-header .identity-chip").wait_for()
            await require_handles(page)
            assert await page.evaluate(HANDLES) == []

            # Under the wheel, at the window's right edge. Wheeled over the
            # header, which is the page's own: over the middle it can land on
            # the room list, which scrolls inside its panel once a busy
            # server has enough rooms (R-UX-19), and scroll that instead.
            header = await page.locator(".lobby-header").bounding_box()
            assert header is not None
            await page.mouse.move(header["x"] + header["width"] / 2, header["y"] + header["height"] / 2)
            await page.mouse.wheel(0, 400)
            await page.wait_for_function(f"() => ({PAGE_HANDLES})().length === 1", timeout=2000)
            [handle] = await page.evaluate(PAGE_HANDLES)
            assert handle["right"] <= 1200, handle

            # Gone about a second after the scrolling stops.
            await page.wait_for_function(f"() => ({PAGE_HANDLES})().length === 0", timeout=3000)

            # Back with the pointer at the edge, and dragged: up by 40px of
            # track scrolls the page back up.
            await page.mouse.move(1194, 300)
            await page.wait_for_function(f"() => ({PAGE_HANDLES})().length === 1", timeout=2000)
            [handle] = await page.evaluate(PAGE_HANDLES)
            before = await page.evaluate("() => scrollY")
            assert before > 0
            grab_y = handle["y"] + handle["height"] / 2
            await page.mouse.move(handle["x"] + 5, grab_y)
            await page.mouse.down()
            await page.mouse.move(handle["x"] + 5, grab_y - 40, steps=4)
            await page.mouse.up()
            assert await page.evaluate("() => scrollY") < before
        finally:
            await context.close()
            await browser.close()


async def test_an_inner_scroll_area_shows_its_own_handle_and_the_program_none():
    """A scroll area inside a dialog gets its handle over its own edge, over
    the dialog. A scroll the program makes - the chat following a new line, a
    page put back at its top - shows nothing: a handle flashing on every chat
    line would be a distraction of its own."""
    async with async_playwright() as p:
        browser = await classic_scrollbars(p)
        context = await browser.new_context(viewport={"width": 1200, "height": 560})
        page = await context.new_page()
        try:
            await use_guest_name(page, unique("Inner"))
            await page.goto(BASE_URL)
            await page.locator(".lobby-header .identity-chip").wait_for()
            await require_handles(page)

            await page.evaluate("() => window.scrollTo(0, 60)")
            await page.wait_for_timeout(300)
            assert await page.evaluate(HANDLES) == []

            # Opening a dialog is a click, not a scroll, whatever it scrolls.
            await open_player_settings(page)
            pane = page.locator(".settings-tab-content")
            await pane.wait_for()
            await page.wait_for_timeout(300)
            assert await page.evaluate(HANDLES) == []
            box = await pane.bounding_box()
            assert box is not None
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await page.mouse.wheel(0, 120)
            await page.wait_for_function(f"() => ({HANDLES})().length === 1", timeout=2000)
            [handle] = await page.evaluate(HANDLES)
            assert abs(handle["right"] - (box["x"] + box["width"])) <= 4, (handle, box)
            assert box["y"] <= handle["y"] and handle["bottom"] <= box["y"] + box["height"], (handle, box)
        finally:
            await context.close()
            await browser.close()


async def test_overlay_scrollbars_are_left_alone():
    """Where the scrollbars take no lane there is nothing to replace: no
    class, no layer. Headless Chromium's hidden scrollbars are that case."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        page = await browser.new_page(viewport={"width": 1200, "height": 560})
        try:
            await page.goto(BASE_URL)
            await page.wait_for_selector(".first-run, .identity-chip")
            assert await page.evaluate(
                """() => !document.documentElement.classList.contains('scroll-handles')
                   && !document.querySelector('.scroll-handle-layer')"""
            )
        finally:
            await browser.close()

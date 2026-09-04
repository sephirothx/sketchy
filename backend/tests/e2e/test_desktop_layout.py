"""The desktop layout spends the width and height the window actually has.

R-UX-01 (a room lays itself out to the viewport), R-UX-06 (the drawing is
presented no wider than 1180px) and R-UX-07 (the shell steps 1240 -> 1600 ->
1960, and the room's columns and canvas cap step with it).

The numbers are arithmetic, not taste: at 2560 the shell is
min(2560 - 96, 1960) = 1960, the room's tracks are 320 / 1fr / 380 with a 12px
gap, so the middle track is 1236 and the canvas cap of 1180 is what binds. At
1440 the shell is min(1440 - 28, 1240) = 1240, the tracks are 250 / 1fr / 300,
so the middle track is 666 and the *width* is what binds. A regression in
either direction moves one of these by more than the tolerance below.
"""
import pytest
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name


BASE_URL = "http://localhost:8000"

WIDE = {"width": 2560, "height": 1440}
LAPTOP = {"width": 1440, "height": 900}


async def box(page, selector):
    """The border box of the first match, as floats."""
    measured = await page.locator(selector).first.bounding_box()
    assert measured is not None, f"{selector} has no box"
    return measured


async def settle(page):
    """Let a viewport change land before anything is measured."""
    await page.evaluate("() => new Promise(requestAnimationFrame)")


@pytest.mark.asyncio
async def test_the_room_is_pinned_and_the_canvas_grows_with_the_shell():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(viewport=WIDE) for _ in range(2)]
        pages = [await context.new_page() for context in contexts]
        host, guest = pages
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "WideHost")
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "WideGuest")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')

            await host.get_by_role("button", name="Start game", exact=True).click()
            for page in pages:
                await page.wait_for_selector("canvas.drawing-canvas")
            await settle(guest)

            # R-UX-07: the shell is at its widest step, and the side columns
            # took their share of it rather than the canvas taking all of it.
            shell = await box(guest, ".game-room")
            assert shell["width"] == pytest.approx(1960, abs=2)
            players = await box(guest, '[data-testid="room-players-region"]')
            chat = await box(guest, '[data-testid="room-chat-region"]')
            assert players["width"] == pytest.approx(320, abs=2)
            assert chat["width"] == pytest.approx(380, abs=2)

            # R-UX-06: the presentation cap is what binds here, not the track.
            canvas = await box(guest, ".canvas-stack")
            assert canvas["width"] == pytest.approx(1180, abs=3)
            assert canvas["height"] == pytest.approx(canvas["width"] * 3 / 4, abs=3)

            # R-UX-01: the room is the window. Nothing scrolls the page, and
            # the columns fill the height instead of stopping at their content
            # -- the chat's old 520px ceiling is gone.
            for page in pages:
                overflow = await page.evaluate(
                    "() => document.documentElement.scrollHeight - window.innerHeight"
                )
                assert overflow <= 1, f"the room page scrolls by {overflow}px"
            assert chat["height"] > 900
            assert players["height"] > 900

            # The same rules one step down: width binds, and the canvas is the
            # middle track rather than the cap.
            for page in pages:
                await page.set_viewport_size(LAPTOP)
            await settle(guest)
            shell = await box(guest, ".game-room")
            assert shell["width"] == pytest.approx(1240, abs=2)
            canvas = await box(guest, ".canvas-stack")
            assert canvas["width"] == pytest.approx(666, abs=3)
            assert canvas["height"] == pytest.approx(canvas["width"] * 3 / 4, abs=3)
            overflow = await guest.evaluate(
                "() => document.documentElement.scrollHeight - window.innerHeight"
            )
            assert overflow <= 1
        finally:
            for context in contexts:
                await context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_the_lobby_puts_its_three_live_lists_side_by_side_when_wide():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        context = await browser.new_context(viewport=WIDE)
        host = await host_context.new_page()
        page = await context.new_page()
        try:
            # One public room, so the list under test has a card in it.
            await host.goto(BASE_URL)
            await use_guest_name(host, "WideLobbyHost")
            await host.click('button:has-text("Create room")')
            await host.fill(
                'input[placeholder="Leave blank for a random name!"]', "Wide lobby room"
            )
            await host.click("button.create-room-submit")
            await host.wait_for_selector('[data-testid="waiting-room"]')

            await page.goto(BASE_URL)
            await use_guest_name(page, "WideLobby")
            await page.locator(
                '[data-testid="public-room-card"]', has_text="Wide lobby room"
            ).wait_for()
            await settle(page)

            shell = await box(page, ".lobby-page")
            assert shell["width"] == pytest.approx(1960, abs=2)

            # Rooms, who is around, and chat are three columns of one grid:
            # each has its own track, and none of them is under another.
            tracks = await page.evaluate(
                "() => getComputedStyle(document.querySelector('.lobby-lists'))"
                ".gridTemplateColumns.split(' ').length"
            )
            assert tracks == 3
            rooms = await box(page, ".lobby-rooms-panel")
            who = await box(page, ".lobby-online-panel")
            chat = await box(page, ".lobby-chat-panel")
            assert rooms["x"] < who["x"] < chat["x"]
            assert rooms["y"] == pytest.approx(who["y"], abs=2)
            assert who["y"] == pytest.approx(chat["y"], abs=2)

            # Three columns of room cards at this width, one at a laptop's.
            assert await room_list_columns(page) == 3
            await page.set_viewport_size(LAPTOP)
            await settle(page)
            assert await room_list_columns(page) == 1
        finally:
            await context.close()
            await host_context.close()
            await browser.close()


async def room_list_columns(page):
    return await page.evaluate(
        """() => {
            const list = document.querySelector('.room-list');
            if (!list) return null;
            return getComputedStyle(list).gridTemplateColumns.split(' ').length;
        }"""
    )

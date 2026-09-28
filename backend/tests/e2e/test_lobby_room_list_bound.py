"""The lobby's room list scrolls inside its panel on a page that scrolls (#1221).

Only the pinned desktop lobby used to size the rooms panel from the window. On
every other desktop page - a visitor with the name tag above the rooms, a
window 721 to 900px wide or under 640px tall - the panel was as tall as its
rooms, and thirty of them put the chat four thousand pixels down.

A 640px window makes the bound (`max(280px, 60dvh)`, 384px here) cheap to
overflow: four cards are taller than it at both widths. The suite's workers
share one server, so other tests' rooms may be in the list too, which only
makes it longer.

From 1500px the people's column sits beside the rooms, and on a window too
short to pin it has to take the row's height rather than set it: a long list
of who is online stretched the row, and the rooms beside it, instead of
scrolling. Four hosts and the visitor are taller than that list's share of a
600px window.
"""
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import (
    answer_play_languages_question,
    open_public_rooms,
    use_guest_name,
)

BASE_URL = "http://localhost:8000"

ROOMS = 4
WINDOW_HEIGHT = 640

# How tall the list is, and how tall what is in it is.
LIST_SIZE = """() => {
  const list = document.querySelector('.lobby-rooms-panel .room-list');
  return { shown: list.clientHeight, content: list.scrollHeight };
}"""


# The same for who is online, and whether the column holding it spills.
PEOPLE_SIZE = """() => {
  const column = document.querySelector('.lobby-social');
  const list = document.querySelector('.online-players-list');
  return {
    column: column.clientHeight, columnContent: column.scrollHeight,
    shown: list.clientHeight, content: list.scrollHeight,
  };
}"""


async def assert_list_scrolls(page) -> None:
    size = await page.evaluate(LIST_SIZE)
    assert size["content"] > size["shown"], f"the list grew to its rooms: {size}"
    assert size["shown"] <= WINDOW_HEIGHT * 0.6 + 1, f"the list is taller than its bound: {size}"


async def assert_people_scroll(page) -> None:
    size = await page.evaluate(PEOPLE_SIZE)
    assert size["content"] > size["shown"], f"who is online grew to its people: {size}"
    assert size["columnContent"] <= size["column"] + 1, f"the people's column spills: {size}"


async def test_the_room_list_scrolls_rather_than_growing_the_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        hosts = []
        visitor_context = await browser.new_context(
            viewport={"width": 1280, "height": WINDOW_HEIGHT}
        )
        try:
            hosts = await open_public_rooms(browser, "Bound", ROOMS)
            visitor = await visitor_context.new_page()

            # A first visit: the name tag sits above the rooms, and the page
            # scrolls rather than being pinned to the window.
            await visitor.goto(BASE_URL)
            await visitor.wait_for_selector(".first-run")
            last_room = visitor.locator(
                '[data-testid="public-room-card"]', has_text=f"Bound room {ROOMS - 1}"
            )
            await expect(last_room).to_be_attached()
            await assert_list_scrolls(visitor)

            # Named, in a window too narrow to pin: the ordinary page.
            await use_guest_name(visitor, "BoundVisitor")
            await answer_play_languages_question(visitor)
            await visitor.set_viewport_size({"width": 800, "height": WINDOW_HEIGHT})
            await expect(last_room).to_be_attached()
            assert await visitor.locator(".first-run").count() == 0
            await assert_list_scrolls(visitor)

            # Named, wide, and too short to pin: the rooms beside the people.
            await visitor.set_viewport_size({"width": 1600, "height": 600})
            await expect(visitor.locator(".online-player-row").nth(ROOMS)).to_be_attached()
            await assert_people_scroll(visitor)
        finally:
            for context in hosts:
                await context.close()
            await visitor_context.close()
            await browser.close()

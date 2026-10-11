"""A correct guess is one line in the chat, with the guess in it for whoever
already knows the prompt (#1421, R-GUESS-06).

It used to be "Ada got it · 9.1s" and then "Ada: elephant" for the drawer and
every correct guesser: the result before its cause, and two lines a guess."""
import asyncio
import uuid

from playwright.async_api import Page, async_playwright, expect
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_new_room,
    open_room_settings,
    open_settings_section,
    room_code,
    save_room_settings,
    use_guest_name,
)


BASE_URL = "http://localhost:8000"


async def drawer_among(pages: list[Page]) -> Page:
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                return page
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received prompt choices within 12 seconds")


async def test_a_correct_guess_is_one_line_with_the_guess_for_those_who_know_the_prompt():
    tag = uuid.uuid4().hex[:5]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(3)]
        pages = [await context.new_page() for context in contexts]
        names = {}
        try:
            host = pages[0]
            await host.goto(BASE_URL)
            names[host] = f"LineHost{tag}"
            await use_guest_name(host, names[host])
            await open_new_room(host)
            code = await room_code(host)
            for index, page in enumerate(pages[1:], start=2):
                await page.goto(BASE_URL)
                names[page] = f"Line{index}{tag}"
                await use_guest_name(page, names[page])
                await join_by_code(page, code)
                await page.locator('[data-testid="waiting-room"]').wait_for()
            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("elephant")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            drawer = await drawer_among(pages)
            scorer, waiting = [page for page in pages if page is not drawer]
            await drawer.locator(".prompt-choices button").first.click()
            await drawer.locator(".prompt-choices").wait_for(state="detached")
            await scorer.locator(".chat-input input").wait_for()
            await scorer.fill(".chat-input input", "elephant")
            await scorer.keyboard.press("Enter")

            name = names[scorer]
            for page in (drawer, scorer):
                line = page.locator(".chat-message.correct", has_text=f"{name} got it — elephant ·")
                await expect(line).to_have_count(1)
                # The guess is not said again as a line of its own.
                await expect(
                    page.locator(".chat-message", has_text=f"{name}: elephant")
                ).to_have_count(0)
            # A guesser still at it hears who got it, and not the word.
            await expect(
                waiting.locator(".chat-message.correct", has_text=f"{name} got it ·")
            ).to_have_count(1)
            await expect(waiting.locator(".chat-message", has_text="elephant")).to_have_count(0)
        finally:
            for context in contexts:
                await context.close()
            await browser.close()

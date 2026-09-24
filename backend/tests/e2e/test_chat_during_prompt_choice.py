"""A line typed while the drawer is choosing a prompt reaches the room (#1008).

The panel used to send it as a guess scoped to the turn it last saw, which
the server dropped as out of scope: nothing was said, and nothing said so.
"""
import asyncio

from playwright.async_api import Page, async_playwright
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_room_settings,
    open_settings_section,
    room_code,
    save_room_settings,
    use_guest_name,
)


BASE_URL = "http://localhost:8000"


async def drawer_among(pages: list[Page]) -> tuple[Page, Page]:
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                return page, next(other for other in pages if other is not page)
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received prompt choices within 12 seconds")


async def test_chat_while_the_drawer_chooses_reaches_the_drawer():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(2)]
        host, second = [await context.new_page() for context in contexts]
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "ChoiceChatHost")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.locator('[data-testid="waiting-room"]').wait_for()
            code = await room_code(host)
            await second.goto(BASE_URL)
            await use_guest_name(second, "ChoiceChatTwo")
            await join_by_code(second, code)
            await second.locator('[data-testid="waiting-room"]').wait_for()
            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("elephant")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            # The first turn cannot show the defect: a client that has seen no
            # turn scopes its guess to none, and the server took it as chat.
            # Play it out, and type while the second drawer is choosing.
            drawer, other = await drawer_among([host, second])
            await drawer.locator(".prompt-choices button").first.click()
            await drawer.locator(".prompt-choices").wait_for(state="detached")
            await other.fill(".chat-input input", "elephant")
            await other.keyboard.press("Enter")
            # The only guesser is right, so the turn ends at once; the results
            # show for a few seconds, then the other seat draws.
            await other.locator(".chat-message.correct").first.wait_for()
            drawer, other = await drawer_among([host, second])
            # The drawer is still choosing: its choices are on screen.
            assert await drawer.locator(".prompt-choices").count() == 1
            await other.fill(".chat-input input", "take the cat one")
            await other.keyboard.press("Enter")
            for page in (drawer, other):
                await page.locator('.chat-message:has-text("take the cat one")').wait_for(
                    timeout=5000
                )
            # Plain chat, not a restricted line: nothing to spoil yet.
            assert (
                await drawer.locator('.chat-message.restricted:has-text("take the cat one")').count()
                == 0
            )
        finally:
            for context in contexts:
                await context.close()
            await browser.close()

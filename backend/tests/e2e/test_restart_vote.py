import pytest
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import (
    close_room_settings,
    join_by_code,
    open_room_settings,
    room_menu_action,
    open_room_menu,
    open_new_room,
)
from tests.e2e.lobby_helpers import room_code as get_room_code, use_guest_name


BASE_URL = "http://localhost:8000"

# The vote is a chip in the room bar with a popover (#1266). The popover opens
# by itself for a seat that can still vote and closes once it has; the chip
# opens it again.
VOTE_CHIP = '.room-notice-chip[data-notice="restart-vote"]'
VOTE = '[data-testid="restart-vote"]'


async def open_vote(page):
    """The vote's popover, opened from its chip if it is not already open."""
    popover = page.locator(VOTE)
    if not await popover.is_visible():
        await page.locator(VOTE_CHIP).click()
    await popover.wait_for()
    return popover


async def test_players_approve_restart_without_losing_room_context():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        third_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        third_page = await third_context.new_page()
        host_page.set_default_timeout(12_000)
        player_page.set_default_timeout(12_000)
        third_page.set_default_timeout(12_000)

        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "RestartHost")
            await open_new_room(host_page)

            room_code = await get_room_code(host_page)
            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "RestartPlayer")
            await join_by_code(player_page, room_code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            await third_page.goto(BASE_URL)
            await use_guest_name(third_page, "RestartThird")
            await join_by_code(third_page, room_code)
            await third_page.wait_for_selector('[data-testid="waiting-room"]')

            # Settings save themselves, so a value the room refuses has to snap
            # back to what the room holds and say why - three players seated is
            # exactly what makes a max of two impossible.
            await open_room_settings(host_page)
            await host_page.fill(
                '.room-settings-editor label:has-text("Max players") input', "2"
            )
            await host_page.locator(".room-settings-save").click()
            await host_page.wait_for_selector(
                '.app-toast:has-text("Max players cannot be below the 3 players")'
            )
            # The draft is not thrown away on a refusal - the host has a value
            # to correct, and may have changed other things in the same draft -
            # so the editor stays open with the reason on it.
            assert await host_page.is_visible(".room-settings-editor")
            assert await host_page.is_visible(
                '.room-settings-editor .create-room-error'
            )

            await player_page.fill(".waiting-chat-form input", "Keep this message")
            await player_page.click(".waiting-chat-form button")
            await host_page.wait_for_selector("text=Keep this message")

            await close_room_settings(host_page)
            await host_page.click('button:has-text("Start game")')
            await host_page.wait_for_selector(".game-layout")
            await player_page.wait_for_selector(".game-layout")
            await third_page.wait_for_selector(".game-layout")

            await room_menu_action(host_page, "Start the game over")
            # Opened by itself for the two who can still vote; the proposer has.
            player_vote = player_page.locator(VOTE)
            third_vote = third_page.locator(VOTE)
            await player_vote.wait_for()
            await third_vote.wait_for()
            await host_page.locator(VOTE_CHIP).wait_for()
            assert not await host_page.locator(VOTE).is_visible()
            host_vote = await open_vote(host_page)
            assert "1 yes" in await player_vote.inner_text()
            assert "2 needed" in await player_vote.inner_text()
            assert await host_vote.locator('button:has-text("Restart")').get_attribute(
                "aria-pressed"
            ) == "true"

            await player_vote.locator('button:has-text("Keep playing")').click()
            # Answered: the popover goes, and the chip brings it back.
            await player_vote.wait_for(state="hidden")
            # A locator assertion rather than `wait_for_function`, which
            # evaluates its predicate as a *string* and so needs `eval` in the
            # page. This app forbids `unsafe-eval` on purpose (R-PLAT-20), so
            # that call only ever worked while Playwright's injected helper
            # happened to be installed in the frame - a race that any change
            # to page timing can lose, and this one did.
            await expect(host_vote).to_contain_text("1 no")
            player_vote = await open_vote(player_page)
            await player_vote.locator('button:has-text("Restart")').click()

            await host_page.wait_for_selector(f'{VOTE}:has-text("Restart approved")')
            await player_page.wait_for_selector(f'{VOTE}:has-text("Restart approved")')
            for page in (host_page, player_page, third_page):
                await page.wait_for_selector(VOTE_CHIP, state="detached")

            assert await host_page.is_visible("text=Keep this message")
            assert await host_page.is_visible(".player-list >> text=RestartHost")
            assert await host_page.is_visible(".player-list >> text=RestartPlayer")
            assert await host_page.is_visible(".player-list >> text=RestartThird")
            await host_page.wait_for_selector(".prompt-choices, [data-testid=choosing-prompt-status]")
            await player_page.wait_for_selector(".prompt-choices, [data-testid=choosing-prompt-status]")
            await third_page.wait_for_selector(".prompt-choices, [data-testid=choosing-prompt-status]")
        finally:
            await host_context.close()
            await player_context.close()
            await third_context.close()
            await browser.close()


async def test_players_see_a_rejected_restart_and_cooldown():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        host_page.set_default_timeout(10_000)
        player_page.set_default_timeout(10_000)

        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "RejectHost")
            await open_new_room(host_page)
            room_code = await get_room_code(host_page)

            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "RejectPlayer")
            await join_by_code(player_page, room_code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')
            await host_page.click('button:has-text("Start game")')
            await host_page.wait_for_selector(".game-layout")
            await player_page.wait_for_selector(".game-layout")

            await room_menu_action(host_page, "Start the game over")
            player_vote = player_page.locator(VOTE)
            await player_vote.wait_for()
            await player_vote.locator('button:has-text("Keep playing")').click()

            await host_page.wait_for_selector(
                '.chat-message:has-text("The restart vote was rejected.")'
            )
            await player_page.wait_for_selector(
                '.chat-message:has-text("The restart vote was rejected.")'
            )
            await host_page.wait_for_selector(VOTE_CHIP, state="detached")
            # The Room menu's row waits out the cooldown, and says for how long.
            menu = await open_room_menu(host_page)
            restart_button = menu.locator("button", has_text="Start the game over")
            assert await restart_button.is_disabled()
            assert " in " in await restart_button.inner_text()
            await host_page.keyboard.press("Escape")
            assert await host_page.is_visible(
                "canvas.drawing-canvas, .prompt-choices, [data-testid=choosing-prompt-status]"
            )
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()


GEOMETRY = """
() => {
  const top = (selector) => {
    const element = document.querySelector(selector);
    if (!element) return null;
    const box = element.getBoundingClientRect();
    return { top: Math.round(box.top), bottom: Math.round(box.bottom), height: Math.round(box.height) };
  };
  return { canvas: top('canvas.drawing-canvas'), field: top('.chat-input input') };
}
"""


@pytest.mark.parametrize(
    "viewport",
    [
        {"width": 390, "height": 844, "phone": True},
        {"width": 844, "height": 390, "phone": True},
        {"width": 1280, "height": 800, "phone": False},
    ],
    ids=["phone", "phone-sideways", "desktop"],
)
async def test_a_restart_vote_moves_nothing_on_the_stage(viewport):
    """#1266: the vote was a banner in the page flow, so proposing one moved
    the drawer's canvas mid-stroke and, on a phone in a Wheel of Fortune room,
    pushed a guesser's field below a fold that does not scroll for the whole
    twenty seconds. As a room-bar chip it moves nothing, for any role, and it
    does not open over the drawer's canvas by itself."""
    from uuid import uuid4

    from tests.e2e.lobby_helpers import open_settings_section, save_room_settings

    size = {"width": viewport["width"], "height": viewport["height"]}
    options = {"viewport": size}
    if viewport["phone"]:
        options.update(is_mobile=True, has_touch=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(**options) for _ in range(3)]
        pages = [await context.new_page() for context in contexts]
        host = pages[0]
        try:
            tag = uuid4().hex[:5]
            await host.goto(BASE_URL)
            await use_guest_name(host, f"StillHost{tag}")
            await open_new_room(host)
            code = await get_room_code(host)
            for index, page in enumerate(pages[1:]):
                await page.goto(BASE_URL)
                await use_guest_name(page, f"Still{index}{tag}")
                await join_by_code(page, code)
                await page.wait_for_selector('[data-testid="waiting-room"]')
            await open_room_settings(host)
            await open_settings_section(host, "Scoring and hints")
            await host.locator('[aria-label="Hints"] button:has-text("Wheel of Fortune")').click()
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("lighthouse\numbrella")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            drawer = None
            for _ in range(100):
                for page in pages:
                    if await page.locator(".prompt-choices button").count():
                        drawer = page
                if drawer:
                    break
                await host.wait_for_timeout(100)
            await drawer.locator(".prompt-choices button").first.click()
            guessers = [page for page in pages if page is not drawer]
            for page in guessers:
                await page.locator(".prompt-masked").first.wait_for()
            await drawer.locator("canvas.drawing-canvas.drawable").wait_for()
            await host.wait_for_timeout(300)

            before = [await page.evaluate(GEOMETRY) for page in pages]
            await room_menu_action(guessers[0], "Start the game over")
            # The room's own line, on either side of this change: the vote is
            # open for everybody once they have it.
            for page in pages:
                await page.locator(".chat-message", has_text="started a vote to restart").first.wait_for()
            await host.wait_for_timeout(400)
            after = [await page.evaluate(GEOMETRY) for page in pages]
            assert after == before, (before, after)
            for page in guessers:
                field = (await page.evaluate(GEOMETRY))["field"]
                assert field["bottom"] <= size["height"], field
            # Opened by itself for the guesser who can still vote, never over
            # the drawer's canvas mid-stroke.
            await guessers[1].locator(VOTE).wait_for()
            assert not await drawer.locator(VOTE).is_visible()
            await drawer.locator(VOTE_CHIP).wait_for()
        finally:
            for context in contexts:
                await context.close()
            await browser.close()


async def test_a_phone_guesser_typing_through_a_vote_can_still_answer_it():
    """Review of #1316: the vote lives in the room bar, and a phone hides the
    bar while the guess keyboard is up - a guesser typing through the vote's
    twenty seconds never saw it. The bar stays while a vote awaits them."""
    from uuid import uuid4

    phone = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(**phone) for _ in range(3)]
        pages = [await context.new_page() for context in contexts]
        host = pages[0]
        try:
            tag = uuid4().hex[:5]
            await host.goto(BASE_URL)
            await use_guest_name(host, f"TypeHost{tag}")
            await open_new_room(host)
            code = await get_room_code(host)
            for index, page in enumerate(pages[1:]):
                await page.goto(BASE_URL)
                await use_guest_name(page, f"Typer{index}{tag}")
                await join_by_code(page, code)
                await page.wait_for_selector('[data-testid="waiting-room"]')
            await host.get_by_role("button", name="Start game").click()
            drawer = None
            for _ in range(100):
                for page in pages:
                    if await page.locator(".prompt-choices button").count():
                        drawer = page
                if drawer:
                    break
                await host.wait_for_timeout(100)
            await drawer.locator(".prompt-choices button").first.click()
            proposer, typist = [page for page in pages if page is not drawer]
            field = typist.locator(".chat-input input")
            await field.wait_for()
            await field.focus()
            await typist.locator(".game-room.guess-focused").wait_for()
            header = typist.locator('[data-testid="room-header"]')
            assert not await header.is_visible(), "the bar should give way to the keyboard"

            await room_menu_action(proposer, "Start the game over")
            chip = typist.locator(VOTE_CHIP)
            await chip.wait_for(state="visible")
            assert await typist.locator(".game-room.guess-focused").count() == 1
            await chip.click()
            await typist.locator(VOTE).get_by_role("button", name="Keep playing").click()
            # Answered: the bar gives way to the keyboard again.
            await field.focus()
            await header.wait_for(state="hidden")
        finally:
            for context in contexts:
                await context.close()
            await browser.close()

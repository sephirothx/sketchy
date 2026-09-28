"""Buying a hint costs nothing up front; the debt is settled by the guess."""
import asyncio

import pytest

from playwright.async_api import Page, async_playwright
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


async def choose_prompt(pages: list[Page]) -> tuple[Page, Page, str]:
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                drawer = page
                guesser = pages[1] if page is pages[0] else pages[0]
                choice = drawer.locator(".prompt-choices button").first
                prompt = (await choice.inner_text()).strip()
                await choice.click()
                await drawer.locator(".prompt-choices").wait_for(state="detached")
                await drawer.locator("canvas.drawing-canvas").wait_for()
                return drawer, guesser, prompt
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received prompt choices within 12 seconds")


async def test_a_bought_hint_is_only_paid_for_by_a_correct_guess():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        host = await host_context.new_page()
        guest = await guest_context.new_page()

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "HintHost")
            await open_new_room(host)

            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "HintGuest")
            await join_by_code(guest, code)
            await guest.locator('[data-testid="waiting-room"]').wait_for()

            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Scoring and hints")
            await host.locator('[aria-label="Hints"] button:has-text("Buy letters")').click()
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("elephant")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await guest.locator('[data-fact="prompts"]', has_text="1 custom only").wait_for()
            await guest.get_by_text("Buy letters", exact=True).wait_for()
            await host.get_by_role("button", name="Start game").click()

            drawer, guesser, prompt = await choose_prompt([host, guest])
            assert prompt == "elephant"

            my_score = guesser.locator(".player-row.is-self .player-score")
            assert (await my_score.inner_text()).strip() == "0"

            # Buying is charged to the turn, not to the balance: the score must
            # not move, and the running debt is shown instead.
            await guesser.locator(".hint-blank").first.click()
            spend_line = guesser.locator(".hint-spend-total")
            await spend_line.wait_for()
            assert (await spend_line.inner_text()).strip() == "Total: 12"
            # On credit (R-SCORE-06): the spend comes out of this turn's
            # points, never out of the running score.
            assert await spend_line.get_attribute("title") == (
                "Taken out of this turn's points if you guess the prompt."
            )
            assert (await my_score.inner_text()).strip() == "0"

            await guesser.fill(".chat-input input", prompt)
            await guesser.keyboard.press("Enter")

            personal = guesser.locator(".turn-results-personal")
            await personal.wait_for(timeout=12_000)
            breakdown = (await personal.inner_text()).strip()
            assert "-12 hints" in breakdown, breakdown

            # "Your turn: +300 -12 hints = 288 points · now #1"
            gross = int(breakdown.split("+")[1].split()[0])
            net = int(breakdown.split("=")[1].split()[0])
            assert net == gross - 12
            await guesser.wait_for_function(
                "expected => document.querySelector('.player-row.is-self .player-score')"
                "?.textContent.trim() === expected",
                arg=str(net),
            )
        finally:
            await browser.close()


@pytest.mark.parametrize(
    "mode, offer",
    [("Buy letters", ".hint-blank"), ("Wheel of Fortune", ".wheel-letter-btn")],
)
async def test_a_spectator_is_offered_no_hints(mode, offer):
    """R-SPEC-02, #1268: a spectator can never buy a hint, so none is offered -
    no priced wheel, no tappable tile. Every tap used to end in "That hint is
    not available.", while the guesser beside them is offered as before."""
    from uuid import uuid4

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(3)]
        host, guest, spectator = [await context.new_page() for context in contexts]
        try:
            tag = uuid4().hex[:5]
            await host.goto(BASE_URL)
            await use_guest_name(host, f"OfferHost{tag}")
            await open_new_room(host)
            code = await room_code(host)
            for page, name, spectate in ((guest, "OfferGuest", False), (spectator, "OfferSpy", True)):
                await page.goto(BASE_URL)
                await use_guest_name(page, f"{name}{tag}")
                await join_by_code(page, code, spectate=spectate)
                await page.locator('[data-testid="waiting-room"]').wait_for()

            await open_room_settings(host)
            await open_settings_section(host, "Scoring and hints")
            await host.locator(f'[aria-label="Hints"] button:has-text("{mode}")').click()
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("elephant\nlighthouse")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            drawer, guesser, _ = await choose_prompt([host, guest])
            await guesser.locator(offer).first.wait_for()
            await spectator.locator("canvas.drawing-canvas").wait_for()
            await spectator.locator(".prompt-masked, .masked-tile").first.wait_for()
            assert await spectator.locator(offer).count() == 0
            assert await spectator.locator(".hint-purchase, .wheel-hint-panel").count() == 0
        finally:
            for context in contexts:
                await context.close()
            await browser.close()

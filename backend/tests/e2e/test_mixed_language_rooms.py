"""Two players who do not share a language, in one Mixed room (#1182).

The host plays in English and the guest in German. Whoever draws is offered
prompts in their own language; the other guesses the drawing by naming it in
the drawer's language - which scores, since any language's spelling does -
and is shown the prompt in their own.
"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import Page, async_playwright

from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name

BASE_URL = "http://localhost:8000"
LISTS = Path(__file__).resolve().parents[2] / "data" / "prompt_lists"


def _standard(language: str) -> dict[str, str]:
    """A Standard list's answers by concept."""
    data = json.loads((LISTS / f"{language}_standard.json").read_text())
    return {entry["conceptId"]: entry["answer"] for entry in data["prompts"]}


async def _drawer_among(pages: list[Page]) -> tuple[Page, Page]:
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                return page, next(other for other in pages if other is not page)
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received prompt choices within 12 seconds")


async def test_each_player_plays_the_drawing_in_their_own_language():
    english, german = _standard("english"), _standard("german")
    concept_of = {answer: concept for concept, answer in english.items()}
    concept_of.update({answer: concept for concept, answer in german.items()})

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        guest_context = await browser.new_context()
        # The guest plays in German and reads the interface in English, so the
        # selectors below read the same on both screens.
        await guest_context.add_init_script(
            "localStorage.setItem('sketchy_promptlanguage', 'de');"
        )
        host = await host_context.new_page()
        guest = await guest_context.new_page()
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "MixedHost")
            await host.goto(f"{BASE_URL}/create")
            await host.get_by_role("button", name="Private").click()
            await host.get_by_role("button", name="Prompt language: English").click()
            await host.get_by_role("option", name="Mixed").click()
            # One language's quick prompts would leave the other players
            # without the word: the field is replaced by a sentence saying so.
            await host.click('summary:has-text("Prompts")')
            await host.get_by_text("Custom prompts are off in a mixed room").wait_for()
            assert await host.locator("#custom-prompts").count() == 0
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.locator('[data-testid="waiting-room"]').wait_for()
            code = await room_code(host)

            await guest.goto(BASE_URL)
            await use_guest_name(guest, "MixedGast")
            await join_by_code(guest, code)
            await guest.locator('[data-testid="waiting-room"]').wait_for()
            await host.get_by_role("button", name="Start game").click()

            drawer, guesser = await _drawer_among([host, guest])
            drawer_words, guesser_words = (
                (english, german) if drawer is host else (german, english)
            )
            # An offer spelled differently in the other language, where there
            # is one, so a client showing the drawer's word would be caught.
            offers = [
                text.strip()
                for text in await drawer.locator(".prompt-choices button").all_inner_texts()
            ]
            pick = next(
                (
                    index
                    for index, text in enumerate(offers)
                    if guesser_words[concept_of[text]].casefold() != text.casefold()
                ),
                0,
            )
            await drawer.locator(".prompt-choices button").nth(pick).click()
            await drawer.locator(".prompt-choices").wait_for(state="detached")
            drawn = (await drawer.locator(".prompt-reveal").inner_text()).strip()
            concept = concept_of[drawn]
            assert drawer_words[concept] == drawn, "offered in the drawer's language"
            theirs = guesser_words[concept]

            # Naming it in the drawer's language scores...
            await guesser.fill(".chat-input input", drawn)
            await guesser.keyboard.press("Enter")
            await guesser.locator(".chat-message.correct").first.wait_for()
            # ...and the guesser is shown the prompt in their own.
            await guesser.locator(".prompt-reveal").filter(has_text=theirs).first.wait_for()
            await guesser.locator(
                f'.chat-message:has-text("The prompt was \\"{theirs}\\"")'
            ).first.wait_for()
            await drawer.locator(
                f'.chat-message:has-text("The prompt was \\"{drawn}\\"")'
            ).first.wait_for()
        finally:
            await host_context.close()
            await guest_context.close()
            await browser.close()

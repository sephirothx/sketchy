"""The turn-results card: its standings before and after they move, and the
line about the viewer's own turn (#1278)."""
import asyncio
from uuid import uuid4

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

# The card as it stood on the frame its rows appeared - recorded by the page,
# since the suite's results phase is half a second (scripts/test-e2e.sh) and
# the card is gone long before a driver's round trips could read it (see
# test_multi_browser_game's WATCH_TURN_RESULTS). The slide itself starts two
# seconds in, past that: its switch to the new numbers is shownStanding's,
# covered by frontend/tests/standings.test.mjs.
WATCH = """
() => {
  window.__standings = null;
  const observer = new MutationObserver(() => {
    if (!document.querySelector('.turn-results-score-row')) return;
    observer.disconnect();
    requestAnimationFrame(() => {
      window.__standings = {
        personal: document.querySelector('.turn-results-personal')?.textContent ?? null,
        rows: [...document.querySelectorAll('.turn-results-score-row')].map((row) => ({
          name: row.querySelector('.turn-results-score-name > span').textContent.trim(),
          rank: Number(row.querySelector('.turn-results-score-rank').textContent.replace('#', '')),
          total: Number(row.querySelector('.turn-results-score-total').textContent),
          top: row.getBoundingClientRect().top,
        })),
      };
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
}
"""


async def _card(page: Page) -> dict:
    await page.wait_for_function("() => window.__standings", timeout=15_000)
    return await page.evaluate("() => window.__standings")


async def _choose_prompt(pages: list[Page]) -> tuple[Page, str]:
    for _ in range(200):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                choice = page.locator(".prompt-choices button").first
                prompt = (await choice.inner_text()).strip()
                await choice.click()
                await page.locator("canvas.drawing-canvas").wait_for()
                return page, prompt
        await asyncio.sleep(0.1)
    raise AssertionError("no drawer was offered prompt choices")


async def _guess(page: Page, text: str) -> None:
    await page.fill(".chat-input input", text)
    await page.keyboard.press("Enter")


def _in_place(rows: list[dict]) -> bool:
    """Top to bottom, the ranks rise and the totals fall: each row's number
    says where it stands."""
    ordered = sorted(rows, key=lambda row: row["top"])
    return all(
        a["rank"] <= b["rank"] and a["total"] >= b["total"] for a, b in zip(ordered, ordered[1:])
    )


async def test_the_card_shows_the_standings_it_came_in_with_and_no_personal_line():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(3)]
        pages = [await context.new_page() for context in contexts]
        try:
            host = pages[0]
            for index, page in enumerate(pages):
                await page.goto(BASE_URL)
                await use_guest_name(page, f"Card{index}{uuid4().hex[:5]}")
            await open_new_room(host)
            code = await room_code(host)
            for page in pages[1:]:
                await join_by_code(page, code)
                await page.locator('[data-testid="waiting-room"]').wait_for()
            await open_room_settings(host)
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("lighthouse\numbrella\nsandcastle")
            await host.get_by_label("Only use custom prompts").check()
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await save_room_settings(host)
            await host.get_by_role("button", name="Start game").click()

            # Turn one: both guess, one after the other, so they part.
            drawer, prompt = await _choose_prompt(pages)
            guessers = [page for page in pages if page is not drawer]
            for page in pages:
                await page.evaluate(WATCH)
            await _guess(guessers[0], prompt)
            await asyncio.sleep(1.2)
            await _guess(guessers[1], prompt)
            cards = [await _card(page) for page in pages]
            # No hints bought: the row says it all, and "Your turn" is the
            # drawer's word.
            assert [card["personal"] for card in cards] == [None, None, None], cards
            # The first turn introduces its rows with their new totals.
            after_one = {row["name"]: row["total"] for row in cards[0]["rows"]}
            assert len(set(after_one.values())) > 1, cards[0]

            # Turn two: standings that already differ, so the rows rearrange -
            # and until they do, each shows where it stood coming in.
            drawer, prompt = await _choose_prompt(pages)
            guessers = [page for page in pages if page is not drawer]
            await drawer.evaluate(WATCH)
            await _guess(guessers[1], prompt)
            await asyncio.sleep(1.2)
            await _guess(guessers[0], prompt)
            card = await _card(drawer)
            assert {row["name"]: row["total"] for row in card["rows"]} == after_one, (card, after_one)
            assert _in_place(card["rows"]), card
            for row in card["rows"]:
                assert row["rank"] == 1 + sum(total > row["total"] for total in after_one.values()), card
        finally:
            for context in contexts:
                await context.close()
            await browser.close()

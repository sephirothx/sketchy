"""A screen reader hears each thing once (#1423, R-A11Y-03).

The chat list is a `role="log"`, which a screen reader already reads as lines
arrive; a hidden chat announcer repeated every system line and correct guess,
and overlays inserted as `role="status"` repeated them a third time. One
two-turn game gave a guesser 31 live updates in about 13 seconds, 12 of them
duplicates, and the game-over card was a live `<main>` whose countdown said a
digit every second.

The page records what every live region is given - text added to a log, a
status, an alert or anything `aria-live`, and a live region inserted with its
text already in it - outside anything `aria-hidden`. That is what a screen
reader is offered, give or take its own politeness queue."""
import asyncio
import re
from uuid import uuid4

from playwright.async_api import async_playwright
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

RECORD_LIVE_REGIONS = """
(() => {
  window.__live = [];
  const LIVE = '[role="log"], [role="status"], [role="alert"], [aria-live]:not([aria-live="off"])';
  // Not rendered - display: none on it or a parent - is not spoken either;
  // clipped out of sight (.visually-hidden) still is.
  const spoken = (el) => el && !el.closest('[aria-hidden="true"]') && (!el.checkVisibility || el.checkVisibility());
  const record = (text, where, inserted = false) => {
    const said = (text || "").replace(/\\s+/g, " ").trim();
    if (said) window.__live.push({ said, where, inserted });
  };
  const name = (el) => el.getAttribute("data-testid") || el.getAttribute("role") || el.tagName.toLowerCase();
  new MutationObserver((records) => {
    for (const r of records) {
      const host = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      const region = host && host.closest(LIVE);
      if (r.type === "characterData") {
        if (region && spoken(host)) record(r.target.textContent, name(region));
        continue;
      }
      for (const node of r.addedNodes) {
        if (node.nodeType === 3) {
          if (region && spoken(host)) record(node.textContent, name(region));
          continue;
        }
        if (node.nodeType !== 1 || !spoken(node)) continue;
        if (region) {
          record(node.textContent, name(region));
          continue;
        }
        // A live region inserted whole, its text already in it.
        const regions = node.matches(LIVE) ? [node] : [...node.querySelectorAll(LIVE)];
        for (const inserted of regions) if (spoken(inserted)) record(inserted.textContent, name(inserted), true);
      }
    }
  }).observe(document, { subtree: true, childList: true, characterData: true });
})();
"""


def normal(text: str) -> str:
    return re.sub(r"[.…!\s]+$", "", re.sub(r"\s+", " ", text.lower())).strip()


async def drawer_among(pages):
    for _ in range(150):
        for page in pages:
            if await page.locator(".prompt-choices button").count():
                return page
        await asyncio.sleep(0.1)
    raise AssertionError("no drawer")


async def test_one_turn_and_the_game_over_say_each_thing_once():
    tag = uuid4().hex[:5]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(viewport={"width": 1280, "height": 860}) for _ in range(2)]
        for context in contexts:
            await context.add_init_script(RECORD_LIVE_REGIONS)
        host, guest = [await context.new_page() for context in contexts]
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, f"LiveHost{tag}")
            await open_new_room(host)
            code = await room_code(host)
            await guest.goto(BASE_URL)
            await use_guest_name(guest, f"LiveGuest{tag}")
            await join_by_code(guest, code)
            await guest.wait_for_selector('[data-testid="waiting-room"]')
            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("elephant")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            for page in (host, guest):
                await page.evaluate("() => { window.__live = []; }")
            await host.get_by_role("button", name="Start game").click()

            # One turn, as the guesser hears it: the drawer choosing, a wrong
            # guess, the right one, and the results.
            drawer = await drawer_among([host, guest])
            guesser = guest if drawer is host else host
            await drawer.wait_for_timeout(500)
            drawer_heard = [entry["said"] for entry in await drawer.evaluate("() => window.__live")]
            await drawer.locator(".prompt-choices button").first.click()
            field = guesser.locator(".chat-input input")
            await field.wait_for()
            await field.fill("giraffe")
            await field.press("Enter")
            await guesser.wait_for_timeout(400)
            await field.fill("elephant")
            await field.press("Enter")
            await guesser.locator('[data-testid="turn-results-overlay"]').wait_for(timeout=10000)
            await guesser.wait_for_timeout(1500)
            turn = await guesser.evaluate("() => window.__live")
            said = [normal(entry["said"]) for entry in turn]
            repeated = sorted({line for line in said if said.count(line) > 1})
            assert not repeated, f"said more than once in one turn: {repeated}\n{turn}"
            # Every sentence arrives as a change in a region already on the
            # page: one inserted with its text is announced unreliably.
            inserted = [entry for entry in turn if entry["inserted"]]
            assert not inserted, f"live regions inserted with their text: {inserted}"

            # The drawer is told it is their turn, and how to take it.
            assert any(normal(line).startswith("your turn: pick") for line in drawer_heard), drawer_heard

            # The game over: one sentence, not the card and then a digit a second.
            for page in (host, guest):
                await page.evaluate("() => { window.__live = []; }")
            second = await drawer_among([host, guest])
            await second.locator(".prompt-choices button").first.click()
            other = guest if second is host else host
            await other.locator(".chat-input input").fill("elephant")
            await other.locator(".chat-input input").press("Enter")
            await other.locator('[data-testid="game-end-overlay"]').wait_for(timeout=15000)
            await other.wait_for_timeout(3500)
            ended = [normal(entry["said"]) for entry in await other.evaluate("() => window.__live")]
            over = [line for line in ended if "game over" in line]
            assert len(over) == 1, f"the game over should be one sentence: {ended}"
            ticks = [line for line in ended if re.fullmatch(r"\d+", line)]
            assert not ticks, f"the countdown was read out: {ended}"
        finally:
            for context in contexts:
                await context.close()
            await browser.close()


async def test_a_phone_guesser_typing_still_hears_the_room():
    """Review of #1423: with the keyboard up a phone hides the feed, and it was
    display: none - so the log, the one live region left carrying the room's
    lines once the duplicate announcer went, said nothing while they typed. It
    is clipped out of sight instead, and keeps speaking."""
    tag = uuid4().hex[:5]
    phone = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context(**phone) for _ in range(3)]
        for context in contexts:
            await context.add_init_script(RECORD_LIVE_REGIONS)
        pages = [await context.new_page() for context in contexts]
        host = pages[0]
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, f"TypeHost{tag}")
            await open_new_room(host)
            code = await room_code(host)
            for index, page in enumerate(pages[1:]):
                await page.goto(BASE_URL)
                await use_guest_name(page, f"Typer{index}{tag}")
                await join_by_code(page, code)
                await page.wait_for_selector('[data-testid="waiting-room"]')
            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("elephant")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await host.get_by_role("button", name="Start game").click()
            drawer = await drawer_among(pages)
            await drawer.locator(".prompt-choices button").first.click()
            typist, scorer = [page for page in pages if page is not drawer]
            field = typist.locator(".chat-input input")
            await field.wait_for()
            await field.focus()
            await typist.locator(".game-room.guess-focused").wait_for()
            await typist.evaluate("() => { window.__live = []; }")
            await scorer.locator(".chat-input input").fill("elephant")
            await scorer.locator(".chat-input input").press("Enter")
            await typist.wait_for_timeout(1500)
            heard = [entry["said"] for entry in await typist.evaluate("() => window.__live")]
            assert any(" got it" in line for line in heard), heard
        finally:
            for context in contexts:
                await context.close()
            await browser.close()

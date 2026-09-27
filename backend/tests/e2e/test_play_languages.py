"""The languages a player plays in: a default and the others, ranked (#1210).

Settings → Appearance holds both. The others are chips that can be added,
moved - by their arrows or by dragging - promoted to the default and removed;
a guest keeps them in this browser, an account on every device it signs in on.
"""
from __future__ import annotations

import re
from uuid import uuid4

import pytest
from playwright.async_api import Page, async_playwright

from tests.e2e.a11y import DEFAULT_DISABLED_RULES, assert_no_axe_violations
from tests.e2e.lobby_helpers import register_account, use_guest_name

BASE_URL = "http://localhost:8000"


async def _extras(page: Page) -> list[str]:
    return await page.locator(".play-language-chip").evaluate_all(
        "chips => chips.map(chip => chip.dataset.language)"
    )


async def _open_appearance(page: Page):
    await page.goto(f"{BASE_URL}/settings/appearance")
    dialog = page.locator(".settings-modal-card")
    await dialog.wait_for(state="visible")
    return dialog


async def _add(dialog, name: str) -> None:
    await dialog.get_by_role("button", name="Add a language you play in").click()
    await dialog.get_by_role("option", name=name).click()


async def test_a_player_ranks_the_other_languages_they_play_in():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        # Italian first, then English: the browser's second language is only
        # ever suggested, never added for the player.
        context = await browser.new_context(locale="it-IT")
        await context.add_init_script(
            "Object.defineProperty(navigator, 'languages', { get: () => ['it-IT', 'en-GB', 'fr'] });"
            "localStorage.setItem('sketchy_locale', 'en');"
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, f"Ranker{uuid4().hex[:6]}")
            dialog = await _open_appearance(page)
            await dialog.get_by_role(
                "button", name="Language you play in: italiano (Italian)"
            ).wait_for()
            assert await _extras(page) == []
            suggestions = dialog.locator(".play-language-suggestions")
            await suggestions.get_by_role("button", name="Add English").wait_for()
            assert await suggestions.get_by_role("button", name="Add français").count() == 1

            # A suggestion taken is a chip, and no longer suggested.
            await suggestions.get_by_role("button", name="Add English").click()
            await _add(dialog, "Nederlands")
            await _add(dialog, "Deutsch")
            assert await _extras(page) == ["en", "nl", "de"]
            assert await suggestions.get_by_role("button", name="Add English").count() == 0

            # By the arrows, which say where it went.
            await dialog.get_by_role("button", name="Move Deutsch earlier").click()
            assert await _extras(page) == ["en", "de", "nl"]
            await dialog.get_by_text("Deutsch is now 2 of 3").wait_for()
            assert await dialog.get_by_role("button", name="Move English earlier").is_disabled()

            # By dragging its grip: Nederlands, held and dropped on English,
            # goes first.
            chips = dialog.locator(".play-language-chip")
            target = await chips.nth(0).locator(".play-language-chip-handle").bounding_box()
            x, y = await _press_on(page, chips.nth(2))
            await page.mouse.move(x, y - 10, steps=3)
            await page.mouse.move(x, target["y"] + target["height"] / 2, steps=8)
            await page.mouse.up()
            assert await _extras(page) == ["nl", "en", "de"]

            # Promoting one of them swaps the old default into its place.
            await dialog.get_by_role(
                "button", name="Language you play in: italiano (Italian)"
            ).click()
            await dialog.get_by_role("option", name="English").click()
            assert await _extras(page) == ["nl", "it", "de"]

            await dialog.get_by_role("button", name="Remove Deutsch").click()
            assert await _extras(page) == ["nl", "it"]

            # "Not now" puts the rest of the suggestions away for this browser.
            await suggestions.get_by_role("button", name="Not now").click()
            assert await dialog.locator(".play-language-suggestions").count() == 0

            # A guest's are this browser's, and survive a reload.
            await page.reload()
            dialog = await _open_appearance(page)
            await dialog.get_by_role(
                "button", name="Language you play in: English"
            ).wait_for()
            assert await _extras(page) == ["nl", "it"]
            assert await dialog.locator(".play-language-suggestions").count() == 0
        finally:
            await context.close()
            await browser.close()


async def test_an_accounts_languages_follow_it_to_another_device():
    username = f"Polyglot{uuid4().hex[:6]}"
    password = "a-good-password"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        first = await browser.new_context()
        page = await first.new_page()
        try:
            # Chosen as a guest, then carried into the account at registration.
            await page.goto(BASE_URL)
            await use_guest_name(page, username)
            dialog = await _open_appearance(page)
            await _add(dialog, "español")
            await dialog.get_by_role("button", name="Close settings").click()
            await register_account(page, username, password)

            dialog = await _open_appearance(page)
            await _add(dialog, "português")
            await _add(dialog, "italiano")
            await dialog.get_by_role("button", name="Move italiano earlier").click()
            # Promoting one goes through the server's own swap rule (#1209).
            async with page.expect_response(
                lambda response: "/api/users/me/settings" in response.url
                and response.request.method == "PATCH"
            ):
                await dialog.get_by_role("button", name="Language you play in: English").click()
                await dialog.get_by_role("option", name="português").click()
            assert await _extras(page) == ["es", "it", "en"]

            fresh = await browser.new_context()
            fresh_page = await fresh.new_page()
            try:
                await fresh_page.goto(BASE_URL)
                await fresh_page.click(".first-run-login")
                login = fresh_page.get_by_role("dialog", name="Sign in")
                await login.get_by_label("Username").fill(username)
                await login.get_by_label("Password").fill(password)
                await login.get_by_role("button", name="Sign in", exact=True).click()
                await login.wait_for(state="hidden")
                await fresh_page.wait_for_function(
                    "() => localStorage.getItem('sketchy_extrapromptlanguages') === '[\"es\",\"it\",\"en\"]'"
                )
                fresh_dialog = await _open_appearance(fresh_page)
                assert await _extras(fresh_page) == ["es", "it", "en"]
                await fresh_dialog.get_by_role(
                    "button", name="Language you play in: português (Portuguese)"
                ).wait_for()
            finally:
                await fresh.close()
        finally:
            await first.close()
            await browser.close()


async def _press_on(page: Page, chip) -> tuple[float, float]:
    """Hold a chip by its grip - the only part that lifts it."""
    box = await chip.locator(".play-language-chip-handle").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    await page.mouse.move(x, y)
    await page.mouse.down()
    return x, y


async def test_a_drag_forward_and_off_the_end_lands_and_escape_puts_one_back():
    """A chip dragged forward used to be moved in the DOM mid-drag, which
    releases its pointer capture: let go past the last chip, the drag never
    heard it, and the preview stuck until the next click committed it."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        await context.add_init_script(
            "localStorage.setItem('sketchy_promptlanguage', 'de');"
            "localStorage.setItem('sketchy_extrapromptlanguages', JSON.stringify(['nl', 'fr', 'es']));"
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, f"Dragger{uuid4().hex[:6]}")
            dialog = await _open_appearance(page)
            chips = dialog.locator(".play-language-chip")
            await chips.nth(2).wait_for()

            # Nederlands, first, carried past español - the last - and let go
            # below the list, on no chip: it stops at the list's end.
            x, y = await _press_on(page, chips.nth(0))
            last = await chips.nth(2).bounding_box()
            await page.mouse.move(x, y + 10, steps=3)
            await page.mouse.move(x - 120, last["y"] + last["height"] + 60, steps=10)
            await page.mouse.up()
            assert await _extras(page) == ["fr", "es", "nl"]
            assert await dialog.locator(".play-language-chip.is-lifted").count() == 0
            stored = await page.evaluate("localStorage.getItem('sketchy_extrapromptlanguages')")
            assert stored == '["fr","es","nl"]'

            # Escape mid-drag puts the chip back and leaves Settings open.
            x, y = await _press_on(page, chips.nth(0))
            await page.mouse.move(x, y + 70, steps=10)
            await page.keyboard.press("Escape")
            await page.mouse.up()
            assert await dialog.is_visible()
            assert await _extras(page) == ["fr", "es", "nl"]

            # Adding the last language keeps the keyboard in the row.
            for name in ("English", "italiano"):
                await _add(dialog, name)
            await _add(dialog, "português")
            assert await dialog.get_by_role("button", name="Add a language you play in").count() == 0
            await page.wait_for_function(
                "() => document.activeElement?.closest('.play-language-chip')?.dataset.language === 'pt'",
                timeout=3000,
            )
        finally:
            await context.close()
            await browser.close()


async def test_a_pane_scrolled_mid_drag_still_drops_where_the_pointer_is():
    """The places a drag can land were measured when it began; measured in
    the window, a pane scrolled mid-drag left them where the chips had been."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 700})
        await context.add_init_script(
            "localStorage.setItem('sketchy_promptlanguage', 'de');"
            "localStorage.setItem('sketchy_extrapromptlanguages', JSON.stringify(['nl', 'fr', 'es']));"
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, f"Scroller{uuid4().hex[:6]}")
            dialog = await _open_appearance(page)
            chips = dialog.locator(".play-language-chip")
            await chips.nth(2).wait_for()
            await chips.nth(0).scroll_into_view_if_needed()
            pane = dialog.locator(".play-language-extras")
            before = await pane.evaluate("row => row.getBoundingClientRect().top")

            x, y = await _press_on(page, chips.nth(0))
            await page.mouse.move(x, y + 10, steps=3)
            await page.mouse.wheel(0, 80)
            await page.wait_for_function(
                f"() => Math.abs(document.querySelector('.play-language-extras').getBoundingClientRect().top - {before}) > 20"
            )
            target = await chips.nth(2).locator(".play-language-chip-handle").bounding_box()
            await page.mouse.move(x, target["y"] + target["height"] / 2, steps=8)
            await page.mouse.up()
            assert await _extras(page) == ["fr", "es", "nl"]
        finally:
            await context.close()
            await browser.close()


@pytest.mark.parametrize(
    "viewport",
    [{"width": 390, "height": 844}, {"width": 1280, "height": 900}],
    ids=lambda v: f"{v['width']}px",
)
async def test_the_ranked_languages_are_accessible(viewport):
    """Chips, their arrows (one of each disabled at the ends), the add picker
    open, and a suggestion row: every state the row has, through axe."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport=viewport)
        await context.add_init_script(
            "Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'fr-FR'] });"
            "localStorage.setItem('sketchy_extrapromptlanguages', JSON.stringify(['nl', 'de']));"
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, f"Axe{uuid4().hex[:6]}")
            dialog = await _open_appearance(page)
            await dialog.locator(".play-language-suggestions").wait_for()
            assert await _extras(page) == ["nl", "de"]
            await assert_no_axe_violations(page, f"play languages {viewport['width']}")
            await dialog.get_by_role("button", name="Add a language you play in").click()
            await dialog.get_by_role("listbox", name="Add a language you play in").wait_for()
            # An open popup lies over the rows below it, and axe's target-size
            # rule ignores stacking, so it counts the controls half covered as
            # undersized. The rule is off for this scan, so its one new target
            # - the popup's own rows - is measured here instead.
            await assert_no_axe_violations(
                page,
                f"play languages add {viewport['width']}",
                disabled_rules=(*DEFAULT_DISABLED_RULES, "target-size"),
            )
            heights = await dialog.get_by_role("option").evaluate_all(
                "rows => rows.map(row => row.getBoundingClientRect().height)"
            )
            assert heights and min(heights) >= 24, heights
        finally:
            await context.close()
            await browser.close()


# Keeps a Quick play press off the wire and on the page, so its payload can be
# read without the press taking a seat in a room another test left waiting.
HOLD_QUICK_PLAY = """
(() => {
  window.__quickPlay = [];
  const held = (data) => typeof data === "string" && data.includes('"quick_play"');
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) {
    if (held(data)) return void window.__quickPlay.push(data);
    return send.call(this, data);
  };
  // The polling fallback carries the same frames in a request body.
  const post = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (body) {
    if (held(body)) return void window.__quickPlay.push(body);
    return post.call(this, body);
  };
})();
"""


async def test_discovery_asks_for_the_ranked_languages():
    """#1211, from the client's side: Quick play sends the others in order
    (the server ranks rooms by them - `tests/handlers/test_quick_play.py`),
    and the create form lists Mixed, the default, then the others in order.

    The press is read off the page and never sent: every public room another
    test leaves waiting is a candidate, and a seat taken in one would be that
    test's failure (e2e global server state)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        await context.add_init_script(
            "localStorage.setItem('sketchy_promptlanguage', 'fr');"
            "localStorage.setItem('sketchy_extrapromptlanguages', JSON.stringify(['nl', 'it']));"
            + HOLD_QUICK_PLAY
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, f"Ranked{uuid4().hex[:6]}")

            await page.click(".lobby-rooms-actions .btn-primary:visible, .lobby-dock-row .btn-primary:visible")
            await page.wait_for_selector(".create-room-submit")
            await page.click(".create-room-language-field .language-picker-trigger")
            options = await page.locator(".language-picker-option").evaluate_all(
                "rows => rows.map(row => row.dataset.language)"
            )
            assert options[:4] == ["mul", "fr", "nl", "it"], options
            assert len(options) == 8
            await page.keyboard.press("Escape")
            await page.goto(BASE_URL)

            async def filter_order(label: str) -> list[str]:
                await page.get_by_role("button", name=re.compile(f"^{label}: ")).click()
                rows = await page.locator(".language-picker-option").evaluate_all(
                    "rows => rows.map(row => row.dataset.language)"
                )
                await page.keyboard.press("Escape")
                return rows

            # The catalogue's filter: every language, then yours. (The lobby's
            # draws only when there are rooms to filter, and a public room
            # made for it would be in every other test's Quick play.)
            await page.goto(f"{BASE_URL}/community-lists")
            catalogue = await filter_order("Language")
            assert catalogue[:4] == ["all", "fr", "nl", "it"], catalogue
            await page.goto(BASE_URL)

            await page.locator('[data-testid="quick-play"]').click()
            await page.wait_for_function("() => window.__quickPlay.length > 0")
            pressed = (await page.evaluate("window.__quickPlay"))[-1]
            assert '"extraPromptLanguages":["nl","it"]' in pressed, pressed
            assert '"promptLanguage":"fr"' in pressed, pressed
        finally:
            await context.close()
            await browser.close()

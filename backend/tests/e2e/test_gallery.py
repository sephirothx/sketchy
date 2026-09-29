"""The Gallery (#524) end to end: two players finish a public game, and a
third account that was never in it finds the drawing on `/gallery`, opens
it, and reacts - counted, unnamed. A visitor with no session sees no
gallery at all. A report filed from the Gallery reaches the moderation
queue with its drawing, and a moderator hides the drawing from there."""
from __future__ import annotations

import random
import re
import string
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qsl, urlsplit

from playwright.async_api import Locator, Page, async_playwright, expect
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.domain_values import UserRole
from tests.e2e.lobby_helpers import (
    BASE_URL,
    join_by_code,
    open_new_room,
    open_room_settings,
    open_settings_section,
    register_account,
    room_code,
    save_room_settings,
    use_guest_name,
)
from tests.e2e.staff_helpers import set_role
from tests.e2e.test_pinned_drawings import scribble
from tests.e2e.test_profile_page import choose_prompt

CARDS = '[data-testid="gallery-card"]'


async def load_next_page(page: Page) -> bool:
    """Scroll the feed's end into view, as a reader does, and wait for the
    next page to add cards. False once the feed has ended, or when a page
    brings nothing new in time."""
    more = page.locator(".gallery-more")
    if await more.count() == 0:
        return False
    shown = await page.locator(CARDS).count()
    # A failed page stops the automatic loading behind a button.
    retry = page.get_by_test_id("gallery-show-more")
    if await retry.count():
        await retry.click()
    else:
        await more.scroll_into_view_if_needed()
    try:
        await page.wait_for_function(
            """shown => document.querySelectorAll('[data-testid="gallery-card"]').length > shown
                || !document.querySelector('.gallery-more')""",
            arg=shown,
            timeout=10_000,
        )
    except PlaywrightTimeoutError:
        return False
    return await page.locator(CARDS).count() > shown


async def find_in_gallery(
    page: Page,
    prompts: list[str],
    *,
    explain: Callable[[], Awaitable[str]] | None = None,
) -> list[Locator]:
    """The cards for `prompts` in the order the page is showing, paged to.

    Other tests' public games share this server, and in a full parallel run
    more than a page of them (24, `MAX_GALLERY_PAGE`) can land ahead of these
    drawings, so the feed is scrolled until every prompt is on screen once or
    the feed ends. The history write lands a moment after the game ends, so a
    feed that ends without them is read again.

    A refused first read leaves the skeleton and an alert, and a refused later
    page an alert and a button, so neither looks like a feed that ended; both
    are kept, with how often each prompt was on screen at the last full read
    and what `explain` finds, for the assertion to say what went wrong (#1332).
    """
    ours = [page.locator(CARDS).filter(has_text=prompt) for prompt in prompts]
    alert = page.locator(".lobby-action-error[role=alert]")
    refused: str | None = None
    counts: list[int] = []
    for attempt in range(20):
        if attempt:
            await page.wait_for_timeout(2_000)
            await page.reload()
        try:
            await page.locator(
                '[data-testid="gallery-feed"], [data-testid="gallery-empty"]'
            ).first.wait_for(timeout=10_000)
        except PlaywrightTimeoutError:
            # Ten seconds, not the default thirty: twenty of those was a
            # ten-minute failure that said nothing more than the first did.
            said = (await alert.first.inner_text()).strip() if await alert.count() else ""
            refused = f"the feed never rendered{f' ({said})' if said else ''}"
            continue
        while True:
            counts = [await card.count() for card in ours]
            if all(count == 1 for count in counts):
                return ours
            if not await load_next_page(page):
                if await alert.count():
                    refused = (await alert.first.inner_text()).strip()
                break
    try:
        reason = await explain() if explain else "no explanation asked for"
    except Exception as error:
        # The failure below is the one to raise; an explanation that broke
        # says so rather than replacing it.
        reason = f"the explanation itself failed ({error!r})"
    raise AssertionError(
        f"the gallery never listed each of {prompts} once"
        f" (on screen at the last full read: {dict(zip(prompts, counts, strict=True)) if counts else 'none'}):"
        f" {reason}"
        + (f"; the page last said {refused!r}" if refused else "")
    )


async def why_not_listed(host: Page, reader: Page, prompts: list[str]) -> str:
    """Which it is (#1332): the game's history record, its drawings'
    readiness, the feed in the order the reader's page shows, or another entry
    carrying the same words - read from the API, where each answers with its
    own status rather than an empty page."""
    me = await host.request.get(f"{BASE_URL}/api/auth/me")
    account = await me.json() if me.ok else None
    if not account:
        return f"the host's account could not be read ({me.status})"
    games = await host.request.get(
        f"{BASE_URL}/api/users/{account['id']}/games?includeAbandoned=true&limit=5"
    )
    if not games.ok:
        return f"the host's games could not be read ({games.status})"
    found = None
    unread: list[int] = []
    for game in (await games.json())["games"]:
        detail = await host.request.get(f"{BASE_URL}/api/games/{game['id']}")
        if not detail.ok:
            unread.append(detail.status)
            continue
        turns = {turn["prompt"]: turn for turn in (await detail.json()).get("turns", [])}
        if all(prompt in turns for prompt in prompts):
            found = (game, [turns[prompt] for prompt in prompts])
            break
    if found is None:
        if unread:
            return f"no readable history record holds these prompts; game reads refused {unread}"
        return "no history record for the game yet - the write has not landed"
    game, turns = found
    if game.get("visibility") != "public":
        return f"the game was recorded as {game.get('visibility')!r}, not public"
    states = {turn["prompt"]: turn.get("drawingStatus") for turn in turns}
    if any(state != "ready" for state in states.values()):
        return f"the game is recorded but its drawings are not ready: {states}"
    # The order the page is showing, read to the end the page could reach.
    order = dict(parse_qsl(urlsplit(reader.url).query))
    order.setdefault("sort", "hot")
    entries: list[dict] = []
    cursor = None
    for _ in range(20):
        feed = await reader.request.get(
            f"{BASE_URL}/api/gallery", params={**order, **({"cursor": cursor} if cursor else {})}
        )
        if not feed.ok:
            return f"recorded and ready, but the feed refused this reader ({feed.status})"
        body = await feed.json()
        entries += body.get("entries", [])
        cursor = body.get("nextCursor")
        if not cursor:
            break
    listed = {entry["turnId"] for entry in entries}
    missing = [turn["prompt"] for turn in turns if turn["id"] not in listed]
    if missing:
        return f"recorded and ready, but the feed's {order} ({len(entries)} entries) lacks {missing}"
    alike = {
        prompt: sum(prompt.lower() in entry["prompt"].lower() for entry in entries)
        for prompt in prompts
    }
    if any(count > 1 for count in alike.values()):
        return f"recorded, ready and listed, but other entries carry the same words: {alike}"
    return f"recorded, ready and in the feed's {order} - the page is what failed"


async def test_a_stranger_finds_a_public_drawing_in_the_gallery_and_reacts():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        other_context = await browser.new_context()
        host = await host_context.new_page()
        other = await other_context.new_page()

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "GalHost")
            await register_account(host, "galhost")
            await open_new_room(host)
            code = await room_code(host)

            await other.goto(BASE_URL)
            await use_guest_name(other, "GalOther")
            await register_account(other, "galother")
            await join_by_code(other, code)
            await other.locator('[data-testid="waiting-room"]').wait_for()

            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            # Words no other game can draw: both "lantern" and "kite" are in the
            # English standard list, and the card match is by text, so any
            # other public game that drew one put a second card in the match
            # and `count() == 1` never held - twenty full reads of the feed,
            # reported as "never listed" (#1332).
            run = "".join(random.choices(string.ascii_lowercase, k=6))
            await host.locator("#custom-prompts").fill(f"lantern {run}\nkite {run}")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await other.locator('[data-fact="prompts"]', has_text="2 custom only").wait_for()
            await host.get_by_role("button", name="Start game").click()

            pages = [host, other]
            prompts: list[str] = []
            for _ in range(2):
                drawer, guesser, prompt = await choose_prompt(pages)
                prompts.append(prompt)
                await scribble(drawer)
                await guesser.fill(".chat-input input", prompt)
                await guesser.keyboard.press("Enter")
            await host.locator('[data-testid="game-end-overlay"]').wait_for(timeout=12_000)

            # A stranger, registered, never in the game: the gallery lists
            # both drawings once the history write lands (R-GAL-01).
            stranger_context = await browser.new_context()
            stranger = await stranger_context.new_page()
            await stranger.goto(BASE_URL)
            await use_guest_name(stranger, "GalStranger")
            await register_account(stranger, "galstranger")
            # Newest first: a drawing that just finished is on the first page
            # there, where Hot puts other tests' reacted drawings ahead of an
            # unreacted one and the stranger has pages to read (#1332).
            await stranger.goto(f"{BASE_URL}/gallery?sort=new")
            # Other tests' public games share this server, so the feed is
            # read for *these* drawings rather than counted.
            ours = await find_in_gallery(
                stranger, prompts, explain=lambda: why_not_listed(host, stranger, prompts)
            )
            # No game id anywhere on the page: nothing to follow into the game.
            assert "/room/" not in await stranger.content()

            # Open the first of ours: its own page, where the drawing replays
            # and the picker lives; react through the gallery door.
            await ours[0].get_by_role("button").first.click()
            await stranger.locator('[data-testid="gallery-drawing-page"]').wait_for()
            assert "/gallery/" in stranger.url
            drawing_url = stranger.url
            await stranger.locator('[data-testid="gallery-drawing-canvas"] canvas').wait_for()
            await stranger.locator('[data-testid="reaction-toggle"]').click()
            await stranger.locator('[data-testid="reaction-option-fire"]').click()
            await expect(
                stranger.locator(
                    '[data-testid="reaction-control"] .reaction-chip[data-emoji="fire"] .reaction-count'
                )
            ).to_have_text("1")

            # Report it from the Gallery (R-GAL-08): the turn is named, the
            # drawing is copied in, and the drawer is resolved by the server.
            await stranger.locator('[data-testid="gallery-report"]').click()
            dialog = stranger.locator('[data-testid="report-drawing-dialog"]')
            await dialog.wait_for()
            await dialog.locator("textarea").fill("Not for a lobby.")
            await dialog.locator('[data-testid="report-drawing-send"]').click()
            await dialog.get_by_role("button", name="Close").wait_for()
            await dialog.get_by_role("button", name="Close").click()

            # Back to the feed, which shows the reaction on the card.
            await stranger.go_back()
            [reacted] = await find_in_gallery(
                stranger, prompts[:1], explain=lambda: why_not_listed(host, stranger, prompts[:1])
            )
            await expect(reacted.locator(".reaction-count")).to_have_text("1")

            # Top over the week still lists it, with its reaction counted.
            await stranger.locator('[data-testid="gallery-sort"]').get_by_role("button", name="Top").click()
            await stranger.locator('[data-testid="gallery-window"]').get_by_role("button", name="This week").click()
            await expect(stranger).to_have_url(re.compile(r"sort=top.*window=week"))
            [reacted] = await find_in_gallery(
                stranger, prompts[:1], explain=lambda: why_not_listed(host, stranger, prompts[:1])
            )
            await expect(reacted.locator(".reaction-count")).to_have_text("1")
            await stranger_context.close()

            # The drawer sees the stranger's reaction in their own history,
            # counted and named by nobody.
            await host.goto(f"{BASE_URL}/profile")
            await host.locator(".profile-game").first.locator(".profile-game-header").click()
            await host.locator(".profile-turns").wait_for()
            await expect(host.locator(".profile-turns .reaction-count").first).to_have_text("1")

            # A moderator finds the report with its drawing, and hides the
            # drawing from the gallery from there (R-GAL-09); the stranger's
            # gallery loses it, the drawer's own history keeps it.
            moderator_context = await browser.new_context()
            moderator = await moderator_context.new_page()
            await moderator.goto(BASE_URL)
            await use_guest_name(moderator, "GalModerator")
            await register_account(moderator, "galmoderator")
            await set_role("galmoderator", UserRole.MODERATOR.value)
            await moderator.goto(f"{BASE_URL}/moderation")
            case = moderator.locator(".mod-queue-item", has_text="Gal")
            await case.first.wait_for()
            await case.first.click()
            figure = moderator.locator('[data-testid="mod-drawing"]')
            await figure.wait_for()
            await figure.locator("canvas").wait_for()
            await moderator.locator(".mod-note textarea").fill("Not for the lobby.")
            await moderator.locator('[data-testid="gallery-hide-from-report"]').click()
            await moderator.wait_for_selector('[role="status"]:has-text("Hidden from the gallery")')
            await moderator_context.close()

            checker_context = await browser.new_context()
            checker = await checker_context.new_page()
            await checker.goto(BASE_URL)
            await use_guest_name(checker, "GalChecker")
            await checker.goto(drawing_url)
            await checker.get_by_test_id("gallery-drawing-missing").wait_for()
            # New puts one game's drawings side by side, so wherever the
            # other one is found, the hidden one would sit next to it: on
            # that page or the one after.
            await checker.goto(f"{BASE_URL}/gallery?sort=new")
            await find_in_gallery(
                checker, prompts[1:], explain=lambda: why_not_listed(host, checker, prompts[1:])
            )
            await load_next_page(checker)
            await expect(checker.locator(CARDS).filter(has_text=prompts[0])).to_have_count(0)
            await checker_context.close()

            # No session: no gallery (R-GAL-02).
            anonymous_context = await browser.new_context()
            anonymous = await anonymous_context.new_page()
            await anonymous.goto(f"{BASE_URL}/gallery")
            await anonymous.get_by_test_id("gallery-signed-out").get_by_text(
                "Sign in to see the gallery", exact=True
            ).wait_for()
            await expect(anonymous.locator('[data-testid="gallery-feed"]')).to_have_count(0)
            await anonymous_context.close()
        finally:
            await host_context.close()
            await other_context.close()
            await browser.close()

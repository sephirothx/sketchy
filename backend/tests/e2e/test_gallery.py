"""The Gallery (#524) end to end: two players finish a public game, and a
third account that was never in it finds the drawing on `/gallery`, opens
it, and reacts - counted, unnamed. A visitor with no session sees no
gallery at all. A report filed from the Gallery reaches the moderation
queue with its drawing, and a moderator hides the drawing from there."""
from __future__ import annotations

from playwright.async_api import async_playwright, expect

from app.domain_values import UserRole
from tests.e2e.lobby_helpers import (
    BASE_URL,
    join_by_code,
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
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.locator('[data-testid="waiting-room"]').wait_for()
            code = await room_code(host)

            await other.goto(BASE_URL)
            await use_guest_name(other, "GalOther")
            await register_account(other, "galother")
            await join_by_code(other, code)
            await other.locator('[data-testid="waiting-room"]').wait_for()

            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("lantern\nkite")
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
            await stranger.goto(f"{BASE_URL}/gallery")
            # Other tests' public games share this server, so the page is
            # read for *these* drawings rather than counted; the history
            # write lands a moment after the game ends, hence the retries.
            cards = stranger.locator('[data-testid="gallery-card"]')
            ours = [cards.filter(has_text=prompt) for prompt in prompts]
            for _ in range(20):
                if all([await card.count() == 1 for card in ours]):
                    break
                await stranger.wait_for_timeout(2_000)
                await stranger.reload()
            await stranger.locator('[data-testid="gallery-feed"]').wait_for()
            for card in ours:
                await expect(card).to_have_count(1)
            # No game id anywhere on the page: nothing to follow into the game.
            assert "/room/" not in await stranger.content()

            # Open the first of ours: its own page, where the drawing replays
            # and the picker lives; react through the gallery door.
            await ours[0].get_by_role("button").first.click()
            await stranger.locator('[data-testid="gallery-drawing-page"]').wait_for()
            assert "/gallery/" in stranger.url
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
            await dialog.get_by_role("button", name="OK", exact=True).wait_for()
            await dialog.get_by_role("button", name="OK", exact=True).click()

            # Back to the feed, which shows the reaction on the card.
            await stranger.go_back()
            await stranger.locator('[data-testid="gallery-feed"]').wait_for()
            await expect(ours[0].locator(".reaction-count")).to_have_text("1")

            # Top over the week still lists it, with its reaction counted.
            await stranger.locator('[data-testid="gallery-sort"]').get_by_role("button", name="Top").click()
            await stranger.locator('[data-testid="gallery-window"]').get_by_role("button", name="This week").click()
            await expect(ours[0]).to_have_count(1)
            await expect(ours[0].locator(".reaction-count")).to_have_text("1")
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
            await checker.goto(f"{BASE_URL}/gallery?sort=new")
            await checker.locator('[data-testid="gallery-feed"], [data-testid="gallery-signed-out"], [data-testid="gallery-empty"]').first.wait_for()
            await expect(checker.locator('[data-testid="gallery-card"]').filter(has_text=prompts[0])).to_have_count(0)
            await checker_context.close()

            # No session: no gallery (R-GAL-02).
            anonymous_context = await browser.new_context()
            anonymous = await anonymous_context.new_page()
            await anonymous.goto(f"{BASE_URL}/gallery")
            await anonymous.get_by_text("signed-in players", exact=False).wait_for()
            await expect(anonymous.locator('[data-testid="gallery-feed"]')).to_have_count(0)
            await anonymous_context.close()
        finally:
            await host_context.close()
            await other_context.close()
            await browser.close()

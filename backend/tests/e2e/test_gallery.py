"""The Gallery (#524) end to end: two players finish a public game, and a
third account that was never in it finds the drawing on `/gallery`, opens
it, and reacts - counted, unnamed. A visitor with no session sees no
gallery at all."""
from __future__ import annotations

from playwright.async_api import async_playwright, expect
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
            await other.get_by_text("Custom prompts only (2)").wait_for()
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
            await stranger.locator('[data-testid="gallery-grid"]').wait_for()
            for card in ours:
                await expect(card).to_have_count(1)
            # No game id anywhere on the page: nothing to follow into the game.
            assert "/room/" not in await stranger.content()

            # Open the first of ours and react through the gallery door.
            await ours[0].get_by_role("button").first.click()
            await stranger.locator(".drawing-recap").wait_for()
            await stranger.locator('[data-testid="reaction-toggle"]').click()
            await stranger.locator('[data-testid="reaction-option-fire"]').click()
            await expect(
                stranger.locator(
                    '[data-testid="reaction-control"] .reaction-chip[data-emoji="fire"] .reaction-count'
                )
            ).to_have_text("1")
            await stranger.keyboard.press("Escape")
            await expect(stranger.locator(".drawing-recap")).to_have_count(0)
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

            # The lobby's This week shelf shows the same drawings, the
            # reacted one first (R-GAL-07).
            # Six at most, so on a server other shards share ours need not
            # be among them; the order is proven by the route's own test.
            await host.goto(BASE_URL)
            shelf = host.locator('[data-testid="this-week"]')
            await shelf.wait_for()
            await shelf.locator('[data-testid="gallery-card"]').first.wait_for()
            shelf_cards = await shelf.locator('[data-testid="gallery-card"]').count()
            assert 1 <= shelf_cards <= 6, shelf_cards

            # No session: no gallery and no shelf (R-GAL-02).
            anonymous_context = await browser.new_context()
            anonymous = await anonymous_context.new_page()
            await anonymous.goto(f"{BASE_URL}/gallery")
            await anonymous.get_by_text("signed-in players", exact=False).wait_for()
            await expect(anonymous.locator('[data-testid="gallery-grid"]')).to_have_count(0)
            await anonymous.goto(BASE_URL)
            await anonymous.locator(".lobby-rooms-panel").wait_for()
            await expect(anonymous.locator('[data-testid="this-week"]')).to_have_count(0)
            await anonymous_context.close()
        finally:
            await host_context.close()
            await other_context.close()
            await browser.close()

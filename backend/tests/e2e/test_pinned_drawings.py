"""Pinned drawings (#440) end to end: pinned from the game-over recap, shown
on the profile shelf to the owner and to another signed-in player, unpinned
from the shelf, and pinned again from the profile's game history."""
from __future__ import annotations

from playwright.async_api import Page, async_playwright, expect
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_room_settings,
    open_settings_section,
    register_account,
    room_code,
    save_room_settings,
    use_guest_name,
)
from tests.e2e.test_profile_page import choose_prompt

BASE_URL = "http://localhost:8000"


async def scribble(drawer: Page) -> None:
    """One stroke, so the stored frame has something a thumbnail can show."""
    box = await drawer.locator("canvas.drawing-canvas").first.bounding_box()
    assert box is not None
    await drawer.mouse.move(box["x"] + box["width"] * 0.2, box["y"] + box["height"] * 0.2)
    await drawer.mouse.down()
    await drawer.mouse.move(box["x"] + box["width"] * 0.7, box["y"] + box["height"] * 0.6, steps=10)
    await drawer.mouse.up()


async def test_a_drawing_pinned_from_the_recap_reaches_the_profile_shelf():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        other_context = await browser.new_context()
        host = await host_context.new_page()
        other = await other_context.new_page()

        try:
            # Both registered: only an account may pin (R-PIN-01), and the
            # shelf is shown to any session, so the other player is the
            # signed-in non-participant... except they were in the game.
            # A third, anonymous context stands in for the stranger below.
            await host.goto(BASE_URL)
            await use_guest_name(host, "PinHost")
            await register_account(host, "pinhost")
            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.locator('[data-testid="waiting-room"]').wait_for()
            code = await room_code(host)

            await other.goto(BASE_URL)
            await use_guest_name(other, "PinOther")
            await register_account(other, "pinother")
            await join_by_code(other, code)
            await other.locator('[data-testid="waiting-room"]').wait_for()

            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("apple\ntree")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await other.locator('[data-fact="prompts"]', has_text="2 custom only").wait_for()
            await host.get_by_role("button", name="Start game").click()

            pages = [host, other]
            for _ in range(2):
                drawer, guesser, prompt = await choose_prompt(pages)
                await scribble(drawer)
                await guesser.fill(".chat-input input", prompt)
                await guesser.keyboard.press("Enter")

            game_end = host.locator('[data-testid="game-end-overlay"]')
            await game_end.get_by_role("button", name="Drawings", exact=True).wait_for(timeout=12_000)

            # Pin the first drawing from the recap. The history write lands
            # just before the recap is offered, so the first press may be
            # answered "still being saved"; the control stays and a second
            # press is the retry the toast asks for.
            await game_end.get_by_role("button", name="Drawings", exact=True).click()
            await host.locator(".drawing-recap").wait_for()
            toggle = host.locator('[data-testid="pin-toggle"]')
            await expect(toggle).to_have_attribute("aria-pressed", "false")
            for _ in range(20):
                await toggle.click()
                try:
                    await expect(toggle).to_have_attribute("aria-pressed", "true", timeout=1_500)
                    break
                except AssertionError:
                    continue
            await expect(toggle).to_have_attribute("aria-pressed", "true")
            first_prompt = (await host.locator("#drawing-recap-title").inner_text()).strip()

            # The owner's shelf shows it, in a lobby tab of the same account.
            lobby = await host_context.new_page()
            await lobby.goto(f"{BASE_URL}/profile")
            shelf = lobby.locator('[data-testid="pinned-drawings"]')
            await shelf.wait_for()
            await expect(shelf.locator(".profile-shelf-item")).to_have_count(1)
            await expect(shelf.locator(".profile-shelf-prompt").first).to_have_text(first_prompt)
            await lobby.locator(".profile-shelf-canvas canvas").first.wait_for()

            # The other player, signed in, sees the shelf without controls.
            visitor = await other_context.new_page()
            host_id = (await (await host_context.request.get(f"{BASE_URL}/api/auth/me")).json())["id"]
            await visitor.goto(f"{BASE_URL}/profile/{host_id}")
            await visitor.locator('[data-testid="pinned-drawings"]').wait_for()
            await expect(visitor.locator(".profile-shelf-item")).to_have_count(1)
            await expect(visitor.get_by_role("button", name="Unpin")).to_have_count(0)

            # A stranger - registered, never in the game - reacts to the pinned
            # drawing from the shelf through the gallery door (R-PIN-08,
            # R-GAL-06): the tally counts it, and nobody is named.
            stranger_context = await browser.new_context()
            stranger = await stranger_context.new_page()
            await stranger.goto(BASE_URL)
            await use_guest_name(stranger, "PinStranger")
            await register_account(stranger, "pinstranger")
            await stranger.goto(f"{BASE_URL}/profile/{host_id}")
            await stranger.locator('[data-testid="pinned-drawings"] .profile-shelf-open').first.click()
            await stranger.locator(".drawing-recap").wait_for()
            await stranger.locator('[data-testid="reaction-toggle"]').click()
            await stranger.locator('[data-testid="reaction-option-wow"]').click()
            await expect(
                stranger.locator(
                    '[data-testid="reaction-control"] .reaction-chip[data-emoji="wow"] .reaction-count'
                )
            ).to_have_text("1")
            await stranger.keyboard.press("Escape")
            await expect(stranger.locator(".drawing-recap")).to_have_count(0)
            await expect(
                stranger.locator('[data-testid="pinned-drawings"] .reaction-chip .reaction-count').first
            ).to_have_text("1")
            await stranger_context.close()

            # A visitor with no session sees no shelf at all (R-PIN-06).
            anonymous_context = await browser.new_context()
            anonymous = await anonymous_context.new_page()
            await anonymous.goto(f"{BASE_URL}/profile/{host_id}")
            await anonymous.locator(".profile-stat").first.wait_for()
            await expect(anonymous.locator('[data-testid="pinned-drawings-panel"]')).to_have_count(0)
            await anonymous_context.close()

            # Unpin from the shelf: the owner's own empty shelf stays, with its hint.
            await shelf.locator(".profile-shelf-item").first.get_by_role("button", name="Unpin").click()
            await expect(shelf.locator(".profile-shelf-item")).to_have_count(0)
            await lobby.get_by_text("Nothing pinned yet", exact=False).wait_for()

            # Pin again from game history: the turn table offers the toggle
            # beside View for each kept drawing, and the shelf above follows.
            game_row = lobby.locator(".profile-game").first
            await game_row.locator(".profile-game-header").click()
            await lobby.locator(".profile-turns").wait_for()
            table_toggles = lobby.locator('.profile-turns [data-testid="pin-toggle"]')
            await expect(table_toggles).to_have_count(2)
            await expect(table_toggles.first).to_have_attribute("aria-pressed", "false")
            await table_toggles.first.click()
            await expect(table_toggles.first).to_have_attribute("aria-pressed", "true")
            await expect(lobby.locator('[data-testid="pinned-drawings"] .profile-shelf-item')).to_have_count(1)
            await table_toggles.nth(1).click()
            await expect(lobby.locator('[data-testid="pinned-drawings"] .profile-shelf-item')).to_have_count(2)
        finally:
            await host_context.close()
            await other_context.close()
            await browser.close()

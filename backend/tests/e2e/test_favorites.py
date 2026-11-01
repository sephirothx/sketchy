"""Favorites (#440) end to end: favorited from the game-over recap, shown
on the profile shelf to the owner and to another signed-in player, unfavorited
from the shelf, and favorited again from the profile's game history."""
from __future__ import annotations

from playwright.async_api import Page, async_playwright, expect
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_new_room,
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


async def test_a_drawing_favorited_from_the_recap_reaches_the_profile_shelf():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        other_context = await browser.new_context()
        host = await host_context.new_page()
        other = await other_context.new_page()

        try:
            # Both registered: only an account may favorite (R-PIN-01), and the
            # shelf is shown to any session, so the other player is the
            # signed-in non-participant... except they were in the game.
            # A third, anonymous context stands in for the stranger below.
            await host.goto(BASE_URL)
            await use_guest_name(host, "FavHost")
            await register_account(host, "favhost")
            await open_new_room(host)
            code = await room_code(host)

            await other.goto(BASE_URL)
            await use_guest_name(other, "FavOther")
            await register_account(other, "favother")
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

            # Favorite the first drawing from the recap. The history write lands
            # just before the recap is offered, so the first press may be
            # answered "still being saved"; the control stays and a second
            # press is the retry the toast asks for.
            await game_end.get_by_role("button", name="Drawings", exact=True).click()
            await host.get_by_test_id("drawing-viewer").wait_for()
            toggle = host.locator('[data-testid="favorite-toggle"]')
            await expect(toggle).to_have_attribute("aria-pressed", "false")
            for _ in range(20):
                await toggle.click()
                try:
                    await expect(toggle).to_have_attribute("aria-pressed", "true", timeout=1_500)
                    break
                except AssertionError:
                    continue
            await expect(toggle).to_have_attribute("aria-pressed", "true")
            first_prompt = (await host.locator("#drawing-viewer-title").inner_text()).strip()

            # The owner's shelf shows it, in a lobby tab of the same account.
            lobby = await host_context.new_page()
            await lobby.goto(f"{BASE_URL}/profile")
            shelf = lobby.locator('[data-testid="favorites"]')
            await shelf.wait_for()
            await expect(shelf.locator(".profile-shelf-item")).to_have_count(1)
            await expect(shelf.locator(".profile-shelf-prompt").first).to_have_text(first_prompt)
            await lobby.locator(".profile-shelf-canvas img").first.wait_for()

            # The other player, signed in, sees the shelf without controls.
            visitor = await other_context.new_page()
            host_id = (await (await host_context.request.get(f"{BASE_URL}/api/auth/me")).json())["id"]
            await visitor.goto(f"{BASE_URL}/profile/{host_id}")
            await visitor.locator('[data-testid="favorites"]').wait_for()
            await expect(visitor.locator(".profile-shelf-item")).to_have_count(1)
            await expect(visitor.locator('[data-testid="favorites"]').get_by_role("button", name="Remove", exact=True)).to_have_count(0)

            # A stranger - registered, never in the game - reacts to the favorited
            # drawing from the shelf through the gallery door (R-PIN-08,
            # R-GAL-06): the tally counts it, and nobody is named.
            stranger_context = await browser.new_context()
            stranger = await stranger_context.new_page()
            await stranger.goto(BASE_URL)
            await use_guest_name(stranger, "FavStranger")
            await register_account(stranger, "favstranger")
            await stranger.goto(f"{BASE_URL}/profile/{host_id}")
            await stranger.locator('[data-testid="favorites"] .profile-shelf-open').first.click()
            await stranger.get_by_test_id("drawing-viewer").wait_for()
            await stranger.locator('[data-testid="reaction-toggle"]').click()
            await stranger.locator('[data-testid="reaction-option-wow"]').click()
            await expect(
                stranger.locator(
                    '[data-testid="reaction-control"] .reaction-chip[data-emoji="wow"] .reaction-count'
                )
            ).to_have_text("1")
            await stranger.keyboard.press("Escape")
            await expect(stranger.get_by_test_id("drawing-viewer")).to_have_count(0)
            await expect(
                stranger.locator('[data-testid="favorites"] .reaction-chip .reaction-count').first
            ).to_have_text("1")
            await stranger_context.close()

            # A visitor with no session sees no shelf at all (R-PIN-06).
            anonymous_context = await browser.new_context()
            anonymous = await anonymous_context.new_page()
            await anonymous.goto(f"{BASE_URL}/profile/{host_id}")
            await anonymous.locator(".profile-stat").first.wait_for()
            await expect(anonymous.locator('[data-testid="favorites-panel"]')).to_have_count(0)
            await anonymous_context.close()

            # Remove it from the shelf: the owner's own empty shelf stays, with its hint.
            await shelf.locator(".profile-shelf-item").first.get_by_role("button", name="Remove").click()
            await expect(shelf.locator(".profile-shelf-item")).to_have_count(0)
            await lobby.get_by_text("No favorites yet", exact=False).wait_for()

            # Favorite again from game history: the turn table offers the toggle
            # beside View for each kept drawing, and the shelf above follows.
            game_row = lobby.locator(".profile-game").first
            await game_row.locator(".profile-game-header").click()
            await lobby.locator(".profile-turns").wait_for()
            table_toggles = lobby.locator('.profile-turns [data-testid="favorite-toggle"]')
            await expect(table_toggles).to_have_count(2)
            await expect(table_toggles.first).to_have_attribute("aria-pressed", "false")
            await table_toggles.first.click()
            await expect(table_toggles.first).to_have_attribute("aria-pressed", "true")
            await expect(lobby.locator('[data-testid="favorites"] .profile-shelf-item')).to_have_count(1)
            await table_toggles.nth(1).click()
            await expect(lobby.locator('[data-testid="favorites"] .profile-shelf-item')).to_have_count(2)

            # Take out of Solo is on the drawer's own row, one of the two
            # (R-SOLO-17), and works from there; the viewer, whose buttons are
            # icons alone, does not offer it (#1497).
            solo = lobby.locator('.profile-turns [data-testid="solo-take-out"]')
            await expect(solo).to_have_count(1)
            before = await solo.inner_text()
            await solo.click()
            await expect(solo).not_to_have_text(before)
            await lobby.locator(".profile-drawing-button").first.click()
            viewer = lobby.get_by_test_id("drawing-viewer")
            await viewer.wait_for()
            await expect(viewer.locator('[data-testid="favorite-toggle"]')).to_have_count(1)
            await expect(viewer.locator('[data-testid="solo-take-out"]')).to_have_count(0)

            # Friends opened over the open viewer - as a friend-request toast's
            # Open does - is a screen of its own: the viewer steps aside rather
            # than covering it and taking its clicks, and is back on the same
            # drawing when Friends closes (#1497). The header is under the
            # viewer, so its menu is driven the way the toast drives the route.
            shown = await viewer.locator('.drawing-viewer-thumb[aria-current="true"]').get_attribute("aria-label")
            await lobby.evaluate("() => document.querySelector('.identity-chip').click()")
            await lobby.evaluate(
                "() => [...document.querySelectorAll('[role=menuitem]')]"
                ".find((item) => item.textContent.trim().startsWith('Friends')).click()"
            )
            await lobby.wait_for_url("**/friends")
            friends = lobby.get_by_test_id("friends")
            await friends.wait_for()
            await expect(viewer).to_be_hidden()
            await friends.locator(".modal-close").click(timeout=5_000)
            await lobby.wait_for_url("**/profile")
            await expect(viewer).to_be_visible()
            await expect(viewer.locator('.drawing-viewer-thumb[aria-current="true"]')).to_have_attribute("aria-label", shown)
        finally:
            await host_context.close()
            await other_context.close()
            await browser.close()

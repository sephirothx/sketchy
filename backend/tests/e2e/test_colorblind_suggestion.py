"""Host-only colorblind-safe room suggestion behavior in real browsers."""
from __future__ import annotations

import pytest
from playwright.async_api import async_playwright, expect

from tests.e2e.lobby_helpers import open_room_settings, room_code, use_guest_name


BASE_URL = "http://localhost:8000"


async def _create_room(host, name: str) -> str:
    await host.goto(BASE_URL)
    await use_guest_name(host, f"{name.replace(' ', '')[:10]}Host")
    await host.get_by_role("button", name="Create room").click()
    await host.get_by_placeholder("Leave blank for a random name!").fill(name)
    await host.get_by_role("button", name="Private").click()
    await host.get_by_role("button", name="Create room").click()
    await host.get_by_test_id("waiting-room").wait_for()
    return await room_code(host)


async def _join_invite(page, code: str, name: str, *, spectator: bool = False):
    await page.goto(f"{BASE_URL}/room/{code}")
    await use_guest_name(page, name)
    await page.get_by_role(
        "button", name="Spectate" if spectator else "Join game", exact=True
    ).click()
    await page.get_by_test_id("waiting-room").wait_for()


@pytest.mark.asyncio
async def test_only_host_sees_suggestion_and_acceptance_switches_room_colors():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, args=["--mute-audio"]
        )
        host_context = await browser.new_context()
        spectator_context = await browser.new_context()
        player_context = await browser.new_context()
        await spectator_context.add_init_script(
            "localStorage.setItem('sketchy_colorblindsafecolors', 'true')"
        )
        await player_context.add_init_script(
            "localStorage.setItem('sketchy_colorblindsafecolors', 'true')"
        )
        host = await host_context.new_page()
        spectator = await spectator_context.new_page()
        player = await player_context.new_page()
        try:
            code = await _create_room(host, "Safe colors")
            suggestion = host.get_by_test_id("colorblind-safe-suggestion")

            await _join_invite(
                spectator, code, "SafeSpectator", spectator=True
            )
            assert not await suggestion.is_visible()

            await _join_invite(player, code, "SafePlayer")
            await suggestion.wait_for()
            assert await suggestion.get_by_text(
                "A player in this room plays with colorblind-safe colors.",
                exact=True,
            ).is_visible()
            assert not await player.get_by_test_id(
                "colorblind-safe-suggestion"
            ).is_visible()
            assert not await spectator.get_by_test_id(
                "colorblind-safe-suggestion"
            ).is_visible()

            await suggestion.get_by_role("button", name="Switch colors").click()
            await suggestion.wait_for(state="hidden")
            await player.get_by_text("Colorblind-safe", exact=True).wait_for()
            await spectator.get_by_text("Colorblind-safe", exact=True).wait_for()

            # The host's own form has to move with the room. The palette is the
            # one setting the room can change without this form asking, and a
            # form still offering the old one would disagree with the game.
            await open_room_settings(host)
            host_colors = host.get_by_role("group", name="Colors").get_by_role(
                "button", name="Colorblind-safe"
            )
            await expect(host_colors).to_have_attribute("aria-pressed", "true")
        finally:
            await host_context.close()
            await spectator_context.close()
            await player_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_dismissed_suggestion_does_not_return_when_preference_changes():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, args=["--mute-audio"]
        )
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        await player_context.add_init_script(
            "localStorage.setItem('sketchy_colorblindsafecolors', 'true')"
        )
        host = await host_context.new_page()
        player = await player_context.new_page()
        try:
            code = await _create_room(host, "Dismiss colors")
            await _join_invite(player, code, "DismissPlayer")
            suggestion = host.get_by_test_id("colorblind-safe-suggestion")
            await suggestion.wait_for()
            await suggestion.get_by_role("button", name="Not now").click()
            await suggestion.wait_for(state="hidden")

            for desired in (False, True):
                await player.locator("button.header-settings-button").click()
                dialog = player.locator(".settings-modal-card")
                await dialog.wait_for()
                preference = dialog.get_by_role(
                    "switch", name="Prefer colorblind-safe colors"
                )
                if desired:
                    await preference.check()
                else:
                    await preference.uncheck()
                await dialog.get_by_role("button", name="Save").click()
                await dialog.wait_for(state="hidden")

            await host.wait_for_timeout(250)
            assert not await suggestion.is_visible()
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_a_colorblind_host_starts_a_room_on_colorblind_safe_colors():
    """The palette a host plays with is the one their room should start on."""

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True, args=["--mute-audio"]
        )
        context = await browser.new_context()
        await context.add_init_script(
            "localStorage.setItem('sketchy_colorblindsafecolors', 'true')"
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, "SafeCreator")
            await page.get_by_role("button", name="Create room").click()

            await page.click('summary:has-text("Drawing")')
            colors = page.get_by_role("group", name="Colors")
            await expect(
                colors.get_by_role("button", name="Colorblind-safe")
            ).to_have_attribute("aria-pressed", "true")
            await expect(
                colors.get_by_role("button", name="All colors")
            ).to_have_attribute("aria-pressed", "false")

            # Still a choice, not a lock.
            await colors.get_by_role("button", name="All colors").click()
            await expect(
                colors.get_by_role("button", name="All colors")
            ).to_have_attribute("aria-pressed", "true")
        finally:
            await context.close()
            await browser.close()

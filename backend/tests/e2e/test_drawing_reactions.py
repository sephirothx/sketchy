"""Reactions to drawings (#520), end to end.

Two registered players and a guest. A registered guesser reacts while the
drawing is underway and everyone sees the tally move; the drawer's pill cannot
be pressed and the guest is offered an account instead of a picker. After the
game the reaction shows up as the most reacted drawing, can be changed from the
recap - which writes to the finished game - and counts on the drawer's profile.
"""
from __future__ import annotations

import asyncio

import pytest
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

BASE_URL = "http://localhost:8000"


async def choose_prompt(pages: list[Page]) -> tuple[Page, list[Page], str]:
    """Whoever is offered prompts picks the first; returns them, the rest, the prompt."""
    for _ in range(120):
        for page in pages:
            if await page.locator(".prompt-choices").count():
                choice = page.locator(".prompt-choices button").first
                prompt = (await choice.inner_text()).strip()
                await choice.click()
                await page.locator(".prompt-choices").wait_for(state="detached")
                await page.locator("canvas.drawing-canvas").wait_for()
                return page, [other for other in pages if other is not page], prompt
        await asyncio.sleep(0.1)
    raise AssertionError("No drawer received prompt choices within 12 seconds")


async def guess(pages: list[Page], prompt: str) -> None:
    for page in pages:
        await page.fill(".chat-input input", prompt)
        await page.keyboard.press("Enter")


def chip(page: Page, code: str):
    return page.locator(
        f'[data-testid="reaction-control"] .reaction-chip[data-emoji="{code}"] .reaction-count'
    )


@pytest.mark.asyncio
async def test_reactions_travel_from_the_live_canvas_to_the_recap_and_the_profile():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        contexts = [await browser.new_context() for _ in range(3)]
        host, other, guest = [await context.new_page() for context in contexts]

        try:
            for page, name in ((host, "ReactHost"), (other, "ReactOther"), (guest, "ReactGuest")):
                await page.goto(BASE_URL)
                await use_guest_name(page, name)
            await register_account(host, "reacthost")
            await register_account(other, "reactother")

            await host.click('button:has-text("Create room")')
            await host.click('button:has-text("Create room")')
            await host.locator('[data-testid="waiting-room"]').wait_for()
            code = await room_code(host)
            for page in (other, guest):
                await join_by_code(page, code)
                await page.locator('[data-testid="waiting-room"]').wait_for()

            # One round of three players: three turns, the host draws first.
            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("apple\ntree\nsun")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await other.get_by_text("Custom prompts only (3)").wait_for()
            await host.get_by_role("button", name="Start game").click()

            pages = [host, other, guest]
            drawer, guessers, first_prompt = await choose_prompt(pages)
            assert drawer is host, "the host joined first, so the host draws first"

            # The drawer gets no control - nothing at all until there is a tally -
            # and the guest is offered an account rather than a picker.
            await expect(drawer.locator('[data-testid="reaction-toggle"]')).to_have_count(0)
            await expect(drawer.locator('[data-testid="reaction-tally"]')).to_have_count(0)
            await guest.locator('[data-testid="reaction-toggle"]').click()
            await expect(guest.get_by_text("Create an account to react.")).to_be_visible()
            await guest.keyboard.press("Escape")

            # A registered guesser reacts; every seat in the room sees it land.
            await other.locator('[data-testid="reaction-toggle"]').click()
            await expect(other.locator('[data-testid="reaction-option-heart"]')).to_be_visible()
            await other.locator('[data-testid="reaction-option-fire"]').click()
            for page in pages:
                await expect(chip(page, "fire")).to_have_text("1")
            await expect(drawer.locator('[data-testid="reaction-tally"]')).to_be_visible()

            # Changing it is not a second reaction.
            await other.locator('[data-testid="reaction-toggle"]').click()
            await expect(other.locator('[data-testid="reaction-option-fire"]')).to_have_attribute(
                "aria-pressed", "true"
            )
            await other.locator('[data-testid="reaction-option-heart"]').click()
            for page in pages:
                await expect(chip(page, "heart")).to_have_text("1")
                await expect(
                    page.locator('[data-testid="reaction-control"] .reaction-chip[data-emoji="fire"]')
                ).to_have_count(0)

            await guess(guessers, first_prompt)
            for _ in range(2):
                _, guessers, prompt = await choose_prompt(pages)
                await guess(guessers, prompt)

            game_end = other.locator('[data-testid="game-end-overlay"]')
            await game_end.get_by_role("button", name="Drawings", exact=True).wait_for(timeout=12_000)

            # The one reacted drawing is the most reacted, and the card opens it.
            await game_end.get_by_role("button", name="Highlights", exact=True).click()
            await other.get_by_text("Most reacted drawing", exact=True).wait_for()
            await expect(other.locator(".game-highlights-value").filter(has_text="1 reaction")).to_be_visible()
            await other.get_by_role("button", name="See it").click()
            await other.locator(".drawing-recap").wait_for()
            await expect(other.get_by_role("heading", name=first_prompt)).to_be_visible()
            await expect(chip(other, "heart")).to_have_text("1")

            # From the recap the reaction is a write to the finished game: take
            # it back, then leave a different one, and the drawer sees both.
            await other.locator('[data-testid="reaction-toggle"]').click()
            await other.locator('[data-testid="reaction-option-heart"]').click()
            await expect(other.locator('[data-testid="reaction-control"] .reaction-chip')).to_have_count(0)
            await other.locator('[data-testid="reaction-toggle"]').click()
            await other.locator('[data-testid="reaction-option-wow"]').click()
            await expect(chip(other, "wow")).to_have_text("1")

            await host.get_by_role("button", name="View drawings", exact=True).click()
            await host.locator(".drawing-recap").wait_for()
            await expect(chip(host, "wow")).to_have_text("1")
            await expect(host.locator('[data-testid="reaction-toggle"]')).to_have_count(0)

            # The drawer's profile counts it, served from the projection.
            lobby = await contexts[0].new_page()
            await lobby.goto(BASE_URL)
            await lobby.locator(".identity-chip").click()
            await lobby.get_by_role("menuitem", name="My profile").click()
            await lobby.wait_for_url("**/profile")
            received = lobby.locator(".profile-stat").filter(has_text="Reactions received")
            await expect(received.locator(".profile-stat-value")).to_have_text("1")

            game_row = lobby.locator(".profile-game").first
            await game_row.locator(".profile-game-header").click()
            await lobby.locator(".profile-turns").wait_for()
            await expect(lobby.locator(".profile-turn-reactions").first).to_contain_text("1")
        finally:
            for context in contexts:
                await context.close()
            await browser.close()

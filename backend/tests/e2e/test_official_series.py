"""A host picks a whole official series from the room form's tree (#1388, #1389)."""
import secrets

from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import choose_room_language, register_account

BASE_URL = "http://localhost:8000"


async def test_a_host_picks_every_pokemon_generation_at_once():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        host = await context.new_page()
        try:
            await host.goto(BASE_URL)
            await register_account(host, f"Trainer{secrets.token_hex(3)}")
            await host.goto(f"{BASE_URL}/create")
            # Private: a public room left waiting is one another test's Quick
            # play could land in (e2e global server state).
            await host.get_by_role("button", name="Private").click()
            await choose_room_language(host, "en")
            await host.click('summary:has-text("Prompts")')

            # Folded: nothing on the shelf is chosen yet.
            await host.get_by_role("button", name="Video games").click()
            series = host.locator(".prompt-list-series .prompt-list-check").filter(has_text="Pokémon")
            await series.get_by_text("0 of 9").wait_for()
            await series.locator("input").check()
            await series.get_by_text("9 of 9").wait_for()
            # The whole series, and nothing but: Standard goes.
            await host.locator(".prompt-list-check").filter(
                has_text="English — Standard"
            ).locator("input").uncheck()
            await host.locator(".form-section-summary").filter(
                has_text="Pokémon · 1,025 prompts"
            ).wait_for()

            await host.get_by_role("button", name="Create room", exact=True).click()
            await host.locator('[data-testid="waiting-room"]').wait_for()
        finally:
            await context.close()
            await browser.close()

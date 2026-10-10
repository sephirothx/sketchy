"""An administrator erases a reported drawing for illegal content (#1419,
R-MOD-22), from the case in the moderation queue, and a recap still open on a
player's screen stops showing it at once."""
from __future__ import annotations

from uuid import uuid4

from playwright.async_api import async_playwright, expect

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
from tests.e2e.test_gallery import share_from_recap
from tests.e2e.test_pinned_drawings import scribble
from tests.e2e.test_profile_page import choose_prompt


async def test_an_administrator_erases_a_reported_drawing_and_an_open_recap_drops_it():
    run = uuid4().hex[:6]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host = await (await browser.new_context()).new_page()
        other = await (await browser.new_context()).new_page()
        admin = await (await browser.new_context()).new_page()
        names = {host: f"EraHost{run}", other: f"EraOther{run}"}
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, names[host])
            await register_account(host, names[host])
            await open_new_room(host)
            code = await room_code(host)
            await other.goto(BASE_URL)
            await use_guest_name(other, names[other])
            await register_account(other, names[other])
            await join_by_code(other, code)
            await other.locator('[data-testid="waiting-room"]').wait_for()

            # One round of two turns, on words no other game draws.
            await open_room_settings(host)
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill(f"anchor {run}\nbridge {run}")
            await host.get_by_label("Only use custom prompts").check()
            await save_room_settings(host)
            await other.locator('[data-fact="prompts"]', has_text="2 custom only").wait_for()
            await host.get_by_role("button", name="Start game").click()
            drawers, prompts = [], []
            for _ in range(2):
                drawer, guesser, prompt = await choose_prompt([host, other])
                drawers.append(drawer)
                prompts.append(prompt)
                await scribble(drawer)
                await guesser.fill(".chat-input input", prompt)
                await guesser.keyboard.press("Enter")

            # The host opens the recap on the first drawing and shares it, so
            # it is in the Gallery to be reported from - and stays looking.
            game_end = host.locator('[data-testid="game-end-overlay"]')
            await game_end.get_by_role("button", name="Drawings", exact=True).click(timeout=12_000)
            recap = host.locator(".drawing-recap")
            await recap.wait_for()
            await share_from_recap(host, recap)
            await recap.locator(".drawing-recap-canvas canvas").wait_for()

            # Whoever did not draw it reports it from the Gallery.
            reporter = other if drawers[0] is host else host
            turn_id = await reporter.evaluate(
                """async (prompt) => {
                    for (let attempt = 0; attempt < 20; attempt++) {
                        const page = await (await fetch('/api/gallery?sort=new')).json();
                        const found = page.entries.find((entry) => entry.prompt === prompt);
                        if (found) return found.turnId;
                        await new Promise((resolve) => setTimeout(resolve, 500));
                    }
                    return null;
                }""",
                prompts[0],
            )
            assert turn_id, "the shared drawing never reached the Gallery"
            filed = await reporter.evaluate(
                """async (turnId) => (await fetch(`/api/gallery/${turnId}/report`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({details: 'Not legal.'}),
                })).status""",
                turn_id,
            )
            assert filed == 201

            # The administrator erases it from the case.
            await admin.goto(BASE_URL)
            await use_guest_name(admin, f"EraAdmin{run}")
            await register_account(admin, f"EraAdmin{run}")
            await set_role(f"EraAdmin{run}", UserRole.ADMIN.value)
            await admin.goto(f"{BASE_URL}/moderation")
            case = admin.locator(".mod-queue-item", has_text=names[drawers[0]])
            await case.click()
            panel = admin.get_by_test_id("mod-erase")
            await panel.locator("textarea").fill("Illegal; reported to the police first.")
            await panel.get_by_role("button", name="Erase drawing").click()
            await admin.get_by_role("alertdialog").get_by_role("button", name="Erase drawing").click()
            await expect(admin.get_by_role("status").filter(has_text="Erased everywhere")).to_be_visible()

            # The recap on the host's screen says so, without a reload.
            await expect(recap).to_contain_text("This drawing was removed by moderation.")
            await expect(recap.locator(".drawing-recap-canvas canvas")).to_have_count(0)
        finally:
            await browser.close()

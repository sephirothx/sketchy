"""The drawing viewer's ways between drawings (#1497, R-UX-24): the arrow keys
on a desktop; on a phone a swipe, the arrows a tap brings up, and a downward
drag that closes it."""
import re

from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import (
    join_by_code,
    open_new_room,
    open_room_settings,
    open_settings_section,
    room_code,
    save_room_settings,
    use_guest_name,
)
from tests.e2e.test_drawing_recap import choose_prompt


BASE_URL = "http://localhost:8000"


async def drag(page, start: tuple[float, float], end: tuple[float, float], steps: int = 8) -> None:
    await page.mouse.move(*start)
    await page.mouse.down()
    for step in range(1, steps + 1):
        await page.mouse.move(
            start[0] + (end[0] - start[0]) * step / steps,
            start[1] + (end[1] - start[1]) * step / steps,
        )
        await page.wait_for_timeout(16)
    await page.mouse.up()


async def test_the_viewer_moves_by_keys_on_a_desktop_and_by_swipe_and_tap_on_a_phone():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        desktop_context = await browser.new_context(viewport={"width": 1280, "height": 800})
        phone_context = await browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        host = await desktop_context.new_page()
        phone = await phone_context.new_page()

        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, "ViewerHost")
            await open_new_room(host)
            code = await room_code(host)
            await phone.goto(BASE_URL)
            await use_guest_name(phone, "ViewerPhone")
            await join_by_code(phone, code)
            await phone.locator('[data-testid="waiting-room"]').wait_for()

            await open_room_settings(host)
            await open_settings_section(host, "Prompts")
            await host.locator("#custom-prompts").fill("apple\ntree")
            await host.get_by_label("Only use custom prompts").check()
            await host.get_by_role("spinbutton", name="Rounds").fill("1")
            await save_room_settings(host)
            await phone.locator('[data-fact="prompts"]', has_text="2 custom only").wait_for()
            await host.get_by_role("button", name="Start game").click()

            prompts = []
            for _ in range(2):
                drawer, guesser, prompt = await choose_prompt([host, phone])
                prompts.append(prompt)
                box = await drawer.locator("canvas.drawing-canvas").bounding_box()
                await drag(drawer, (box["x"] + 60, box["y"] + 60), (box["x"] + 200, box["y"] + 150))
                await guesser.fill(".chat-input input", prompt)
                await guesser.keyboard.press("Enter")

            # A desktop: the arrow keys move between drawings, Escape closes.
            game_end = host.locator('[data-testid="game-end-overlay"]')
            await game_end.get_by_role("button", name="Drawings", exact=True).click(timeout=12_000)
            viewer = host.get_by_test_id("drawing-viewer")
            await expect(viewer.get_by_role("heading", name=prompts[0])).to_be_visible()
            await host.keyboard.press("ArrowRight")
            await expect(viewer.get_by_role("heading", name=prompts[1])).to_be_visible()
            await host.keyboard.press("ArrowLeft")
            await expect(viewer.get_by_role("heading", name=prompts[0])).to_be_visible()
            await host.keyboard.press("Escape")
            await expect(viewer).to_have_count(0)

            # A phone: no arrows over the drawing until it is tapped.
            phone_end = phone.locator('[data-testid="game-end-overlay"]')
            await phone_end.get_by_role("button", name="Drawings", exact=True).click(timeout=12_000)
            on_phone = phone.get_by_test_id("drawing-viewer")
            await on_phone.locator(".drawing-viewer-slide.is-current img").wait_for()
            arrows = on_phone.locator(".drawing-viewer-arrow")
            await expect(arrows).to_have_count(0)
            frame = await on_phone.locator(".drawing-viewer-frame").bounding_box()
            middle = (frame["x"] + frame["width"] / 2, frame["y"] + frame["height"] / 2)
            await phone.mouse.click(*middle)
            await expect(arrows).to_have_count(2)
            # A second tap, well after the first, hides them again.
            await phone.wait_for_timeout(400)
            await phone.mouse.click(*middle)
            await expect(arrows).to_have_count(0)

            # A swipe to the left brings up the next drawing.
            await expect(on_phone.get_by_role("heading", name=prompts[0])).to_be_visible()
            await drag(
                phone,
                (frame["x"] + frame["width"] * 0.85, middle[1]),
                (frame["x"] + frame["width"] * 0.1, middle[1]),
            )
            await expect(on_phone.get_by_role("heading", name=prompts[1])).to_be_visible()
            await expect(
                on_phone.locator('.drawing-viewer-thumb[aria-current="true"]')
            ).to_have_attribute("aria-label", re.compile(f"^Drawing of {re.escape(prompts[1])} by "))

            # A downward drag closes it.
            await drag(phone, middle, (middle[0], middle[1] + 260))
            await expect(on_phone).to_have_count(0)
        finally:
            await desktop_context.close()
            await phone_context.close()
            await browser.close()

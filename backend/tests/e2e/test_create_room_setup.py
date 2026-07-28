import pytest
from playwright.async_api import async_playwright


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_create_room_uses_progressive_disclosure_and_validates_custom_words():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 390, "height": 844})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await page.fill('input[placeholder="Your name"]', "SetupHost")
            await page.click('button:has-text("Create room")')
            await page.wait_for_url(f"{BASE_URL}/create")
            assert not await page.is_visible('#custom-words')
            assert await page.input_value('input[placeholder="Your name"]') == "SetupHost"

            await page.fill('input[placeholder="Leave blank for a random name!"]', "Setup room")
            await page.click('text=Advanced settings')
            await page.fill('#custom-words', "apple\nred panda\nAPPLE\nthis entry is deliberately longer than thirty two characters")
            assert await page.is_visible('text=2 usable custom words')
            assert await page.is_visible('text=1 duplicate ignored')
            assert await page.is_visible('text=1 entry is over 32 characters')
            assert await page.is_disabled('.create-room-submit')

            await page.fill('#custom-words', "apple\nred panda\nAPPLE")
            assert await page.is_visible('text=2 usable custom words')
            await page.check('label:has-text("Only use custom words") input')
            await page.select_option('label:has-text("Scoring") select', "none")
            await page.check('label:has-text("Always hide the masked prompt") input')
            assert await page.is_visible('text=Hints are off because the masked prompt is hidden.')
            await page.evaluate(
                """() => {
                    window.__inviteLoaderSeen = false;
                    new MutationObserver(() => {
                        if (document.querySelector(".invite-loading-card")) {
                            window.__inviteLoaderSeen = true;
                        }
                    }).observe(document.body, { childList: true, subtree: true });
                }"""
            )
            await page.click('.create-room-submit')
            await page.wait_for_selector('[data-testid="waiting-room"]')
            assert not await page.evaluate("window.__inviteLoaderSeen")
        finally:
            await context.close()
            await browser.close()

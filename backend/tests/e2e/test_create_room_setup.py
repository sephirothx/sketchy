import pytest
from playwright.async_api import async_playwright


BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_create_room_uses_progressive_disclosure_and_validates_custom_prompts(
    assert_input_contract,
):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(viewport={"width": 390, "height": 844})
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            room_code_input = page.locator('input[placeholder="ABC123"]')
            await assert_input_contract(room_code_input, {
                "type": "search",
                "role": None,
                "inputMode": "text",
                "autoComplete": "off",
                "autoCapitalize": "characters",
                "spellCheck": False,
                "autoCorrect": "off",
                "enterKeyHint": "go",
            })
            await room_code_input.fill("ab-c12")
            assert await room_code_input.input_value() == "ABC12"
            await room_code_input.fill("")

            # The first-run name field carries the app's input contract, except
            # that autoCapitalize is off: names are case-sensitive and cannot
            # contain spaces.
            nickname_input = page.locator(".first-run-guest-row input")
            await nickname_input.wait_for(state="visible")
            await assert_input_contract(nickname_input, {
                "type": "search",
                "role": None,
                "inputMode": "text",
                "autoComplete": "nickname",
                "autoCapitalize": "off",
                "spellCheck": False,
                "autoCorrect": "off",
                "enterKeyHint": "go",
            })
            await nickname_input.fill("SetupHost")
            await page.click(".first-run-guest-submit")
            await page.wait_for_selector('.identity-name:has-text("SetupHost")')
            await page.click('button:has-text("Create room")')
            await page.wait_for_url(f"{BASE_URL}/create")
            # History updates before React finishes the route swap; wait for the
            # create page before asserting lobby controls are gone.
            await page.wait_for_selector(".create-room-page")
            await page.locator(".lobby-page").wait_for(state="detached")
            assert not await page.is_visible('#custom-prompts')
            assert not await page.locator('label:has-text("Nickname")').count()

            room_name_input = page.locator(
                'input[placeholder="Leave blank for a random name!"]'
            )
            await assert_input_contract(room_name_input, {
                "type": "search",
                "role": None,
                "inputMode": "text",
                "autoComplete": "off",
                "autoCapitalize": "sentences",
                "spellCheck": True,
                "autoCorrect": None,
                "enterKeyHint": "done",
            })
            await room_name_input.fill("Setup room")
            await page.click('summary:has-text("Prompts")')
            await page.fill('#custom-prompts', "apple\nred panda\nAPPLE\nthis entry is deliberately longer than thirty two characters")
            assert await page.is_visible('text=2 usable custom prompts')
            assert await page.is_visible('text=1 duplicate ignored')
            assert await page.is_visible('text=1 entry is over 32 characters')
            assert await page.is_disabled('.create-room-submit')

            await page.fill('#custom-prompts', "apple\nred panda\nAPPLE")
            assert await page.is_visible('text=2 usable custom prompts')
            await page.check('label:has-text("Only use custom prompts") input')
            await page.click('summary:has-text("Scoring and hints")')
            await page.get_by_role("button", name="No scoring").click()
            await page.check('label:has-text("Hide blanks") input')
            assert await page.is_visible('text=Hints are off because blanks are hidden.')
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

from playwright.async_api import Page

async def submit_guest_nickname(page: Page, nickname: str) -> None:
    """Complete the guest nickname dialog shown when a name is required."""
    dialog = page.get_by_role("dialog", name="Choose a nickname")
    await dialog.wait_for()
    await dialog.locator('input[placeholder="Your name"]').fill(nickname)
    await dialog.get_by_role("button", name="Continue").click()
    await dialog.wait_for(state="hidden")

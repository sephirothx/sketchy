"""Shared lobby interactions for E2E tests."""
from __future__ import annotations


async def use_guest_name(page, name: str) -> None:
    """Give this page's guest a specific name.

    Sets it through the account, the same way the UI does, so tests that assert
    on a particular name do not each have to walk the first-run block. That
    block, and renaming from Settings, are covered by test_auth_accounts.py.
    """
    # Wait for the app's own provisioning to finish first. Setting the name
    # while GET /api/auth/me is still in flight races it: both calls create an
    # account, and whichever cookie lands second wins - usually discarding the
    # name that was just set. The first-run block is what proves it has landed.
    await page.wait_for_selector(".first-run, .identity-chip")

    result = await page.evaluate(
        """async (value) => {
            const response = await fetch('/api/auth/display-name', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ displayName: value }),
            });
            return response.status;
        }""",
        name,
    )
    assert result == 200, f"could not set guest name {name!r}: HTTP {result}"
    # The store caches the account, so a reload is what picks the name up.
    # The identity chip appears in every header once a name exists, so this
    # works on the lobby, the invite screen, and the create-room page alike.
    await page.reload()
    await page.wait_for_selector(".identity-chip")


async def register_account(page, username: str, password: str = "a-good-password") -> None:
    """Claim the current guest account through the header control.

    Registering keeps the same user id, so the player holds their seat and
    simply stops being a guest on it.
    """
    # The claim dialog is reached from the identity chip once a guest is named,
    # or from the first-run block before that. Outside a room the chip opens a
    # menu first, since a guest has a profile to reach as well; the compact chip
    # inside a room still goes straight to the dialog.
    if await page.locator(".identity-chip").count():
        await page.click(".identity-chip")
        claim = page.get_by_role("menuitem", name="Create account")
        if await claim.count():
            await claim.click()
    else:
        await page.click(".first-run-signup")
    dialog = page.locator(".modal-card").filter(has_text="Password")
    await dialog.wait_for(state="visible")
    inputs = dialog.locator("input")
    await inputs.nth(0).fill(username)
    await inputs.nth(1).fill(password)
    await dialog.locator('button[type="submit"]').click()
    await dialog.wait_for(state="hidden")
    # The unclaimed dot disappearing is the signal, and it works whether the
    # chip is showing its name or collapsed to the avatar inside a room.
    await page.wait_for_function("() => !document.querySelector('.identity-unclaimed')")


async def room_code(page) -> str:
    """The current room's code, read from the header's copy control.

    Prefers the stable data-room-code attribute so the helper survives header
    redesigns; falls back to parsing the visible "Code: XXXXXX" label.
    """
    button = page.locator(".room-copy-button").first
    await button.wait_for()
    attr = await button.get_attribute("data-room-code")
    if attr:
        return attr.strip()
    text = await button.inner_text()
    return text.split("Code:")[1].strip()


async def open_room_settings(page) -> None:
    """Open the host's room-settings editor, which lives in a modal."""
    await page.get_by_role("button", name="Edit settings").click()
    await page.wait_for_selector(".room-settings-editor")


async def close_room_settings(page) -> None:
    """Close the room-settings modal (Escape) and wait for it to unmount."""
    await page.keyboard.press("Escape")
    await page.locator(".room-settings-editor").wait_for(state="detached")

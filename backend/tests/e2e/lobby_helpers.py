"""Shared lobby interactions for E2E tests."""
from __future__ import annotations


async def use_guest_name(page, name: str) -> None:
    """Give this page's guest a specific name.

    Players are never asked for a name - one is generated on first load - so
    tests that assert on a particular name set it the same way the UI does,
    through the account. Renaming through the control itself is covered by
    test_auth_accounts.py.
    """
    # Wait for the app's own provisioning to finish first. Setting the name
    # while GET /api/auth/me is still in flight races it: both calls create an
    # account, and whichever cookie lands second wins - usually discarding the
    # name that was just set.
    await page.wait_for_selector(".guest-name-chip")

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
    # The name control is in every header, so this works on the lobby, the
    # invite screen, and the create-room page alike.
    await page.reload()
    await page.wait_for_selector(".guest-name-chip")


async def register_account(page, username: str, password: str = "a-good-password") -> None:
    """Claim the current guest account through the header control.

    Registering keeps the same user id, so the player holds their seat and
    simply stops being a guest on it.
    """
    await page.click('button:has-text("Create account")')
    dialog = page.locator(".modal-card", has_text="Create your account")
    await dialog.wait_for(state="visible")
    inputs = dialog.locator("input")
    await inputs.nth(0).fill(username)
    await inputs.nth(1).fill(password)
    await dialog.locator('button[type="submit"]').click()
    await dialog.wait_for(state="hidden")
    # The account chip replaces the guest buttons once identity has switched.
    await page.wait_for_selector(f'.account-name:has-text("{username}")')

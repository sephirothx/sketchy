"""Shared lobby interactions for E2E tests."""
from __future__ import annotations


async def use_guest_name(page, name: str) -> None:
    """Pre-answer the guest nickname dialog for a page already on the lobby.

    The name is asked in a dialog at create/join time rather than in a lobby
    field, so tests that merely need *a* named player seed it here instead of
    stepping through the dialog. The dialog itself, and the rules it enforces,
    are covered by test_auth_accounts.py.
    """
    await page.evaluate("(value) => localStorage.setItem('sketchy_nickname', value)", name)
    # The store reads the stored nickname at startup, so the reload is what
    # makes the seeded value take effect.
    await page.reload()
    await page.wait_for_selector('button:has-text("Create room")')


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

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.async_api import async_playwright, expect


BASE_URL = "http://localhost:8000"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / "frontend" / "dist" / ".vite" / "manifest.json"


def asset_closure(manifest: dict, entry_key: str) -> set[str]:
    visited: set[str] = set()
    assets: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        visited.add(key)
        entry = manifest[key]
        assets.add(entry["file"])
        assets.update(entry.get("css", []))
        for imported_key in entry.get("imports", []):
            visit(imported_key)

    visit(entry_key)
    return assets


def record_asset_requests(page, requested_assets: set[str]) -> None:
    def on_response(response) -> None:
        path = urlparse(response.url).path.lstrip("/")
        if path.startswith("assets/"):
            requested_assets.add(path)

    page.on("response", on_response)


@pytest.mark.asyncio
async def test_lobby_defers_create_and_game_route_assets():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    initial_assets = asset_closure(manifest, "index.html")
    create_key = "src/pages/CreateRoomPage.tsx"
    game_key = "src/pages/GameRoomPage.tsx"
    create_assets = asset_closure(manifest, create_key) - initial_assets
    game_assets = asset_closure(manifest, game_key) - initial_assets
    game_only_assets = game_assets - create_assets
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context()
        page = await context.new_page()
        requested_assets: set[str] = set()
        record_asset_requests(page, requested_assets)

        try:
            await page.goto(BASE_URL)
            await page.wait_for_selector(".lobby-page")
            badge_styles = await page.locator(".version-badge").evaluate(
                """element => {
                    const styles = getComputedStyle(element);
                    return {
                        position: styles.position,
                        right: styles.right,
                        bottom: styles.bottom,
                        fontSize: styles.fontSize,
                    };
                }"""
            )
            assert badge_styles == {
                "position": "fixed",
                "right": "8px",
                "bottom": "6px",
                "fontSize": "11px",
            }
            assert initial_assets <= requested_assets
            assert create_assets.isdisjoint(requested_assets)
            assert game_assets.isdisjoint(requested_assets)

            await page.fill('input[placeholder="Your name"]', "RouteTester")
            await page.get_by_role("button", name="Create room", exact=True).click()
            await page.wait_for_selector(".create-room-page")
            assert create_assets <= requested_assets
            assert game_only_assets.isdisjoint(requested_assets)
            await expect(page.get_by_role("status")).to_have_count(0)
        finally:
            await context.close()
            await browser.close()


@pytest.mark.asyncio
async def test_direct_create_and_room_routes_load_their_lazy_assets():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    initial_assets = asset_closure(manifest, "index.html")
    create_assets = (
        asset_closure(manifest, "src/pages/CreateRoomPage.tsx") - initial_assets
    )
    game_assets = asset_closure(manifest, "src/pages/GameRoomPage.tsx") - initial_assets
    game_only_assets = game_assets - create_assets

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        try:
            create_context = await browser.new_context()
            create_page = await create_context.new_page()
            create_requests: set[str] = set()
            record_asset_requests(create_page, create_requests)
            await create_page.goto(f"{BASE_URL}/create")
            await create_page.wait_for_selector(".create-room-page")
            assert create_assets <= create_requests
            assert game_only_assets.isdisjoint(create_requests)
            await create_context.close()

            room_context = await browser.new_context()
            room_page = await room_context.new_page()
            room_requests: set[str] = set()
            record_asset_requests(room_page, room_requests)
            await room_page.goto(f"{BASE_URL}/room/ABC123")
            await room_page.wait_for_selector(".invite-entry-page")
            assert game_assets <= room_requests
            assert manifest["src/pages/CreateRoomPage.tsx"]["file"] not in room_requests
            await room_context.close()
        finally:
            await browser.close()

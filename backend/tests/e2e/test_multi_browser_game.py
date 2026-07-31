import pytest
from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8000"

@pytest.mark.asyncio
async def test_multi_browser_gameplay_scenario():
    """
    Multi-browser test scenario:
    1. Browser 1 (Host in Chromium) creates a room and enters waiting lobby.
    2. Browser 2 (Player in Firefox) joins using room code in a separate browser context.
    3. Host sees 2 players joined in waiting lobby, clicks Start Game.
    4. Round starts: Drawer receives word choices, picks a word.
    5. Drawer draws on canvas.
    6. Guesser submits guess in chat.
    7. Both browsers sync in real time over Socket.IO.
    """
    async with async_playwright() as p:
        browser1 = await p.chromium.launch(headless=True, args=['--mute-audio'])
        browser2 = await p.firefox.launch(headless=True, firefox_user_prefs={'media.volume_scale': '0.0'})

        context1 = await browser1.new_context()
        context2 = await browser2.new_context()

        page1 = await context1.new_page()
        page2 = await context2.new_page()

        try:
            # Step 1: Host creates a room
            await page1.goto(BASE_URL)
            await page1.fill('input[placeholder="Your name"]', "HostAlice")
            await page1.click('button:has-text("Create room")')
            await page1.click('button:has-text("Create room")')

            # Wait for navigation to room waiting panel
            await page1.wait_for_selector('.room-copy-button')
            room_code_text = await page1.inner_text('.room-copy-button')
            code = room_code_text.split("Code:")[1].strip()
            assert len(code) > 0

            # Step 2: Player joins using room code from Browser 2 (Firefox)
            await page2.goto(BASE_URL)
            await page2.fill('input[placeholder="Your name"]', "BobGuesser")
            await page2.fill('input[placeholder="ABC123"]', code)
            await page2.click('button:has-text("Join by code")')

            # Wait for Browser 2 to enter waiting panel
            await page2.wait_for_selector('.room-copy-button')

            # Step 3: Host verifies 2 players joined in waiting panel
            await page1.wait_for_selector('[data-testid="waiting-room"]')
            await page2.fill('.waiting-chat-form input', "Ready for a seamless round")
            await page2.click('.waiting-chat-form button')
            await page1.wait_for_selector('text=Ready for a seamless round')

            waiting_regions = await page1.evaluate(
                """
                () => {
                  const players = document.querySelector('[data-testid="room-players-region"]');
                  const chat = document.querySelector('[data-testid="room-chat-region"]');
                  window.__persistentRoomRegions = { players, chat };
                  const rect = (element) => {
                    const box = element.getBoundingClientRect();
                    return { x: box.x, y: box.y, width: box.width, height: box.height };
                  };
                  return { players: rect(players), chat: rect(chat) };
                }
                """
            )
            await page1.set_viewport_size({"width": 800, "height": 900})
            waiting_mobile_order = await page1.evaluate(
                """
                () => ({
                  main: document.querySelector(".room-shell-main").getBoundingClientRect().y,
                  chat: document.querySelector('[data-testid="room-chat-region"]').getBoundingClientRect().y,
                  players: document.querySelector('[data-testid="room-players-region"]').getBoundingClientRect().y,
                })
                """
            )
            assert (
                waiting_mobile_order["main"]
                < waiting_mobile_order["chat"]
                < waiting_mobile_order["players"]
            )
            await page1.set_viewport_size({"width": 1280, "height": 720})

            # Step 4: Host starts the game
            await page1.click('button:has-text("Start game")')

            # Both pages enter round / playing phase
            await page1.wait_for_selector('.game-layout')
            await page2.wait_for_selector('.game-layout')

            # Verify PlayerList rendered on both browsers
            await page1.wait_for_selector('.player-list')
            await page2.wait_for_selector('.player-list')
            playing_regions = await page1.evaluate(
                """
                () => {
                  const players = document.querySelector('[data-testid="room-players-region"]');
                  const chat = document.querySelector('[data-testid="room-chat-region"]');
                  const rect = (element) => {
                    const box = element.getBoundingClientRect();
                    return { x: box.x, y: box.y, width: box.width, height: box.height };
                  };
                  return {
                    samePlayers: window.__persistentRoomRegions.players === players,
                    sameChat: window.__persistentRoomRegions.chat === chat,
                    players: rect(players),
                    chat: rect(chat),
                  };
                }
                """
            )
            assert playing_regions["samePlayers"]
            assert playing_regions["sameChat"]
            for region in ("players", "chat"):
                for dimension in ("x", "y", "width"):
                    assert abs(
                        waiting_regions[region][dimension]
                        - playing_regions[region][dimension]
                    ) <= 1
            assert abs(
                waiting_regions["chat"]["height"]
                - playing_regions["chat"]["height"]
            ) <= 1
            assert await page1.is_visible('text=Ready for a seamless round')
            await page1.set_viewport_size({"width": 800, "height": 900})
            playing_mobile_layout = await page1.evaluate(
                """
                () => {
                  const players = document.querySelector('[data-testid="room-players-region"]');
                  return {
                    main: document.querySelector(".room-shell-main").getBoundingClientRect().y,
                    chat: document.querySelector('[data-testid="room-chat-region"]').getBoundingClientRect().y,
                    playersDisplay: players ? getComputedStyle(players).display : null,
                    headerActionsWidth: document.querySelector(".game-header-actions")?.scrollWidth ?? 0,
                    headerActionsClient: document.querySelector(".game-header-actions")?.clientWidth ?? 0,
                  };
                }
                """
            )
            assert playing_mobile_layout["main"] < playing_mobile_layout["chat"]
            assert playing_mobile_layout["playersDisplay"] == "none"
            assert (
                playing_mobile_layout["headerActionsWidth"]
                <= playing_mobile_layout["headerActionsClient"] + 1
            )
            await page1.click('[data-testid="open-players-drawer"]')
            await page1.wait_for_selector('[data-testid="players-drawer"]')
            assert await page1.is_visible('[data-testid="players-drawer"] .player-list')
            await page1.click('.players-drawer-close')
            await page1.wait_for_selector('[data-testid="players-drawer"]', state="detached")
            await page1.set_viewport_size({"width": 1280, "height": 720})

            # Step 5: Identify who is drawer and choose word if prompt choice is present
            drawer_page = page1 if await page1.query_selector('.word-choices') else page2
            guesser_page = page2 if drawer_page == page1 else page1
            drawer_name = "HostAlice" if drawer_page == page1 else "BobGuesser"

            choosing_status = guesser_page.get_by_test_id("choosing-word-status")
            await choosing_status.wait_for()
            assert await choosing_status.get_by_text(
                f"{drawer_name} is choosing a word…",
                exact=True,
            ).is_visible()
            assert not await drawer_page.get_by_test_id(
                "choosing-word-status"
            ).is_visible()

            if await drawer_page.query_selector('.word-choices button'):
                await drawer_page.evaluate(
                    """
                    () => {
                      window.__wordSelectionErrorSeen = false;
                      new MutationObserver(() => {
                        if (document.querySelector('.app-toast.error')) {
                          window.__wordSelectionErrorSeen = true;
                        }
                      }).observe(document.body, { childList: true, subtree: true });
                    }
                    """
                )
                await drawer_page.click('.word-choices button:first-child')

            # Wait for drawing phase
            await choosing_status.wait_for(state="detached")
            await drawer_page.wait_for_selector('canvas.drawing-canvas')
            await guesser_page.wait_for_selector('canvas.drawing-canvas')
            assert not await drawer_page.evaluate("window.__wordSelectionErrorSeen")

            # Mobile drawing toolbar: touch-sized chips in portrait and landscape
            await drawer_page.set_viewport_size({"width": 390, "height": 844})
            mobile_toolbar = await drawer_page.evaluate(
                """
                () => {
                  const strip = document.querySelector('[data-testid="toolbar-mobile"]');
                  if (!strip) return null;
                  const chips = [...strip.querySelectorAll('.toolbar-mobile-chip')];
                  return {
                    chipSizes: chips.map((chip) => {
                      const box = chip.getBoundingClientRect();
                      return { width: box.width, height: box.height };
                    }),
                    saveInHeader: Boolean(document.querySelector('.game-header-save-button')),
                  };
                }
                """
            )
            assert mobile_toolbar is not None
            assert mobile_toolbar["saveInHeader"]
            assert len(mobile_toolbar["chipSizes"]) >= 5
            assert all(
                size["width"] >= 40 and size["height"] >= 40
                for size in mobile_toolbar["chipSizes"]
            )
            await drawer_page.set_viewport_size({"width": 844, "height": 390})
            assert await drawer_page.query_selector('[data-testid="toolbar-mobile"]')
            await drawer_page.set_viewport_size({"width": 1280, "height": 720})

            # Step 6: Drawer draws on canvas
            canvas = await drawer_page.query_selector('canvas.drawing-canvas')
            box = await canvas.bounding_box()
            assert box is not None

            # Draw a stroke across the canvas
            await drawer_page.mouse.move(box["x"] + 100, box["y"] + 100)
            await drawer_page.mouse.down()
            await drawer_page.mouse.move(box["x"] + 200, box["y"] + 200)
            await drawer_page.mouse.up()

            # Both the drawer and observer cache the semantic stroke. Undo is
            # then applied incrementally and both canvases replay their local
            # cache without a full history broadcast.
            await guesser_page.wait_for_function(
                """
                () => {
                  const canvas = document.querySelector('canvas.drawing-canvas');
                  const data = canvas.getContext('2d').getImageData(
                    0, 0, canvas.width, canvas.height
                  ).data;
                  for (let index = 0; index < data.length; index += 4) {
                    if (data[index] !== 255 || data[index + 1] !== 255
                        || data[index + 2] !== 255) return true;
                  }
                  return false;
                }
                """
            )
            await drawer_page.click("button.undo-button")
            canvas_is_blank = """
                () => {
                  const canvas = document.querySelector('canvas.drawing-canvas');
                  const data = canvas.getContext('2d').getImageData(
                    0, 0, canvas.width, canvas.height
                  ).data;
                  for (let index = 0; index < data.length; index += 4) {
                    if (data[index] !== 255 || data[index + 1] !== 255
                        || data[index + 2] !== 255) return false;
                  }
                  return true;
                }
            """
            await guesser_page.wait_for_function(canvas_is_blank)
            await drawer_page.wait_for_function(
                canvas_is_blank,
            )

            canvas_has_ink = """
                () => {
                  const canvas = document.querySelector('canvas.drawing-canvas');
                  const data = canvas.getContext('2d').getImageData(
                    0, 0, canvas.width, canvas.height
                  ).data;
                  for (let index = 0; index < data.length; index += 4) {
                    if (data[index] !== 255 || data[index + 1] !== 255
                        || data[index + 2] !== 255) return true;
                  }
                  return false;
                }
            """

            # Undo/Clear while the pointer is down are ignored so mid-stroke
            # actions cannot race sequence recovery on slow links.
            await drawer_page.mouse.move(box["x"] + 120, box["y"] + 120)
            await drawer_page.mouse.down()
            await drawer_page.mouse.move(box["x"] + 220, box["y"] + 220)
            await drawer_page.keyboard.press("Control+z")
            await drawer_page.mouse.up()
            await guesser_page.wait_for_function(canvas_has_ink)
            await drawer_page.wait_for_function(canvas_has_ink)
            await drawer_page.click("button.undo-button")
            await guesser_page.wait_for_function(canvas_is_blank)
            await drawer_page.wait_for_function(canvas_is_blank)

            await drawer_page.mouse.move(box["x"] + 140, box["y"] + 140)
            await drawer_page.mouse.down()
            await drawer_page.mouse.move(box["x"] + 240, box["y"] + 240)
            await drawer_page.evaluate(
                "document.querySelector('button.clear-button').click()"
            )
            await drawer_page.mouse.up()
            await guesser_page.wait_for_function(canvas_has_ink)
            await drawer_page.wait_for_function(canvas_has_ink)
            await drawer_page.click("button.clear-button")
            await guesser_page.wait_for_function(canvas_is_blank)
            await drawer_page.wait_for_function(canvas_is_blank)

            # Step 7: Guesser submits a guess in chat
            await guesser_page.fill('.chat-input input', 'apple')
            await guesser_page.keyboard.press('Enter')

            # Verify chat message container is present
            await guesser_page.wait_for_selector('.chat-messages')

        finally:
            await context1.close()
            await context2.close()
            await browser1.close()
            await browser2.close()

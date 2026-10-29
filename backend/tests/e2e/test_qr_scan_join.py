"""Join by code's QR scanner (#1530, R-UX-25).

The camera is a stand-in: `getUserMedia` answers with a canvas stream that
paints whatever image the test hands it - the QR code the host's own waiting
room draws, screenshotted - so the code read is the real one, end to end.
Headless Chromium has no BarcodeDetector, so this goes through the bundled
decoder, the path an iPhone takes.
"""
import base64
from uuid import uuid4

import pytest
from playwright.async_api import async_playwright, expect
from tests.e2e.lobby_helpers import open_new_room, room_code, use_guest_name

BASE_URL = "http://localhost:8000"

PHONE = {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True}

# Answers getUserMedia with a canvas painting `window.__fakeCamera` (a data
# URL set by the test) in the middle of a grey frame, ten times a second; or
# refuses with the DOMException named by `window.__cameraError`.
FAKE_CAMERA = """
(() => {
  const getUserMedia = async () => {
    if (window.__cameraError) throw new DOMException("refused", window.__cameraError);
    const image = new Image();
    image.src = window.__fakeCamera;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 640;
    const context = canvas.getContext("2d");
    const paint = () => {
      context.fillStyle = "#777";
      context.fillRect(0, 0, 640, 640);
      context.drawImage(image, 140, 140, 360, 360);
    };
    paint();
    setInterval(paint, 100);
    return canvas.captureStream(10);
  };
  if (navigator.mediaDevices) {
    navigator.mediaDevices.getUserMedia = getUserMedia;
  } else {
    Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia } });
  }
})();
"""


async def _open_scanner(page):
    await page.locator(".lobby-dock-code").click()
    sheet = page.get_by_test_id("lobby-code-sheet")
    await sheet.wait_for()
    await sheet.get_by_role("button", name="Scan").click()
    return sheet


async def test_a_phone_scans_the_hosts_qr_code_and_lands_in_the_room():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context(viewport={"width": 1280, "height": 860})
        phone_context = await browser.new_context(**PHONE)
        await phone_context.add_init_script(FAKE_CAMERA)
        host, phone = await host_context.new_page(), await phone_context.new_page()
        try:
            await host.goto(BASE_URL)
            await use_guest_name(host, f"QrHost{uuid4().hex[:6]}")
            # A desktop is not offered the scanner: a laptop is the screen
            # showing the code, not the one reading it.
            await host.get_by_role("button", name="Join by code").first.click()
            desktop_sheet = host.get_by_test_id("lobby-code-sheet")
            await desktop_sheet.wait_for()
            assert await desktop_sheet.get_by_role("button", name="Scan").count() == 0
            await host.keyboard.press("Escape")

            await open_new_room(host)
            code = await room_code(host)
            await host.get_by_role("button", name="Show a QR code").click()
            qr = host.get_by_role("img", name=f"QR code for the invite link to room {code}")
            await qr.wait_for()
            picture = base64.b64encode(await qr.screenshot()).decode()

            await phone.goto(BASE_URL)
            await use_guest_name(phone, f"QrGuest{uuid4().hex[:6]}")
            await phone.evaluate(f"() => {{ window.__fakeCamera = 'data:image/png;base64,{picture}'; }}")
            await _open_scanner(phone)

            # Nothing else is pressed: the read is the join.
            await phone.wait_for_url(f"**/room/{code}", timeout=20_000)
            await phone.wait_for_selector('[data-testid="waiting-room"]')
            assert await room_code(phone) == code
        finally:
            await host_context.close()
            await phone_context.close()
            await browser.close()


@pytest.mark.parametrize(
    ("error", "message"),
    [
        ("NotAllowedError", "The camera is blocked"),
        # Another app holding the camera, as Android often has it: not "no
        # camera", and worth a second try.
        ("NotReadableError", "The camera could not start"),
    ],
)
async def test_a_camera_that_will_not_start_says_why_and_goes_back_to_typing(error, message):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        context = await browser.new_context(**PHONE)
        await context.add_init_script(FAKE_CAMERA)
        page = await context.new_page()
        try:
            await page.goto(BASE_URL)
            await use_guest_name(page, f"QrBlocked{uuid4().hex[:6]}")
            await page.evaluate(f"() => {{ window.__cameraError = '{error}'; }}")
            sheet = await _open_scanner(page)
            await expect(sheet.get_by_role("alert")).to_contain_text(message)
            await expect(sheet.get_by_role("button", name="Try again")).to_be_visible()
            await sheet.get_by_role("button", name="Type the code").click()
            # Focus follows to the field the view gave way to.
            await expect(sheet.locator("input").first).to_be_focused()
            await expect(sheet.get_by_role("button", name="Scan")).to_be_visible()
        finally:
            await context.close()
            await browser.close()

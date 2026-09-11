"""The drawing toolbar at every width the desktop room gives it (#781).

The toolbar lives in the room's middle column, which runs from 293px at a
901px window to 632px once the room reaches its 1240px cap - never wide enough
for tools, size, palette and canvas actions on one line. Left to flex-wrap, the
groups broke wherever the pixels ran out: a divider ended a line or sat on one
of its own, and below ~1034px the palette spilled out of the card.

So this walks the whole desktop range rather than a few breakpoints, because
where the old toolbar broke depended on what it held, not on any width in the
stylesheet. At each width it asks two things a person would see at a glance:
that nothing is wider than the column, and that every divider has a group on
either side of it on the same line.
"""
from __future__ import annotations

from playwright.async_api import async_playwright

from tests.e2e.lobby_helpers import join_by_code, room_code, use_guest_name


BASE_URL = "http://localhost:8000"

# 901 is the narrowest window with the desktop room; 1240 is the width at
# which the column stops growing. Every 20px between them, then two past it.
WIDTHS = [*range(901, 1241, 20), 1240, 1440, 1920]

# Everything the toolbar shows that could break, as a list of sentences.
# Empty is the only pass.
PROBLEMS = """
() => {
  const column = document.querySelector('.canvas-area');
  const card = column && column.querySelector(':scope > .toolbar-container');
  if (!card) return ['there is no toolbar in the canvas column'];
  const problems = [];
  const page = document.documentElement;
  if (page.scrollWidth > page.clientWidth) {
    problems.push(`the page scrolls sideways by ${page.scrollWidth - page.clientWidth}px`);
  }
  const col = column.getBoundingClientRect();
  const box = card.getBoundingClientRect();
  if (box.left < col.left - 0.5 || box.right > col.right + 0.5) {
    problems.push(`the toolbar is ${box.width}px in a ${col.width}px column`);
  }
  for (const control of card.querySelectorAll('button, label')) {
    const rect = control.getBoundingClientRect();
    if (rect.width === 0) continue;
    if (rect.left < box.left - 0.5 || rect.right > box.right + 0.5) {
      problems.push(`${control.getAttribute('aria-label') || control.className} spills out of the toolbar`);
    }
  }
  const sameLine = (a, b) => {
    const middle = (a.top + a.bottom) / 2;
    return b.top <= middle && middle <= b.bottom;
  };
  for (const divider of card.querySelectorAll('.toolbar-divider')) {
    const rect = divider.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    const before = divider.previousElementSibling;
    const after = divider.nextElementSibling;
    const isGroup = (el) => el && el.classList.contains('toolbar-group');
    if (!isGroup(before) || !isGroup(after)) {
      problems.push('a divider is not between two groups');
      continue;
    }
    const left = before.getBoundingClientRect();
    const right = after.getBoundingClientRect();
    if (!sameLine(rect, left) || !sameLine(rect, right) || left.right > rect.left || rect.right > right.left) {
      problems.push(`a divider between ${before.className} and ${after.className} is not on their line`);
    }
  }
  const chips = [...card.querySelectorAll('.toolbar-mobile-chip')].map((c) => c.getBoundingClientRect());
  if (chips.some((chip) => Math.abs(chip.top - chips[0].top) > 1)) {
    problems.push('the compact strip wrapped');
  }
  const strip = card.querySelector('.toolbar-mobile-strip');
  if (strip && strip.scrollWidth > strip.clientWidth) {
    problems.push(`the compact strip overflows by ${strip.scrollWidth - strip.clientWidth}px`);
  }
  return problems;
}
"""


# The toolbar re-arranges itself from a ResizeObserver, which reports in the
# frame after a resize; React commits the new arrangement in a task after
# that. Three frames and a beat is ample for both.
SETTLED = """
() => new Promise((resolve) => {
  const frame = (n) => (n === 0 ? setTimeout(resolve, 100) : requestAnimationFrame(() => frame(n - 1)));
  frame(3);
})
"""


async def _problems_at(page, width: int) -> list[str]:
    """What is wrong with the toolbar once it has settled at this width.

    Waited for rather than polled: the arrangement the old width left behind
    is usually a valid toolbar too, so polling for "no problems" passes on it
    before the one this width gets has been drawn.
    """
    await page.set_viewport_size({"width": width, "height": 900})
    await page.evaluate(SETTLED)
    return await page.evaluate(PROBLEMS)


async def test_the_toolbar_holds_together_at_every_desktop_width():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context(viewport={"width": 1280, "height": 900})
        player_context = await browser.new_context(viewport={"width": 1280, "height": 900})
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "WideHost")
            await host_page.click('button:has-text("Create room")')
            # Private, so it stays out of the lobby list other tests read.
            await host_page.click('[role="group"][aria-label="Visibility"] button:has-text("Private")')
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)

            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "NarrowPlayer")
            await join_by_code(player_page, code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            # The drawer is whoever is offered the prompts; identify them while
            # the choosing phase is still up.
            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector('.prompt-choices, [data-testid="choosing-prompt-status"]')
            drawer = host_page if await host_page.query_selector('.prompt-choices') else player_page
            await drawer.click('.prompt-choices button:first-child')
            await drawer.wait_for_selector('canvas.drawing-canvas')
            await drawer.wait_for_selector('.canvas-area .toolbar-container')

            broken = {}
            for width in WIDTHS:
                problems = await _problems_at(drawer, width)
                if problems:
                    broken[width] = problems
            assert not broken, "the toolbar breaks at: " + "; ".join(
                f"{width}px: {', '.join(problems)}" for width, problems in broken.items()
            )

            # Where the column is too narrow for the palette, the toolbar is
            # the chip strip a phone gets rather than a squeezed full one.
            await _problems_at(drawer, 901)
            assert await drawer.locator('.canvas-area [data-testid="toolbar-mobile"]').count() == 1

            # The narrowest column the room ever has: this window with a
            # classic 17px scrollbar down the page, which headless Chromium
            # hides. Taken off the room's padding instead, through the CSSOM
            # because the built app's CSP refuses an injected stylesheet.
            await drawer.evaluate(
                "document.querySelector('.game-room').style.setProperty('padding-right', '33px', 'important')"
            )
            assert await _problems_at(drawer, 901) == [], (
                "the toolbar breaks in the narrowest column the room has"
            )
            await drawer.evaluate(
                "document.querySelector('.game-room').style.removeProperty('padding-right')"
            )

            # On a laptop it is two lines: the tools, the size and the canvas
            # actions, with the palette under them.
            assert await _problems_at(drawer, 1280) == []
            lines = await drawer.evaluate(
                """() => Object.fromEntries(
                  ['.toolbar-tools', '.brush-size-dropdown', '.toolbar-actions', '.toolbar-colors']
                    .map((selector) => [selector, Math.round(document.querySelector(selector).getBoundingClientRect().top)])
                )"""
            )
            first_line = lines['.toolbar-tools']
            assert lines['.brush-size-dropdown'] <= first_line + 44
            assert lines['.toolbar-actions'] == first_line
            assert lines['.toolbar-colors'] > first_line + 40
        finally:
            await host_context.close()
            await player_context.close()
            await browser.close()

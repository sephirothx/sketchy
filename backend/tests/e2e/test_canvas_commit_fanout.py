"""A viewer's commits ride the frames that cause them (#418).

The server used to answer every committed drawing action with two room-wide
events: the rebroadcast of the drawer's frame, then a `canvas_commit` carrying
the four integers a viewer needs to advance its revision bookkeeping. The
commit now travels on the committing frame itself.

Two things have to hold, and only one of them is visible on the canvas. The
first is that the viewer stops receiving `canvas_commit` at all. The second is
that it still *processes* the commits, which is invisible in pixels - a viewer
whose bookkeeping falls behind renders exactly the same strokes.

Nothing forces it to notice, either, until something arrives that is checked
against its sequence. That is what the undo at the end is for: `canvas_undo` is
still an event of its own and refuses a sequence that is not the next one
expected, so a viewer that ignored its commits asks for a full resync there.
This therefore watches the socket rather than the canvas: no commit events in,
an undo accepted, and no resync of either shape out.
"""
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from tests.e2e.lobby_helpers import join_by_code, open_create_room, room_code, use_guest_name


BASE_URL = "http://localhost:8000"


# Every event the page's socket receives and sends, recorded by the socket
# itself the moment the diagnostics build installs it. A setter rather than a
# poll, so nothing that arrives first is missed. Outgoing events are counted
# when they leave, so one buffered across a reconnect counts once, when sent.
# A received event's arguments are kept by reference and serialized only when
# a test asks for them.
_RECORD_SOCKET_EVENTS = """
(() => {
  const received = window.__socketReceived = [];
  const receivedArgs = window.__socketReceivedArgs = [];
  const sent = window.__socketSent = [];
  let socket;
  Object.defineProperty(window, "__SKETCHY_SOCKET__", {
    configurable: true,
    get: () => socket,
    set: (value) => {
      socket = value;
      value.onAny((event, ...args) => {
        received.push(event);
        receivedArgs.push(args);
      });
      value.onAnyOutgoing((event) => sent.push(event));
    },
  });
})();
"""


class SocketEventLog:
    """Every Socket.IO event one page receives or sends, by name, in order -
    over whichever transport carried it.

    Not its WebSocket frames: a session is not always on a WebSocket. A
    connection attempt that errors or stalls opens on long-polling (#601), as
    a reconnect can on a loaded runner, and a log of WebSocket frames then sees
    nothing - a reconnect's tail arrived over HTTP within milliseconds and the
    wait for it gave up five seconds later, and an assertion that an event
    never came passed without having watched. Needs the diagnostics build,
    which exposes the socket.
    """

    def __init__(self, page):
        self._page = page

    @classmethod
    async def attach(cls, page) -> "SocketEventLog":
        """Before the page's first navigation: the recorder rides every load."""
        await page.add_init_script(_RECORD_SOCKET_EVENTS)
        return cls(page)

    async def mark(self) -> int:
        """The point in what arrives from which the next assertions read."""
        return await self._page.evaluate("() => window.__socketReceived.length")

    async def received(self, since: int = 0) -> list[str]:
        return await self._page.evaluate("(since) => window.__socketReceived.slice(since)", since)

    async def payloads(self, event: str, since: int = 0) -> list[list]:
        """The arguments of each `event` received from `since` on, as JSON."""
        return await self._page.evaluate(
            """([event, since]) => window.__socketReceived
                .map((name, index) => [name, index])
                .filter(([name, index]) => name === event && index >= since)
                .map(([, index]) => JSON.parse(JSON.stringify(window.__socketReceivedArgs[index])))""",
            [event, since],
        )

    async def sent_mark(self) -> int:
        """The point in what goes out from which the next assertions read."""
        return await self._page.evaluate("() => window.__socketSent.length")

    async def sent(self, since: int = 0) -> list[str]:
        return await self._page.evaluate("(since) => window.__socketSent.slice(since)", since)

    async def wait_for(self, *events: str, since: int, timeout_s: float = 5) -> None:
        """Until any of `events` arrives at or after the mark `since`.

        The mark is required: an event of the same name received earlier -
        the join's own `room_state`, say - would otherwise answer at once, and
        the wait would prove nothing. Five seconds is for an answer to
        something that has already happened on a live socket; a wait that
        spans a reconnect waits for the new socket first, on its own bound.
        A caller waiting on something slower than an answer names its own.
        """
        try:
            await self._page.wait_for_function(
                "([since, events]) => window.__socketReceived.slice(since).some((e) => events.includes(e))",
                arg=[since, list(events)],
                polling=50,
                timeout=timeout_s * 1000,
            )
        except PlaywrightTimeoutError as timeout:
            # A bare timeout names neither the event nor the mark.
            raise AssertionError(
                f"none of {events} arrived after event {since} within {timeout_s:g} s"
            ) from timeout


async def _draw_stroke(page, box, offset: int) -> None:
    await page.mouse.move(box["x"] + offset, box["y"] + offset)
    await page.mouse.down()
    await page.mouse.move(box["x"] + offset + 90, box["y"] + offset + 60)
    await page.mouse.move(box["x"] + offset + 140, box["y"] + offset + 30)
    await page.mouse.up()


async def test_a_viewer_gets_its_commits_on_the_frame_and_never_resyncs():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--mute-audio"])
        host_context = await browser.new_context()
        player_context = await browser.new_context()
        host_page = await host_context.new_page()
        player_page = await player_context.new_page()
        host_events = await SocketEventLog.attach(host_page)
        player_events = await SocketEventLog.attach(player_page)
        try:
            await host_page.goto(BASE_URL)
            await use_guest_name(host_page, "CommitHost")
            await open_create_room(host_page)
            # Private: a public room would sit in the lobby list the other
            # tests read.
            await host_page.click(
                '[role="group"][aria-label="Visibility"] button:has-text("Private")'
            )
            await host_page.click('button:has-text("Create room")')
            await host_page.wait_for_selector('[data-testid="waiting-room"]')
            code = await room_code(host_page)

            await player_page.goto(BASE_URL)
            await use_guest_name(player_page, "CommitViewer")
            await join_by_code(player_page, code)
            await player_page.wait_for_selector('[data-testid="waiting-room"]')

            await host_page.click('.waiting-start-button')
            await host_page.wait_for_selector(
                '.prompt-choices, [data-testid="choosing-prompt-status"]'
            )
            drawing = host_page if await host_page.query_selector('.prompt-choices') else player_page
            viewing = player_page if drawing is host_page else host_page
            viewer_events = player_events if viewing is player_page else host_events
            await drawing.click('.prompt-choices button:first-child')
            # `.drawable`, not just the canvas: the canvas is on screen before
            # `turn_started` makes this seat the drawer, and a stroke begun in
            # between is ignored - nothing is sent, so the viewer waits on ink
            # that was never drawn (the flake seen on a loaded CI runner).
            await drawing.wait_for_selector('canvas.drawing-canvas.drawable')
            await viewing.wait_for_selector('canvas.drawing-canvas')

            canvas = await drawing.query_selector('canvas.drawing-canvas')
            box = await canvas.bounding_box()
            assert box is not None

            # Everything the viewer received while joining - including the
            # `sync_strokes` every turn start sends it - belongs to the past.
            watch_from = await viewer_events.mark()

            await _draw_stroke(drawing, box, 60)
            await _draw_stroke(drawing, box, 180)

            has_ink = """
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
            await viewing.wait_for_function(has_ink)

            # The undo is what makes a viewer that *ignored* its commits give
            # itself away. `canvas_undo` is still an event of its own, and the
            # client refuses one whose sequence is not the next it expects - so
            # a viewer two commits behind refuses this and asks for a full
            # resync, while a viewer that read them off the frames accepts it.
            await drawing.click("button.undo-button")
            await viewer_events.wait_for("canvas_undo", since=watch_from)
            # A resync is requested the moment the undo is refused, so a short
            # settle is enough for one to show up if it is going to. Proving an
            # event *absent* needs a window; this is that window.
            await viewing.wait_for_timeout(750)

            watched = await viewer_events.received(watch_from)
            assert "canvas_undo" in watched, (
                "the undo never reached the viewer, so nothing was proven"
            )
            assert "canvas_commit" not in watched, (
                "the viewer was still sent a separate commit event"
            )
            # Both shapes of resync, because they are not interchangeable here.
            # A viewer that drifts still holds a *correct* history - only its
            # sequence is stale - so its prefix claim is accepted and it is
            # answered with the incremental tail, not the full dump. Watching
            # only for `sync_strokes` misses exactly the case this guards.
            resyncs = [event for event in watched if event in ("sync_strokes", "sync_strokes_tail")]
            assert resyncs == [], (
                "the viewer's bookkeeping fell behind and it asked for a resync"
            )
        finally:
            await browser.close()

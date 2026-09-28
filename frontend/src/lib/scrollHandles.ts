/**
 * Overlay scroll handles in place of classic scrollbars (#1222).
 *
 * A classic scrollbar - Windows, Linux, macOS with a mouse or set to always
 * show them - takes a lane out of whatever it scrolls. On the page that lane
 * was a strip down the window's right edge that the banner could not reach,
 * and the root had to keep it on every page, scrolling or not, so that nothing
 * centred moved between a page that scrolls and one that fits (#1178); inside
 * a panel it took the same width off the chat, the lists and the tables.
 * Phones and trackpads draw overlay scrollbars that take nothing, and a page
 * cannot ask the browser for those. So where the platform's scrollbars take a
 * lane, the native ones are hidden (`html.scroll-handles`,
 * styles/scroll-handles.css) and this draws a handle over the edge of whatever
 * is scrolling instead: while the player scrolls it, and while the pointer is
 * near that edge. It lingers a second, fades, and can be dragged.
 *
 * Everything still scrolls natively, so the wheel, the keyboard and touch are
 * untouched, and no scroll area's DOM changes: the handles are drawn in one
 * layer of their own over the page, placed from each area's box. A scroll area
 * that wants no handle - a strip of tabs that hid its scrollbar on purpose -
 * says so with `--scroll-handle: none`.
 *
 * Where the scrollbars are overlay ones already this does nothing at all. The
 * test is a box that always has a scrollbar, whose lane is 0 there. It is read
 * once, at start, before `html.scroll-handles` hides that box's scrollbar too.
 * A page cannot tell *Always show scroll bars* from a mouse being plugged in,
 * so both get the handles.
 */

/** How near an area's edge the pointer calls its handle up. */
export const EDGE_ZONE = 16;
/** The handle's gap from the area's edge and from the ends of its track. */
export const INSET = 2;
/** The handle's hit box across; the bar drawn inside it is thinner until the
    pointer is on it (styles/scroll-handles.css). */
export const HIT = 10;
/** The shortest a handle gets, so a long page still leaves something to grab. */
export const MIN_LENGTH = 24;
/** How long a handle stays once its area stops scrolling or the pointer leaves the edge. */
export const LINGER_MS = 1000;
/** How long after the player's own input a scroll still counts as theirs: a
    wheel's or a key's smooth scroll runs on after the event. */
export const INPUT_WINDOW_MS = 700;
/** Longer than the fade (`--dur`), so a handle is only taken away once it is out of sight. */
const FADE_MS = 400;
/** The keys that scroll what has focus. */
// Not copy: `KeyboardEvent.key` values, never shown to anyone.
const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "PageUp", "PageDown", "Home", "End", " "]);

export type Axis = "y" | "x";

export interface HandlePlace {
  length: number;
  offset: number;
}

/** Where the handle sits along a track of `track` pixels, for an area that
    shows `viewport` of `content` scrolled to `scroll`; null when there is
    nothing to scroll. */
export function handleGeometry(track: number, viewport: number, content: number, scroll: number): HandlePlace | null {
  const range = content - viewport;
  if (range < 1 || track <= 0) return null;
  const length = Math.min(track, Math.max(MIN_LENGTH, (track * viewport) / content));
  const offset = ((track - length) * Math.min(Math.max(scroll, 0), range)) / range;
  return { length, offset };
}

/** The scroll offset a drag of `delta` pixels along the track asks for, from
    `startScroll`: the handle moves with the pointer, so a pixel of track is
    as much content as the track's free length stands for. */
export function scrollForDrag(
  track: number,
  viewport: number,
  content: number,
  startScroll: number,
  delta: number,
): number {
  const place = handleGeometry(track, viewport, content, startScroll);
  if (!place) return startScroll;
  const free = track - place.length;
  const range = content - viewport;
  if (free <= 0) return startScroll;
  return Math.min(range, Math.max(0, startScroll + (delta * range) / free));
}

/** Whether the platform's scrollbars take a lane: measured on a box that
    always has one, with nothing in it to scroll. Fixed and zero-height, so it
    neither shows nor adds to what the page can scroll; styled through the
    CSSOM, which the CSP allows where a style attribute would not be. */
function scrollbarsTakeALane(): boolean {
  const probe = document.createElement("div");
  Object.assign(probe.style, {
    position: "fixed",
    top: "0",
    left: "0",
    width: "100px",
    height: "0",
    overflowY: "scroll",
    visibility: "hidden",
    pointerEvents: "none",
  });
  document.body.appendChild(probe);
  const lane = probe.offsetWidth - probe.clientWidth;
  probe.remove();
  return lane > 0;
}

interface Shown {
  until: number;
  handles: Map<Axis, HTMLDivElement>;
}

interface Drag {
  area: Element;
  axis: Axis;
  start: number;
  startScroll: number;
}

/** Hide the native scrollbars and draw the handles, where the platform's
    scrollbars take a lane; nothing otherwise. */
export function installScrollHandles(): void {
  if (!scrollbarsTakeALane()) return;
  const root = document.documentElement;
  root.classList.add("scroll-handles");
  // WebKit styles the page's own scrollbar once, when it makes it, and the
  // page has been laid out by now: a class added this late never reached it,
  // so the prefixed rule Safari before 18.2 relies on left the page's lane in
  // place. Taking the root's overflow away and giving it back makes WebKit
  // build that scrollbar again, with the class in force.
  root.style.overflow = "hidden";
  root.getBoundingClientRect();
  root.style.removeProperty("overflow");
  const layer = document.createElement("div");
  layer.className = "scroll-handle-layer";
  layer.setAttribute("aria-hidden", "true");
  document.body.appendChild(layer);

  const shown = new Map<Element, Shown>();
  let drag: Drag | null = null;
  let lastInput = { at: Number.NEGATIVE_INFINITY, target: null as EventTarget | null };
  let lastPressed: EventTarget | null = null;
  let pointer: { x: number; y: number; target: EventTarget | null } | null = null;
  let hoverQueued = false;
  let frameQueued = false;

  const size = (area: Element, axis: Axis) =>
    axis === "y"
      ? { viewport: area.clientHeight, content: area.scrollHeight, scroll: area.scrollTop }
      : { viewport: area.clientWidth, content: area.scrollWidth, scroll: area.scrollLeft };

  const scrolls = (area: Element, axis: Axis): boolean => {
    const { viewport, content } = size(area, axis);
    if (content - viewport < 1) return false;
    const style = getComputedStyle(area);
    if (style.getPropertyValue("--scroll-handle").trim() === "none") return false;
    let overflow = axis === "y" ? style.overflowY : style.overflowX;
    if (area === root) {
      // The window scrolls unless the root - or `body`, which lends the
      // window its overflow when the root's is `visible` - says it may not.
      if (overflow === "visible") {
        const body = getComputedStyle(document.body);
        overflow = axis === "y" ? body.overflowY : body.overflowX;
      }
      return overflow !== "hidden" && overflow !== "clip";
    }
    return overflow === "auto" || overflow === "scroll";
  };

  // The area's padding box on screen; the window's for the page.
  const box = (area: Element) => {
    if (area === root) return { left: 0, top: 0, width: root.clientWidth, height: root.clientHeight };
    const rect = area.getBoundingClientRect();
    return {
      left: rect.left + area.clientLeft,
      top: rect.top + area.clientTop,
      width: area.clientWidth,
      height: area.clientHeight,
    };
  };

  // The track a handle runs along, keeping clear of the other axis's handle
  // where an area scrolls both ways.
  const track = (area: Element, axis: Axis, both: boolean) => {
    const b = box(area);
    const corner = both ? HIT : 0;
    return axis === "y"
      ? { x: b.left + b.width - INSET - HIT, y: b.top + INSET, length: b.height - 2 * INSET - corner }
      : { x: b.left + INSET, y: b.top + b.height - INSET - HIT, length: b.width - 2 * INSET - corner };
  };

  const queueFrame = () => {
    if (frameQueued) return;
    frameQueued = true;
    requestAnimationFrame(frame);
  };

  const makeHandle = (area: Element, axis: Axis) => {
    const handle = document.createElement("div");
    handle.className = `scroll-handle ${axis === "y" ? "is-vertical" : "is-horizontal"}`;
    handle.addEventListener("pointerdown", (event) => startDrag(event, area, axis, handle));
    layer.appendChild(handle);
    return handle;
  };

  const show = (area: Element, axes: Axis[]) => {
    let state = shown.get(area);
    if (!state) {
      state = { until: 0, handles: new Map() };
      shown.set(area, state);
    }
    for (const axis of axes) {
      if (!state.handles.has(axis)) state.handles.set(axis, makeHandle(area, axis));
    }
    state.until = performance.now() + LINGER_MS;
    queueFrame();
  };

  const axesOf = (area: Element) => (["y", "x"] as const).filter((axis) => scrolls(area, axis));

  // Every frame while any handle is up, since what it measures - the area's
  // place, its content's length - can change under it without a scroll.
  function frame() {
    frameQueued = false;
    const now = performance.now();
    for (const [area, state] of shown) {
      const handles = [...state.handles.values()];
      if (drag?.area === area || handles.some((handle) => handle.matches(":hover"))) {
        state.until = now + LINGER_MS;
      }
      if (now >= state.until + FADE_MS || !area.isConnected) {
        for (const handle of handles) handle.remove();
        shown.delete(area);
        continue;
      }
      const both = scrolls(area, "y") && scrolls(area, "x");
      for (const [axis, handle] of state.handles) {
        const { viewport, content, scroll } = size(area, axis);
        const t = track(area, axis, both);
        const place = handleGeometry(t.length, viewport, content, scroll);
        if (place) {
          const x = axis === "y" ? t.x : t.x + place.offset;
          const y = axis === "y" ? t.y + place.offset : t.y;
          handle.style.transform = `translate(${x}px, ${y}px)`;
          if (axis === "y") handle.style.height = `${place.length}px`;
          else handle.style.width = `${place.length}px`;
        }
        handle.classList.toggle("is-visible", place !== null && now < state.until);
      }
    }
    if (shown.size > 0) queueFrame();
  }

  function startDrag(event: PointerEvent, area: Element, axis: Axis, handle: HTMLDivElement) {
    if (event.button !== 0 || !handle.classList.contains("is-visible")) return;
    // Not the press's usual work: no text selection starting under the
    // handle, and no focus leaving whatever had it.
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    drag = { area, axis, start: axis === "y" ? event.clientY : event.clientX, startScroll: size(area, axis).scroll };
    handle.classList.add("is-dragging");
    const move = (moved: PointerEvent) => {
      if (!drag) return;
      const { viewport, content } = size(area, axis);
      const t = track(area, axis, scrolls(area, "y") && scrolls(area, "x"));
      const delta = (axis === "y" ? moved.clientY : moved.clientX) - drag.start;
      const next = scrollForDrag(t.length, viewport, content, drag.startScroll, delta);
      area.scrollTo(axis === "y" ? { top: next, behavior: "instant" } : { left: next, behavior: "instant" });
    };
    // Lost capture too: a handle taken away mid-drag, with its area, must not
    // leave a drag behind that stops every other handle answering the pointer.
    const end = () => {
      drag = null;
      handle.classList.remove("is-dragging");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("lostpointercapture", end);
      show(area, [axis]);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("lostpointercapture", end);
  }

  // A scroll the player made - with the wheel, the keys, a finger, or a
  // selection dragged past the edge - calls the handle up. One the program
  // made does not, even straight after a click: the chat following a new
  // message, a page scrolled back to its top, a field scrolled into view as a
  // dialog opens. A handle flashing on every chat line would be the lane's
  // distraction back again.
  const noteInput = (event: Event) => {
    let target = event.target;
    if (event.type === "keydown") {
      if (!SCROLL_KEYS.has((event as KeyboardEvent).key)) return;
      // The keys scroll what has focus, or else what was last pressed.
      const focused = document.activeElement;
      target = focused && focused !== document.body ? focused : lastPressed;
    }
    lastInput = { at: performance.now(), target };
  };
  const byThePlayer = (area: Element) =>
    performance.now() - lastInput.at < INPUT_WINDOW_MS &&
    (area === root || (lastInput.target instanceof Node && area.contains(lastInput.target)));

  document.addEventListener("wheel", noteInput, { capture: true, passive: true });
  document.addEventListener("keydown", noteInput, { capture: true });
  document.addEventListener("touchmove", noteInput, { capture: true, passive: true });
  document.addEventListener(
    "pointerdown",
    (event) => {
      lastPressed = event.target;
    },
    { capture: true, passive: true },
  );

  document.addEventListener(
    "scroll",
    (event) => {
      const area = event.target === document ? root : event.target;
      if (!(area instanceof Element)) return;
      if (drag?.area === area || shown.has(area)) queueFrame();
      if (drag?.area === area || !byThePlayer(area)) return;
      const axes = axesOf(area);
      if (axes.length > 0) show(area, axes);
    },
    { capture: true, passive: true },
  );

  // Near an edge, the innermost area scrolling that way shows its handle. Read
  // once a frame at most, and only for a mouse with no button down: a button
  // held is a drag or a stroke on the canvas, which must not pay for this.
  const nearEdge = (area: Element, axis: Axis, x: number, y: number) => {
    const b = box(area);
    const right = b.left + b.width;
    const bottom = b.top + b.height;
    return axis === "y"
      ? x >= right - EDGE_ZONE && x < right && y >= b.top && y < bottom
      : y >= bottom - EDGE_ZONE && y < bottom && x >= b.left && x < right;
  };
  const checkHover = () => {
    hoverQueued = false;
    if (!pointer || drag) return;
    const { x, y, target } = pointer;
    // On a handle already: it keeps itself up while the pointer is on it.
    if (!(target instanceof Element) || layer.contains(target)) return;
    for (let area: Element | null = target; area; area = area.parentElement) {
      const here = area;
      if ((["y", "x"] as const).some((axis) => scrolls(here, axis) && nearEdge(here, axis, x, y))) {
        show(here, axesOf(here));
        return;
      }
    }
  };
  document.addEventListener(
    "pointermove",
    (event) => {
      if (event.buttons !== 0) {
        noteInput(event);
        return;
      }
      if (event.pointerType !== "mouse") return;
      pointer = { x: event.clientX, y: event.clientY, target: event.target };
      if (hoverQueued) return;
      hoverQueued = true;
      requestAnimationFrame(checkHover);
    },
    { capture: true, passive: true },
  );
}

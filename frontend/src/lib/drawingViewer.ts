/** The drawing viewer's rules, free of React and the DOM (#1497).

`components/DrawingViewer.tsx` is the one viewer the Recap, game history and the
pinned shelf open. What a gesture means, where the thumbnail strip stands and
when the overview is offered are decided here, so `tests/drawingViewer.test.mjs`
can hold them without a browser. */

/** How far a pointer moves before a drag commits to an axis. Below it the
    gesture may still be a tap. PhotoSwipe's figure (`AXIS_SWIPE_HYSTERISIS`). */
export const AXIS_LOCK_PX = 10;

/** A horizontal drag changes drawing once it passes half the drawing's width... */
export const SWIPE_COMMIT_RATIO = 0.5;

/** ...or when it is flicked faster than this, however short. PhotoSwipe's and
    Swiper's rule: the velocity is what makes a short swipe feel intended. */
export const SWIPE_FLICK_PX_PER_MS = 0.5;

/** A downward drag closes the viewer past this distance, or flicked faster
    than `CLOSE_FLICK_PX_PER_MS`. It spares the stretch to the close button at
    the top of a phone, the hardest place on the screen to reach. */
export const CLOSE_DRAG_PX = 120;
export const CLOSE_FLICK_PX_PER_MS = 0.6;

/** Past either end the drawing follows the finger at a third of its travel,
    so the end of the game is felt rather than looped past. */
export const RUBBER_BAND = 1 / 3;

/** Two taps this close together are a double tap, which zooms. A single tap
    waits this long before it acts, so the two never both happen. */
export const DOUBLE_TAP_MS = 250;

/** How long arrows shown by a tap stay before they fade again. */
export const ARROWS_SHOWN_MS = 3000;

/** How much a double tap enlarges the drawing. */
export const ZOOM_SCALE = 2;

/** Thumbnails a desktop strip shows at once; a phone's strip scrolls instead. */
export const DESKTOP_STRIP_SIZE = 8;

/** The overview of every drawing is offered only above this many. A default
    game - eight players, three rounds - is 24 drawings: three strips on a
    desktop, where the strip's own paging is enough, and an extra control would
    be clutter. A bigger game (up to 16 players and 10 rounds, 160 drawings) is
    where paging gets slow. A count rather than a number of strips, so the same
    games show it on every screen. */
export const OVERVIEW_THRESHOLD = 24;

export type DragAxis = "x" | "y";

/** The axis a drag has committed to, or null while it could still be a tap. */
export function dragAxis(dx: number, dy: number): DragAxis | null {
  if (Math.hypot(dx, dy) <= AXIS_LOCK_PX) return null;
  return Math.abs(dx) > Math.abs(dy) ? "x" : "y";
}

/** Where a horizontal drag shows the track: one for one, but damped past the
    first or the last drawing. */
export function dragOffset(dx: number, index: number, total: number): number {
  const pastStart = dx > 0 && index <= 0;
  const pastEnd = dx < 0 && index >= total - 1;
  return pastStart || pastEnd ? dx * RUBBER_BAND : dx;
}

/** What a horizontal drag does when the pointer lets go. */
export function swipeOutcome({
  dx,
  ms,
  width,
  index,
  total,
}: {
  dx: number;
  ms: number;
  width: number;
  index: number;
  total: number;
}): "previous" | "next" | "stay" {
  const far = Math.abs(dx) > width * SWIPE_COMMIT_RATIO;
  const flicked = Math.abs(dx) / Math.max(1, ms) > SWIPE_FLICK_PX_PER_MS;
  if (!far && !flicked) return "stay";
  if (dx < 0 && index < total - 1) return "next";
  if (dx > 0 && index > 0) return "previous";
  return "stay";
}

/** Whether a downward drag that let go closes the viewer. An upward one never does. */
export function closesOnRelease(dy: number, ms: number): boolean {
  if (dy <= 0) return false;
  return dy > CLOSE_DRAG_PX || dy / Math.max(1, ms) > CLOSE_FLICK_PX_PER_MS;
}

/** How long the slide to the next drawing takes: the less is left to travel
    after a drag, the shorter, so a long swipe finishes briskly and an arrow
    press from rest still reads as movement. 140 ms to 300 ms. */
export function slideDurationMs(dragged: number, width: number): number {
  const remaining = width > 0 ? Math.max(0, 1 - Math.abs(dragged) / width) : 1;
  return Math.round(140 + 160 * remaining);
}

/** The first thumbnail of the strip page that holds `index`. */
export function stripStartFor(index: number, size: number): number {
  return Math.floor(Math.max(0, index) / size) * size;
}

/** The first thumbnail of the last strip page. */
export function lastStripStart(total: number, size: number): number {
  return stripStartFor(Math.max(0, total - 1), size);
}

/** Where the strip stands after moving to `index`: where it was, if `index` is
    on it, or the page that holds `index` otherwise. Paging the strip by hand
    never moves the drawing, and moving the drawing only pages the strip when
    it has to. */
export function stripStartAfterMove(start: number, index: number, size: number): number {
  return index >= start && index < start + size ? start : stripStartFor(index, size);
}

/** Whether the overview of every drawing is offered for a game of `total`. */
export function offersOverview(total: number): boolean {
  return total > OVERVIEW_THRESHOLD;
}

/** Where a double tap at (`fx`, `fy`) - fractions of the drawing's box - moves
    the zoomed drawing, so the point tapped stays under the finger. */
export function zoomOriginOffset(fx: number, fy: number, width: number, height: number) {
  return {
    x: (0.5 - fx) * width * (ZOOM_SCALE - 1),
    y: (0.5 - fy) * height * (ZOOM_SCALE - 1),
  };
}

/** A pan of the zoomed drawing, kept inside its box: never so far that an
    edge of the drawing comes away from the frame. */
export function clampPan(x: number, y: number, width: number, height: number) {
  const limitX = (width * (ZOOM_SCALE - 1)) / 2;
  const limitY = (height * (ZOOM_SCALE - 1)) / 2;
  return {
    x: Math.max(-limitX, Math.min(limitX, x)),
    y: Math.max(-limitY, Math.min(limitY, y)),
  };
}

/** Whether a key press in the page should move the viewer: not while somebody
    is typing, and not when something else already answered it. */
export function arrowKeyMoves(event: {
  key: string;
  defaultPrevented: boolean;
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  target: { tagName?: string; isContentEditable?: boolean } | null;
}): "previous" | "next" | null {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return null;
  const tag = event.target?.tagName?.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" || event.target?.isContentEditable) {
    return null;
  }
  if (event.key === "ArrowLeft") return "previous";
  if (event.key === "ArrowRight") return "next";
  return null;
}

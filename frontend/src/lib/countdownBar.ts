/** How far along a countdown bar is drawn: a full-width fill inside an
    `overflow: hidden` track, slid left by what has run out (#1256).

`transform` rather than `width`: the compositor runs it, where a width that
changed four or ten times a second - and a transition joining the steps -
was a style recalc, a layout and a paint on the main thread every frame the
bar was on screen. Sliding keeps the fill's rounded end, which a `scaleX`
would squash. An empty bar slides one pixel further: at a fractional track
width, -100% can leave a device pixel of the fill showing at the track's
edge, and an empty bar has to read as empty. */
export function barTransform(fraction: number): string {
  const shown = Number.isFinite(fraction) ? Math.max(0, Math.min(1, fraction)) : 0;
  // Not copy: a CSS transform, the same in every language.
  if (shown === 0) return "translateX(calc(-100% - 1px))";
  return `translateX(${-(1 - shown) * 100}%)`;
}

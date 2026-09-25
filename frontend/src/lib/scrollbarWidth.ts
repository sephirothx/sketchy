/**
 * The width of the window's classic scrollbar, as `--scrollbar-width` on
 * `:root`, for layout that has to measure from the window.
 *
 * `100vw` counts the scrollbar's lane, and CSS has no unit that does not. The
 * page header reaches out of each page's column to the shell
 * (`.lobby-header` in styles/settings-shared.css), and with a 15px scrollbar
 * sized from `100vw` alone it sat 8.5px from the window's edge instead of 16.
 * This keeps it at 16 on every page. It does not stop the header moving by
 * half a lane between a page that scrolls and one that fits - the pinned
 * lobby - where the browser leaves no lane on the page that fits: `html`
 * asks for a stable gutter (reset.css), and a classic scrollbar drawn where
 * that is not honoured still takes its lane only when there is something to
 * scroll, moving every centred column on the page with it, the header
 * included. Overlay scrollbars - phones, macOS by default - take no lane,
 * and this is 0 there.
 */

/** The lane a classic scrollbar takes: never negative, whatever zoom rounds. */
export function scrollbarLane(innerWidth: number, clientWidth: number): number {
  return Math.max(0, Math.round(innerWidth - clientWidth));
}

/** Keep `--scrollbar-width` current: on start, on a resize, and whenever the
    page grows or shrinks enough to gain or lose its scrollbar - which changes
    the root's width without resizing the window. */
export function installScrollbarWidth(): void {
  const root = document.documentElement;
  let written = -1;
  const update = () => {
    const lane = scrollbarLane(window.innerWidth, root.clientWidth);
    if (lane === written) return;
    written = lane;
    root.style.setProperty("--scrollbar-width", `${lane}px`);
  };
  update();
  window.addEventListener("resize", update);
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(update).observe(root);
}

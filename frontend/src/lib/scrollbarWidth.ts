/**
 * How much of a classic scrollbar's lane `100vw` counts, as
 * `--scrollbar-width` on `:root`, for layout that has to measure from the
 * window.
 *
 * The page header reaches out of each page's column to the shell, or to the
 * window's 16px gutter when that is nearer (`.lobby-header` in
 * styles/settings-shared.css), and CSS has no unit for the width the page is
 * laid out in: only `100vw`. Whether `100vw` counts the lane depends on the
 * browser. `html` asks for a stable gutter (reset.css), so the lane is
 * reserved on every page, scrolling or not; Chromium then leaves it out of
 * `100vw`, and a browser that does not still counts it. So this measures
 * what `100vw` resolves to against the width `html` is laid out in, and
 * writes the difference - rather than the scrollbar's own width.
 *
 * It used to write the scrollbar's width, `innerWidth - clientWidth`. That
 * took the lane off twice in Chromium, which had already taken it off
 * `100vw`, but only on a page that scrolls - on one that fits, the root's
 * `clientWidth` still includes the empty gutter - so below the
 * shell's width the header stood 16px from the window on the pinned lobby
 * and 23.5px on Rules, and moved 7.5px between them (#1178). Overlay
 * scrollbars - phones, macOS by default - take no lane, and this is 0 there.
 */

/** The lane `100vw` counts beyond the page: never negative, whatever zoom rounds. */
export function scrollbarLane(viewportUnitWidth: number, pageWidth: number): number {
  return Math.max(0, Math.round(viewportUnitWidth - pageWidth));
}

/** Keep `--scrollbar-width` current: on start, and whenever the window or
    the page's width changes - a page gaining or losing its scrollbar changes
    the root's width without resizing the window, in a browser with no stable
    gutter. */
export function installScrollbarWidth(): void {
  const root = document.documentElement;
  // `100vw` as the browser resolves it. Fixed and zero-height, so it neither
  // shows nor adds to what the page can scroll. Set through the CSSOM, which
  // the CSP allows where a style attribute would not be.
  const probe = document.createElement("div");
  probe.setAttribute("aria-hidden", "true");
  Object.assign(probe.style, {
    position: "fixed",
    top: "0",
    left: "0",
    width: "100vw",
    height: "0",
    visibility: "hidden",
    pointerEvents: "none",
  });
  document.body.appendChild(probe);
  let written = -1;
  const update = () => {
    const lane = scrollbarLane(probe.getBoundingClientRect().width, root.getBoundingClientRect().width);
    if (lane === written) return;
    written = lane;
    root.style.setProperty("--scrollbar-width", `${lane}px`);
  };
  update();
  window.addEventListener("resize", update);
  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(update);
    observer.observe(root);
    observer.observe(probe);
  }
}

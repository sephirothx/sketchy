/**
 * A classic scrollbar's lane, as two properties on `:root`.
 *
 * `--scrollbar-reserve` is the lane the page keeps for itself while the
 * window shows no scrollbar: `body` pads its right side by it (reset.css), so
 * every page is laid out in the same width whether it scrolls or fits, and
 * nothing centred moves between Rules and the pinned lobby (#1178). It is the
 * platform's scrollbar width while the window has none of its own, and 0
 * while it does - and always 0 for overlay scrollbars (phones, macOS by
 * default), which take no lane. The banner stack reaches back over it, to the
 * window's edge.
 *
 * The lane used to be the root's `scrollbar-gutter: stable`, which needs no
 * script. But an empty root gutter is painted in the root's background colour
 * and nothing else - no element, shadow, fixed box or background image
 * reaches into it - so on every page that fit, the banner stopped 15px short
 * of the window's edge beside a strip of the page's colour (#1222).
 *
 * `--scrollbar-width` is how much of the lane `100vw` counts beyond the width
 * the page is laid out in, for layout that has to measure from the window.
 * The page header reaches out of each page's column to the shell, or to the
 * window's 16px gutter when that is nearer (`.lobby-header` in
 * styles/settings-shared.css), and CSS has no unit for the width the page is
 * laid out in: only `100vw`. Whether `100vw` counts a lane depends on the
 * browser and on how the lane is kept, so this measures what `100vw`
 * resolves to against the page's width, rather than assuming either. Writing
 * the scrollbar's own width, `innerWidth - clientWidth`, once took the lane
 * off twice in Chromium, which left the stable gutter out of `100vw`, and
 * moved the header 7.5px between a page that scrolls and one that fits.
 */

/** The lane `100vw` counts beyond the page: never negative, whatever zoom rounds. */
export function scrollbarLane(viewportUnitWidth: number, pageWidth: number): number {
  return Math.max(0, Math.round(viewportUnitWidth - pageWidth));
}

/** The lane the page keeps for itself: the platform's scrollbar while the
    window shows none, nothing while it shows one. Half a lane decides which,
    not any difference at all: at a zoom that is not a whole number the widths
    it is read from round apart by a pixel. */
export function scrollbarReserve(platformScrollbar: number, windowScrollbar: number): number {
  const lane = Math.max(0, Math.round(platformScrollbar));
  return windowScrollbar >= lane / 2 ? 0 : lane;
}

/** A hidden, zero-height box fixed to the window, styled through the CSSOM,
    which the CSP allows where a style attribute would not be. Fixed and
    zero-height, so it neither shows nor adds to what the page can scroll. */
function probe(style: Partial<CSSStyleDeclaration>): HTMLDivElement {
  const box = document.createElement("div");
  box.setAttribute("aria-hidden", "true");
  Object.assign(box.style, {
    position: "fixed",
    top: "0",
    left: "0",
    height: "0",
    visibility: "hidden",
    pointerEvents: "none",
    ...style,
  });
  document.body.appendChild(box);
  return box;
}

/** Keep both current: on start, and whenever the window resizes or gains or
    loses its scrollbar. */
export function installScrollbarWidth(): void {
  const root = document.documentElement;
  // `100vw` as the browser resolves it, and a scrollbar of the platform's
  // own: `overflow-y: scroll` draws one with nothing to scroll.
  const viewport = probe({ width: "100vw", overflowY: "scroll" });
  // The width the window leaves beside its own scrollbar, if it has one.
  // Watched instead of `html`, whose height changes as the reserve reflows the
  // page: a second resize of the root inside one frame is the browser's
  // "ResizeObserver loop" error.
  const area = probe({ right: "0" });
  let written: { reserve: number; lane: number } | null = null;
  const update = () => {
    const areaWidth = area.getBoundingClientRect().width;
    const reserve = scrollbarReserve(
      viewport.offsetWidth - viewport.clientWidth,
      window.innerWidth - areaWidth,
    );
    const lane = scrollbarLane(viewport.getBoundingClientRect().width, areaWidth - reserve);
    if (written?.reserve !== reserve) root.style.setProperty("--scrollbar-reserve", `${reserve}px`);
    if (written?.lane !== lane) root.style.setProperty("--scrollbar-width", `${lane}px`);
    written = { reserve, lane };
  };
  update();
  window.addEventListener("resize", update);
  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(update);
    observer.observe(area);
    observer.observe(viewport);
  }
}

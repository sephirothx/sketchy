import { useCallback, useRef } from "react";

/** Publishes how far a page's bottom controls reach up from the bottom edge, as
`--dock-clearance`, so what floats bottom-centre - the friend invite and the
toasts - stands above them instead of on them (R-UX-07).

The friend invite used to sit on the phone lobby's dock, over Quick play and
Create a room, and a toast on the waiting room's Start. The docks are fixed
bars whose height depends on what they hold (an error line, a name field, the
drawing toolbar), so like the banner stack (`--banner-height`) the height is
measured rather than restated in CSS.

Returns a callback ref. An element counts while it is fixed to the viewport -
itself, or inside a fixed shell such as the phone's playing room - and only
where it spans the bottom centre, which is where the invite and the toasts
stand: the landscape room's toolbar rail and its guess field in the right-hand
column are beside that spot, not under it, and counting them pushed the invite
into the middle of the canvas. An element may also reserve room above itself
with `--dock-reserve` (the guess field keeps a slot for the verdict on the last
guess, which floats outside its box). Several can be mounted at once; the
highest reach wins. */

const reaches = new Map<HTMLElement, number>();

function publish(): void {
  const reach = Math.max(0, ...reaches.values());
  document.documentElement.style.setProperty("--dock-clearance", `${reach}px`);
}

function fixedContainer(element: HTMLElement): HTMLElement | null {
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    if (getComputedStyle(node).position === "fixed") return node;
  }
  return null;
}

export function useBottomDock(): (element: HTMLElement | null) => void {
  const cleanupRef = useRef<(() => void) | null>(null);
  return useCallback((element: HTMLElement | null) => {
    cleanupRef.current?.();
    cleanupRef.current = null;
    if (!element) return;

    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => measure());
    const measure = () => {
      const container = fixedContainer(element);
      const box = element.getBoundingClientRect();
      const centre = window.innerWidth / 2;
      const spansCentre = box.height > 0 && box.left < centre && centre < box.right;
      const reserve = Number.parseFloat(getComputedStyle(element).getPropertyValue("--dock-reserve")) || 0;
      const reach = container && spansCentre ? Math.round(window.innerHeight - box.top + reserve) : 0;
      if (reach > 0) reaches.set(element, reach);
      else reaches.delete(element);
      publish();
      // A band that grows under this one - the drawing toolbar arriving under
      // the guess field - moves it up without resizing it, so the shell's
      // bands are watched too.
      if (observer && container) for (const band of container.children) observer.observe(band);
    };

    measure();
    observer?.observe(element);
    // Crossing a breakpoint un-fixes a dock without necessarily resizing it.
    window.addEventListener("resize", measure);
    cleanupRef.current = () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      reaches.delete(element);
      publish();
    };
  }, []);
}

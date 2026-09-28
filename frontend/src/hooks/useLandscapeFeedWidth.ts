import { useLayoutEffect, type RefObject } from "react";

/** The custom property the landscape feed column is sized by (game-room.css). */
export const LANDSCAPE_FEED_WIDTH = "--landscape-feed-width";
const FEED_MIN = 180;
const FEED_MAX = 320;
/** The column's border, and a little air between it and the drawing. */
const FEED_ALLOWANCE = 12;

/**
 * Size the landscape phone room's feed column from the width the canvas
 * leaves, between 180 and 320px (#1267).
 *
 * The column used to be `min(26vw, 180px)`, on the reasoning that every pixel
 * it takes comes off the canvas. Sideways, though, the 4:3 canvas is bound by
 * the height, not the width: at 844 x 390 a guesser's main column was 664px
 * against a 402px drawing - 262px unused - while the guess field had 81px of
 * text and read "Type your g". The canvas's width here is the wrapper's height
 * times 4/3, so what is left of the shell after the rail and that width is the
 * column's to take - but never so much that the prompt's row (its tiles, and
 * the wheel's toggle) wraps onto a second line, whose height would come off
 * the canvas and be counted as width to spare on the next measure. So the
 * height is read with the column at its narrowest, and the column then backs
 * off while the row has wrapped: the same answer from either side of a resize.
 * Written a frame later, as the banner stack's late measure is, so a resize
 * this causes is never delivered inside the observer that caused it; written
 * on the root, where the notices' `--dock-inline-inset` reads it.
 *
 * While the canvas is hidden - the drawer choosing a prompt - the last width
 * stands, so the column does not jump between the two phases.
 */
export function useLandscapeFeedWidth(active: boolean, shellRef: RefObject<HTMLElement | null>): void {
  useLayoutEffect(() => {
    const shell = shellRef.current;
    if (!active || !shell) return;
    const root = document.documentElement;
    let frame = 0;
    const observed = new Set<Element>();
    const observer = new ResizeObserver(() => schedule());

    function measure() {
      const wrapper = shell!.querySelector<HTMLElement>(".canvas-wrapper");
      if (wrapper && !observed.has(wrapper)) {
        observed.add(wrapper);
        observer.observe(wrapper);
      }
      if (!wrapper || wrapper.clientHeight === 0) return;
      const set = (px: number) => root.style.setProperty(LANDSCAPE_FEED_WIDTH, `${px}px`);
      const turnBar = shell!.querySelector<HTMLElement>(".turn-bar");
      // Read at the narrowest column, where the main column is widest and
      // nothing in the turn bar has wrapped: a wrapped bar is height taken off
      // the canvas, which a measure made after it would count as width to
      // spare - and widen the column further.
      set(FEED_MIN);
      const canvasWidth = (wrapper.clientHeight * 4) / 3;
      const barHeight = turnBar?.offsetHeight ?? 0;
      const rail = shell!.querySelector<HTMLElement>(".room-shell-dock")?.getBoundingClientRect().width ?? 0;
      let width = Math.floor(
        Math.min(FEED_MAX, Math.max(FEED_MIN, shell!.clientWidth - rail - canvasWidth - FEED_ALLOWANCE)),
      );
      set(width);
      // Only as wide as keeps the prompt's row on one line: its tiles and the
      // wheel's "Buy a letter" share it (#1267).
      while (turnBar && width > FEED_MIN && turnBar.offsetHeight > barHeight) {
        width = Math.max(FEED_MIN, width - 16);
        set(width);
      }
    }

    function schedule() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    }

    observer.observe(shell);
    measure();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      root.style.removeProperty(LANDSCAPE_FEED_WIDTH);
    };
  }, [active, shellRef]);
}

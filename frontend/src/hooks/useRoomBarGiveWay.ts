import { useLayoutEffect, type RefObject } from "react";

/** What a phone's room bar gives up, in order, when it runs short (R-UX-11).

A step is kept only if the one before it was not enough, and each is written
into the bar's `data-gave-way` as a word the stylesheet acts on:

- `round` - the round's word: *Round 2/3* becomes *2/3*;
- `mark` - the wordmark, which is also the way out, and the Room menu's Leave
  is the other one;
- `labels` - the words on the notice chips and the *AFK* chip, which keep their
  icons and their accessible names, and whose sentences are a tap away;
- `tight` - the room between things: the gaps, the chips' own padding and the
  bar's edges shrink;
- `wrap` - the round, the clock and the chips take a row of their own under the
  wordmark, the Room menu and the avatar.

Past `labels` nothing on the bar depends on the language, so `tight` is what a
300px phone needs for every combination the bar can hold - the round, the
clock, a drain or a lost connection (never both: the drain's notice ends with
the connection), an invitation and *AFK*. `wrap` is the guarantee, for a bar
narrower than that or a larger text size: the bar is never wider than the
screen and nothing on it lies over anything else. It costs the canvas a row,
so it comes last.

The clock, the round's numbers, the Room menu and the avatar never give way. */
export const ROOM_BAR_STEPS = ["round", "mark", "labels", "tight", "wrap"] as const;

export type RoomBarStep = (typeof ROOM_BAR_STEPS)[number];

/**
 * The fewest steps, in order, with which the bar fits. `fits` lays the bar
 * out with the steps given and says whether it fits; the last step is taken
 * without asking, since it is the one that always does.
 */
export function chooseGiveWay(fits: (steps: readonly RoomBarStep[]) => boolean): readonly RoomBarStep[] {
  for (let count = 0; count < ROOM_BAR_STEPS.length; count += 1) {
    const steps = ROOM_BAR_STEPS.slice(0, count);
    if (fits(steps)) return steps;
  }
  return ROOM_BAR_STEPS;
}

/** The boxes a flex container lays out: `display: contents` wrappers stand
    for their children, and hidden or out-of-flow elements take no room. */
function flexItems(container: Element): HTMLElement[] {
  return Array.from(container.children).flatMap((child) => {
    const style = getComputedStyle(child);
    if (style.display === "contents") return flexItems(child);
    if (style.display === "none" || style.position === "absolute" || style.position === "fixed") return [];
    return [child as HTMLElement];
  });
}

function rowWidth(items: HTMLElement[], container: Element): number {
  const gap = parseFloat(getComputedStyle(container).columnGap) || 0;
  return items.reduce((sum, item) => sum + item.getBoundingClientRect().width, 0)
    + gap * Math.max(0, items.length - 1);
}

/**
 * Whether the bar's one row holds everything on it as laid out now. The
 * middle slot stretches to whatever is left, so it counts as what it holds
 * rather than as its own box.
 */
function rowFits(bar: HTMLElement): boolean {
  const center = bar.querySelector(".game-header-center");
  const style = getComputedStyle(bar);
  const available = bar.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  const items = flexItems(bar);
  const gap = parseFloat(style.columnGap) || 0;
  const needed = items.reduce(
    (sum, item) => sum + (item === center ? rowWidth(flexItems(center), center) : item.getBoundingClientRect().width),
    0,
  ) + gap * Math.max(0, items.length - 1);
  // Half a pixel for the rounding of fractional widths.
  return needed <= available + 0.5;
}

/**
 * Measures a phone's room bar and writes what it gives up into its
 * `data-gave-way`, on mount and on every change of its width or of what is on
 * it: a notice arriving or ending, *AFK*, a new round, the countdown's digits.
 *
 * Measured rather than set at breakpoints, because what the bar holds changes
 * while a game runs and its words are seven languages long. Every measure
 * starts again from nothing given up and adds steps until the bar fits, so
 * the answer depends only on what is on the bar and never on the last answer
 * - it cannot flip back and forth. The steps are tried synchronously, inside
 * one observer callback, so none of the tries is ever painted.
 *
 * The attribute is the hook's, not React's: the header does not render it.
 */
export function useRoomBarGiveWay(barRef: RefObject<HTMLElement | null>, enabled: boolean) {
  useLayoutEffect(() => {
    const bar = barRef.current;
    if (!enabled || !bar) return;
    let width = -1;
    const measure = () => {
      // Not drawn (the guess keyboard is up): there is nothing to fit, and a
      // zero width would give everything up. It is measured again when shown.
      if (bar.clientWidth === 0) return;
      const steps = chooseGiveWay((tried) => {
        bar.dataset.gaveWay = tried.join(" ");
        return rowFits(bar);
      });
      bar.dataset.gaveWay = steps.join(" ");
    };
    measure();
    // Only its width: its height changes with `wrap`, which this decided.
    const resizes = new ResizeObserver(() => {
      if (bar.clientWidth === width) return;
      width = bar.clientWidth;
      measure();
    });
    resizes.observe(bar);
    const changes = new MutationObserver(measure);
    changes.observe(bar, { childList: true, subtree: true, characterData: true });
    // The first measure may run on the fallback font.
    let live = true;
    void document.fonts?.ready.then(() => {
      if (live) measure();
    });
    return () => {
      live = false;
      resizes.disconnect();
      changes.disconnect();
      delete bar.dataset.gaveWay;
    };
  }, [barRef, enabled]);
}

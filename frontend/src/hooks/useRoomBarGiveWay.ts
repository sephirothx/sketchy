import { useLayoutEffect, type RefObject } from "react";

/** What a phone's room bar gives up, in order, when it runs short (R-UX-11).

Each step is written into the bar's `data-gave-way` as a word the stylesheet
acts on:

- `round` - the round's word: *Round 2/3* becomes *2/3*;
- `mark` - the wordmark, which is also the way out, and the Room menu's Leave
  is the other one;
- `labels` - the words on the notice chips and the *AFK* chip, which keep their
  icons and their accessible names, and the drain's chip its countdown;
- `tight` - the room between things: the gaps, the chips' own padding and the
  bar's edges shrink;
- `wrap` - the round, the clock and the chips take a row of their own under the
  wordmark, the Room menu and the avatar.

Steps are taken in order until the bar fits, and then any earlier one the
later ones made room for is handed back: the wordmark's room is usually
enough for the round's word, and a bar that has given up the wordmark should
still say *Round 2/3*. Past `labels` nothing on the bar depends on the
language, so `tight` is what a 300px phone needs for the round, the clock, a
lost connection, an invitation and *AFK*. A drain's countdown is wider than
the lost connection's icon and never goes (#806), so with the invitation and
*AFK* beside it a 300px bar takes `wrap`: the guarantee, for that and for
anything narrower or a larger text size, that the bar is never wider than the
screen and nothing on it lies over anything else. It costs the canvas a row,
so it comes last.

The clock, the round's numbers, the drain's seconds, the Room menu and the
avatar never give way. */
export const ROOM_BAR_STEPS = ["round", "mark", "labels", "tight", "wrap"] as const;

export type RoomBarStep = (typeof ROOM_BAR_STEPS)[number];

/**
 * The steps with which the bar fits: the fewest in order, then with every
 * earlier step handed back that still fits, the latest first - the round's
 * word went first, so it is the last to be offered its room back. `fits`
 * lays the bar out with the steps given and says whether it fits. A pure
 * function of `fits`, so the answer depends only on what is on the bar and
 * cannot flip back and forth. If nothing fits, every step is taken: `wrap`
 * lets even an overfull row wrap again rather than run off the screen.
 */
export function chooseGiveWay(fits: (steps: readonly RoomBarStep[]) => boolean): readonly RoomBarStep[] {
  let count = 0;
  while (count <= ROOM_BAR_STEPS.length && !fits(ROOM_BAR_STEPS.slice(0, count))) count += 1;
  if (count > ROOM_BAR_STEPS.length) return ROOM_BAR_STEPS;
  let steps: RoomBarStep[] = ROOM_BAR_STEPS.slice(0, count);
  for (const step of steps.slice(0, -1).reverse()) {
    const without: RoomBarStep[] = steps.filter((taken) => taken !== step);
    if (fits(without)) steps = without;
  }
  return steps;
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

function barAvailable(bar: HTMLElement): number {
  const style = getComputedStyle(bar);
  return bar.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
}

/**
 * Whether the bar holds everything on it as laid out now: on one row, or -
 * once it has wrapped - with the wordmark, the menu and the avatar on the
 * first and the middle slot's contents on the second. The middle slot
 * stretches to whatever is left, so it counts as what it holds rather than
 * as its own box.
 */
function barFits(bar: HTMLElement, wrapped: boolean): boolean {
  const center = bar.querySelector(".game-header-center");
  const available = barAvailable(bar);
  const items = flexItems(bar);
  const content = center ? rowWidth(flexItems(center), center) : 0;
  const others = items.filter((item) => item !== center);
  const gap = parseFloat(getComputedStyle(bar).columnGap) || 0;
  const othersWidth = others.reduce((sum, item) => sum + item.getBoundingClientRect().width, 0);
  // Half a pixel for the rounding of fractional widths.
  if (wrapped) {
    return othersWidth + gap * Math.max(0, others.length - 1) <= available + 0.5
      && content <= available + 0.5;
  }
  const count = others.length + (center ? 1 : 0);
  return othersWidth + content + gap * Math.max(0, count - 1) <= available + 0.5;
}

function insideClock(node: Node): boolean {
  const element = node instanceof Element ? node : node.parentElement;
  return !!element?.closest(".timer");
}

/**
 * Measures a phone's room bar and writes what it gives up into its
 * `data-gave-way`, on mount and on every change of its width or of what is on
 * it: a notice arriving or ending, *AFK*, a new round, the countdown's digits.
 *
 * Measured rather than set at breakpoints, because what the bar holds changes
 * while a game runs and its words are seven languages long. Every measure
 * starts again from nothing given up (`chooseGiveWay`), so the answer depends
 * only on what is on the bar and never on the last answer - it cannot flip
 * back and forth. The steps are tried synchronously, inside one observer
 * callback, so none of the tries is ever painted.
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
        return barFits(bar, tried.includes("wrap"));
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
    // Not the clock's own ticks: its digits are tabular and its ring a fixed
    // size, so a second going by changes nothing's width, and each measure
    // lays the bar out once per step it tries. Everything else is worth one.
    const changes = new MutationObserver((records) => {
      if (records.some((record) => !insideClock(record.target))) measure();
    });
    changes.observe(bar, { childList: true, subtree: true, characterData: true });
    // A measure taken on the fallback font is taken again when a face arrives
    // - the bar's, or any other, since each can change what fits.
    const fonts = document.fonts;
    fonts?.addEventListener("loadingdone", measure);
    return () => {
      resizes.disconnect();
      changes.disconnect();
      fonts?.removeEventListener("loadingdone", measure);
      delete bar.dataset.gaveWay;
    };
  }, [barRef, enabled]);
}

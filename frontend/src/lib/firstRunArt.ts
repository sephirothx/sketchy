/**
 * The doodles around the first-run block (#588).
 *
 * Decoration, but not the same decoration twice: the three are drawn from the
 * deployment's own avatar doodles, dealt to the two sides of the tag, and each
 * given its own tilt, size and drop. Picked once per visit and held for the
 * life of the tab, like the line above them (`lib/firstRunLines.ts`) - a card
 * whose art moved while somebody was typing their name would be a card nobody
 * could take seriously.
 *
 * The numbers are deliberately small. This is a lobby, not a scrapbook: a
 * doodle may lean, sit a little high or low, and be a little bigger than its
 * neighbour, and that is the whole of it. Every one of them is spent on a
 * transform - rotate, translate, scale - and never on the box, so the deal
 * cannot change the height of the card it decorates: a panel that is a
 * different size on every load is a page that jumps.
 */

import { DOODLES } from "./avatarDoodles.ts";

export interface FirstRunDoodle {
  name: string;
  /** Degrees, -9 to 9. */
  rotate: number;
  /** Pixels up or down off the middle, -14 to 14. Drawn, not laid out. */
  shift: number;
  /** 0.85 to 1.15 of the size the card gives it. Drawn, not laid out. */
  scale: number;
}

export interface FirstRunArt {
  /** Left of the tag; the first doodle of the deal is the one a narrow card
   keeps, in its bottom-right corner. */
  left: FirstRunDoodle[];
  right: FirstRunDoodle[];
}

/** How many doodles the card holds when it is wide enough for them. */
export const FIRST_RUN_DOODLES = 3;

const range = (roll: number, from: number, to: number) => from + roll * (to - from);

/**
 * Deal the doodles. `roll` is called for every decision, so a test can feed a
 * known sequence and a browser can feed `Math.random`.
 */
export function pickArt(pool: readonly string[], roll: () => number): FirstRunArt {
  const left: FirstRunDoodle[] = [];
  const right: FirstRunDoodle[] = [];
  const remaining = [...pool];
  const wanted = Math.min(FIRST_RUN_DOODLES, remaining.length);
  // One side gets one and the other two, either way round: the tag sits in the
  // middle of the card, not in the middle of a symmetrical frame.
  const leftCount = wanted <= 1 ? wanted : roll() < 0.5 ? 1 : wanted - 1;
  for (let index = 0; index < wanted; index += 1) {
    const [name] = remaining.splice(Math.floor(roll() * remaining.length), 1);
    const doodle: FirstRunDoodle = {
      name,
      rotate: Math.round(range(roll(), -9, 9) * 2) / 2,
      shift: Math.round(range(roll(), -14, 14)),
      scale: Math.round(range(roll(), 0.85, 1.15) * 100) / 100,
    };
    (index < leftCount ? left : right).push(doodle);
  }
  return { left, right };
}

let dealt: FirstRunArt | null = null;

/** This visit's doodles. The same ones for the life of the tab. */
export function firstRunArt(): FirstRunArt {
  dealt ??= pickArt(DOODLES, Math.random);
  return dealt;
}

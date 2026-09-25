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
  /** Pixels up or down off the middle, -6 to 6. Drawn, not laid out. */
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

/** The largest lean, either way, in degrees. */
export const MAX_TILT = 9;
/** The size range, as a share of the box the card gives a doodle. */
export const MIN_SCALE = 0.85;
export const MAX_SCALE = 1.15;

/** How far a doodle may sit off the middle, up or down. It was 14, which on
    top of a corner doodle placed 14px *below* the card's edge put half of it
    out of sight: in a card that clips, it read as an overflow bug rather than
    a peek. The corner now insets the doodle (`.first-run-art.is-left` in
    styles/account.css) by at least `cornerOverhang` - see the test, which
    reads the inset from the stylesheet. */
export const MAX_DROP = 6;

/** How far past its own square a doodle's drawn square can reach, at worst,
    across (`x`) and downwards (`y`): scaled up to MAX_SCALE, turned by
    MAX_TILT, and - downwards only - dropped by MAX_DROP. The corner's inset
    has to be at least this for the doodle never to be clipped. */
export function cornerOverhang(box: number): { x: number; y: number } {
  const turned = (MAX_TILT * Math.PI) / 180;
  const half = (box / 2) * MAX_SCALE * (Math.cos(turned) + Math.sin(turned));
  const past = half - box / 2;
  return { x: past, y: past + MAX_DROP };
}

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
      rotate: Math.round(range(roll(), -MAX_TILT, MAX_TILT) * 2) / 2,
      shift: Math.round(range(roll(), -MAX_DROP, MAX_DROP)),
      scale: Math.round(range(roll(), MIN_SCALE, MAX_SCALE) * 100) / 100,
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

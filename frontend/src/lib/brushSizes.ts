/** The brush sizes the toolbar's slider stops at, and the default among them.

A size is always one of these: the slider snaps to them, the `[` and `]`
shortcuts step through them, and a player's **default brush size** - what a
turn starts at, since every turn resets the toolbar - is one of them too,
because a default the slider could not show would be a size nobody could get
back to. Mirrors `BRUSH_SIZES` in `backend/app/domain_values.py`, which the
account's copy is checked against. */

export const BRUSH_SIZES = [2, 4, 6, 8, 12, 16, 24, 32] as const;
export type BrushSize = (typeof BRUSH_SIZES)[number];

export const DEFAULT_BRUSH_SIZE: BrushSize = 6;
/** The eraser's is not a setting: it removes, and wide is what removing wants. */
export const DEFAULT_ERASER_SIZE: BrushSize = 24;

export function isBrushSize(value: unknown): value is BrushSize {
  return (BRUSH_SIZES as readonly unknown[]).includes(value);
}

/** Where along the slider a stop sits, 0-1. The stops are evenly spaced
whatever their sizes, which is what makes 2 and 4 as easy to hit as 24 and 32. */
export function stopPosition(size: BrushSize): number {
  return BRUSH_SIZES.indexOf(size) / (BRUSH_SIZES.length - 1);
}

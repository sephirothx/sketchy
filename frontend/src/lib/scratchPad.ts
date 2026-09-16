/**
 * The scratch pad (#829): a canvas that is only ever the player's own.
 *
 * Nothing drawn on it leaves the tab - no socket, no storage, no history - so
 * it can be offered exactly where the game cannot be played: while the
 * connection is down. That is also why it is not the game canvas. R-UX-08
 * holds that a room must never look live while it is not, and a pad that
 * looked like the stage would be the screen lying about what it is.
 */

import { CANVAS_HEIGHT, CANVAS_WIDTH } from "./canvasHistory.ts";
import type { Point } from "./canvasGeometry.ts";

/** Black and three of the palette's primaries: enough to draw with, too few to fuss over. */
export const SCRATCH_PAD_COLORS: readonly string[] = ["#000000", "#ed1c24", "#1234de", "#22b14c"];

/** In canvas pixels, the same 800 × 600 sheet the game draws on. */
export const SCRATCH_PAD_BRUSH_WIDTH = 8;

export interface PadRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Where a pointer at (`clientX`, `clientY`) lands on the pad's sheet.
 *
 * The canvas keeps its 800 × 600 backing store however small it is drawn, so
 * a saved pad is the same size as a saved drawing. Clamped to the sheet: a
 * pointer captured past the edge keeps drawing along it rather than off it.
 */
export function padPoint(clientX: number, clientY: number, rect: PadRect): Point {
  if (rect.width <= 0 || rect.height <= 0) return { x: 0, y: 0 };
  const x = ((clientX - rect.left) / rect.width) * CANVAS_WIDTH;
  const y = ((clientY - rect.top) / rect.height) * CANVAS_HEIGHT;
  return {
    x: Math.min(CANVAS_WIDTH - 1, Math.max(0, x)),
    y: Math.min(CANVAS_HEIGHT - 1, Math.max(0, y)),
  };
}

import assert from "node:assert/strict";
import test from "node:test";

import { SCRATCH_PAD_COLORS, padPoint } from "../src/lib/scratchPad.ts";
import { PALETTE_COLORS } from "../src/lib/drawingRules.ts";

// Squashed on purpose: a different scale on each axis, so neither can stand in for the other.
const rect = { left: 100, top: 50, width: 200, height: 300 };

test("a pointer maps onto the pad's full 800 x 600 sheet however small it is drawn", () => {
  assert.deepEqual(padPoint(100, 50, rect), { x: 0, y: 0 });
  assert.deepEqual(padPoint(200, 200, rect), { x: 400, y: 300 });
  assert.deepEqual(padPoint(150, 125, rect), { x: 200, y: 150 });
});

test("a captured pointer past the edge draws along it, not off it", () => {
  assert.deepEqual(padPoint(20, 10, rect), { x: 0, y: 0 });
  assert.deepEqual(padPoint(900, 900, rect), { x: 799, y: 599 });
});

test("a pad with no size yet maps everything to the corner rather than to NaN", () => {
  assert.deepEqual(padPoint(10, 10, { left: 0, top: 0, width: 0, height: 0 }), { x: 0, y: 0 });
});

test("the pad's colors are the game's own swatches", () => {
  for (const color of SCRATCH_PAD_COLORS) assert.ok(PALETTE_COLORS.includes(color), color);
});

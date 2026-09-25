import assert from "node:assert/strict";
import test from "node:test";

import { scrollbarLane } from "../src/lib/scrollbarWidth.ts";

test("a classic scrollbar's lane is the window less the root", () => {
  assert.equal(scrollbarLane(1280, 1265), 15);
});

test("an overlay scrollbar takes no lane", () => {
  assert.equal(scrollbarLane(390, 390), 0);
});

test("zoom rounding never makes the lane negative or fractional", () => {
  assert.equal(scrollbarLane(1279.6, 1280), 0);
  assert.equal(scrollbarLane(1280.4, 1265), 15);
});

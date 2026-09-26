import assert from "node:assert/strict";
import test from "node:test";

import { scrollbarLane } from "../src/lib/scrollbarWidth.ts";

test("a lane that 100vw counts is taken off the window", () => {
  assert.equal(scrollbarLane(1280, 1265), 15);
});

test("a lane that 100vw already leaves out is not taken off twice", () => {
  // Chromium with `scrollbar-gutter: stable` on the root: 100vw and the page
  // are both 1185 in a 1200px window, scrolling or not (#1178).
  assert.equal(scrollbarLane(1185, 1185), 0);
});

test("an overlay scrollbar takes no lane", () => {
  assert.equal(scrollbarLane(390, 390), 0);
});

test("zoom rounding never makes the lane negative or fractional", () => {
  assert.equal(scrollbarLane(1279.6, 1280), 0);
  assert.equal(scrollbarLane(1280.4, 1265), 15);
});

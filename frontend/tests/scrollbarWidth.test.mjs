import assert from "node:assert/strict";
import test from "node:test";

import { scrollbarLane, scrollbarReserve } from "../src/lib/scrollbarWidth.ts";

test("a lane that 100vw counts is taken off the window", () => {
  assert.equal(scrollbarLane(1280, 1265), 15);
});

test("a lane that 100vw already leaves out is not taken off twice", () => {
  // Chromium did with `scrollbar-gutter: stable` on the root: 100vw and the
  // page were both 1185 in a 1200px window, scrolling or not (#1178).
  assert.equal(scrollbarLane(1185, 1185), 0);
});

test("an overlay scrollbar takes no lane", () => {
  assert.equal(scrollbarLane(390, 390), 0);
  assert.equal(scrollbarReserve(0, 0), 0);
});

test("zoom rounding never makes the lane negative or fractional", () => {
  assert.equal(scrollbarLane(1279.6, 1280), 0);
  assert.equal(scrollbarLane(1280.4, 1265), 15);
});

test("a window with no scrollbar leaves the page to keep the lane", () => {
  // The pinned lobby with a classic scrollbar: the banner stack reaches over
  // this to the window's edge (#1222).
  assert.equal(scrollbarReserve(15, 0), 15);
});

test("a window showing its scrollbar keeps the lane itself", () => {
  assert.equal(scrollbarReserve(15, 15), 0);
});

test("zoom rounding the two widths a pixel apart does not flip the reserve", () => {
  // At 110% a 15px scrollbar is 13.6 CSS px, read as 14 on the probe and 13
  // off the window; a page that fits can round the other way.
  assert.equal(scrollbarReserve(14, 13), 0);
  assert.equal(scrollbarReserve(14, 1), 14);
  assert.equal(scrollbarReserve(13.6, 0), 14);
});

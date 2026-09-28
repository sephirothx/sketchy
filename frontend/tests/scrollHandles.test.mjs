import assert from "node:assert/strict";
import test from "node:test";

import { MIN_LENGTH, handleGeometry, scrollForDrag } from "../src/lib/scrollHandles.ts";

test("nothing to scroll draws no handle", () => {
  assert.equal(handleGeometry(400, 800, 800, 0), null);
  // A fractional overflow is rounding, not something to scroll.
  assert.equal(handleGeometry(400, 800, 800.5, 0), null);
});

test("the handle is the share of the track the view is of the content", () => {
  // A window showing a quarter of the page, at the top.
  assert.deepEqual(handleGeometry(400, 800, 3200, 0), { length: 100, offset: 0 });
});

test("the handle travels the free track as the content scrolls", () => {
  assert.deepEqual(handleGeometry(400, 800, 3200, 1200), { length: 100, offset: 150 });
  assert.deepEqual(handleGeometry(400, 800, 3200, 2400), { length: 100, offset: 300 });
});

test("a very long content keeps a handle long enough to grab", () => {
  const place = handleGeometry(400, 800, 800_000, 0);
  assert.equal(place.length, MIN_LENGTH);
  // And still reaches the end of the track at the end of the content.
  assert.equal(handleGeometry(400, 800, 800_000, 799_200).offset, 400 - MIN_LENGTH);
});

test("an overscrolled or rubber-banded offset stays on the track", () => {
  assert.equal(handleGeometry(400, 800, 3200, -40).offset, 0);
  assert.equal(handleGeometry(400, 800, 3200, 2600).offset, 300);
});

test("a handle never outgrows a track shorter than its minimum", () => {
  assert.deepEqual(handleGeometry(16, 100, 400, 0), { length: 16, offset: 0 });
});

test("dragging the handle moves the content as far as the handle went", () => {
  // 300px of free track stands for 2400px of content: 8px each.
  assert.equal(scrollForDrag(400, 800, 3200, 0, 30), 240);
  assert.equal(scrollForDrag(400, 800, 3200, 1200, -75), 600);
});

test("a drag past either end stops at that end", () => {
  assert.equal(scrollForDrag(400, 800, 3200, 0, 900), 2400);
  assert.equal(scrollForDrag(400, 800, 3200, 1200, -900), 0);
});

test("a drag on something that no longer scrolls leaves it where it was", () => {
  assert.equal(scrollForDrag(400, 800, 800, 0, 50), 0);
  // A handle that fills its track has no free length to map a drag onto.
  assert.equal(scrollForDrag(16, 100, 400, 0, 5), 0);
});

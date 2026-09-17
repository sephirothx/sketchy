import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  BRUSH_SIZES,
  DEFAULT_BRUSH_SIZE,
  DEFAULT_ERASER_SIZE,
  isBrushSize,
  stopPosition,
} from "../src/lib/brushSizes.ts";

test("the defaults are stops, so the slider can always show and return to them", () => {
  assert.ok(isBrushSize(DEFAULT_BRUSH_SIZE));
  assert.ok(isBrushSize(DEFAULT_ERASER_SIZE));
  assert.deepEqual([...BRUSH_SIZES], [...BRUSH_SIZES].sort((a, b) => a - b));
  for (const junk of [0, 5, 6.5, 64, "6", null, undefined, Number.NaN]) {
    assert.equal(isBrushSize(junk), false, String(junk));
  }
});

test("stops are evenly spaced along the slider whatever their sizes", () => {
  assert.equal(stopPosition(BRUSH_SIZES[0]), 0);
  assert.equal(stopPosition(BRUSH_SIZES.at(-1)), 1);
  const gaps = BRUSH_SIZES.slice(1).map((size, index) => stopPosition(size) - stopPosition(BRUSH_SIZES[index]));
  for (const gap of gaps) assert.ok(Math.abs(gap - gaps[0]) < 1e-12);
});

test("the server checks an account's default against the same stops", async () => {
  // `user_settings.default_brush_size` has a CHECK built from this tuple, and
  // the API a literal of the same numbers: a stop added here and not there
  // would be a default a guest can keep and an account cannot.
  const values = await readFile(new URL("../../backend/app/domain_values.py", import.meta.url), "utf8");
  const tuple = values.match(/^BRUSH_SIZES = \(([^)]*)\)/m);
  assert.ok(tuple);
  assert.deepEqual(tuple[1].split(",").map((part) => Number(part.trim())), [...BRUSH_SIZES]);
  assert.equal(Number(values.match(/^DEFAULT_BRUSH_SIZE = (\d+)/m)[1]), DEFAULT_BRUSH_SIZE);

  const api = await readFile(new URL("../../backend/app/api/user_settings.py", import.meta.url), "utf8");
  const literal = api.match(/^BrushSize = Literal\[([^\]]*)\]/m);
  assert.deepEqual(literal[1].split(",").map((part) => Number(part.trim())), [...BRUSH_SIZES]);
});

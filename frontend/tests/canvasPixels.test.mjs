import assert from "node:assert/strict";
import test from "node:test";

import {
  colorsEqual,
  colorsMatchForFill,
  floodFillPixels,
  hexToRgba,
  rasterizePath,
} from "../src/lib/canvasPixels.ts";

const WHITE = [255, 255, 255, 255];
const BLACK = [0, 0, 0, 255];
const RED = [255, 0, 0, 255];

function solidPixels(width, height, color = WHITE) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let index = 0; index < data.length; index += 4) data.set(color, index);
  return data;
}

function pixel(data, width, x, y) {
  const index = (y * width + x) * 4;
  return [...data.slice(index, index + 4)];
}

test("hex colors and fill matching preserve the readback tolerance policy", () => {
  assert.deepEqual(hexToRgba("#12abef"), [18, 171, 239, 255]);
  assert.deepEqual(hexToRgba("invalid"), [0, 0, 0, 255]);

  const data = new Uint8ClampedArray([100, 110, 120, 255]);
  assert.equal(colorsEqual(data, 0, [100, 110, 120, 255]), true);
  assert.equal(colorsEqual(data, 0, [101, 110, 120, 255]), false);
  assert.equal(colorsMatchForFill(data, 0, [108, 102, 128, 247]), true);
  assert.equal(colorsMatchForFill(data, 0, [109, 110, 120, 255]), false);
});

test("typed-array path rasterization draws exact flat pixels", () => {
  const width = 7;
  const data = solidPixels(width, 5);
  rasterizePath(
    data,
    width,
    5,
    [{ x: 1.5, y: 2.5 }, { x: 5.5, y: 2.5 }],
    0.6,
    BLACK,
    false,
  );

  assert.deepEqual(pixel(data, width, 0, 2), WHITE);
  for (let x = 1; x <= 5; x++) assert.deepEqual(pixel(data, width, x, 2), BLACK);
  assert.deepEqual(pixel(data, width, 6, 2), WHITE);
  assert.deepEqual(pixel(data, width, 3, 1), WHITE);
  assert.deepEqual(pixel(data, width, 3, 3), WHITE);
});

test("closed rasterization includes the final-to-first segment", () => {
  const data = solidPixels(5, 5);
  const points = [{ x: 1.5, y: 1.5 }, { x: 3.5, y: 1.5 }, { x: 3.5, y: 3.5 }];
  rasterizePath(data, 5, 5, points, 0.6, BLACK, false);
  assert.deepEqual(pixel(data, 5, 2, 2), WHITE);
  rasterizePath(data, 5, 5, points, 0.6, BLACK, true);
  assert.deepEqual(pixel(data, 5, 2, 2), BLACK);
});

test("flood fill is 8-connected, bounded, and reports no-op fills", () => {
  const width = 3;
  const data = solidPixels(width, 3, BLACK);
  data.set(WHITE, 0);
  data.set(WHITE, (width + 1) * 4);
  data.set(WHITE, (2 * width + 2) * 4);

  assert.equal(floodFillPixels(data, width, 3, 0, 0, RED), true);
  assert.deepEqual(pixel(data, width, 0, 0), RED);
  assert.deepEqual(pixel(data, width, 2, 2), RED);
  assert.deepEqual(pixel(data, width, 1, 0), BLACK);
  assert.equal(floodFillPixels(data, width, 3, 0, 0, RED), false);
});

test("flood fill absorbs small readback perturbations but keeps visible boundaries", () => {
  const data = new Uint8ClampedArray([
    100, 100, 100, 255,
    108, 92, 104, 255,
    109, 100, 100, 255,
  ]);
  assert.equal(floodFillPixels(data, 3, 1, 0, 0, RED), true);
  assert.deepEqual(pixel(data, 3, 0, 0), RED);
  assert.deepEqual(pixel(data, 3, 1, 0), RED);
  assert.deepEqual(pixel(data, 3, 2, 0), [109, 100, 100, 255]);
});

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

function setPixel(data, width, x, y, color) {
  data.set(color, (y * width + x) * 4);
}

function pixelsFromRows(rows) {
  const width = rows[0].length;
  const data = solidPixels(width, rows.length, BLACK);
  rows.forEach((row, y) => {
    assert.equal(row.length, width);
    [...row].forEach((cell, x) => {
      if (cell === "." || cell === "S") setPixel(data, width, x, y, WHITE);
    });
  });
  return { data, width, height: rows.length };
}

function countPixels(data, color) {
  let count = 0;
  for (let index = 0; index < data.length; index += 4) {
    if (colorsEqual(data, index, color)) count++;
  }
  return count;
}

function referenceFloodFillPixels(
  data,
  width,
  height,
  startX,
  startY,
  fillColor,
) {
  const startIndex = (startY * width + startX) * 4;
  if (colorsEqual(data, startIndex, fillColor)) return false;
  const target = [...data.slice(startIndex, startIndex + 4)];
  const visited = new Uint8Array(width * height);
  const stack = [startX, startY];

  while (stack.length > 0) {
    const y = stack.pop();
    const x = stack.pop();
    if (x < 0 || x >= width || y < 0 || y >= height) continue;
    const pixelIndex = y * width + x;
    if (visited[pixelIndex]) continue;
    const index = pixelIndex * 4;
    if (!colorsMatchForFill(data, index, target)) continue;
    visited[pixelIndex] = 1;
    data.set(fillColor, index);
    stack.push(
      x + 1, y,
      x - 1, y,
      x, y + 1,
      x, y - 1,
      x + 1, y + 1,
      x + 1, y - 1,
      x - 1, y + 1,
      x - 1, y - 1,
    );
  }
  return true;
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

test("flood fill crosses diagonal-only connections", () => {
  const width = 3;
  const data = solidPixels(width, 3, BLACK);
  data.set(WHITE, 0);
  data.set(WHITE, (width + 1) * 4);
  data.set(WHITE, (2 * width + 2) * 4);

  assert.equal(floodFillPixels(data, width, 3, 0, 0, RED), true);
  assert.deepEqual(pixel(data, width, 0, 0), RED);
  assert.deepEqual(pixel(data, width, 2, 2), RED);
  assert.deepEqual(pixel(data, width, 1, 0), BLACK);
});

test("flood fill is bounded and reports no-op fills", () => {
  const data = solidPixels(3, 2);
  setPixel(data, 3, 1, 0, BLACK);
  setPixel(data, 3, 1, 1, BLACK);

  assert.equal(floodFillPixels(data, 3, 2, -1, 0, RED), false);
  assert.equal(floodFillPixels(data, 3, 2, 3, 1, RED), false);
  assert.equal(floodFillPixels(data, 3, 2, 0, 0, RED), true);
  assert.deepEqual(pixel(data, 3, 0, 0), RED);
  assert.deepEqual(pixel(data, 3, 2, 0), WHITE);
  assert.equal(floodFillPixels(data, 3, 2, 0, 0, RED), false);
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

test("flood fill handles narrow passages, islands, and irregular spans", () => {
  const rows = [
    "###########",
    "#S....#...#",
    "#####.#.#.#",
    "#.....#.#.#",
    "#.#####.#.#",
    "#.........#",
    "###########",
  ];
  const { data, width, height } = pixelsFromRows(rows);

  assert.equal(floodFillPixels(data, width, height, 1, 1, RED), true);
  assert.equal(countPixels(data, RED), rows.join("").match(/[.S]/g).length);
  assert.equal(countPixels(data, BLACK), rows.join("").match(/#/g).length);
});

test("flood fill handles alternating diagonal runs without crossing boundaries", () => {
  const size = 17;
  const data = solidPixels(size, size, BLACK);
  let targetPixels = 0;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if ((x + y) % 2 === 0) {
        setPixel(data, size, x, y, WHITE);
        targetPixels++;
      }
    }
  }

  assert.equal(floodFillPixels(data, size, size, 0, 0, RED), true);
  assert.equal(countPixels(data, RED), targetPixels);
  assert.equal(countPixels(data, BLACK), size * size - targetPixels);
});

test("large flood fills are deterministic when fill and target are tolerance-close", () => {
  const width = 200;
  const height = 150;
  const nearWhite = [250, 250, 250, 255];
  const first = solidPixels(width, height, WHITE);
  for (let y = 20; y < height - 20; y++) {
    setPixel(first, width, Math.floor(width / 2), y, BLACK);
  }
  const second = first.slice();

  assert.equal(floodFillPixels(first, width, height, 0, 0, nearWhite), true);
  assert.equal(floodFillPixels(second, width, height, 0, 0, nearWhite), true);
  assert.deepEqual(first, second);
  assert.equal(countPixels(first, BLACK), height - 40);
  assert.equal(countPixels(first, nearWhite), width * height - (height - 40));
});

test("scanline fill is pixel-equivalent to the previous eight-neighbour fill", () => {
  let randomState = 0x191149;
  const random = () => {
    randomState = (Math.imul(randomState, 1664525) + 1013904223) >>> 0;
    return randomState / 0x1_0000_0000;
  };
  const palette = [WHITE, [250, 252, 248, 255], BLACK, [20, 30, 40, 255]];

  for (let fixture = 0; fixture < 40; fixture++) {
    const width = 19;
    const height = 13;
    const input = new Uint8ClampedArray(width * height * 4);
    for (let index = 0; index < width * height; index++) {
      input.set(palette[Math.floor(random() * palette.length)], index * 4);
    }
    const startX = Math.floor(random() * width);
    const startY = Math.floor(random() * height);
    const expected = input.slice();
    const actual = input.slice();

    assert.equal(
      floodFillPixels(actual, width, height, startX, startY, RED),
      referenceFloodFillPixels(expected, width, height, startX, startY, RED),
    );
    assert.deepEqual(actual, expected, `fixture ${fixture}`);
  }
});

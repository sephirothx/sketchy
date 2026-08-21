import assert from "node:assert/strict";
import test from "node:test";

import { CANVAS_HEIGHT, CANVAS_WIDTH } from "../src/lib/canvasHistory.ts";
import {
  applyFillAtPixel,
  renderCanvasActions,
} from "../src/lib/canvasRenderer.ts";

const WHITE = [255, 255, 255, 255];
const BLACK = [0, 0, 0, 255];
const RED = [255, 0, 0, 255];

/** The smallest 2D context these renderers need: a pixel buffer they can
 * read back from and write to, plus the fillRect that paints it white. */
function fakeContext(fill = WHITE) {
  const data = new Uint8ClampedArray(CANVAS_WIDTH * CANVAS_HEIGHT * 4);
  for (let index = 0; index < data.length; index += 4) data.set(fill, index);
  return {
    pixels: data,
    fillStyle: "",
    save() {},
    restore() {},
    fillRect() {
      for (let index = 0; index < data.length; index += 4) data.set(WHITE, index);
    },
    createImageData(width, height) {
      return { width, height, data: new Uint8ClampedArray(width * height * 4) };
    },
    getImageData(x, y, width, height) {
      const out = new Uint8ClampedArray(width * height * 4);
      for (let row = 0; row < height; row++) {
        const from = ((y + row) * CANVAS_WIDTH + x) * 4;
        out.set(data.subarray(from, from + width * 4), row * width * 4);
      }
      return { width, height, data: out };
    },
    putImageData(imageData, x, y) {
      const { width, height } = imageData;
      for (let row = 0; row < height; row++) {
        const to = ((y + row) * CANVAS_WIDTH + x) * 4;
        data.set(
          imageData.data.subarray(row * width * 4, (row + 1) * width * 4),
          to,
        );
      }
    },
  };
}

function pixelAt(context, x, y) {
  const index = (y * CANVAS_WIDTH + x) * 4;
  return Array.from(context.pixels.subarray(index, index + 4));
}

function paintBlackColumn(context, x) {
  for (let y = 0; y < CANVAS_HEIGHT; y++) {
    context.pixels.set(BLACK, (y * CANVAS_WIDTH + x) * 4);
  }
}

test("a live fill spreads through the strokes already on the canvas", () => {
  const context = fakeContext();
  // A black wall down the middle: a fill on the left must stop at it.
  const wall = Math.floor(CANVAS_WIDTH / 2);
  paintBlackColumn(context, wall);

  assert.equal(applyFillAtPixel(context, 10, 10, "#ff0000"), true);

  assert.deepEqual(pixelAt(context, 10, 10), RED, "fills the clicked region");
  assert.deepEqual(pixelAt(context, wall, 10), BLACK, "leaves the stroke alone");
  assert.deepEqual(
    pixelAt(context, wall + 5, 10),
    WHITE,
    "does not cross the stroke",
  );
});

test("a live fill reports no change when the region is already that colour", () => {
  const context = fakeContext();
  assert.equal(applyFillAtPixel(context, 10, 10, "#ffffff"), false);
  assert.deepEqual(pixelAt(context, 10, 10), WHITE);
});

test("a replay starts from white regardless of what the canvas held", () => {
  const context = fakeContext(RED);
  paintBlackColumn(context, 4);

  renderCanvasActions(context, []);

  assert.deepEqual(pixelAt(context, 4, 4), WHITE, "old strokes are gone");
  assert.deepEqual(pixelAt(context, 40, 40), WHITE);
});

test("a replayed fill stops at a replayed stroke", () => {
  const context = fakeContext();
  const wall = Math.floor(CANVAS_WIDTH / 2);
  renderCanvasActions(context, [
    {
      kind: "path",
      color: "#000000",
      width: 2,
      points: [
        { x: wall, y: 0 },
        { x: wall, y: CANVAS_HEIGHT },
      ],
    },
    { kind: "fill", x: 10, y: 10, color: "#ff0000" },
  ]);

  assert.deepEqual(pixelAt(context, 10, 10), RED);
  assert.deepEqual(pixelAt(context, wall, 10), BLACK);
  assert.deepEqual(pixelAt(context, wall + 5, 10), WHITE);
});

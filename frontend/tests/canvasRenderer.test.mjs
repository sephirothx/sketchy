import assert from "node:assert/strict";
import test from "node:test";

import { CANVAS_HEIGHT, CANVAS_WIDTH } from "../src/lib/canvasHistory.ts";
import {
  applyFillAtPixel,
  rasterizePath,
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

test("a saved drawing played out in stretches ends as its whole-history raster (#940)", async () => {
  const { applyCanvasStrokeSpan, applyCanvasAction } = await import("../src/lib/canvasRenderer.ts");
  const { replayStroke } = await import("../src/lib/replay.ts");
  const blank = () => new Uint8ClampedArray(800 * 600 * 4).fill(255);
  const paintedAlike = (a, b) => a.every((value, index) => value === b[index]);
  // The review's case: width 8, a diagonal, split at 0.51. Cut there and
  // painted as two segments of their own, pixel (36, 23) went missing. It is
  // exactly the radius from the line, on the side the half-open rule leaves
  // white - it was ink only by float dust until the distance was exact - so
  // the stretches must leave it white too.
  const stroke = { points: [{ x: 25.5, y: 17.75 }, { x: 55.5, y: 49.25 }], width: 8, color: "#000000" };
  const whole = blank();
  applyCanvasAction(whole, { kind: "path", color: stroke.color, width: stroke.width, points: stroke.points });
  const played = blank();
  applyCanvasStrokeSpan(played, stroke, 0, 0.51);
  applyCanvasStrokeSpan(played, stroke, 0.51, 1);
  assert.equal(whole[(23 * 800 + 36) * 4], 255);
  assert.ok(paintedAlike(played, whole));

  // And any polyline, played in random stretches, pen widths included.
  let seed = 940;
  const next = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  for (let trial = 0; trial < 150; trial += 1) {
    const points = [];
    for (let index = 0; index < 4; index += 1) {
      points.push({ x: 40 + Math.floor(next() * 600) / 4, y: 40 + Math.floor(next() * 600) / 4 });
    }
    const widths = trial % 2 ? [[2, 4 + Math.floor(next() * 12)]] : undefined;
    const action = { kind: "path", color: "#000000", width: 2 + Math.floor(next() * 14), points, widths };
    const reference = blank();
    applyCanvasAction(reference, action);
    // What ReplayCanvas grows: the stroke with its ramps expanded.
    const path = replayStroke(action);
    const grown = blank();
    const end = path.points.length - 1;
    let at = 0;
    while (at < end) {
      const next_at = Math.min(end, at + next() * 0.9 + 0.05);
      applyCanvasStrokeSpan(grown, path, at, next_at);
      at = next_at;
    }
    assert.ok(paintedAlike(grown, reference), `trial ${trial}`);
  }
});

test("the drawer's ink, painted into a crop of the canvas, is the replay's raster", () => {
  // The drawer paints each kept segment into a `getImageData` crop, its points
  // moved to the crop's corner; a replay paints the history on the whole
  // canvas. Found by benchmarks/join_to_drawing.py: pixel (510, 351) is
  // exactly the radius from this segment, and the two routes rounded that
  // distance to opposite sides of it - a late joiner had one pixel more.
  const segment = [{ x: 504.75, y: 342.5 }, { x: 518.5, y: 354.5 }];
  const drawer = fakeContext();
  rasterizePath(drawer, segment, 3, BLACK, false);
  const joiner = fakeContext();
  renderCanvasActions(joiner, [{ kind: "path", color: "#000000", width: 6, points: segment }]);
  assert.deepEqual(pixelAt(drawer, 510, 351), pixelAt(joiner, 510, 351));
  assert.ok(drawer.pixels.every((value, index) => value === joiner.pixels[index]));

  // And any segment on the wire's grid, at any width.
  let seed = 949;
  const next = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const quarter = (limit) => 20 + Math.floor(next() * limit * 4) / 4;
  for (let trial = 0; trial < 300; trial += 1) {
    const a = { x: quarter(760), y: quarter(560) };
    const b = { x: a.x + Math.floor((next() - 0.5) * 120) / 4, y: a.y + Math.floor((next() - 0.5) * 120) / 4 };
    const width = 1 + Math.floor(next() * 24);
    const live = fakeContext();
    rasterizePath(live, [a, b], width / 2, BLACK, false);
    const replay = fakeContext();
    renderCanvasActions(replay, [{ kind: "path", color: "#000000", width, points: [a, b] }]);
    assert.ok(
      live.pixels.every((value, index) => value === replay.pixels[index]),
      `${JSON.stringify([a, b])} at width ${width}`,
    );
  }
});

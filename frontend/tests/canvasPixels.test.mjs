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

test("a stroke painted segment by segment is the stroke painted as one polyline (#560)", () => {
  // The drawer's canvas paints each kept segment as it is kept; a viewer
  // paints the flushed batch as one polyline. The rasterizer is a union of
  // per-segment capsules, so the two are one raster, pixel for pixel -
  // which is what lets a flood fill see the same edges on every screen.
  const points = [
    { x: 4.25, y: 5 }, { x: 12, y: 5.5 }, { x: 12.75, y: 14 }, { x: 20, y: 20.25 }, { x: 20, y: 6 },
  ];
  const width = 32;
  const height = 32;
  const bySegment = solidPixels(width, height);
  for (let i = 0; i + 1 < points.length; i++) {
    rasterizePath(bySegment, width, height, [points[i], points[i + 1]], 2.5, BLACK, false);
  }
  const asPolyline = solidPixels(width, height);
  rasterizePath(asPolyline, width, height, points, 2.5, BLACK, false);
  assert.deepEqual(Array.from(bySegment), Array.from(asPolyline));
});

test("a stroke of width w covers w pixels across wherever on the quarter-pixel grid its centre sits", () => {
  // Half-open on the edge (#940): a closed rule made a line centred on a half
  // pixel w + 1 thick, and float dust on the drawer's canvas used to decide
  // which edge rows it kept - so a late joiner's replay and the room parted.
  for (const width of [1, 2, 5, 6, 32]) {
    for (const offset of [0, 0.25, 0.5, 0.75]) {
      const across = 80;
      const horizontal = solidPixels(across, across);
      rasterizePath(horizontal, across, across, [{ x: 10, y: 40 + offset }, { x: 70, y: 40 + offset }], width / 2, BLACK, false);
      const vertical = solidPixels(across, across);
      rasterizePath(vertical, across, across, [{ x: 40 + offset, y: 10 }, { x: 40 + offset, y: 70 }], width / 2, BLACK, false);
      let rows = 0;
      let columns = 0;
      for (let k = 0; k < across; k += 1) {
        if (horizontal[(k * across + 40) * 4] === 0) rows += 1;
        if (vertical[(40 * across + k) * 4] === 0) columns += 1;
      }
      assert.equal(rows, width, `horizontal, width ${width}, centre +${offset}`);
      assert.equal(columns, width, `vertical, width ${width}, centre +${offset}`);
    }
  }
});

test("every painter reaches a wire coordinate as the same float, across the whole accepted range", async () => {
  const { toPixels } = await import("../src/lib/canvasGeometry.ts");
  // The live route: the decoder's normalized packed / 3200, then toPixels.
  // The replay route: packed / 4. They must be the same number, or an ulp
  // decides pixels on an edge (and no fixed tie margin fixes that: far off
  // the canvas, distinct exact distances are closer than any margin).
  for (let packed = -32768; packed <= 32767; packed += 1) {
    const live = toPixels({ x: packed / 3200, y: packed / 2400 });
    assert.equal(live.x, packed / 4, `x ${packed}`);
    assert.equal(live.y, packed / 4, `y ${packed}`);
  }
  // The review's case: a width-60 segment far off the canvas, pixel (0, 0).
  const [ax, ay, bx, by] = [7745, 11931, -9222, -14698];
  const live = [toPixels({ x: ax / 3200, y: ay / 2400 }), toPixels({ x: bx / 3200, y: by / 2400 })];
  const replay = [{ x: ax / 4, y: ay / 4 }, { x: bx / 4, y: by / 4 }];
  const paint = (points) => {
    const data = solidPixels(4, 4);
    rasterizePath(data, 4, 4, points, 30, BLACK, false);
    return data;
  };
  assert.deepEqual(paint(live), paint(replay));
});

test("a dot of width w is w pixels across when its edge falls on pixel centres, and never wider", () => {
  // A tap is a zero-length segment: no direction to take an edge's side from,
  // so a closed rule made it w + 1 wide and a directional one w - 1. Centred
  // on a pixel centre its whole edge is ties; elsewhere a disc covers what
  // its geometry covers - a width-1 dot on a pixel corner reaches no pixel
  // centre under any rule - but no offset may make it wider than the brush.
  for (let width = 1; width <= 32; width += 1) {
    for (const dx of [0, 0.25, 0.5, 0.75]) {
      for (const dy of [0, 0.25, 0.5, 0.75]) {
        const size = 64;
        const centre = { x: 30 + dx, y: 30 + dy };
        const data = solidPixels(size, size);
        rasterizePath(data, size, size, [centre, centre], width / 2, BLACK, false);
        let [minX, maxX, minY, maxY] = [size, -1, size, -1];
        for (let y = 0; y < size; y += 1) {
          for (let x = 0; x < size; x += 1) {
            if (data[(y * size + x) * 4] !== 0) continue;
            minX = Math.min(minX, x);
            maxX = Math.max(maxX, x);
            minY = Math.min(minY, y);
            maxY = Math.max(maxY, y);
          }
        }
        const [across, down] = [Math.max(0, maxX - minX + 1), Math.max(0, maxY - minY + 1)];
        const where = `width ${width} at +${dx},+${dy}`;
        assert.ok(across <= width && down <= width, `${where}: ${across}x${down}`);
        if (dx === 0.5 && dy === 0.5) {
          assert.equal(across, width, where);
          assert.equal(down, width, where);
        }
      }
    }
  }
});

test("a thumbnail is the area average of what it covers, not a sample of it", async () => {
  const { downscalePixels } = await import("../src/lib/canvasThumbnail.ts");
  // A 4x2 source: left half black, right half white, halved to 2x1.
  const source = new Uint8ClampedArray(4 * 2 * 4);
  for (let y = 0; y < 2; y++) for (let x = 0; x < 4; x++) source.set(x < 2 ? [0, 0, 0, 255] : [255, 255, 255, 255], (y * 4 + x) * 4);
  assert.deepEqual([...downscalePixels(source, 4, 2, 2, 1)], [0, 0, 0, 255, 255, 255, 255, 255]);
  // A one-pixel line a sample could miss still leaves its trace.
  const line = new Uint8ClampedArray(4 * 4 * 4).fill(255);
  line.set([0, 0, 0, 255], (1 * 4 + 1) * 4);
  const small = downscalePixels(line, 4, 4, 2, 2);
  assert.ok(small[0] < 255, "the dark pixel is averaged in, not skipped");
});

test("a fill reports the box it painted, and nothing beyond it (#990)", () => {
  // A 3x2 white hole inside a black frame on a 7x6 canvas: the fill must say
  // it painted exactly the hole, so a commit of that box shows all of it.
  const width = 7;
  const height = 6;
  const data = new Uint8ClampedArray(width * height * 4).fill(255);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const inHole = x >= 2 && x <= 4 && y >= 2 && y <= 3;
      const onFrame = x >= 1 && x <= 5 && y >= 1 && y <= 4 && !inHole;
      if (onFrame) data.set([0, 0, 0, 255], (y * width + x) * 4);
    }
  }
  const bounds = { left: -1, top: -1, right: -1, bottom: -1 };
  assert.equal(floodFillPixels(data, width, height, 3, 2, RED, bounds), true);
  assert.deepEqual(bounds, { left: 2, top: 2, right: 5, bottom: 4 });
});

test("a buffer that is not word-aligned fills exactly as an aligned one", () => {
  // The word fast path needs a 4-byte-aligned buffer; anything else takes the
  // byte path, which must paint the same pixels.
  const width = 9;
  const height = 7;
  const aligned = new Uint8ClampedArray(width * height * 4).fill(255);
  for (let x = 0; x < width; x++) aligned.set([250, 251, 255, 255], (3 * width + x) * 4);
  aligned.set([0, 0, 0, 255], (3 * width + 4) * 4);
  const backing = new Uint8ClampedArray(aligned.length + 1);
  const unaligned = backing.subarray(1);
  unaligned.set(aligned);
  assert.equal(floodFillPixels(aligned, width, height, 0, 0, RED), true);
  assert.equal(floodFillPixels(unaligned, width, height, 0, 0, RED), true);
  assert.deepEqual([...unaligned], [...aligned]);
});

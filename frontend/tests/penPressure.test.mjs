import assert from "node:assert/strict";
import test from "node:test";

import {
  FULL_PRESSURE,
  MAX_WIDTH_LEVELS,
  MIN_PEN_WIDTH,
  createPressureQuantizer,
  createPressureSource,
  widthLevels,
} from "../src/lib/penPressure.ts";
import { createPointThinner, maxThinningErrorPx, THINNING_TOLERANCE_PX } from "../src/lib/pointThinning.ts";
import { rasterizePath, floodFillPixels } from "../src/lib/canvasPixels.ts";

const PRESETS = [2, 4, 6, 8, 12, 16, 24, 32];

test("every brush tops out at itself, bottoms out at two pixels, and has at most six widths", () => {
  for (const brush of [...PRESETS, 3, 64]) {
    const { floor, widths } = widthLevels(brush);
    assert.equal(widths.at(-1), brush, `brush ${brush} at full pressure is the selected size`);
    assert.equal(widths[0], MIN_PEN_WIDTH, `brush ${brush} reaches the floor whatever its size`);
    assert.equal(floor, MIN_PEN_WIDTH);
    assert.ok(widths.length <= MAX_WIDTH_LEVELS, `brush ${brush}: ${widths}`);
    assert.deepEqual(widths, [...new Set(widths)].sort((a, b) => a - b));
    for (const width of widths) assert.ok(Number.isInteger(width) && width >= 1 && width <= 64);
  }
  assert.deepEqual(widthLevels(2).widths, [2], "the smallest brush has nowhere to go");
  assert.deepEqual(widthLevels(6).widths, [2, 3, 4, 5, 6]);
});

test("the widths are spaced by ratio, so the fine end is not one jump", () => {
  // Six even steps from 2 to 32 would be 2, 8, 14, ...: four times the width
  // at the first step, where a pen's control matters most.
  assert.deepEqual(widthLevels(32).widths, [2, 3, 6, 11, 18, 32]);
  assert.deepEqual(widthLevels(12).widths, [2, 3, 4, 6, 8, 12]);
  for (const brush of [16, 24, 32, 64]) {
    const { widths } = widthLevels(brush);
    const ratios = widths.slice(1).map((width, index) => width / widths[index]);
    assert.ok(Math.max(...ratios) <= 2, `brush ${brush}: no step more than doubles the line (${widths})`);
  }
});

test("the whole brush arrives before the pen is pressed as hard as it goes", () => {
  for (const brush of PRESETS) {
    assert.equal(createPressureQuantizer(brush).width(FULL_PRESSURE), brush);
    assert.equal(createPressureQuantizer(brush).width(1), brush);
    assert.equal(createPressureQuantizer(brush).width(0), widthLevels(brush).widths[0]);
  }
  // And not from a touch: a light hand on the largest brush is still a fine line.
  assert.ok(createPressureQuantizer(32).width(0.05) <= 6);
  assert.ok(createPressureQuantizer(32).width(FULL_PRESSURE / 2) < 32);
});

test("each level owns a band of pressure a hand can stop in", () => {
  // Mapped in pixels, a 32 px brush's three finest widths shared the lightest
  // twentieth of the range. By ratio, every level is reachable on the way up
  // in steps of 1% of the sensor's range, and none is narrower than 5%.
  for (const brush of [12, 32]) {
    const quantizer = createPressureQuantizer(brush);
    const band = new Map();
    for (let step = 0; step <= 100; step += 1) {
      const width = quantizer.width(step / 100);
      band.set(width, (band.get(width) ?? 0) + 1);
    }
    assert.deepEqual([...band.keys()], widthLevels(brush).widths);
    for (const [width, samples] of band) {
      if (width !== brush) assert.ok(samples >= 5, `brush ${brush}: ${width}px held for ${samples}%`);
    }
  }
});

test("two pixels is the floor because one does not hold a fill", () => {
  // The reason for MIN_PEN_WIDTH, kept as a test so the constant cannot be
  // lowered without meeting it: a line across the buffer, a fill on one side.
  const leaks = (width) => {
    let leaked = 0;
    for (let angle = 0; angle < 180; angle += 3) {
      const size = 120;
      const pixels = new Uint8ClampedArray(size * size * 4).fill(255);
      const t = (angle * Math.PI) / 180;
      const [cx, cy] = [60.25, 60.5];
      rasterizePath(pixels, size, size, [
        { x: cx - Math.cos(t) * 300, y: cy - Math.sin(t) * 300 },
        { x: cx + Math.cos(t) * 300, y: cy + Math.sin(t) * 300 },
      ], width / 2, [0, 0, 0, 255], false);
      const side = (sign) => [Math.round(cx - Math.sin(t) * 20 * sign), Math.round(cy + Math.cos(t) * 20 * sign)];
      floodFillPixels(pixels, size, size, ...side(1), [255, 0, 0, 255]);
      const [ox, oy] = side(-1);
      if (pixels[(oy * size + ox) * 4 + 1] === 0) leaked += 1;
    }
    return leaked;
  };
  assert.equal(leaks(MIN_PEN_WIDTH), 0);
  assert.ok(leaks(1) > 30);
});

test("pressure rises through the levels and falls back, never outside them", () => {
  const quantizer = createPressureQuantizer(12);
  const { widths } = widthLevels(12);
  const seen = [];
  for (let step = 0; step <= 100; step++) seen.push(quantizer.width(step / 100));
  for (let step = 100; step >= 0; step--) seen.push(quantizer.width(step / 100));
  assert.equal(seen[0], widths[0]);
  assert.equal(seen[100], 12);
  assert.equal(seen.at(-1), widths[0]);
  for (const width of seen) assert.ok(widths.includes(width));
  for (let index = 1; index <= 100; index++) assert.ok(seen[index] >= seen[index - 1]);
  assert.equal(createPressureQuantizer(12).width(Number.NaN), widths[0]);
  assert.equal(createPressureQuantizer(12).width(7), 12);
});

test("a hand held on the border of two levels does not chatter between them", () => {
  const quantizer = createPressureQuantizer(32);
  let changes = 0;
  let last = quantizer.width(0.3);
  for (let sample = 0; sample < 500; sample++) {
    // +/- 2% of the sensor's range around one pressure: noise, not intent.
    const width = quantizer.width(0.3 + 0.02 * Math.sin(sample * 1.7));
    if (width !== last) changes += 1;
    last = width;
  }
  assert.ok(changes <= 1, `${changes} changes`);
});

test("only a pen that has shown a working sensor is believed", () => {
  const source = createPressureSource();
  assert.equal(source.trusts("mouse", 0.5), false);
  assert.equal(source.trusts("touch", 0.8), false);
  // A pen with no sensor reports the constant the specification prescribes.
  assert.equal(source.trusts("pen", 0.5), false);
  assert.equal(source.trusts("pen", 0), false, "hovering");
  assert.equal(source.trusts("pen", 0.07), true);
  assert.equal(source.trusts("pen", 0.5), true, "a real sensor passes through 0.5 too");
  assert.equal(source.trusts("mouse", 0.07), false);
});

test("the thinner keeps the point two widths share, and every kept width is its whole run's", () => {
  // A ruler-straight line: without widths the thinner keeps only its ends.
  const line = Array.from({ length: 61 }, (_, i) => ({ x: 0.1 + i / 200, y: 0.5 }));
  const plain = createPointThinner(line[0]);
  const keptPlain = [line[0], ...line.slice(1).flatMap((p) => plain.push(p)), ...plain.end()];
  assert.equal(keptPlain.length, 2);

  const widthAt = (i) => (i <= 20 ? 3 : i <= 40 ? 7 : 5);
  const pen = line.map((p, i) => ({ ...p, width: widthAt(i) }));
  const thinner = createPointThinner(pen[0]);
  const kept = [pen[0], ...pen.slice(1).flatMap((p) => thinner.push(p)), ...thinner.end()];
  // The ends, and sample 20 and 40: where one width's last segment ends.
  assert.deepEqual(kept.map((p) => Math.round((p.x - 0.1) * 200)), [0, 20, 40, 60]);
  assert.deepEqual(kept.slice(1).map((p) => p.width), [3, 7, 5]);
  assert.ok(maxThinningErrorPx(pen, kept) <= THINNING_TOLERANCE_PX);
});

test("a flush between two widths still leaves each segment one width", () => {
  const thinner = createPointThinner({ x: 0.1, y: 0.5, width: 3 });
  assert.deepEqual(thinner.push({ x: 0.11, y: 0.5, width: 3 }), []);
  assert.deepEqual(thinner.flush().map((p) => p.width), [3]);
  // Nothing pending: the first sample at the new width just becomes pending,
  // and the anchor it will be joined to is the boundary.
  assert.deepEqual(thinner.push({ x: 0.12, y: 0.5, width: 7 }), []);
  assert.deepEqual(thinner.push({ x: 0.13, y: 0.5, width: 7 }), []);
  assert.deepEqual(thinner.end().map((p) => [p.x, p.width]), [[0.13, 7]]);
});

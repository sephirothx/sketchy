import assert from "node:assert/strict";
import test from "node:test";

import {
  FULL_PRESSURE,
  MIN_PEN_WIDTH,
  createPressureSource,
  targetWidth,
  wholeWidth,
} from "../src/lib/penPressure.ts";
import { createPointThinner } from "../src/lib/pointThinning.ts";
import { WIDTH_TOLERANCE_PX, createWidthThinner, widthTolerance } from "../src/lib/widthKeyframes.ts";
import { rasterizePath, floodFillPixels } from "../src/lib/canvasPixels.ts";

const PRESETS = [2, 4, 6, 8, 12, 16, 24, 32];

test("every brush spans two pixels to itself, and the whole of it arrives before full pressure", () => {
  for (const brush of PRESETS) {
    assert.equal(wholeWidth(targetWidth(0, brush), brush), MIN_PEN_WIDTH);
    assert.equal(targetWidth(FULL_PRESSURE, brush), brush);
    assert.equal(targetWidth(1, brush), brush);
    assert.equal(targetWidth(7, brush), brush);
    assert.equal(targetWidth(Number.NaN, brush), Math.min(brush, MIN_PEN_WIDTH));
    let last = 0;
    for (let step = 0; step <= 100; step += 1) {
      const width = targetWidth(step / 100, brush);
      assert.ok(width >= last && width >= MIN_PEN_WIDTH && width <= brush);
      last = width;
    }
  }
  assert.equal(targetWidth(0.3, 2), 2, "the smallest brush has nowhere to go");
  assert.ok(targetWidth(FULL_PRESSURE * 0.75, 32) < 32, "but not from three quarters of the way there");
});

test("pressure moves the width by ratio: equal shares multiply it by equal amounts", () => {
  // Half the way up the (lifted) pressure scale is the geometric middle of
  // the brush's range - 8 px of 2..32 - not the arithmetic one, 17.
  const half = FULL_PRESSURE * 0.5 ** (1 / 0.8);
  assert.ok(Math.abs(targetWidth(half, 32) - 8) < 1e-9);
  // So the fine end is not a sliver: a fifth of the sensor's range is spent under 6 px.
  assert.ok(targetWidth(0.2, 32) < 6);
});

test("a keyframe's width is whole pixels inside the brush's range", () => {
  assert.equal(wholeWidth(1.2, 32), 2);
  assert.equal(wholeWidth(17.5, 32), 18);
  assert.equal(wholeWidth(40, 32), 32);
  assert.equal(wholeWidth(3.4, 2), 2);
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


// --- which widths are sent ----------------------------------------------------------

/** Keyframes for a width curve sampled every `step` pixels of path. */
function keyframes(curve, step = 3) {
  const thinner = createWidthThinner({ at: 0, width: curve[0] });
  const keys = [{ at: 0, width: curve[0] }];
  let previous = null;
  curve.slice(1).forEach((width, index) => {
    const sample = { at: (index + 1) * step, width };
    if (thinner.push(sample) && previous) keys.push(previous);
    previous = sample;
  });
  keys.push(previous);
  return keys;
}

function rampAt(keys, at) {
  const next = keys.findIndex((key) => key.at >= at);
  if (next <= 0) return keys[Math.max(0, next)].width;
  const [a, b] = [keys[next - 1], keys[next]];
  return a.width + (b.width - a.width) * ((at - a.at) / (b.at - a.at));
}

test("a swell and a taper are a few keyframes, and no sample is further from their ramps than the tolerance", () => {
  // Lands, leans in over sixty samples, holds, eases off: the shape of a stroke.
  const curve = [];
  for (let i = 0; i <= 60; i += 1) curve.push(2 + 30 * (0.5 - 0.5 * Math.cos((i / 60) * Math.PI)));
  for (let i = 0; i < 80; i += 1) curve.push(32);
  for (let i = 0; i <= 60; i += 1) curve.push(32 - 30 * (0.5 - 0.5 * Math.cos((i / 60) * Math.PI)));
  const keys = keyframes(curve);
  assert.ok(keys.length <= 16, `${keys.length} keyframes for ${curve.length} samples`);
  curve.forEach((width, index) => {
    const error = Math.abs(width - rampAt(keys, index * 3));
    assert.ok(error <= widthTolerance(width) + 1e-9, `sample ${index}: ${width} drawn ${rampAt(keys, index * 3)}`);
  });
});

test("a steady hand sends nothing, however its sensor wobbles inside the tolerance", () => {
  const curve = Array.from({ length: 300 }, (_, i) => 20 + 1.4 * Math.sin(i * 1.7));
  assert.equal(keyframes(curve).length, 2, "the start and the end");
  assert.equal(widthTolerance(20), 3);
  assert.equal(widthTolerance(3), WIDTH_TOLERANCE_PX, "a pixel matters on a fine line");
});

test("a keyframe lands on a kept point: the point thinner gives up its pending sample when asked", () => {
  // A ruler-straight line keeps only its ends - unless a keyframe needs a point in between.
  const line = Array.from({ length: 41 }, (_, i) => ({ x: 0.1 + i / 200, y: 0.5 }));
  const thinner = createPointThinner(line[0]);
  const kept = [line[0]];
  line.slice(1).forEach((point, index) => {
    if (index + 1 === 21) {
      const forced = thinner.flush();
      forced[0].key = 9;
      kept.push(...forced);
    }
    kept.push(...thinner.push(point));
  });
  kept.push(...thinner.end());
  assert.deepEqual(kept.map((point) => Math.round((point.x - 0.1) * 200)), [0, 20, 40]);
  assert.deepEqual(kept.map((point) => point.key), [undefined, 9, undefined]);
});

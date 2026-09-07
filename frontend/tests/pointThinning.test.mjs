import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  THINNING_TOLERANCE_PX,
  createPointThinner,
  maxThinningErrorPx,
} from "../src/lib/pointThinning.ts";
import { decodeLiveDrawing } from "../src/lib/liveDrawing.ts";
import { CANVAS_HEIGHT, CANVAS_WIDTH } from "../src/lib/canvasHistory.ts";

// Canvas-pixel helpers: the thinner works in normalized coordinates.
const px = (x, y) => ({ x: x / CANVAS_WIDTH, y: y / CANVAS_HEIGHT });
const inPx = (p) => [p.x * CANVAS_WIDTH, p.y * CANVAS_HEIGHT];

/** Run a whole stroke through, as the hook does: push every sample, force
the pending one at each flush boundary, keep the last at the end. */
function thinStroke(samples, flushAfter = new Set(), tolerance = THINNING_TOLERANCE_PX) {
  const thinner = createPointThinner(samples[0], tolerance);
  const kept = [samples[0]];
  samples.slice(1).forEach((sample, index) => {
    kept.push(...thinner.push(sample));
    if (flushAfter.has(index + 1)) kept.push(...thinner.flush());
  });
  kept.push(...thinner.end());
  return kept;
}

test("exact duplicates go, at any tolerance", () => {
  const kept = thinStroke([px(10, 10), px(10, 10), px(10, 10), px(20, 10), px(20, 10)], new Set(), 0);
  assert.deepEqual(kept.map(inPx), [[10, 10], [20, 10]]);
});

test("collinear samples go at tolerance zero and pixels are unchanged", () => {
  const kept = thinStroke([px(0, 0), px(1, 1), px(2, 2), px(3, 3), px(4, 4)], new Set(), 0);
  assert.deepEqual(kept.map(inPx), [[0, 0], [4, 4]]);
});

test("a corner is kept exactly where the pen turned", () => {
  const kept = thinStroke([px(0, 0), px(5, 0), px(10, 0), px(10, 5), px(10, 10)]);
  assert.deepEqual(kept.map(inPx), [[0, 0], [10, 0], [10, 10]]);
});

test("a reversal along the same line keeps its turning point", () => {
  // Out to 20 and back to 0: the far point is far from the segment 0->0.
  const kept = thinStroke([px(0, 0), px(10, 0), px(20, 0), px(10, 0), px(0.25, 0)]);
  assert.deepEqual(kept.map(inPx), [[0, 0], [20, 0], [0.25, 0]]);
});

test("a dot is one sample, and a stroke always keeps its last sample", () => {
  assert.deepEqual(thinStroke([px(3, 3)]).map(inPx), [[3, 3]]);
  const kept = thinStroke([px(0, 0), px(1, 0), px(2, 0), px(3, 0.5)]);
  assert.deepEqual(kept.map(inPx).at(-1), [3, 0.5]);
});

test("a flush forces the pending sample out, and the bound still holds", () => {
  const samples = [px(0, 0), px(1, 0), px(2, 0), px(3, 0), px(4, 0), px(5, 0)];
  const kept = thinStroke(samples, new Set([2, 4]));
  assert.deepEqual(kept.map(inPx), [[0, 0], [2, 0], [4, 0], [5, 0]]);
  assert.equal(maxThinningErrorPx(samples, kept), 0);
});

test("the preview knows the anchor and the pending sample", () => {
  const thinner = createPointThinner(px(0, 0));
  assert.equal(thinner.pending(), null);
  thinner.push(px(1, 0));
  assert.deepEqual(inPx(thinner.pending()), [1, 0]);
  assert.deepEqual(inPx(thinner.anchor()), [0, 0]);
  thinner.push(px(2, 0));
  thinner.push(px(2, 5)); // corner: (2,0) is kept
  assert.deepEqual(inPx(thinner.anchor()), [2, 0]);
  assert.deepEqual(inPx(thinner.pending()), [2, 5]);
});

test("the error bound is a whole-stroke bound: a slow arc cannot drift past it", () => {
  // Every consecutive pair is within tolerance of the previous line, which
  // is where a one-sample lookahead accumulates error; the bound must hold
  // against the segment finally sent.
  const samples = [];
  for (let i = 0; i <= 200; i++) {
    const angle = (i / 200) * Math.PI;
    samples.push(px(100 + 60 * Math.cos(angle), 100 + 60 * Math.sin(angle)));
  }
  const kept = thinStroke(samples);
  assert.ok(kept.length < samples.length / 2, `kept ${kept.length}`);
  assert.ok(maxThinningErrorPx(samples, kept) <= THINNING_TOLERANCE_PX + 1e-9);
});

// The recorded traces: the same replay `benchmarks/point_thinning.py` does,
// so the two implementations must agree on the count, and the bound must
// hold over every real hand stroke.
const EXPECTED_KEPT = { "hand-long.json": 1484, "hand-short.json": 531, "scripted-120hz.json": 351 };

for (const [name, expectedKept] of Object.entries(EXPECTED_KEPT)) {
  test(`recorded trace ${name}: the bound holds and the count matches the benchmark`, async () => {
    const trace = JSON.parse(await readFile(new URL(`../../fixtures/live_strokes/${name}`, import.meta.url)));
    let kept = 0;
    let original = 0;
    for (const stroke of trace.strokes) {
      const samples = [];
      const flushAfter = new Set();
      for (const frame of stroke.frames) {
        if (typeof frame.frame !== "string") continue;
        const packet = decodeLiveDrawing(new Uint8Array(Buffer.from(frame.frame, "base64")));
        if (packet?.event === "draw_start") samples.push({ x: packet.payload.x, y: packet.payload.y });
        else if (packet?.event === "draw_move") {
          packet.payload.points.forEach((p) => samples.push({ x: p.x, y: p.y }));
          flushAfter.add(samples.length - 1);
        }
      }
      if (samples.length === 0) continue;
      const thinned = thinStroke(samples, flushAfter);
      assert.ok(maxThinningErrorPx(samples, thinned) <= THINNING_TOLERANCE_PX + 1e-9, "bound");
      assert.deepEqual(thinned[0], samples[0]);
      assert.deepEqual(thinned.at(-1), samples.at(-1));
      kept += thinned.length;
      original += samples.length;
    }
    assert.equal(kept, expectedKept);
    assert.ok(kept < original);
  });
}

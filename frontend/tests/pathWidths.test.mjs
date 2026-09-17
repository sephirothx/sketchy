import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  CANVAS_HEIGHT,
  CANVAS_WIDTH,
  ClientCanvasHistory,
  calculateCanvasHistoryHash,
  canvasPointCount,
  decodeCanvasHistory,
} from "../src/lib/canvasHistory.ts";
import { pointCount, repackDrawFrames } from "../src/lib/canvasRecovery.ts";
import { applyCanvasAction, applyCanvasStrokeSpan } from "../src/lib/canvasRenderer.ts";
import { rasterizePath } from "../src/lib/canvasPixels.ts";
import {
  decodeLiveDrawing,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
} from "../src/lib/liveDrawing.ts";
import { expandWidthRamps, finalWidth, rampedBatch, segmentWidths, widthRuns } from "../src/lib/pathWidths.ts";
import { PenStroke } from "../src/lib/penStroke.ts";
import { QUIET_FRAME_SHARE, createWidthThinner, widthTolerance } from "../src/lib/widthKeyframes.ts";
import { replayPlan, replayStroke, stepReplay } from "../src/lib/replay.ts";
import { createStrokePlayback } from "../src/lib/strokePlayback.ts";

const fixtures = JSON.parse(await readFile(
  new URL("../../fixtures/canvas_protocol_v1.json", import.meta.url),
  "utf8",
));

function bytesFromHex(hex) {
  return Uint8Array.from(hex.match(/../g) ?? [], (byte) => Number.parseInt(byte, 16));
}

const PREVIOUS = { x: 0.5, y: 0.5 };
const THREE = [{ x: 0.5, y: 0.51 }, { x: 0.505, y: 0.515 }, { x: 0.51, y: 0.52 }];

// --- the codec ------------------------------------------------------------------

test("a width change costs two bytes in a frame already being sent", () => {
  const plain = encodePathPoints({ points: THREE, previous: PREVIOUS });
  const changed = encodePathPoints({ points: THREE, previous: PREVIOUS, widths: [[1, 5]] });
  assert.equal(changed.byteLength, plain.byteLength + 2);
  assert.deepEqual(Array.from(changed.slice(3, 5)), [0x81, 5]);
  const packet = decodeLiveDrawing(changed, PREVIOUS);
  assert.deepEqual(packet.payload.widths, [[1, 5]]);
  assert.deepEqual(packet.payload.points, decodeLiveDrawing(plain, PREVIOUS).payload.points);
});

test("a path that never changes width is byte for byte what it was", () => {
  for (const payload of [
    { points: THREE },
    { points: THREE, previous: PREVIOUS },
    { points: THREE, previous: PREVIOUS, ends: true },
  ]) {
    assert.deepEqual(encodePathPoints({ ...payload, widths: [] }), encodePathPoints(payload));
    assert.equal("widths" in decodeLiveDrawing(encodePathPoints(payload), PREVIOUS).payload, false);
  }
});

test("without a predecessor a width change rides the delta form, never the absolute one", () => {
  const far = [{ x: 0.1, y: 0.1 }, { x: 0.9, y: 0.9 }, { x: 0.1, y: 0.9 }];
  assert.equal(encodePathPoints({ points: far })[0] & 0x0f, 1);
  const frame = encodePathPoints({ points: far, widths: [[1, 3]] });
  assert.equal(frame[0] & 0x0f, 6);
  assert.deepEqual(decodeLiveDrawing(frame).payload.widths, [[1, 3]]);
  assert.throws(() => encodePathPoints({ points: far, widths: [[0, 3]] }));
});

test("a step of -127 escapes now that the byte is the marker", () => {
  const step = 127 / (CANVAS_WIDTH * 4);
  const frame = encodePathPoints({
    points: [{ x: 0.5, y: 0.5 }, { x: 0.5 - step, y: 0.5 }],
    previous: { x: 0.5, y: 0.49 },
  });
  assert.equal(frame[3], 0x80);
  assert.equal("widths" in decodeLiveDrawing(frame, { x: 0.5, y: 0.49 }).payload, false);
});

test("the encoder refuses width changes it cannot place", () => {
  for (const widths of [[[3, 5]], [[-1, 5]], [[1, 5], [1, 6]], [[2, 5], [1, 6]], [[1, 0]], [[1, 65]], [[1, 5.5]], [[0.5, 5]]]) {
    assert.throws(() => encodePathPoints({ points: THREE, previous: PREVIOUS, widths }), JSON.stringify(widths));
  }
});

test("malformed width changes are refused", () => {
  for (const bytes of [
    [0x17, 0x81],
    [0x17, 0x81, 5],
    [0x17, 1, 1, 0x81, 5],
    [0x17, 0x81, 5, 0x81, 6, 1, 1],
    [0x17, 0x81, 0, 1, 1],
    [0x17, 0x81, 65, 1, 1],
    [0x18, 0x81, 5],
    [0x16, 0, 0, 0, 0, 0x81, 5],
  ]) {
    assert.equal(decodeLiveDrawing(Uint8Array.from(bytes), PREVIOUS), null, JSON.stringify(bytes));
  }
});

test("no frame may carry the coordinate the history reads as a marker", () => {
  const floor = [0x00, 0x80];
  for (const bytes of [
    [0x10, 0, 0, 0, 1, ...floor, 0, 0],
    [0x11, ...floor, 0, 0],
    [0x16, ...floor, 0, 0],
    [0x17, 0x80, ...floor, 0, 0],
    [0x13, 0, 0, 0, 0, 1, ...floor, 0, 0, 0, 0, 0, 0],
  ]) {
    assert.equal(decodeLiveDrawing(Uint8Array.from(bytes), PREVIOUS), null, JSON.stringify(bytes));
  }
});

// --- the history ----------------------------------------------------------------

const PEN_FRAMES = () => {
  const start = { x: 0.25, y: 0.25 };
  const first = [{ x: 0.26, y: 0.25 }, { x: 0.27, y: 0.26 }, { x: 0.28, y: 0.26 }];
  return [
    encodePathStart({ ...start, color: "#102030", width: 6 }),
    encodePathPoints({ points: first, widths: [[0, 4], [2, 5]], previous: start }),
    encodePathPoints({ points: [{ x: 0.29, y: 0.27 }], widths: [[0, 6]], previous: first[2] }),
    encodePathEnd(),
    encodePathStart({ x: 0.5, y: 0.5, color: "#000000", width: 2 }),
    encodePathPoints({ points: [{ x: 0.6, y: 0.5 }], previous: { x: 0.5, y: 0.5 } }),
    encodePathEnd(),
  ];
};

function replayInto(frames) {
  const history = new ClientCanvasHistory();
  history.replace([], 0, 1, 0, 0);
  for (const frame of frames) assert.ok(history.apply(decodeLiveDrawing(frame, history.openPathLastPoint())));
  return history;
}

test("the client's history of a pen path hashes to what the server's does", () => {
  // The fixture's history and hash were written by the Python recorder from
  // these same actions: the two ends agree on where a marker sits in a record.
  const golden = fixtures.histories.find((entry) => entry.name === "width-runs");
  const history = replayInto(PEN_FRAMES());
  assert.equal(history.historyHash, golden.hash);
  assert.deepEqual(history.actions[0].widths, [[1, 4], [3, 5], [4, 6]]);
  assert.equal("widths" in history.actions[1], false);
  // The decoded points are exact quarter-pixels and the live ones carry float
  // dust, so the two are compared by what is hashed and by where the widths sit.
  const decoded = decodeCanvasHistory(bytesFromHex(golden.binary));
  assert.deepEqual(decoded.map((action) => action.widths), history.actions.map((action) => action.widths));
  assert.equal(calculateCanvasHistoryHash(decoded), golden.hash);
});

test("a width change is charged as a point", () => {
  assert.equal(canvasPointCount(replayInto(PEN_FRAMES()).actions), 5 + 3 + 2);
  assert.equal(pointCount(PEN_FRAMES().slice(0, 4)), 4 + 3);
});

test("a history with a misplaced or invalid width marker is refused", () => {
  const frame = (entries) => {
    const record = [0, 0, 0, 0, 6, ...entries.flatMap(([x, y]) => [x & 0xff, (x >> 8) & 0xff, y & 0xff, (y >> 8) & 0xff])];
    const header = [0x53, 0x4b, 0x43, 0x48, 1, 1, 0, 0, 0, 0, 0, record.length, 0, 0, 0];
    return Uint8Array.from([...header, ...record]);
  };
  const MARK = -0x8000;
  assert.notEqual(decodeCanvasHistory(frame([[0, 0], [MARK, 5], [4, 4]])), null);
  for (const entries of [
    [[MARK, 5], [0, 0]],
    [[0, 0], [MARK, 5]],
    [[0, 0], [MARK, 5], [MARK, 6], [4, 4]],
    [[0, 0], [MARK, 0], [4, 4]],
    [[0, 0], [MARK, 65], [4, 4]],
  ]) {
    assert.equal(decodeCanvasHistory(frame(entries)), null, JSON.stringify(entries));
  }
});

test("a replayed pen path repacks to the same history, width changes included", () => {
  const points = Array.from({ length: 600 }, (_, i) => ({ x: 0.1 + i / 1000, y: 0.1 + (i % 7) / 500 }));
  const frames = [encodePathStart({ x: 0.1, y: 0.1, color: "#000000", width: 12 })];
  let previous = { x: 0.1, y: 0.1 };
  for (let index = 0; index < points.length; index += 1) {
    // A change on every fifth point - including 255 and 256, either side of
    // the repack's chunk boundary, and 0, the first point after the start.
    const widths = index % 5 === 0 || index === 256 ? [[0, 3 + (index % 9)]] : undefined;
    frames.push(encodePathPoints({ points: [points[index]], previous, widths }));
    previous = points[index];
  }
  frames.push(encodePathEnd());

  const repacked = repackDrawFrames(frames);
  assert.equal(repacked.length, 1 + 3 + 1);
  assert.equal(replayInto(repacked).historyHash, replayInto(frames).historyHash);
  assert.equal(replayInto(repacked).actions[0].widths.length, 121);
});

// --- the raster -----------------------------------------------------------------

test("runs share the point they meet at, and a change on the first segment keeps the opening dot", () => {
  assert.deepEqual(widthRuns(5, 6, undefined), [{ from: 0, to: 4, width: 6 }]);
  assert.deepEqual(widthRuns(1, 6, undefined), [{ from: 0, to: 0, width: 6 }]);
  assert.deepEqual(widthRuns(5, 6, [[2, 4], [4, 9]]), [
    { from: 0, to: 1, width: 6 },
    { from: 1, to: 3, width: 4 },
    { from: 3, to: 4, width: 9 },
  ]);
  assert.deepEqual(widthRuns(3, 6, [[1, 2]]), [
    { from: 0, to: 0, width: 6 },
    { from: 0, to: 2, width: 2 },
  ]);
  assert.deepEqual(segmentWidths(4, 6, [[1, 4], [3, 9]]), [6, 4, 4, 9]);
  assert.equal(finalWidth(6, [[1, 4], [3, 9]]), 9);
  assert.equal(finalWidth(6, undefined), 6);
});

const PEN_ACTION = {
  kind: "path",
  color: "#000000",
  width: 14,
  points: [
    { x: 40.5, y: 60 }, { x: 90.25, y: 70 }, { x: 140, y: 140.75 }, { x: 200, y: 90 },
    { x: 260, y: 95 }, { x: 300.5, y: 180 }, { x: 380, y: 200 },
  ],
  widths: [[1, 3], [3, 9], [4, 20], [6, 2]],
};

function blank() {
  return new Uint8ClampedArray(CANVAS_WIDTH * CANVAS_HEIGHT * 4).fill(255);
}

test("a viewer painting a pen path live, in arbitrary parts, ends on the raster of replaying it whole (R-DRAW-01)", () => {
  const whole = blank();
  applyCanvasAction(whole, PEN_ACTION);

  // As Canvas.tsx does: the opening dot, then batches played out over time.
  const live = blank();
  const paint = (points, style) => rasterizePath(live, CANVAS_WIDTH, CANVAS_HEIGHT, points, style.radius, style.color, false);
  const play = createStrokePlayback({ intervalMs: () => 100, paint });
  const color = [0, 0, 0, 255];
  const [first, ...rest] = PEN_ACTION.points;
  paint([first, first], { radius: PEN_ACTION.width / 2, color });
  let width = PEN_ACTION.width;
  let last = first;
  let offset = 1;
  // Frames as the drawer's client cuts them: a keyframe of a new width always
  // has the one it ramps from in its own frame or ending the frame before.
  for (const size of [1, 2, 1, 2]) {
    const batch = rest.slice(offset - 1, offset - 1 + size);
    const widths = PEN_ACTION.widths
      .filter(([index]) => index >= offset && index < offset + size)
      .map(([index, to]) => [index - offset, to]);
    const ramped = rampedBatch(last, batch, width, widths);
    play.enqueueSegments(last, ramped.points, { radius: width / 2, color }, 0, ramped.segmentWidths.map((value) => value / 2));
    width = ramped.finalWidth;
    last = batch.at(-1);
    offset += size;
  }
  for (const at of [7, 13, 29, 51, 99, 100, 147, 166, 190, 233, 260, 300]) play.advance(at);
  assert.equal(play.pending(), false);
  assert.deepEqual(live, whole);
});

test("a replay growing a pen path a fraction of a segment at a time ends on the same raster", () => {
  const whole = blank();
  applyCanvasAction(whole, PEN_ACTION);

  const grown = blank();
  const actions = [PEN_ACTION];
  const plan = replayPlan(actions);
  let position = { action: 0, point: 0 };
  const painter = {
    span: (stroke, from, to) => applyCanvasStrokeSpan(grown, stroke, from, to),
    whole: (action) => applyCanvasAction(grown, action),
  };
  while (position.action < actions.length) {
    position = stepReplay(actions, plan, position, 0.37, painter).position;
  }
  assert.deepEqual(grown, whole);
  // The stroke the replay grows is the ramped one, as every painter's is.
  const ramped = expandWidthRamps(PEN_ACTION.points, PEN_ACTION.width, PEN_ACTION.widths);
  assert.deepEqual(replayStroke(PEN_ACTION).widths, ramped.widths);
  assert.deepEqual(replayStroke(PEN_ACTION).points, ramped.points);
});

test("the runs are really painted at different widths", () => {
  const pixels = blank();
  applyCanvasAction(pixels, PEN_ACTION);
  const inked = (x, y) => pixels[(y * CANVAS_WIDTH + x) * 4] === 0;
  // Between points 1 and 2 the path is 3 wide: ink on the line, none 4 px off
  // it. Between points 4 and 5 it has reached 20: ink 8 px off it.
  assert.equal(inked(115, 105), true);
  assert.equal(inked(120, 102), false);
  assert.equal(inked(288, 140), true);
});

// --- ramps ------------------------------------------------------------------------

function thickness(pixels, x) {
  let ink = 0;
  for (let y = 0; y < CANVAS_HEIGHT; y += 1) if (pixels[(y * CANVAS_WIDTH + x) * 4] === 0) ink += 1;
  return ink;
}

test("between two keyframes the width is a ramp along the path, never a shoulder", () => {
  // The widest change there is, 2 px to 32, with the keyframes 140 px apart
  // and two kept points between them.
  const action = {
    kind: "path",
    color: "#000000",
    width: 2,
    points: [{ x: 100, y: 300 }, { x: 200, y: 300 }, { x: 240, y: 300 }, { x: 300, y: 300 }, { x: 340, y: 300 }, { x: 500, y: 300 }],
    widths: [[1, 2], [4, 32]],
  };
  const pixels = blank();
  applyCanvasAction(pixels, action);
  assert.equal(thickness(pixels, 150), 2, "flat up to the keyframe the ramp starts from");
  assert.equal(thickness(pixels, 420), 32, "and flat after the one it ends on");
  let steepest = 0;
  for (let x = 120; x < 480; x += 1) {
    steepest = Math.max(steepest, Math.abs(thickness(pixels, x + 1) - thickness(pixels, x)));
    if (x >= 200 && x < 340) assert.ok(thickness(pixels, x + 1) >= thickness(pixels, x), `a bulge at ${x}`);
  }
  // Recorded as it is, the line would gain thirty pixels between two columns.
  assert.ok(steepest <= 2, `steepest column-to-column change: ${steepest}`);
  // A straight line in width over length: half way along is half way between.
  assert.ok(Math.abs(thickness(pixels, 270) - 17) <= 2, `${thickness(pixels, 270)} px at the middle`);
});

test("a ramp is derived, not recorded: a pixel a piece, equal shares of the path between the keyframes", () => {
  const ramped = expandWidthRamps(
    [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 20, y: 0 }, { x: 30, y: 0 }],
    6,
    [[1, 6], [3, 9]],
  );
  // 6, 7, 8, 9 over the twenty pixels from the hold to the keyframe, across
  // the kept point between them.
  assert.deepEqual(ramped.points.map((point) => point.x), [0, 10, 15, 20, 20, 25, 30]);
  // (The second cut falls on the kept point itself: a piece of no length there.)
  assert.deepEqual(ramped.widths, [[3, 7], [4, 8], [6, 9]]);
  // Narrowing, from the path's start; a keyframe at the width it already has; none at all.
  assert.deepEqual(expandWidthRamps([{ x: 0, y: 0 }, { x: 9, y: 0 }], 5, [[1, 3]]).widths, [[2, 4], [3, 3]]);
  assert.equal(expandWidthRamps([{ x: 0, y: 0 }, { x: 8, y: 0 }], 5, [[1, 5]]).widths, undefined);
  const plain = [{ x: 0, y: 0 }, { x: 8, y: 0 }];
  assert.equal(expandWidthRamps(plain, 5, undefined).points, plain);
});

test("cut points land on the quarter-pixel grid, whatever float dust the ends carry", () => {
  const clean = expandWidthRamps([{ x: 224, y: 156 }, { x: 232, y: 162 }], 2, [[1, 7]]);
  const dusty = expandWidthRamps([{ x: 224.00000000000003, y: 156 }, { x: 231.99999999999997, y: 162 }], 2, [[1, 7]]);
  assert.deepEqual(dusty.points.slice(1, -1), clean.points.slice(1, -1));
  for (const point of clean.points) assert.equal(point.x * 4, Math.round(point.x * 4));
});

// --- the promise a live viewer relies on ------------------------------------------

/** A pen stroke run through the client's own bookkeeping, a frame every
`flushEvery` samples: what the drawer painted, and the frames it sent. */
function drawWithPen(samples, flushEvery, brush) {
  const range = { floor: 2, brush };
  const start = samples[0];
  const startWidth = Math.round(start.width);
  const stroke = new PenStroke(start, startWidth);
  const thinner = createWidthThinner({ at: 0, width: startWidth }, range);
  const drawn = [];
  const frames = [];
  let frame = [];
  let arc = 0;
  let before = null;
  const paint = (runs) => drawn.push(...runs);
  const send = (final) => {
    if (frame.length === 0) return;
    const target = samples[Math.min(samples.length - 1, sent + frame.length)].width;
    const moved = final || Math.abs(target - stroke.width) > widthTolerance(target, range) * QUIET_FRAME_SHARE;
    const { runs, placed } = stroke.flush(moved ? Math.round(target) : stroke.width);
    paint(runs);
    if (placed) thinner.anchorAt({ at: arc, width: stroke.width });
    frames.push({ points: frame, widths: stroke.takeFrame() });
    stroke.frameSent();
    sent += frame.length;
    frame = [];
  };
  let sent = 0;
  for (let index = 1; index < samples.length; index += 1) {
    const sample = samples[index];
    arc += Math.hypot(sample.x - samples[index - 1].x, sample.y - samples[index - 1].y);
    const isKey = thinner.push({ at: arc, width: sample.width }) && before;
    if (isKey) {
      const keyed = stroke.keyLast(Math.round(before.width));
      if (keyed) {
        paint(keyed.runs);
        if (keyed.held) thinner.anchorAt({ at: before.at, width: stroke.width });
      }
    }
    before = { at: arc, width: sample.width };
    paint(stroke.accept({ x: sample.x, y: sample.y }).runs);
    frame.push({ x: sample.x, y: sample.y });
    if (index % flushEvery === 0) send(false);
  }
  send(true);
  return { startWidth, drawn, frames };
}

function penSamples(seed, count, brush) {
  let state = seed;
  const random = () => ((state = (state * 1664525 + 1013904223) % 4294967296) / 4294967296);
  const samples = [];
  let pressure = 0.02;
  let goal = random();
  for (let index = 0; index < count; index += 1) {
    // A hand: heads for a pressure, holds a while, picks another.
    if (index % 25 === 0) goal = random() < 0.3 ? pressure : random();
    pressure += (goal - pressure) * 0.15 + (random() - 0.5) * 0.02;
    const lifted = Math.min(1, (count - index) / 10);
    const share = Math.min(1, Math.max(0, pressure * lifted));
    samples.push({
      x: Math.round((60 + index * 2.25) * 4) / 4,
      y: Math.round((300 + 80 * Math.sin(index / 18)) * 4) / 4,
      width: 2 * (brush / 2) ** share,
    });
  }
  return samples;
}

test("the drawer, a viewer painting frame by frame, and a replay of the whole path are one raster", () => {
  for (const [seed, flushEvery, brush] of [[1, 5, 32], [2, 9, 32], [3, 3, 12], [4, 7, 6], [5, 1, 32], [6, 40, 24]]) {
    const samples = penSamples(seed, 280, brush);
    const { startWidth, drawn, frames } = drawWithPen(samples, flushEvery, brush);
    const color = [0, 0, 0, 255];
    const dot = (pixels) => rasterizePath(pixels, CANVAS_WIDTH, CANVAS_HEIGHT, [samples[0], samples[0]], startWidth / 2, color, false);

    const drawer = blank();
    dot(drawer);
    for (const run of drawn) rasterizePath(drawer, CANVAS_WIDTH, CANVAS_HEIGHT, run.points, run.width / 2, color, false);

    // As Canvas.tsx does: each frame ramped from where the path ends, at the
    // last keyframe's width, with no knowledge of the frames to come.
    const viewer = blank();
    dot(viewer);
    let last = samples[0];
    let width = startWidth;
    const points = [samples[0]];
    const widths = [];
    for (const frame of frames) {
      const batch = rampedBatch(last, frame.points, width, frame.widths);
      let from = last;
      batch.points.forEach((point, index) => {
        rasterizePath(viewer, CANVAS_WIDTH, CANVAS_HEIGHT, [from, point], batch.segmentWidths[index] / 2, color, false);
        from = point;
      });
      for (const [index, to] of frame.widths) widths.push([points.length + index, to]);
      points.push(...frame.points);
      width = batch.finalWidth;
      last = frame.points.at(-1);
    }

    const replay = blank();
    applyCanvasAction(replay, { kind: "path", color: "#000000", width: startWidth, points, widths });

    const label = `seed ${seed}, a frame every ${flushEvery}, brush ${brush}`;
    assert.ok(widths.length > 0, `${label}: the stroke has keyframes`);
    assert.deepEqual(viewer, replay, `${label}: a viewer's frames against the whole path`);
    assert.deepEqual(drawer, replay, `${label}: the drawer's own ink against the whole path`);
    // And the keyframes are sparse: that is the point of them.
    assert.ok(widths.length < points.length / 2, `${label}: ${widths.length} keyframes for ${points.length} points`);
  }
});

test("a change after a quiet stretch is given a hold to ramp from, in its own frame", () => {
  const stroke = new PenStroke({ x: 0, y: 0 }, 6);
  // Two frames with nothing to say...
  for (const x of [10, 20]) stroke.accept({ x, y: 0 });
  stroke.flush(6);
  assert.deepEqual(stroke.takeFrame(), []);
  for (const x of [30, 40]) stroke.accept({ x, y: 0 });
  stroke.flush(6);
  assert.deepEqual(stroke.takeFrame(), []);
  // ...then a keyframe of another width, three points into the next one.
  stroke.accept({ x: 50, y: 0 });
  stroke.accept({ x: 60, y: 0 });
  assert.equal(stroke.accept({ x: 70, y: 0 }, 12).held, false);
  assert.deepEqual(stroke.takeFrame(), [[0, 6], [2, 12]], "a hold at the old width, then the keyframe");

  // The keyframe ended the frame, so the next change may ramp from it as it is.
  stroke.accept({ x: 80, y: 0 }, 20);
  assert.deepEqual(stroke.takeFrame(), [[0, 20]]);

  // On a frame's very first point there is nothing before it to hold: it
  // becomes the hold, and the caller is told the width was not placed.
  stroke.accept({ x: 90, y: 0 });
  stroke.flush(20);
  stroke.takeFrame();
  assert.equal(stroke.accept({ x: 100, y: 0 }, 9).held, true);
  assert.deepEqual(stroke.takeFrame(), [[0, 20]]);
});

test("a frame that goes out part way through a change says how far it got", () => {
  const stroke = new PenStroke({ x: 0, y: 0 }, 4);
  stroke.accept({ x: 10, y: 0 });
  stroke.accept({ x: 20, y: 0 });
  const { runs, placed } = stroke.flush(9);
  assert.equal(placed, true);
  assert.deepEqual(stroke.takeFrame(), [[1, 9]]);
  stroke.frameSent();
  // And what the drawer painted for it is the ramp, not a step.
  assert.deepEqual(runs.map((run) => run.width), [4, 5, 6, 7, 8, 9]);
  // A refused frame leaves the server where it was: the next change ramps from a hold.
  stroke.accept({ x: 30, y: 0 });
  stroke.accept({ x: 40, y: 0 }, 15);
  stroke.takeFrame();
  stroke.frameRefused();
  assert.equal(stroke.width, 9);
});

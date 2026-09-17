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
import { finalWidth, segmentWidths, widthRuns } from "../src/lib/pathWidths.ts";
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
  for (const size of [2, 1, 3]) {
    const batch = rest.slice(offset - 1, offset - 1 + size);
    const widths = PEN_ACTION.widths
      .filter(([index]) => index >= offset && index < offset + size)
      .map(([index, to]) => [index - offset, to]);
    const each = segmentWidths(batch.length, width, widths);
    play.enqueueSegments(last, batch, { radius: width / 2, color }, 0, each.map((value) => value / 2));
    width = each.at(-1);
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
  assert.deepEqual(replayStroke(PEN_ACTION).widths, PEN_ACTION.widths);
});

test("the runs are really painted at different widths", () => {
  const pixels = blank();
  applyCanvasAction(pixels, PEN_ACTION);
  const inked = (x, y) => pixels[(y * CANVAS_WIDTH + x) * 4] === 0;
  // Segment 0->1 is 3 wide: ink on the line, none 4 px off it. Segment 3->4
  // is 20 wide: ink 8 px off it.
  assert.equal(inked(65, 65), true);
  assert.equal(inked(65, 70), false);
  assert.equal(inked(230, 100), true);
});

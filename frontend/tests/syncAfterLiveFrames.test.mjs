/* #1043: a full `sync_strokes` that lands after a viewer already painted live
frames of an open stroke. The reply bytes and the commit are what the server
produces (`CanvasSession`, probed with the backend) for: draw_start + one batch
recorded, then the snapshot, then one more batch and the end - pinned on the
server side by `test_a_full_sync_taken_mid_stroke_carries_the_open_path` in
`backend/tests/test_canvas_session.py`. The glue mirrors `useCanvasProtocol`'s
`onDraw` / `onSyncStrokes` for a viewer. */
import assert from "node:assert/strict";
import test from "node:test";

import {
  CANVAS_HEIGHT as H,
  CANVAS_WIDTH as W,
  ClientCanvasHistory,
  decodeCanvasHistory,
} from "../src/lib/canvasHistory.ts";
import { renderCanvasActions } from "../src/lib/canvasRenderer.ts";
import { createCanvasSurface } from "../src/lib/canvasSurface.ts";
import {
  decodeLiveDrawing,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
  endsPath,
} from "../src/lib/liveDrawing.ts";
import { createProtocolRenderer } from "../src/lib/protocolRenderer.ts";

// Server truth, from backend/app/canvas_session.py (generation 3).
const REPLY_OPEN_PATH = "534b4348010100000000001100000000e03131084001f0008002f000c003e001";
const REPLY = { revision: 1, generation: 3, sequence: 0, hash: 2229650042 };
const COMMIT = [3, 1, 1, 3966873977];
const FINAL = "534b4348010100000000001500000000e03131084001f0008002f000c003e0010005d002";

let now = 0;
let frames = [];
Object.defineProperty(globalThis, "performance", { value: { now: () => now }, configurable: true });
globalThis.window = {
  requestAnimationFrame: (callback) => frames.push(callback),
  cancelAnimationFrame: () => { frames = []; },
};
function flushAnimation() {
  now += 10_000;
  while (frames.length) frames.shift()();
}

function surface() {
  const screen = new Uint8ClampedArray(W * H * 4);
  const context = {
    createImageData: (width, height) => ({ width, height, data: new Uint8ClampedArray(width * height * 4) }),
    getImageData() { throw new Error("read"); },
    putImageData(image, x, y, dx = 0, dy = 0, dw = image.width, dh = image.height) {
      for (let row = dy; row < dy + dh; row++) {
        const from = (row * image.width + dx) * 4;
        screen.set(image.data.subarray(from, from + dw * 4), ((y + row) * W + x + dx) * 4);
      }
    },
  };
  const result = createCanvasSurface(context);
  result.screen = screen;
  return result;
}

function viewer() {
  const history = new ClientCanvasHistory();
  const view = surface();
  const renderer = createProtocolRenderer({ current: view }, () => 80, null);
  const resyncs = [];
  const onDraw = (payload, commit) => {
    const packet = decodeLiveDrawing(payload, history.openPathLastPoint());
    if (!packet || packet.event === "draw_move_relative") return resyncs.push("undecodable");
    const applied = history.apply(packet);
    renderer.apply(packet);
    const commits = applied && endsPath(packet);
    if (commits !== (commit !== undefined)) return resyncs.push("commit mismatch");
    if (commit !== undefined && !history.confirmAction(commit)) resyncs.push("commit refused");
  };
  const onSyncStrokes = (hex, { revision, generation, sequence, hash }) => {
    const actions = decodeCanvasHistory(Buffer.from(hex, "hex"));
    assert.ok(history.replace(actions, revision, generation, sequence, hash));
    renderer.replay(history.actions);
  };
  return { history, view, onDraw, onSyncStrokes, resyncs };
}

const START = encodePathStart({ x: 0.1, y: 0.1, color: "#e03131", width: 8 });
const FIRST = encodePathPoints({ points: [{ x: 0.2, y: 0.1 }, { x: 0.3, y: 0.2 }] });
const SECOND = encodePathPoints({ points: [{ x: 0.4, y: 0.3 }], previous: { x: 0.3, y: 0.2 } });

test("a full reply after live frames keeps the open stroke, and the stroke finishes on screen", () => {
  const v = viewer();
  v.onDraw(START);
  v.onDraw(FIRST);
  // Nothing has been synced yet: this history has no generation.
  assert.equal(v.history.generation, null);
  v.onSyncStrokes(REPLY_OPEN_PATH, REPLY);
  v.onDraw(SECOND);
  v.onDraw(encodePathEnd(), COMMIT);
  flushAnimation();

  assert.deepEqual(v.resyncs, []);
  assert.equal(v.history.sequence, 1);
  assert.equal(v.history.historyHash, COMMIT[3]);
  assert.deepEqual(v.history.actions, decodeCanvasHistory(Buffer.from(FINAL, "hex")));
  const reference = surface();
  renderCanvasActions(reference, v.history.actions);
  assert.ok(v.view.screen.some((byte, index) => byte !== 255 && index % 4 !== 3), "ink on screen");
  let differing = 0;
  for (let index = 0; index < reference.screen.length; index++) if (v.view.screen[index] !== reference.screen[index]) differing++;
  assert.equal(differing, 0, "viewer pixels match a replay of the final history");
});

test("the issue's premise - a reply that lacks the open stroke - is caught at the commit, not left silent", () => {
  const v = viewer();
  v.onDraw(START);
  v.onDraw(FIRST);
  // A reply cut before the draw_start was recorded: empty canvas, generation 3.
  v.onSyncStrokes("534b434801000000000000", { revision: 0, generation: 3, sequence: 0, hash: 0 });
  v.onDraw(SECOND);
  v.onDraw(encodePathEnd(), COMMIT);
  assert.deepEqual(v.history.actions, []);
  assert.deepEqual(v.resyncs, ["commit mismatch"]);
});

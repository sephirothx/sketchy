import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateCanvasHistoryHash,
  ClientCanvasHistory,
} from "../src/lib/canvasHistory.ts";
import {
  decodeLiveDrawing,
  encodePathEnd,
  encodePathPoints,
  encodePathStart,
} from "../src/lib/liveDrawing.ts";

function replace(history, actions, revision, generation, sequence) {
  return history.replace(
    actions,
    revision,
    generation,
    sequence,
    calculateCanvasHistoryHash(actions),
  );
}

test("a commit from a stale canvas generation is rejected", () => {
  const history = new ClientCanvasHistory();
  assert.equal(replace(history, [], 4, 8, 2), true);

  assert.equal(history.confirmAction([7, 3, 4, 0]), false);
  assert.equal(history.generation, 8);
  assert.equal(history.sequence, 2);
});

test("checkpoint commit payloads may include folded count and PNG", () => {
  const history = new ClientCanvasHistory();
  assert.equal(replace(history, [], 4, 8, 2), true);
  assert.equal(history.confirmAction([8, 3, 4, 0, 1, new Uint8Array()]), true);
  assert.equal(history.sequence, 3);
});

test("authoritative sync rejects a mismatched history hash", () => {
  const history = new ClientCanvasHistory();
  const actions = [{ kind: "clear" }];

  assert.equal(history.replace(actions, 3, 2, 1, 0xdeadbeef), false);
  assert.equal(history.generation, null);
  assert.deepEqual(history.actions, []);
});

test("reconnect sync replaces stale local history and sequence", () => {
  const history = new ClientCanvasHistory();
  assert.equal(replace(history, [{ kind: "clear" }], 3, 4, 1), true);
  const authoritative = [{
    kind: "fill",
    color: "#112233",
    x: 20,
    y: 30,
  }];

  assert.equal(replace(history, authoritative, 12, 9, 7), true);
  assert.equal(history.generation, 9);
  assert.equal(history.sequence, 7);
  assert.deepEqual(history.actions, authoritative);
});

test("pending path frames replay in order after reconnect sync", () => {
  const history = new ClientCanvasHistory();
  assert.equal(replace(history, [], 20, 5, 3), true);
  const pendingFrames = [
    encodePathStart({ x: 0.1, y: 0.2, color: "#abcdef", width: 6 }),
    encodePathPoints({ points: [{ x: 0.3, y: 0.4 }, { x: 0.5, y: 0.6 }] }),
    encodePathEnd(),
  ];

  for (const frame of pendingFrames) {
    const packet = decodeLiveDrawing(frame);
    assert.ok(packet);
    assert.equal(history.apply(packet), true);
  }

  assert.equal(history.revision, 21);
  assert.deepEqual(history.actions, [{
    kind: "path",
    color: "#abcdef",
    width: 6,
    points: [
      { x: 80, y: 120 },
      { x: 240, y: 240 },
      { x: 400, y: 360 },
    ],
  }]);
});

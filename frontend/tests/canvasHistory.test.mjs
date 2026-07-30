import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateCanvasHistoryHash,
  ClientCanvasHistory,
} from "../src/lib/canvasHistory.ts";

function replace(history, actions, revision, sequence = 0, generation = 1) {
  return history.replace(
    actions,
    revision,
    generation,
    sequence,
    calculateCanvasHistoryHash(actions),
  );
}

test("client history groups path batches into one revisioned action", () => {
  const history = new ClientCanvasHistory();
  assert.equal(replace(history, [], 10), true);

  history.apply({
    event: "draw_start",
    payload: { x: 0.1, y: 0.2, color: "#123456", width: 4 },
  });
  history.apply({
    event: "draw_move",
    payload: { points: [{ x: 0.3, y: 0.4 }, { x: 0.5, y: 0.6 }] },
  });
  history.apply({ event: "draw_end", payload: {} });

  assert.equal(history.revision, 11);
  assert.equal(history.actions.length, 1);
  assert.deepEqual(history.actions[0], {
    kind: "path",
    color: "#123456",
    width: 4,
    points: [
      { x: 80, y: 120 },
      { x: 240, y: 240 },
      { x: 400, y: 360 },
    ],
  });
});

test("client history preserves Clear undo and discards it on a new action", () => {
  const history = new ClientCanvasHistory();
  replace(history, [], 3);
  history.apply({
    event: "draw_shape",
    payload: {
      shape: "rectangle",
      from: { x: 0.1, y: 0.1 },
      to: { x: 0.2, y: 0.2 },
      color: "#000000",
      width: 4,
    },
  });
  const shapeHash = history.historyHash;
  assert.equal(
    history.confirmAction([1, 1, history.revision, history.historyHash]),
    true,
  );
  history.apply({ event: "clear_canvas", payload: {} });
  assert.equal(
    history.confirmAction([1, 2, history.revision, history.historyHash]),
    true,
  );

  assert.equal(history.actions.length, 2);
  assert.equal(history.confirmUndo([1, 3, 5, 6, shapeHash]), true);
  assert.equal(history.actions.length, 1);
  assert.equal(history.actions[0].kind, "shape");

  history.apply({ event: "clear_canvas", payload: {} });
  history.apply({
    event: "draw_fill",
    payload: { x: 0.5, y: 0.5, color: "#abcdef" },
  });
  assert.deepEqual(history.actions, [{
    kind: "fill",
    color: "#abcdef",
    x: 400,
    y: 300,
  }]);
});

test("stale incremental Undo is rejected for full-sync recovery", () => {
  const history = new ClientCanvasHistory();
  replace(history, [{ kind: "clear" }], 7);

  assert.equal(history.confirmUndo([1, 1, 5, 6, 0]), false);
  assert.equal(history.revision, 7);
  assert.deepEqual(history.actions, [{ kind: "clear" }]);
});

test("a path synchronized mid-stroke continues collecting live batches", () => {
  const history = new ClientCanvasHistory();
  const actions = [{
    kind: "path",
    color: "#000000",
    width: 4,
    points: [{ x: 80, y: 60 }],
  }];
  replace(history, actions, 12);

  assert.equal(history.apply({
    event: "draw_move",
    payload: { points: [{ x: 0.2, y: 0.3 }] },
  }), true);
  assert.deepEqual(history.actions[0].points, [
    { x: 80, y: 60 },
    { x: 160, y: 180 },
  ]);
});

test("CRC32 history hash matches the backend canonical action encoding", () => {
  const actions = [
    {
      kind: "path",
      color: "#aabbcc",
      width: 4,
      points: [{ x: 80, y: 120 }, { x: 240, y: 240 }],
    },
    {
      kind: "shape",
      payload: {
        shape: "ellipse",
        from: { x: 0.2, y: 0.3 },
        to: { x: 0.8, y: 0.9 },
        color: "#102030",
        width: 8,
      },
    },
    { kind: "fill", color: "#ffffff", x: 799, y: 599 },
    { kind: "clear" },
  ];

  assert.equal(calculateCanvasHistoryHash(actions), 0x0c816f97);
});

test("optimistic Undo is confirmed by sequence, revision, and CRC32", () => {
  const actions = [{ kind: "clear" }];
  const initialHash = calculateCanvasHistoryHash(actions);
  const history = new ClientCanvasHistory();
  assert.equal(replace(history, actions, 5, 7), true);
  const request = history.prepareUndo(8);

  assert.deepEqual(request, [1, 8, 5, initialHash]);
  assert.equal(history.revision, 6);
  assert.equal(history.historyHash, 0);
  assert.equal(history.confirmUndo([1, 8, 5, 6, 0], 6, 0), true);
  assert.equal(history.sequence, 8);
});

test("full sync rejects a mismatched CRC32", () => {
  const history = new ClientCanvasHistory();
  assert.equal(history.replace([{ kind: "clear" }], 1, 1, 1, 123), false);
  assert.equal(history.revision, null);
});

import assert from "node:assert/strict";
import test from "node:test";

import { ClientCanvasHistory } from "../src/lib/canvasHistory.ts";

test("client history groups path batches into one revisioned action", () => {
  const history = new ClientCanvasHistory();
  assert.equal(history.replace([], 10), true);

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
  history.replace([], 3);
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
  history.apply({ event: "clear_canvas", payload: {} });

  assert.equal(history.actions.length, 2);
  assert.equal(history.undo([5, 6]), true);
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
  history.replace([{ kind: "clear" }], 7);

  assert.equal(history.undo([6, 7]), false);
  assert.equal(history.revision, 7);
  assert.deepEqual(history.actions, [{ kind: "clear" }]);
});

test("a path synchronized mid-stroke continues collecting live batches", () => {
  const history = new ClientCanvasHistory();
  history.replace([{
    kind: "path",
    color: "#000000",
    width: 4,
    points: [{ x: 80, y: 60 }],
  }], 12);

  assert.equal(history.apply({
    event: "draw_move",
    payload: { points: [{ x: 0.2, y: 0.3 }] },
  }), true);
  assert.deepEqual(history.actions[0].points, [
    { x: 80, y: 60 },
    { x: 160, y: 180 },
  ]);
});

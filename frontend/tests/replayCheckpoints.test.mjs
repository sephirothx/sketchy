import assert from "node:assert/strict";
import test from "node:test";

import { CANVAS_HEIGHT, CANVAS_WIDTH } from "../src/lib/canvasHistory.ts";
import { renderCanvasActions } from "../src/lib/canvasRenderer.ts";
import {
  CHECKPOINT_EVERY,
  MIN_CHECKPOINT_LENGTH,
  createReplayCheckpoints,
} from "../src/lib/replayCheckpoints.ts";

// What a replay from white paints: the reference every checkpointed replay
// must equal byte for byte (#989).
function fromWhite(actions) {
  const pixels = new Uint8ClampedArray(CANVAS_WIDTH * CANVAS_HEIGHT * 4);
  renderCanvasActions({ pixels, commit: () => undefined }, actions);
  return pixels;
}

let seed = 11;
const random = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
const colors = ["#e11d48", "#2563eb", "#16a34a", "#f59e0b", "#111827"];

function path() {
  const points = [];
  let x = random();
  let y = random();
  for (let index = 0; index < 6; index++) {
    points.push({ x, y });
    x = Math.min(1, Math.max(0, x + (random() - 0.5) * 0.2));
    y = Math.min(1, Math.max(0, y + (random() - 0.5) * 0.2));
  }
  return { kind: "path", color: colors[Math.floor(random() * colors.length)], width: 4 + Math.floor(random() * 20), points };
}

function action() {
  return random() < 0.2
    ? { kind: "fill", color: colors[Math.floor(random() * colors.length)], x: random(), y: random() }
    : path();
}

function assertSame(checkpoints, actions, message) {
  const pixels = new Uint8ClampedArray(CANVAS_WIDTH * CANVAS_HEIGHT * 4).fill(7);
  const applied = checkpoints.replayInto(pixels, actions);
  assert.ok(Buffer.from(pixels).equals(Buffer.from(fromWhite(actions))), message);
  return applied;
}

test.beforeEach(() => {
  seed = 11;
});

test("an undo after the first replay repaints only what followed the newest copy", () => {
  const checkpoints = createReplayCheckpoints();
  const actions = Array.from({ length: 40 }, action);
  assert.equal(assertSame(checkpoints, actions, "first replay"), 40, "the first replay is whole");
  actions.pop();
  const applied = assertSame(checkpoints, actions, "after an undo");
  assert.ok(applied <= CHECKPOINT_EVERY, `an undo replayed ${applied} actions`);
});

test("a short history takes no copies", () => {
  const checkpoints = createReplayCheckpoints();
  const actions = Array.from({ length: MIN_CHECKPOINT_LENGTH - 1 }, action);
  assertSame(checkpoints, actions, "first");
  actions.pop();
  assert.equal(assertSame(checkpoints, actions, "second"), actions.length);
});

test("pops below a copy, a sync, and pushes all stay exact", () => {
  const checkpoints = createReplayCheckpoints();
  let actions = Array.from({ length: 48 }, action);
  assertSame(checkpoints, actions, "initial");
  for (let step = 0; step < 60; step++) {
    const roll = random();
    if (roll < 0.35 && actions.length > 1) {
      actions.pop();
    } else if (roll < 0.45) {
      // Undo far below every copy.
      actions.length = Math.max(1, actions.length - 20);
    } else if (roll < 0.5) {
      // A sync decodes the same drawing into new objects: no copy may match.
      actions = actions.map((entry) => structuredClone(entry));
      assert.equal(assertSame(checkpoints, actions, `sync at ${step}`), actions.length, "a copy outlived a sync");
      continue;
    } else {
      actions.push(action());
    }
    assertSame(checkpoints, actions, `step ${step}`);
  }
});

test("a copy whose last path grew since is not used", () => {
  // The history extends its open path in place; if an undo ever leaves a
  // copied path last and it is extended, the copy must be dropped.
  const checkpoints = createReplayCheckpoints();
  const actions = Array.from({ length: 33 }, () => path());
  assertSame(checkpoints, actions, "initial");
  actions.length = 24; // the copy at 24 now ends on the last action
  actions[23].points.push({ x: 0.5, y: 0.5 }, { x: 0.9, y: 0.1 });
  actions.push(path());
  const applied = assertSame(checkpoints, actions, "after the copied path grew");
  assert.equal(applied, actions.length, "a copy was used though its last path had grown");
});

test("a sync's fresh objects match no copy, however alike they look", () => {
  const checkpoints = createReplayCheckpoints();
  const actions = Array.from({ length: 40 }, action);
  assertSame(checkpoints, actions, "initial");
  const synced = actions.map((entry) => structuredClone(entry));
  synced.pop();
  assert.equal(assertSame(checkpoints, synced, "after a sync"), synced.length, "a copy outlived a sync");
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  canFillWithinBudget,
  canvasReplayWork,
  MAX_TURN_REPLAY_WORK,
  REPLAY_WORK_BY_KIND,
} from "../src/lib/canvasHistory.ts";

const fill = (x = 10) => ({ kind: "fill", color: "#123456", x, y: 20 });
const stroke = (points = 1) => ({
  kind: "path",
  color: "#000000",
  width: 4,
  points: Array.from({ length: points }, (_, index) => ({ x: index, y: index })),
});
const shape = () => ({
  kind: "shape",
  payload: {
    shape: "rectangle",
    color: "#000000",
    width: 4,
    from: { x: 0.1, y: 0.1 },
    to: { x: 0.5, y: 0.5 },
  },
});

test("a fill is charged what two hundred strokes are", () => {
  assert.equal(canvasReplayWork([fill()]), REPLAY_WORK_BY_KIND.fill);
  assert.equal(
    canvasReplayWork(Array.from({ length: 200 }, () => stroke())),
    REPLAY_WORK_BY_KIND.fill,
  );
  assert.equal(canvasReplayWork([{ kind: "clear" }]), 0);
});

test("the points inside a stroke are free", () => {
  // They ride inside one replayed action, so a long stroke costs what a dab does.
  assert.equal(canvasReplayWork([stroke(1)]), canvasReplayWork([stroke(500)]));
});

test("a busy real drawing spends a fraction of the budget", () => {
  const actions = [
    ...Array.from({ length: 600 }, () => stroke(12)),
    ...Array.from({ length: 8 }, () => shape()),
    ...Array.from({ length: 12 }, (_, index) => fill(index)),
  ];
  assert.equal(canvasReplayWork(actions), 600 + 8 + 12 * 200);
  assert.ok(canFillWithinBudget(actions));
});

test("the fill tool locks one fill early, never on the last of the budget", () => {
  const fillCost = REPLAY_WORK_BY_KIND.fill;
  // Exactly enough left for one more fill and nothing else: refused, because
  // taking it would leave the drawer with no budget at all.
  const spentToExactlyOneFill = Array.from(
    { length: MAX_TURN_REPLAY_WORK / fillCost - 1 },
    (_, index) => fill(index),
  );
  assert.equal(
    MAX_TURN_REPLAY_WORK - canvasReplayWork(spentToExactlyOneFill),
    fillCost,
  );
  assert.equal(canFillWithinBudget(spentToExactlyOneFill), false);

  // One fill less: allowed, and it leaves a fill's worth of pen behind it.
  const oneFillFewer = spentToExactlyOneFill.slice(0, -1);
  assert.equal(canFillWithinBudget(oneFillFewer), true);
});

test("the budget always leaves room to keep drawing", () => {
  const actions = [];
  while (canFillWithinBudget(actions)) actions.push(fill(actions.length));
  const remaining = MAX_TURN_REPLAY_WORK - canvasReplayWork(actions);
  assert.ok(
    remaining >= REPLAY_WORK_BY_KIND.fill,
    "filling as far as allowed must never strand the pen",
  );
  assert.ok(remaining > 0);
});

test("undoing hands the budget back, because the action leaves the history", () => {
  const actions = Array.from({ length: 99 }, (_, index) => fill(index));
  assert.equal(canFillWithinBudget(actions), false);
  actions.pop();
  assert.equal(canFillWithinBudget(actions), true);
});

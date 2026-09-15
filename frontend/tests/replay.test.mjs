import assert from "node:assert/strict";
import test from "node:test";

import {
  REPLAY_MAX_SECONDS,
  REPLAY_MIN_SECONDS,
  REPLAY_STEP_COST,
  replayPlan,
  stepReplay,
} from "../src/lib/replay.ts";

const path = (n) => ({ kind: "path", color: "#000000", width: 4, points: Array.from({ length: n }, (_, i) => ({ x: i, y: i })) });

test("a replay runs for a few seconds whatever the drawing's size", () => {
  const doodle = replayPlan([path(10), { kind: "fill", color: "#ff0000", x: 1, y: 1 }]);
  assert.equal(doodle.seconds, REPLAY_MIN_SECONDS);
  const dense = replayPlan(Array.from({ length: 200 }, () => path(60)));
  assert.equal(dense.seconds, REPLAY_MAX_SECONDS);
  const middling = replayPlan([path(661)]);
  assert.equal(middling.seconds, 3);
  assert.equal(Math.round(middling.pointsPerSecond), 220);
});

test("a dot, a shape, a fill or a clear is one step; a stroke costs its segments", () => {
  const plan = replayPlan([path(1), { kind: "clear" }, path(31)]);
  assert.equal(plan.total, REPLAY_STEP_COST * 2 + 30);
  assert.equal(plan.fractionAt(0, 0), 0);
  assert.equal(plan.fractionAt(2, 0), (REPLAY_STEP_COST * 2) / plan.total);
  assert.equal(plan.fractionAt(2, 15), (REPLAY_STEP_COST * 2 + 15) / plan.total);
  assert.equal(plan.fractionAt(3, 0), 1);
});

test("an empty drawing is finished before it starts", () => {
  const plan = replayPlan([]);
  assert.equal(plan.total, 0);
  assert.equal(plan.fractionAt(0, 0), 1);
  assert.ok(plan.pointsPerSecond >= 1);
});

test("a replay advances by its budget, one stretch of a stroke per frame", () => {
  const actions = [path(3), { kind: "fill", color: "#ff0000", x: 1, y: 1 }];
  const plan = replayPlan(actions);
  const painted = [];
  const painter = {
    span: (action, from, to) => painted.push(["span", from, to]),
    whole: (action) => painted.push(["whole", action.kind]),
  };
  let position = { action: 0, point: 0 };
  // A first frame at the plan's pace uncovers a fraction of the first segment.
  let step = stepReplay(actions, plan, position, 0.25, painter);
  position = step.position;
  assert.deepEqual(position, { action: 0, point: 0.25 });
  assert.equal(step.left, 0);
  assert.deepEqual(painted, [["span", 0, 0.25]]);
  // A frame that reaches the fill lands it and goes into debt for the rest
  // of its cost, which the next frames repay before anything else lands.
  step = stepReplay(actions, plan, position, 2, painter);
  assert.deepEqual(step.position, { action: 2, point: 0 });
  assert.deepEqual(painted.slice(1), [["span", 0.25, 2], ["whole", "fill"]]);
  assert.equal(plan.fractionAt(step.position.action, step.position.point), 1);
  // Done: nothing moves, nothing is painted, and no debt is owed.
  const done = stepReplay(actions, plan, step.position, 5, painter);
  assert.deepEqual(done, { position: step.position, left: 0 });
  assert.equal(painted.length, 3);
});

test("a vanishing remainder ends the frame rather than looping or skipping", () => {
  const actions = [path(2)];
  const plan = replayPlan(actions);
  const painted = [];
  const painter = { span: (a, from, to) => painted.push([from, to]), whole: () => {} };
  const near = { action: 0, point: 0.5 };
  const step = stepReplay(actions, plan, near, 1e-18, painter);
  assert.deepEqual(step, { position: near, left: 0 });
  assert.deepEqual(painted, []);
  // The dust a subtraction leaves behind is not a reason to draw the rest.
  const dusty = stepReplay(actions, plan, { action: 0, point: 0 }, 0.3 + 1e-17, painter);
  assert.ok(dusty.position.point > 0.29 && dusty.position.point < 0.31);
  assert.equal(dusty.position.action, 0);
});

test("a frame's budget is spread over a few seconds, not spent at once", () => {
  const actions = [path(3)];
  const plan = replayPlan(actions);
  // 16 ms at the plan's pace is a sliver of a segment, never the whole stroke.
  const budget = (16 / 1000) * plan.pointsPerSecond;
  const { position } = stepReplay(actions, plan, { action: 0, point: 0 }, budget, { span() {}, whole() {} });
  assert.ok(position.point > 0 && position.point < 0.05, String(position.point));
  assert.equal(position.action, 0);
});

test("a run of dots is paced by the debt each one leaves", () => {
  const actions = Array.from({ length: 10 }, () => path(1));
  const plan = replayPlan(actions);
  const frame = (16 / 1000) * plan.pointsPerSecond;
  let position = { action: 0, point: 0 };
  let carry = 0;
  let frames = 0;
  while (position.action < actions.length && frames < 10_000) {
    const step = stepReplay(actions, plan, position, carry + frame, { span() {}, whole() {} });
    position = step.position;
    carry = step.left;
    frames += 1;
  }
  // Ten dots at the floor of 2.5 s is about 150 frames, not ten.
  assert.ok(frames > 120 && frames < 180, String(frames));
});

test("a fraction maps back to a position: part way along a stroke, or on a step", () => {
  const actions = [path(5), { kind: "fill", color: "#ff0000", x: 1, y: 1 }, path(3)];
  const plan = replayPlan(actions);
  // 4 segments + a 12-point fill + 2 segments = 18.
  assert.equal(plan.total, 18);
  assert.deepEqual(plan.positionAt(0), { action: 0, point: 0 });
  assert.deepEqual(plan.positionAt(2 / 18), { action: 0, point: 2 });
  // Inside the fill's cost: the fill has not landed yet.
  assert.deepEqual(plan.positionAt(10 / 18), { action: 1, point: 0 });
  // Its cost paid: landed, and the last stroke not yet begun.
  assert.deepEqual(plan.positionAt(16 / 18), { action: 2, point: 0 });
  assert.deepEqual(plan.positionAt(17 / 18), { action: 2, point: 1 });
  assert.deepEqual(plan.positionAt(1), { action: 3, point: 0 });
  // Round trip: the fraction of a position is the position of the fraction.
  const back = plan.positionAt(plan.fractionAt(0, 2.5));
  assert.equal(back.action, 0);
  assert.ok(Math.abs(back.point - 2.5) < 1e-9);
  assert.deepEqual(replayPlan([]).positionAt(0.5), { action: 0, point: 0 });
});

import assert from "node:assert/strict";
import test from "node:test";

import { ROOM_BAR_STEPS, chooseGiveWay } from "../src/hooks/useRoomBarGiveWay.ts";

test("the bar gives way in R-UX-11's order: the round's word, the wordmark, the chips' words, the gaps, a second row", () => {
  assert.deepEqual(ROOM_BAR_STEPS, ["round", "mark", "labels", "tight", "wrap"]);
});

test("a bar that fits gives nothing up", () => {
  assert.deepEqual(chooseGiveWay(() => true), []);
});

test("only as many steps as it takes, each with every step before it", () => {
  const tried = [];
  const steps = chooseGiveWay((given) => {
    tried.push(given.join(" "));
    return given.includes("labels");
  });
  assert.deepEqual(steps, ["round", "mark", "labels"]);
  assert.deepEqual(tried, ["", "round", "round mark", "round mark labels"]);
});

test("a bar nothing else fits takes the second row without asking", () => {
  const tried = [];
  const steps = chooseGiveWay((given) => {
    tried.push(given.length);
    return false;
  });
  assert.deepEqual(steps, ROOM_BAR_STEPS);
  // The row is the step that always fits, so it is never measured.
  assert.deepEqual(tried, [0, 1, 2, 3, 4]);
});

import assert from "node:assert/strict";
import test from "node:test";

import { ROOM_BAR_STEPS, chooseGiveWay } from "../src/hooks/useRoomBarGiveWay.ts";

test("the bar gives way in R-UX-11's order: the round's word, the wordmark, the chips' words, the gaps, a second row", () => {
  assert.deepEqual(ROOM_BAR_STEPS, ["round", "mark", "labels", "tight", "wrap"]);
});

test("a bar that fits gives nothing up", () => {
  assert.deepEqual(chooseGiveWay(() => true), []);
});

test("the round keeps its word when the wordmark's room is enough", () => {
  // "Round 2/3" beside a notice on a 390px phone: the wordmark has to go, and
  // once it has, the word fits again.
  assert.deepEqual(chooseGiveWay((steps) => steps.includes("mark")), ["mark"]);
});

test("steps are taken in order, and handed back latest first while the bar still fits", () => {
  const tried = [];
  const steps = chooseGiveWay((given) => {
    tried.push(given.join(" "));
    // Needs the wordmark's room and the chips' words; the round's word fits.
    return given.includes("mark") && given.includes("labels");
  });
  assert.deepEqual(steps, ["mark", "labels"]);
  assert.deepEqual(tried, [
    "", "round", "round mark", "round mark labels",
    "round labels", "mark labels",
  ]);
});

test("a step still needed is kept", () => {
  assert.deepEqual(chooseGiveWay((steps) => steps.length >= 2), ["round", "mark"]);
});

test("a bar nothing fits takes every step, so its row can wrap again", () => {
  const tried = [];
  assert.deepEqual(chooseGiveWay((given) => (tried.push(given.length), false)), ROOM_BAR_STEPS);
  assert.deepEqual(tried, [0, 1, 2, 3, 4, 5]);
});

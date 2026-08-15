import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_CUSTOM_WORDS,
  MAX_RAW_INPUT_LENGTH,
  createCustomWordsState,
  customWordsReducer,
} from "../src/lib/customWords.ts";
import { createMaximumCustomWordsFixture } from "./helpers/customWordsFixture.mjs";

test("maximum custom-word fixture stays valid and within the payload limit", () => {
  const fixture = createMaximumCustomWordsFixture();
  const state = createCustomWordsState(fixture.raw, true);

  assert.equal(fixture.words.length, MAX_CUSTOM_WORDS);
  assert.ok(fixture.raw.length < MAX_RAW_INPUT_LENGTH);
  assert.equal(state.analysis.usableCount, MAX_CUSTOM_WORDS);
  assert.equal(state.analysis.hasErrors, false);
  assert.equal(state.only, true);
});

test("custom-word state retains one analysis across unrelated updates", () => {
  const initial = createCustomWordsState("apple\npear", true);
  const unchanged = customWordsReducer(initial, {
    type: "change",
    value: initial.value,
  });
  const toggled = customWordsReducer(initial, { type: "set-only", only: false });

  assert.strictEqual(unchanged, initial);
  assert.strictEqual(toggled.analysis, initial.analysis);
  assert.equal(toggled.only, false);
});

test("changing or resetting a value stores its exact analysis", () => {
  const initial = createCustomWordsState("apple", true);
  const invalid = customWordsReducer(initial, {
    type: "change",
    value: "this entry is deliberately longer than thirty two characters",
  });
  const empty = customWordsReducer(invalid, { type: "change", value: "" });
  const valid = customWordsReducer(empty, {
    type: "reset",
    value: "red panda\npear",
    only: true,
  });

  assert.equal(invalid.analysis.hasErrors, true);
  assert.equal(invalid.only, false);
  assert.equal(empty.analysis.usableCount, 0);
  assert.equal(empty.only, false);
  assert.equal(valid.analysis.usableCount, 2);
  assert.equal(valid.only, true);
});

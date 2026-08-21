import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_CUSTOM_PROMPTS,
  MAX_RAW_INPUT_LENGTH,
  createCustomPromptsState,
  customPromptsReducer,
} from "../src/lib/customPrompts.ts";
import { createMaximumCustomPromptsFixture } from "./helpers/customPromptsFixture.mjs";

test("maximum custom-prompt fixture stays valid and within the payload limit", () => {
  const fixture = createMaximumCustomPromptsFixture();
  const state = createCustomPromptsState(fixture.raw, true);

  assert.equal(fixture.prompts.length, MAX_CUSTOM_PROMPTS);
  assert.ok(fixture.raw.length < MAX_RAW_INPUT_LENGTH);
  assert.equal(state.analysis.usableCount, MAX_CUSTOM_PROMPTS);
  assert.equal(state.analysis.hasErrors, false);
  assert.equal(state.only, true);
});

test("custom-prompt state retains one analysis across unrelated updates", () => {
  const initial = createCustomPromptsState("apple\npear", true);
  const unchanged = customPromptsReducer(initial, {
    type: "change",
    value: initial.value,
  });
  const toggled = customPromptsReducer(initial, { type: "set-only", only: false });

  assert.strictEqual(unchanged, initial);
  assert.strictEqual(toggled.analysis, initial.analysis);
  assert.equal(toggled.only, false);
});

test("changing or resetting a value stores its exact analysis", () => {
  const initial = createCustomPromptsState("apple", true);
  const invalid = customPromptsReducer(initial, {
    type: "change",
    value: "this entry is deliberately longer than thirty two characters",
  });
  const empty = customPromptsReducer(invalid, { type: "change", value: "" });
  const valid = customPromptsReducer(empty, {
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

import assert from "node:assert/strict";
import test from "node:test";

import {
  describePromptMerge,
  mergePromptEntries,
  promptEntriesFromQuickInput,
  MAX_LIST_PROMPTS,
} from "../src/lib/promptListDrafts.ts";

const texts = (entries) => entries.map((entry) => entry.prompt);

test("a batch splits on both newlines and commas", () => {
  const result = mergePromptEntries([], "apple\nbicycle, cathedral\n\ndragon");

  assert.deepEqual(texts(result.entries), ["apple", "bicycle", "cathedral", "dragon"]);
  assert.equal(result.added, 4);
});

test("a second batch adds to the list rather than replacing it", () => {
  const first = mergePromptEntries([], "apple");
  const second = mergePromptEntries(first.entries, "bicycle");

  assert.deepEqual(texts(second.entries), ["apple", "bicycle"]);
});

test("duplicates are dropped whatever their case, including across batches", () => {
  const first = mergePromptEntries([], "apple, apple");
  const second = mergePromptEntries(first.entries, "APPLE\nApple\nbicycle");

  assert.deepEqual(texts(second.entries), ["apple", "bicycle"]);
  assert.equal(first.duplicates, 1);
  assert.equal(second.duplicates, 2);
});

test("a prompt longer than the limit is reported rather than truncated", () => {
  const long = "x".repeat(33);
  const result = mergePromptEntries([], `apple\n${long}`);

  assert.deepEqual(texts(result.entries), ["apple"]);
  assert.deepEqual(result.tooLong, [long]);
});

test("the list stops at its cap and says how many did not fit", () => {
  const full = Array.from({ length: MAX_LIST_PROMPTS }, (_, i) => ({
    prompt: `p${i}`,
    aliases: [],
  }));

  const result = mergePromptEntries(full, "one\ntwo");

  assert.equal(result.entries.length, MAX_LIST_PROMPTS);
  assert.equal(result.added, 0);
  assert.equal(result.overLimit, 2);
});

test("a clean import says nothing; a lossy one explains itself", () => {
  const clean = mergePromptEntries([], "apple\nbicycle");
  assert.equal(describePromptMerge(clean), null);

  const lossy = mergePromptEntries([{ prompt: "apple", aliases: [] }], "apple\nbicycle");
  assert.equal(
    describePromptMerge(lossy),
    "Added 1 prompt; skipped 1 already in the list.",
  );
});

test("an empty carry-over starts an empty list, not a blank row", () => {
  assert.deepEqual(promptEntriesFromQuickInput(undefined), []);
  assert.deepEqual(texts(promptEntriesFromQuickInput("apple, pear")), ["apple", "pear"]);
});

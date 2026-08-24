import assert from "node:assert/strict";
import test from "node:test";

import { maskedPromptWords, splitMaskedPrompt } from "../src/lib/maskedPrompt.ts";

test("splitMaskedPrompt separates blanks from trailing counts", () => {
  assert.deepEqual(splitMaskedPrompt("___  _____  3 5"), {
    blanks: "___  _____",
    counts: ["3", "5"],
  });
});

test("single word becomes one word with sequential slots and its count", () => {
  assert.deepEqual(maskedPromptWords("_______  7"), [
    {
      tiles: [
        { kind: "slot", char: null, slot: 0 },
        { kind: "slot", char: null, slot: 1 },
        { kind: "slot", char: null, slot: 2 },
        { kind: "slot", char: null, slot: 3 },
        { kind: "slot", char: null, slot: 4 },
        { kind: "slot", char: null, slot: 5 },
        { kind: "slot", char: null, slot: 6 },
      ],
      counts: ["7"],
    },
  ]);
});

test("multi-word prompts assign counts to their own words", () => {
  const words = maskedPromptWords("___  _____  3 5");
  assert.equal(words.length, 2);
  assert.deepEqual(words[0].counts, ["3"]);
  assert.deepEqual(words[1].counts, ["5"]);
  assert.equal(words[0].tiles.length, 3);
  assert.equal(words[1].tiles.length, 5);
  // Slot numbering continues across words.
  assert.deepEqual(
    words[1].tiles.map((tile) => tile.slot),
    [3, 4, 5, 6, 7],
  );
});

test("revealed letters keep their slot position and character", () => {
  const words = maskedPromptWords("_a__er_  7");
  assert.equal(words.length, 1);
  assert.deepEqual(words[0].tiles, [
    { kind: "slot", char: null, slot: 0 },
    { kind: "slot", char: "a", slot: 1 },
    { kind: "slot", char: null, slot: 2 },
    { kind: "slot", char: null, slot: 3 },
    { kind: "slot", char: "e", slot: 4 },
    { kind: "slot", char: "r", slot: 5 },
    { kind: "slot", char: null, slot: 6 },
  ]);
});

test("punctuation renders as literals and splits letter runs within a word", () => {
  // "spider-man" masks to one word whose hyphen stays visible, with a count
  // per letter run ("6 3"), matching the backend's masked_prompt contract.
  const words = maskedPromptWords("______-___  6 3");
  assert.equal(words.length, 1);
  const word = words[0];
  assert.deepEqual(word.counts, ["6", "3"]);
  assert.equal(word.tiles.length, 10);
  assert.deepEqual(word.tiles[6], { kind: "literal", char: "-", slot: null });
  // Literals do not consume slot numbers.
  assert.equal(word.tiles[5].slot, 5);
  assert.equal(word.tiles[7].slot, 6);
});

test("unicode revealed letters count as slots", () => {
  const words = maskedPromptWords("_é__  4");
  assert.equal(words.length, 1);
  assert.deepEqual(words[0].tiles[1], { kind: "slot", char: "é", slot: 1 });
  assert.equal(words[0].tiles.length, 4);
});

test("returns null when counts cannot be mapped onto letter runs", () => {
  // Two runs but only one count: the caller falls back to plain rendering.
  assert.equal(maskedPromptWords("___-___  6"), null);
  // No counts at all.
  assert.equal(maskedPromptWords("______"), null);
});

test("fully hidden prompt marker is not parseable into words", () => {
  assert.equal(maskedPromptWords("???"), null);
});

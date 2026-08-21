import assert from "node:assert/strict";
import test from "node:test";

import {
  PROMPT_STATS_SORTS,
  difficultyBand,
  emptyStatsMessage,
  isPromptStatsSort,
  ratioLabel,
  statsRows,
  unratedNote,
} from "../src/lib/promptStats.ts";

test("only the sorts the server accepts are recognised", () => {
  for (const sort of PROMPT_STATS_SORTS) {
    assert.ok(isPromptStatsSort(sort.value), `${sort.value} should be valid`);
  }
  assert.equal(isPromptStatsSort("sideways"), false);
  assert.equal(isPromptStatsSort(""), false);
});

test("ratios render as whole percentages", () => {
  assert.equal(ratioLabel(0), "0%");
  assert.equal(ratioLabel(0.8571), "86%");
  assert.equal(ratioLabel(1), "100%");
});

test("the difficulty bands cover the whole range without a gap", () => {
  for (let ratio = 0; ratio <= 1.0001; ratio += 0.01) {
    assert.ok(
      difficultyBand(Math.min(ratio, 1)).length > 0,
      `no band for ratio ${ratio}`,
    );
  }
  assert.equal(difficultyBand(1), "Gets guessed");
  assert.equal(difficultyBand(0), "Rarely guessed");
});

test("an empty list and an unranked list say different things", () => {
  // Nothing in the list at all.
  assert.equal(emptyStatsMessage(0, 0, 5), "This prompt list has no prompts yet.");
  // Prompts exist, none has enough guessers behind it yet.
  const unranked = emptyStatsMessage(0, 12, 5);
  assert.ok(unranked?.includes("12"));
  assert.ok(unranked?.includes("5"));
  // Once anything is ranked the table speaks for itself.
  assert.equal(emptyStatsMessage(3, 12, 5), null);
});

test("the unrated note stays quiet when everything is ranked", () => {
  assert.equal(unratedNote(0, 5), null);
  assert.ok(unratedNote(1, 5)?.includes("prompt is"));
  assert.ok(unratedNote(4, 5)?.includes("prompts are"));
});

test("rows keep the server's order and gain their display fields", () => {
  const rows = statsRows([
    {
      text: "roller coaster",
      offerCount: 10,
      pickCount: 2,
      correctGuessCount: 1,
      totalGuesserCount: 10,
      pickRate: 0.2,
      correctGuessRatio: 0.1,
    },
    {
      text: "cat",
      offerCount: 10,
      pickCount: 9,
      correctGuessCount: 9,
      totalGuesserCount: 10,
      pickRate: 0.9,
      correctGuessRatio: 0.9,
    },
  ]);
  assert.deepEqual(rows.map((row) => row.text), ["roller coaster", "cat"]);
  assert.equal(rows[0].guessedLabel, "10%");
  assert.equal(rows[0].band, "Rarely guessed");
  assert.equal(rows[1].band, "Gets guessed");
  assert.equal(rows[1].pickedLabel, "90%");
});

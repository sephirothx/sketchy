import assert from "node:assert/strict";
import test from "node:test";

import {
  PROMPT_STATS_SORTS,
  coverageNote,
  difficultyBand,
  isPromptStatsSort,
  matchingPrompts,
  ratioLabel,
  searchNote,
  statsRows,
} from "../src/lib/promptStats.ts";

function prompt(text, overrides = {}) {
  return {
    text,
    offerCount: 10,
    pickCount: 5,
    correctGuessCount: 5,
    totalGuesserCount: 10,
    pickRate: 0.5,
    correctGuessRatio: 0.5,
    isRated: true,
    ...overrides,
  };
}

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

test("an unrated prompt shows no difficulty rather than a measured-looking zero", () => {
  const [row] = statsRows([
    prompt("never-played", {
      isRated: false,
      correctGuessRatio: 0,
      pickRate: 0,
      totalGuesserCount: 1,
    }),
  ]);
  assert.equal(row.guessedLabel, "—");
  assert.equal(row.pickedLabel, "—");
  assert.notEqual(row.band, "Rarely guessed");
});

test("rows keep the server's order and gain their display fields", () => {
  const rows = statsRows([
    prompt("roller coaster", { correctGuessRatio: 0.1, pickRate: 0.2 }),
    prompt("cat", { correctGuessRatio: 0.9, pickRate: 0.9 }),
  ]);
  assert.deepEqual(rows.map((row) => row.text), ["roller coaster", "cat"]);
  assert.equal(rows[0].guessedLabel, "10%");
  assert.equal(rows[0].band, "Rarely guessed");
  assert.equal(rows[1].band, "Gets guessed");
  assert.equal(rows[1].pickedLabel, "90%");
});

test("the coverage note distinguishes an empty list from an unplayed one", () => {
  assert.equal(coverageNote(0, 0, 5), null);
  const unplayed = coverageNote(0, 12, 5);
  assert.ok(unplayed?.includes("12"));
  assert.ok(unplayed?.includes("5"));
  assert.ok(coverageNote(9, 0, 5)?.includes("All 9"));
  const mixed = coverageNote(3, 12, 5);
  assert.ok(mixed?.includes("3 ranked"));
  assert.ok(mixed?.includes("12 more"));
});

test("search matches on any part of the prompt, ignoring case and padding", () => {
  const prompts = [prompt("roller coaster"), prompt("cat"), prompt("Cathedral")];
  assert.deepEqual(
    matchingPrompts(prompts, "cat").map((p) => p.text),
    ["cat", "Cathedral"],
  );
  assert.deepEqual(
    matchingPrompts(prompts, "  COASTER ").map((p) => p.text),
    ["roller coaster"],
  );
});

test("an empty search is not a filter", () => {
  const prompts = [prompt("a"), prompt("b")];
  assert.equal(matchingPrompts(prompts, "").length, 2);
  assert.equal(matchingPrompts(prompts, "   ").length, 2);
  assert.equal(searchNote("", 2), null);
});

test("the search note says how many matched, or that none did", () => {
  assert.ok(searchNote("cat", 2)?.includes("2 prompts"));
  assert.ok(searchNote("cat", 1)?.includes("1 prompt "));
  assert.ok(searchNote("zzz", 0)?.includes("No prompt"));
});

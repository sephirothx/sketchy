import assert from "node:assert/strict";
import test from "node:test";

import {
  PROMPT_STATS_SORTS,
  coverageNote,
  difficultyBand,
  isPromptStatsSort,
  matchingPrompts,
  nothingRanked,
  plainPromptNames,
  ratioLabel,
  searchExample,
  searchNote,
  listsByLanguage,
  sortPromptStats,
  statsRows,
} from "../src/lib/promptStats.ts";

function prompt(text, overrides = {}) {
  return {
    text,
    offerCount: 10,
    pickCount: 5,
    correctGuessCount: 5,
    totalGuesserCount: 10,
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
      correctGuessCount: 0,
      pickCount: 0,
      totalGuesserCount: 1,
    }),
  ]);
  assert.equal(row.guessedLabel, "—");
  assert.equal(row.pickedLabel, "—");
  assert.notEqual(row.band, "Rarely guessed");
  // How often it has been drawn is a plain count, true either way.
  assert.equal(row.drawnLabel, "0");
});

test("times drawn is reported for rated and unrated prompts alike", () => {
  const rows = statsRows([
    prompt("often", { pickCount: 27 }),
    prompt("once", { pickCount: 1, isRated: false }),
  ]);
  assert.deepEqual(rows.map((row) => row.drawnLabel), ["27", "1"]);
});

test("rows keep the server's order and gain their display fields", () => {
  const rows = statsRows([
    // The ratios are divided here from the counts (#1424).
    prompt("roller coaster", { correctGuessCount: 1, pickCount: 2 }),
    prompt("cat", { correctGuessCount: 9, pickCount: 9 }),
  ]);
  assert.deepEqual(rows.map((row) => row.text), ["roller coaster", "cat"]);
  assert.equal(rows[0].guessedLabel, "10%");
  assert.equal(rows[0].drawnLabel, "2");
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

test("a slice with nothing ranked or drawn is told apart from one with something to show", () => {
  const unplayed = [prompt("cat", { pickCount: 0, isRated: false }), prompt("dog", { pickCount: 0, isRated: false })];
  assert.equal(nothingRanked({ ratedCount: 0, unratedCount: 2, prompts: unplayed }), true);
  assert.equal(nothingRanked({ ratedCount: 1, unratedCount: 1, prompts: unplayed }), false);
  // An empty list has nothing to list plainly either.
  assert.equal(nothingRanked({ ratedCount: 0, unratedCount: 0, prompts: [] }), false);
  // Drawn but not yet ranked keeps the table: its count, and "Most picked".
  const drawnOnce = [unplayed[0], prompt("dog", { pickCount: 1, isRated: false })];
  assert.equal(nothingRanked({ ratedCount: 0, unratedCount: 2, prompts: drawnOnce }), false);
});

test("an unranked list is named alphabetically in its own language", () => {
  // A code-point sort would put "Äpfel" after "Zebra"; German files it under A.
  const prompts = [prompt("Zebra"), prompt("Äpfel"), prompt("birne"), prompt("Banane")];
  assert.deepEqual(plainPromptNames(prompts, "de"), ["Äpfel", "Banane", "birne", "Zebra"]);
});

test("the search example is a prompt from the list, whatever order it arrives in", () => {
  const listed = [prompt("cat"), prompt("roller coaster"), prompt("ant")];
  const example = searchExample(listed, "en");
  assert.equal(example, "cat");
  assert.equal(searchExample([...listed].reverse(), "en"), example);
  assert.equal(searchExample([], "en"), null);
});

test("the prompts are ranked here as the server ranks them, so a new sort is not a request (#1424)", () => {
  const prompts = [
    prompt("b-easy", { correctGuessCount: 9, offerCount: 10, pickCount: 1 }),
    prompt("a-hard", { correctGuessCount: 1, offerCount: 10, pickCount: 9 }),
    prompt("c-hard", { correctGuessCount: 1, offerCount: 10, pickCount: 4 }),
    prompt("unrated-z", { isRated: false, correctGuessCount: 0 }),
    prompt("unrated-a", { isRated: false, correctGuessCount: 0 }),
  ];
  const order = (sort) => sortPromptStats(prompts, sort).map((p) => p.text);
  assert.deepEqual(order("hardest"), ["a-hard", "c-hard", "b-easy", "unrated-a", "unrated-z"]);
  assert.deepEqual(order("easiest"), ["b-easy", "a-hard", "c-hard", "unrated-a", "unrated-z"]);
  assert.deepEqual(order("most-picked"), ["a-hard", "c-hard", "b-easy", "unrated-a", "unrated-z"]);
});

test("the list selector groups by language, the reader's play languages first", () => {
  const list = (slug, language) => ({ slug, name: slug, language, promptCount: 10 });
  const groups = listsByLanguage(
    [list("de-standard", "de"), list("en-standard", "en"), list("fr-standard", "fr"), list("en-extended", "en")],
    ["fr", "en"],
  );
  assert.deepEqual(groups.map((group) => group.language), ["fr", "en", "de"]);
  assert.deepEqual(groups[1].lists.map((entry) => entry.slug), ["en-standard", "en-extended"]);
});

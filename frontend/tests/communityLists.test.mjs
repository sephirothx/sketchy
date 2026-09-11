import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_FILTERS,
  filtersFromParams,
  findInPrompt,
  groupAlphabetically,
  isFiltered,
  paramsFromFilters,
  queryFromFilters,
  withTag,
} from "../src/lib/communityLists.ts";

const VOCABULARY = ["animals", "food-and-drink", "nature", "places"];

test("a filtered view survives being shared as a link", () => {
  const filters = { language: "de", tags: ["animals", "nature"], sort: "newest", starred: true };

  assert.deepEqual(filtersFromParams(paramsFromFilters(filters)), filters);
});

test("a link nobody could have been given reads as no filter", () => {
  // The only way to hold these is to have edited the URL, and a catalogue
  // that refuses to render is worse than one that shows everything.
  const params = new URLSearchParams("language=klingon&sort=sideways");

  assert.deepEqual(filtersFromParams(params), DEFAULT_FILTERS);
});

test("the default view carries no parameters at all", () => {
  assert.equal(paramsFromFilters(DEFAULT_FILTERS).toString(), "");
});

test("a tag keeps vocabulary order however it was clicked", () => {
  const first = withTag(withTag(DEFAULT_FILTERS, "nature", VOCABULARY), "animals", VOCABULARY);
  const other = withTag(withTag(DEFAULT_FILTERS, "animals", VOCABULARY), "nature", VOCABULARY);

  assert.deepEqual(first.tags, ["animals", "nature"]);
  assert.deepEqual(first.tags, other.tags, "the same selection is the same link");
});

test("clicking a tag twice removes it", () => {
  const once = withTag(DEFAULT_FILTERS, "places", VOCABULARY);

  assert.deepEqual(withTag(once, "places", VOCABULARY).tags, []);
});

test("sorting is not filtering", () => {
  // Otherwise "clear filters" would appear against a view nobody narrowed.
  assert.equal(isFiltered({ ...DEFAULT_FILTERS, sort: "newest" }), false);
  assert.equal(isFiltered({ ...DEFAULT_FILTERS, starred: true }), true);
  assert.equal(isFiltered({ ...DEFAULT_FILTERS, tags: ["animals"] }), true);
});

test("the request asks for a shortlist only when one was asked for", () => {
  assert.equal(queryFromFilters(DEFAULT_FILTERS, null).starred, undefined);
  assert.equal(queryFromFilters({ ...DEFAULT_FILTERS, starred: true }, null).starred, true);
});

test("a search ignores case and accents", () => {
  // Typed on a keyboard without the accent, which is what the reader means.
  assert.deepEqual(findInPrompt("Crème brûlée", "BRULEE", "fr"), { start: 6, end: 12 });
  assert.deepEqual(findInPrompt("Äpfel", "apf", "de"), { start: 0, end: 3 });
});

test("a match is found where the reader sees it, not where folding moved it", () => {
  // NFD turns "é" into two code points. If folding kept both, every offset
  // after it would shift by one and the wrong letters would be highlighted.
  const text = "café au lait";
  const match = findInPrompt(text, "lait", "fr");

  assert.deepEqual(match, { start: 8, end: 12 });
  assert.equal([...text].slice(match.start, match.end).join(""), "lait");
});

test("an empty search is not a search", () => {
  assert.equal(findInPrompt("octopus", "", "en"), null);
  assert.equal(findInPrompt("octopus", "   ", "en"), null);
  assert.equal(findInPrompt("octopus", "squid", "en"), null);
});

test("A–Z files an accented initial under its base letter", () => {
  const groups = groupAlphabetically(["Éclair", "apple", "eagle", "Äpfel"], (text) => text, "de");

  assert.deepEqual(groups.map((group) => group.initial), ["A", "E"]);
  // Letters decide before accents do: a-p-f comes before a-p-p.
  assert.deepEqual(groups[0].entries, ["Äpfel", "apple"]);
});

test("A–Z sorts in the list's own language", () => {
  // Code-point order would put Äpfel after Zebra; German does not.
  const sorted = groupAlphabetically(["Zebra", "Äpfel", "Apfel"], (text) => text, "de")
    .flatMap((group) => group.entries);

  assert.deepEqual(sorted, ["Apfel", "Äpfel", "Zebra"]);
});

test("a prompt that does not start with a letter files under #", () => {
  const groups = groupAlphabetically(["7 dwarfs", "anchor"], (text) => text, "en");

  assert.deepEqual(groups.map((group) => group.initial), ["#", "A"]);
});

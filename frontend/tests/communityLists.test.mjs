import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_FILTERS,
  filtersFromParams,
  findInPrompt,
  groupAlphabetically,
  readEveryPage,
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

test("a paged read is followed to its last page", async () => {
  const pages = { "": ["a", "b"], two: ["c", "d"], three: ["e"] };
  const next = { "": "two", two: "three", three: null };
  const asked = [];

  const everything = await readEveryPage(async (cursor) => {
    asked.push(cursor);
    return { lists: pages[cursor ?? ""], nextCursor: next[cursor ?? ""] };
  }, 10);

  assert.deepEqual(everything, { lists: ["a", "b", "c", "d", "e"], complete: true });
  assert.deepEqual(asked, [null, "two", "three"], "each cursor is asked for once, the first with none");
});

test("a cursor that never ends stops at the guard, and says it stopped", async () => {
  let reads = 0;
  const everything = await readEveryPage(async () => {
    reads += 1;
    return { lists: [reads], nextCursor: "again" };
  }, 3);

  assert.equal(reads, 3);
  // Not handed back as if it were everything: that is the silent truncation
  // the reader exists to prevent.
  assert.deepEqual(everything, { lists: [1, 2, 3], complete: false });
});

test("a read that ends exactly at the guard is complete", async () => {
  const everything = await readEveryPage(async (cursor) => (
    cursor ? { lists: ["b"], nextCursor: null } : { lists: ["a"], nextCursor: "two" }
  ), 2);

  assert.deepEqual(everything, { lists: ["a", "b"], complete: true });
});

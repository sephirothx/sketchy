import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_FILTERS,
  filtersFromParams,
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

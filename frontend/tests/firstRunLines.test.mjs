import assert from "node:assert/strict";
import test from "node:test";

import { pickLine } from "../src/lib/firstRunLines.ts";
import { CATALOGUE_LOCALES, catalogueFor, loadCatalogue } from "../src/content/ui/index.ts";

await Promise.all(CATALOGUE_LOCALES.map(loadCatalogue));

const POOL = ["one", "two", "three", "four", "five"];

test("a roll picks the line at that share of the pool, and 1 cannot fall off the end", () => {
  assert.equal(pickLine(POOL, 0), "one");
  assert.equal(pickLine(POOL, 0.39), "two");
  assert.equal(pickLine(POOL, 0.5), "three");
  assert.equal(pickLine(POOL, 0.999999), "five");
  // Math.random() never returns 1, but a stub or a future engine might.
  assert.equal(pickLine(POOL, 1), "five");
  assert.equal(pickLine(POOL, -0.2), "one");
});

test("an empty pool says nothing rather than throwing on the lobby", () => {
  assert.equal(pickLine([], 0.5), "");
});

test("every language has its own pool, and every line fits the block", () => {
  const english = catalogueFor("en").firstRunIdentity.lines;
  assert.ok(english.length >= 3, "the pool is worth drawing from");
  for (const locale of CATALOGUE_LOCALES) {
    const lines = catalogueFor(locale).firstRunIdentity.lines;
    assert.equal(lines.length, english.length, `${locale} offers a different number of lines`);
    for (const line of lines) {
      assert.ok(line.trim().length > 0, `${locale} has a blank line`);
      // Long enough to be a joke, short enough to stay two lines on a phone.
      assert.ok(line.length <= 72, `${locale} line too long to set: ${line}`);
    }
    if (locale !== "en") {
      assert.notDeepEqual(lines, english, `${locale} still shows the English pool`);
    }
  }
});

test("the visit keeps its place in the pool, not the words: a new language reads its own", () => {
  const english = catalogueFor("en").firstRunIdentity.lines;
  const italian = catalogueFor("it").firstRunIdentity.lines;
  for (const roll of [0, 0.2, 0.45, 0.8, 0.99]) {
    const at = english.indexOf(pickLine(english, roll));
    assert.equal(pickLine(italian, roll), italian[at], `roll ${roll} landed elsewhere`);
  }
});

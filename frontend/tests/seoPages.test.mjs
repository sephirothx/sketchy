import assert from "node:assert/strict";
import test from "node:test";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { bundledLists, expandedLists, LIST_DIRECTORY, seoPages } from "../scripts/seo-pages.mjs";
import { LOCALES } from "../src/content/ui/index.ts";

const lists = bundledLists();
const pages = await seoPages(lists);

test("every interface language has a head for every public page", () => {
  assert.deepEqual(Object.keys(pages.locales).sort(), [...LOCALES].sort());
  for (const [locale, entry] of Object.entries(pages.locales)) {
    assert.deepEqual(Object.keys(entry.pages).sort(), ["/", "/privacy", "/rules", "/solo", "/terms"], locale);
    for (const [path, head] of Object.entries(entry.pages)) {
      assert.ok(head.title.trim() && head.description.trim(), `${locale} ${path}`);
      assert.match(head.title, /Sketchy/, `${locale} ${path}`);
      // A search result cuts a description at about 160 characters.
      assert.ok(head.description.length <= 170, `${locale} ${path}: ${head.description.length}`);
    }
  }
});

test("every official list has its own head in every language", () => {
  assert.ok(lists.length > 0);
  for (const [locale, entry] of Object.entries(pages.locales)) {
    assert.deepEqual(Object.keys(entry.promptLists).sort(), lists.map((list) => list.slug).sort(), locale);
    assert.ok(entry.standardList && entry.promptLists[entry.standardList], locale);
  }
});

test("a list's head names it and counts its words in the reader's language", () => {
  const standard = lists.find((list) => list.slug === "english_standard");
  assert.equal(
    pages.locales.en.promptLists.english_standard.title,
    `English — Standard: ${standard.count.toLocaleString("en")} words to draw · Sketchy`,
  );
  assert.equal(pages.locales.de.standardList, "german_standard");
});

test("a name list stands for one list per language, as the server seeds it", () => {
  const file = JSON.parse(readFileSync(join(LIST_DIRECTORY, "pokemon_gen1.json"), "utf-8"));
  const expanded = expandedLists(file);
  assert.deepEqual(
    expanded.map((list) => list.slug).sort(),
    ["dutch", "english", "french", "german", "italian", "polish", "portuguese", "spanish"]
      .map((language) => `${language}_pokemon_gen1`),
  );
  const french = expanded.find((list) => list.language === "fr");
  assert.equal(french.name, file.names.fr);
  assert.equal(french.count, file.prompts.length);
  // The list's own name whatever language the page is read in: official lists
  // have no other.
  assert.match(pages.locales.de.promptLists.french_pokemon_gen1.title, new RegExp(`^${file.names.fr}`));
  assert.ok(!("pokemon_gen1" in pages.locales.en.promptLists));
});

test("the home page's title is the brand and the tagline", () => {
  assert.equal(pages.locales.en.pages["/"].title, `Sketchy – ${pages.locales.en.tagline}`);
});

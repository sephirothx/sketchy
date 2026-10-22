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

test("the readable text is the words each page draws, in every language", async () => {
  const { rulesFor } = await import("../src/content/rules/index.ts");
  const { legalFor } = await import("../src/content/legal/index.ts");
  const { escapeHtml } = await import("../scripts/seo-pages.mjs");
  for (const [locale, entry] of Object.entries(pages.locales)) {
    const rules = rulesFor(locale);
    const body = entry.pages["/rules"].body;
    for (const section of rules.sections) {
      for (const rule of section.rules) {
        assert.ok(body.includes(`<h3 id="${rule.id}">${escapeHtml(rule.heading)}</h3>`), `${locale} ${rule.id}`);
        for (const paragraph of rule.body) assert.ok(body.includes(escapeHtml(paragraph)), `${locale} ${rule.id}`);
      }
    }
    for (const which of ["terms", "privacy"]) {
      const text = entry.pages[`/${which}`].body;
      assert.ok(text.includes(`<h1>${escapeHtml(legalFor(locale)[which].title)}</h1>`), `${locale} ${which}`);
      // The age is the build's to fill; the address is the server's.
      assert.ok(!text.includes("{age}"), `${locale} ${which}`);
    }
    assert.ok(entry.pages["/privacy"].body.includes("{contact}"), locale);
    // The site's links, for a crawler that follows no script.
    const home = entry.pages["/"].body;
    for (const href of ["/solo", "/community-lists", "/prompt-lists", "/rules", "/terms", "/privacy"]) {
      assert.ok(home.includes(`href="${href}"`), `${locale} ${href}`);
    }
    assert.ok(home.includes(`<h1>${escapeHtml(entry.pages["/"].title)}</h1>`), locale);
    for (const page of Object.values(entry.pages)) assert.match(page.body, /^<noscript><div class="prerender">.*<\/div><\/noscript>$/s);
  }
});

test("text is escaped where it lands", async () => {
  const { escapeHtml } = await import("../scripts/seo-pages.mjs");
  assert.equal(escapeHtml(`<a href="x">Tom & Jerry</a>`), "&lt;a href=&quot;x&quot;&gt;Tom &amp; Jerry&lt;/a&gt;");
});

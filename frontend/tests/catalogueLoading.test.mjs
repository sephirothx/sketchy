import assert from "node:assert/strict";
import test from "node:test";

// Its own file on purpose: node runs each test file in a fresh process, so the
// catalogue module starts here with nothing but English loaded - the state a
// first visit is in (#982).
import { EN } from "../src/content/ui/en.ts";
import {
  catalogueFor,
  interfaceLocale,
  isCatalogueLoaded,
  loadCatalogue,
  setCatalogue,
  ui,
} from "../src/content/ui/index.ts";

test("only English is there before anything is fetched", () => {
  assert.equal(isCatalogueLoaded("en"), true);
  assert.equal(isCatalogueLoaded("de"), false);
  assert.equal(catalogueFor("de"), EN, "an unfetched locale reads as English");
});

test("switching to an unfetched locale keeps the words in force", () => {
  assert.equal(setCatalogue("fr"), "en");
  assert.equal(interfaceLocale(), "en");
  assert.equal(ui, EN);
});

test("a locale is fetched once, and is then switched to at once", async () => {
  const first = loadCatalogue("it");
  assert.equal(loadCatalogue("it"), first, "two readers share one fetch");
  assert.equal(await first, "it");
  assert.equal(isCatalogueLoaded("it"), true);
  assert.notEqual(catalogueFor("it"), EN);
  assert.equal(setCatalogue("it"), "it");
  assert.equal(ui, catalogueFor("it"));
  setCatalogue("en");
});

test("a locale this build does not have loads as English", async () => {
  assert.equal(await loadCatalogue("kl"), "en");
  assert.equal(isCatalogueLoaded("kl"), true);
});

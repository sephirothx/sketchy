import assert from "node:assert/strict";
import test from "node:test";

import {
  FALLBACK_LOCALE,
  LOCALES,
  isLocale,
  preferredLocale,
  resolveLocale,
} from "../src/lib/interfaceLocale.ts";
import { catalogueFor, setCatalogue, ui } from "../src/content/ui/index.ts";

test("a locale is offered only when its catalogue is complete", () => {
  // The list is derived from the catalogues rather than declared beside them,
  // so a language cannot be offered before somebody has finished writing it.
  assert.ok(LOCALES.includes(FALLBACK_LOCALE));
  for (const locale of LOCALES) {
    assert.equal(typeof catalogueFor(locale), "object");
  }
});

test("the account's choice wins, then this browser's, then the browser's languages", () => {
  assert.equal(
    resolveLocale({ account: "en", stored: "en", browser: ["en-GB"] }),
    "en",
  );
  // Each step is only reached when the one above it has nothing to say.
  assert.equal(resolveLocale({ account: null, stored: "en", browser: [] }), "en");
  assert.equal(resolveLocale({ browser: ["en-GB"] }), "en");
  assert.equal(resolveLocale({}), FALLBACK_LOCALE);
});

test("a language this build does not speak is not a choice", () => {
  // A stored choice from a build that offered more languages, or an account
  // setting this bundle is behind on: both fall through rather than
  // rendering a page with no words.
  assert.equal(resolveLocale({ account: "kl", stored: null, browser: [] }), FALLBACK_LOCALE);
  assert.equal(resolveLocale({ stored: "kl", browser: ["kl"] }), FALLBACK_LOCALE);
  assert.equal(isLocale("kl"), false);
});

test("a regional tag reads down to its base language", () => {
  // Somebody who asked for Austrian German would rather have German than a
  // language they never asked for.
  assert.equal(preferredLocale(["en-GB", "de"]), "en");
  assert.equal(preferredLocale(["kl-GL", "en-AU"]), "en");
  assert.equal(preferredLocale(["EN-us"]), "en");
  assert.equal(preferredLocale([]), FALLBACK_LOCALE);
});

test("setting a locale this build cannot read leaves the words in place", () => {
  const before = ui.lastSeen.online;
  assert.equal(setCatalogue("kl"), FALLBACK_LOCALE);
  assert.equal(ui.lastSeen.online, before);
});

test("the document description comes from the catalogue, like every other word", () => {
  assert.equal(typeof catalogueFor(FALLBACK_LOCALE).document.description, "string");
  assert.notEqual(catalogueFor(FALLBACK_LOCALE).document.description.trim(), "");
});

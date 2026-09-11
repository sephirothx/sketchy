/** Every locale is complete, and says how much of it a person has read.

Two separate claims, and this file keeps them apart on purpose.

**Completeness** is the compiler's: `Catalogue` is `typeof EN`, so a locale
missing a key does not build. What is left for a test is the part `tsc`
cannot see - that a locale's entries are *different words*, not the English
ones copied across, which is what a half-finished draft looks like from the
outside.

**Quality** is not a build rule and must not pretend to be. The six locales
are machine-drafted and unreviewed; the count is printed rather than
asserted, so it is visible in CI without failing a build that is honestly
labelled (R-I18N-07).
*/
import assert from "node:assert/strict";
import test from "node:test";

import { CATALOGUE_LOCALES, catalogueFor, FALLBACK_LOCALE } from "../src/content/ui/index.ts";
import { REVIEWED } from "../src/content/ui/reviewed.ts";

/** Every leaf of a catalogue, as `group.entry` paths. */
function entries(node, path = []) {
  const out = [];
  for (const [key, value] of Object.entries(node)) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      out.push(...entries(value, [...path, key]));
    } else {
      out.push([[...path, key].join("."), value]);
    }
  }
  return out;
}

/** What an entry says, with a plausible argument if it takes one. */
function render(value) {
  if (typeof value !== "function") return String(value);
  const probe = {
    count: 2, total: 2, shown: 1, seconds: 2, minutes: 2, points: 2, cost: 2,
    price: 2, limit: 2, here: 1, capacity: 4, rounds: 2, players: 2, prompts: 2,
    waiting: 2, rank: 2, index: 1, length: 6, width: 4, delta: 2, base: 2,
    hintSpend: 1, position: 1, yes: 1, no: 1, pending: 1, recoveryCodesRemaining: 2,
    scoringVersion: 1, reconnects: 2, schemaVersion: 7, seated: 2,
    name: "Ada", nickname: "Ada", previous: "Grace", label: "Size", value: "x",
    text: "x", letter: "A", color: "#fff", tool: "Brush", what: "Code",
    when: "today", where: "here", reason: "x", state: "x", theme: "dark",
    action: "do", prompt: "x", word: "DELETE", code: "ABC123", chips: "x",
    language: "English", listLanguage: "English", roomLanguage: "English",
    address: "a@b.c", place: "1st", shape: "4", visibility: "private",
    moderationState: null, nextAllowed: null, finishedAt: "today",
    scoringMode: "x", hintMode: "x", promptSource: "x", commitDate: "x",
    builtAt: "x", role: "admin", isGuest: false, rematch: false, full: false,
    connected: true, isFriend: false, guessed: false, replacing: false,
    confirmAuthenticator: false, unit: "minute",
  };
  try {
    return String(value(probe));
  } catch {
    // An entry whose shape this probe does not fit is not evidence either way.
    return "";
  }
}

const TRANSLATED = CATALOGUE_LOCALES.filter((locale) => locale !== FALLBACK_LOCALE);

test("every locale the app offers is a complete catalogue", () => {
  // The compiler proves the keys; this proves the list of offered locales and
  // the list of catalogues are the same list, which is what stops a language
  // being offered before it is written (R-I18N-07).
  const reference = entries(catalogueFor(FALLBACK_LOCALE)).map(([key]) => key);
  for (const locale of CATALOGUE_LOCALES) {
    const keys = entries(catalogueFor(locale)).map(([key]) => key);
    assert.deepEqual(keys, reference, `${locale} does not match the reference catalogue`);
  }
});

test("a translated locale is actually translated, not English copied across", () => {
  // The failure this catches is a draft that stopped early: a whole locale, or
  // a whole screen inside one, still reading in English.
  const english = new Map(entries(catalogueFor(FALLBACK_LOCALE)).map(([k, v]) => [k, render(v)]));
  for (const locale of TRANSLATED) {
    const same = entries(catalogueFor(locale)).filter(([key, value]) => {
      const rendered = render(value);
      // Short entries and proper nouns legitimately match: "OK", "Sketchy",
      // "Zoom", "Chat". Only longer sentences are evidence of a gap.
      return rendered.length > 24 && rendered === english.get(key);
    });
    const share = same.length / english.size;
    assert.ok(
      share < 0.1,
      `${locale}: ${same.length} of ${english.size} long entries are still the `
        + `English words (${Math.round(share * 100)}%) - first few: `
        + `${same.slice(0, 5).map(([key]) => key).join(", ")}`,
    );
  }
});

test("the unreviewed count is reported for every locale", () => {
  // Printed, not asserted: the six are drafts and say so. A locale reaching
  // zero unreviewed is a launch gate (R-I18N-07), which is a person's
  // decision rather than a build's.
  const total = entries(catalogueFor(FALLBACK_LOCALE)).length;
  const lines = TRANSLATED.map((locale) => {
    const reviewed = REVIEWED[locale].size;
    const percent = Math.round((reviewed / total) * 100);
    return `  ${locale}: ${reviewed}/${total} reviewed (${percent}%)`;
  });
  console.log(`native review, ${total} entries per locale:\n${lines.join("\n")}`);
  for (const locale of CATALOGUE_LOCALES) {
    assert.ok(REVIEWED[locale] instanceof Set, `${locale} has no review record`);
    for (const key of REVIEWED[locale]) {
      assert.ok(
        entries(catalogueFor(locale)).some(([entry]) => entry === key),
        `${locale} claims a review of ${key}, which is not an entry`,
      );
    }
  }
});

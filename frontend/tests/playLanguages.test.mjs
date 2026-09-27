import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_EXTRA_PROMPT_LANGUAGES,
  addExtraPromptLanguage,
  chooseDefaultPlayLanguage,
  moveExtraPromptLanguage,
  normalizeExtraPromptLanguages,
  removeExtraPromptLanguage,
  suggestedExtraPromptLanguages,
} from "../src/lib/playLanguages.ts";

const current = { promptLanguage: "it", extraPromptLanguages: ["nl", "en", "es"] };

test("the others are kept to the rules the server holds: known, once, never the default", () => {
  assert.deepEqual(normalizeExtraPromptLanguages(["en", "it", "en", "xx", 7, "de"], "it"), ["en", "de"]);
  assert.deepEqual(normalizeExtraPromptLanguages("en", "it"), []);
  assert.deepEqual(normalizeExtraPromptLanguages(null, "it"), []);
  assert.equal(MAX_EXTRA_PROMPT_LANGUAGES, 6);
  assert.equal(
    normalizeExtraPromptLanguages(["de", "en", "es", "fr", "it", "nl", "pt"], "pt").length,
    6,
  );
});

test("promoting one of the others swaps the old default into its place", () => {
  assert.deepEqual(chooseDefaultPlayLanguage(current, "en"), {
    promptLanguage: "en",
    extraPromptLanguages: ["nl", "it", "es"],
  });
});

test("a default from outside the others replaces the old one, as one language always did", () => {
  assert.deepEqual(chooseDefaultPlayLanguage(current, "fr"), {
    promptLanguage: "fr",
    extraPromptLanguages: ["nl", "en", "es"],
  });
  assert.equal(chooseDefaultPlayLanguage(current, "it"), current);
});

test("adding goes last and never repeats; removing keeps the rest in order", () => {
  assert.deepEqual(addExtraPromptLanguage(current, "de").extraPromptLanguages, ["nl", "en", "es", "de"]);
  assert.deepEqual(addExtraPromptLanguage(current, "en").extraPromptLanguages, ["nl", "en", "es"]);
  assert.deepEqual(addExtraPromptLanguage(current, "it").extraPromptLanguages, ["nl", "en", "es"]);
  assert.deepEqual(removeExtraPromptLanguage(current, "en").extraPromptLanguages, ["nl", "es"]);
});

test("a move lands where it was dropped, clamped to the list", () => {
  assert.deepEqual(moveExtraPromptLanguage(["nl", "en", "es"], 0, 2), ["en", "es", "nl"]);
  assert.deepEqual(moveExtraPromptLanguage(["nl", "en", "es"], 2, 0), ["es", "nl", "en"]);
  assert.deepEqual(moveExtraPromptLanguage(["nl", "en", "es"], 1, 9), ["nl", "es", "en"]);
  assert.deepEqual(moveExtraPromptLanguage(["nl", "en", "es"], 5, 0), ["nl", "en", "es"]);
});

test("suggestions are the browser's other languages, once, minus chosen and waved away", () => {
  assert.deepEqual(
    suggestedExtraPromptLanguages(["it-IT", "en-GB", "en-US", "fr", "ja", "nl"], current),
    ["fr"],
  );
  assert.deepEqual(
    suggestedExtraPromptLanguages(["de-CH", "fr-FR", "pt-BR"], current, ["fr"]),
    ["de", "pt"],
  );
  assert.deepEqual(suggestedExtraPromptLanguages(undefined, current), []);
});

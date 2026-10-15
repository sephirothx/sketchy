import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { fitsAGuess, judge, promptMatchKey } from "../src/lib/guessJudge.ts";

// The Python judge's verdicts (backend/tests/test_guess_judge_corpus.py
// writes them). The corpus names a form's text `answer`, as Python does;
// the wire and this port call it `prompt`.
const CORPUS = JSON.parse(
  readFileSync(new URL("../../fixtures/guess_judge_cases.json", import.meta.url)),
);

const form = ({ answer, aliases }) => ({ prompt: answer, aliases });

const target = (raw) => ({
  language: raw.language,
  own: form(raw.own),
  others: Object.fromEntries(
    Object.entries(raw.others).map(([language, other]) => [language, form(other)]),
  ),
  taken: raw.taken,
});

test("the corpus is not empty", () => {
  assert.ok(CORPUS.cases.length > 0);
});

for (const [index, entry] of CORPUS.cases.entries()) {
  test(`corpus ${index}: ${entry.note} - ${JSON.stringify(entry.text)}`, () => {
    assert.equal(judge(entry.text, target(entry.target)), entry.expected);
  });
}

test("a guess's length is counted in code points, whitespace collapsed", () => {
  // 32 emoji are 64 UTF-16 units and one guess.
  assert.equal(fitsAGuess("🍎".repeat(32)), true);
  assert.equal(fitsAGuess("🍎".repeat(33)), false);
  // Doubled and Python-only whitespace (\x1c, \x85, U+3000) collapses to one space.
  assert.equal(fitsAGuess(`${"a".repeat(16)}\x1c\x85　  ${"b".repeat(15)}`), true);
  assert.equal(fitsAGuess(`${"a".repeat(16)} ${"b".repeat(16)}`), false);
  // Trailing Python whitespace is stripped; U+FEFF is none to Python, though
  // it is to JavaScript's \s.
  assert.equal(fitsAGuess(`${"a".repeat(32)}\x1c\x85　`), true);
  assert.equal(fitsAGuess(`${"a".repeat(32)}﻿`), false);
});

test("keys case-fold as Python's str.casefold does, not toLowerCase", () => {
  assert.equal(promptMatchKey("Fußball", "de"), "fussball");
  assert.equal(promptMatchKey("GROẞ", "de"), "gross");
  assert.equal(promptMatchKey("ﬁsh", "en"), "fish");
  // A final sigma folds to the medial one, as a capital sigma does.
  assert.equal(promptMatchKey("ΚΌΣΜΟΣ", "en"), promptMatchKey("κόσμος", "en"));
  assert.equal(promptMatchKey("κόσμος", "en"), "κοσμοσ");
});

test("keys fold accents by combining class and drop separators", () => {
  assert.equal(promptMatchKey("Mädchen", "de"), "maedchen");
  assert.equal(promptMatchKey("Mädchen", "en"), "madchen");
  assert.equal(promptMatchKey("Mädchen", "de"), "maedchen");
  assert.equal(promptMatchKey("Łódź", "pl"), "lodz");
  assert.equal(promptMatchKey("hang‑glider", "en"), "hangglider");
  assert.equal(promptMatchKey("feu d’artifice", "fr"), "feudartifice");
  assert.equal(promptMatchKey("Nunu & Willump", "en"), "nunuandwillump");
  assert.equal(promptMatchKey("bad​word", "en"), "badword");
  // A mark of combining class 0 is no accent to `unicodedata.combining`.
  assert.equal(promptMatchKey("กั", "en"), "กั");
});

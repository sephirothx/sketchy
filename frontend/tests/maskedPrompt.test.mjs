import assert from "node:assert/strict";
import test from "node:test";

import { maskedWords, splitMaskedPrompt } from "../src/lib/maskedPrompt.ts";

test("the trailing counts are separated from the blanks", () => {
  assert.deepEqual(splitMaskedPrompt("___  _____  3 5"), {
    blanks: "___  _____",
    counts: ["3", "5"],
  });
  assert.deepEqual(splitMaskedPrompt("???"), { blanks: "???", counts: [] });
});

test("a plain word is one run of tiles", () => {
  assert.deepEqual(maskedWords("____"), [[{ kind: "tiles", chars: ["_", "_", "_", "_"] }]]);
});

test("words are grouped by whitespace, runs by punctuation", () => {
  // The server counts per alphanumeric run ("spider-man" reports "6 3"), so
  // band-aid must yield two runs - grouping by whitespace alone renders one
  // group and drops a count.
  assert.deepEqual(maskedWords("____-___"), [
    [
      { kind: "tiles", chars: ["_", "_", "_", "_"] },
      { kind: "glyph", text: "-" },
      { kind: "tiles", chars: ["_", "_", "_"] },
    ],
  ]);
  assert.deepEqual(maskedWords("___  _____"), [
    [{ kind: "tiles", chars: ["_", "_", "_"] }],
    [{ kind: "tiles", chars: ["_", "_", "_", "_", "_"] }],
  ]);
});

test("revealed letters stay inside their run", () => {
  assert.deepEqual(maskedWords("_a_'__"), [
    [
      { kind: "tiles", chars: ["_", "a", "_"] },
      { kind: "glyph", text: "'" },
      { kind: "tiles", chars: ["_", "_"] },
    ],
  ]);
});

test("a revealed accented letter is a tile, not punctuation", () => {
  // The server masks with str.isalnum, which is Unicode-aware; the client
  // must classify a revealed "à" the same way.
  assert.deepEqual(maskedWords("____à"), [
    [{ kind: "tiles", chars: ["_", "_", "_", "_", "à"] }],
  ]);
});

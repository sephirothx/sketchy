import assert from "node:assert/strict";
import test from "node:test";

import { MAX_NICKNAME_LENGTH, NICKNAME_PATTERN, keepNameCharacters, nameCharactersToInsert } from "../src/lib/roomEntryState.ts";

test("only the name rule's characters are entered", () => {
  assert.equal(keepNameCharacters("a b!c").value, "abc");
  assert.equal(keepNameCharacters("Ada_Lovelace-1815").value, "Ada_Lovelace-181");
  // Accented letters are their letters now (#1420), not deleted.
  assert.equal(keepNameCharacters("José Ñandú").value, "JoseNandu");
  assert.equal(keepNameCharacters("名前🙂").value, "");
});

test("a pasted space is dropped, not turned into an underscore", () => {
  assert.equal(keepNameCharacters("Jo Jo").value, "JoJo");
  assert.equal(keepNameCharacters("  Marta  ").value, "Marta");
});

test("the caret stays after what was typed", () => {
  // "ab|c" with "!" typed at the caret: the raw value is "ab!|c".
  assert.deepEqual(keepNameCharacters("ab!c", 3), { value: "abc", caret: 2 });
  // "Jo Jo" pasted into "x|y": raw "xJo Jo|y".
  assert.deepEqual(keepNameCharacters("xJo Joy", 6), { value: "xJoJoy", caret: 5 });
  assert.deepEqual(keepNameCharacters("abc", 3), { value: "abc", caret: 3 });
});

test("past the limit the new characters give way, not the end of the name", () => {
  const full = "abcdefghijklmnop";
  assert.equal(full.length, MAX_NICKNAME_LENGTH);
  // "X" typed after "abc" in a full name.
  assert.deepEqual(keepNameCharacters("abcXdefghijklmnop", 4), { value: full, caret: 3 });
  // A long paste into an empty field keeps its start.
  assert.deepEqual(keepNameCharacters("abcdefghijklmnopqrst"), { value: full, caret: 16 });
});

test("whatever it keeps can only fail the rule by being short or reserved", () => {
  for (const raw of ["a b!c", "Jo Jo", "x".repeat(40), "é-_é", "0123456789abcdefXYZ"]) {
    const { value } = keepNameCharacters(raw);
    assert.ok(value.length <= MAX_NICKNAME_LENGTH, raw);
    if (value.length >= 3) assert.match(value, NICKNAME_PATTERN, raw);
  }
});

test("an insertion keeps its allowed characters, up to the room left", () => {
  assert.equal(nameCharactersToInsert("!", 10), "");
  assert.equal(nameCharactersToInsert("Jo Jo", 10), "JoJo");
  assert.equal(nameCharactersToInsert("abc", 10), "abc");
  assert.equal(nameCharactersToInsert("1 2 3 4", 2), "12");
  assert.equal(nameCharactersToInsert("abc", 0), "");
  assert.equal(nameCharactersToInsert("🙂a", 5), "a");
});


test("a name in any of the eight languages keeps its letters, plainly (#1420)", () => {
  const names = {
    "Łukasz": "Lukasz",
    "Jürgen": "Jurgen",
    "José": "Jose",
    "François": "Francois",
    "Zoë": "Zoe",
    "Straße": "Strasse",
    "Przemysław": "Przemyslaw",
    "Søren": "Soren",
    "Ærø": "AEro",
    "Œdipe": "OEdipe",
    "Đorđe": "Dorde",
  };
  for (const [typed, plain] of Object.entries(names)) {
    // Pasted whole, cleaned up after the fact.
    assert.equal(keepNameCharacters(typed).value, plain, `pasted ${typed}`);
    // Typed a key at a time, each insertion filtered before it goes in.
    let value = "";
    for (const key of typed) value += nameCharactersToInsert(key, MAX_NICKNAME_LENGTH - value.length);
    assert.equal(value, plain, `typed ${typed}`);
    // Composed: the accent as its own combining mark after the letter.
    assert.equal(keepNameCharacters(typed.normalize("NFD")).value, plain, `composed ${typed}`);
    assert.ok(NICKNAME_PATTERN.test(plain), plain);
  }
});

test("the caret follows a folded letter, two-letter folds included", () => {
  // "Stra|e" with "ß" composed at the caret: raw "Straß|e" - the caret after "ss".
  assert.deepEqual(keepNameCharacters("Straße", 5), { value: "Strasse", caret: 6 });
  // "Jos|" with "é" committed by a dead key: raw "José|".
  assert.deepEqual(keepNameCharacters("José", 4), { value: "Jose", caret: 4 });
  // A combining mark typed on its own after the letter is nothing at all.
  assert.deepEqual(keepNameCharacters("Zoe\u0308", 4), { value: "Zoe", caret: 3 });
});

test("a two-letter fold goes in whole or not at all", () => {
  assert.equal(nameCharactersToInsert("ß", 2), "ss");
  assert.equal(nameCharactersToInsert("ß", 1), "", "half a letter is not the letter");
  assert.equal(nameCharactersToInsert("aß", 2), "a");
});

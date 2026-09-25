import assert from "node:assert/strict";
import test from "node:test";

import { MAX_NICKNAME_LENGTH, NICKNAME_PATTERN, nicknameInput } from "../src/lib/roomEntryState.ts";

test("only the name rule's characters are entered", () => {
  assert.equal(nicknameInput("a b!c").value, "abc");
  assert.equal(nicknameInput("Ada_Lovelace-1815").value, "Ada_Lovelace-181");
  assert.equal(nicknameInput("José Ñandú").value, "Josand");
  assert.equal(nicknameInput("名前🙂").value, "");
});

test("a pasted space is dropped, not turned into an underscore", () => {
  assert.equal(nicknameInput("Jo Jo").value, "JoJo");
  assert.equal(nicknameInput("  Marta  ").value, "Marta");
});

test("the caret stays after what was typed", () => {
  // "ab|c" with "!" typed at the caret: the raw value is "ab!|c".
  assert.deepEqual(nicknameInput("ab!c", 3), { value: "abc", caret: 2 });
  // "Jo Jo" pasted into "x|y": raw "xJo Jo|y".
  assert.deepEqual(nicknameInput("xJo Joy", 6), { value: "xJoJoy", caret: 5 });
  assert.deepEqual(nicknameInput("abc", 3), { value: "abc", caret: 3 });
});

test("past the limit the new characters give way, not the end of the name", () => {
  const full = "abcdefghijklmnop";
  assert.equal(full.length, MAX_NICKNAME_LENGTH);
  // "X" typed after "abc" in a full name.
  assert.deepEqual(nicknameInput("abcXdefghijklmnop", 4), { value: full, caret: 3 });
  // A long paste into an empty field keeps its start.
  assert.deepEqual(nicknameInput("abcdefghijklmnopqrst"), { value: full, caret: 16 });
});

test("whatever it keeps can only fail the rule by being short or reserved", () => {
  for (const raw of ["a b!c", "Jo Jo", "x".repeat(40), "é-_é", "0123456789abcdefXYZ"]) {
    const { value } = nicknameInput(raw);
    assert.ok(value.length <= MAX_NICKNAME_LENGTH, raw);
    if (value.length >= 3) assert.match(value, NICKNAME_PATTERN, raw);
  }
});

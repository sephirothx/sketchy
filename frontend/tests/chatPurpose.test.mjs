import assert from "node:assert/strict";
import test from "node:test";

import { inputPurposeFor } from "../src/lib/chatPurpose.ts";

test("a line is a guess only while this seat may guess (#1008)", () => {
  assert.equal(inputPurposeFor("playing", true), "guess");
  // The drawer choosing a prompt, the drawer drawing, a spectator, a seat
  // that already guessed: chat, sent as chat rather than as a guess scoped
  // to a turn that has moved on.
  assert.equal(inputPurposeFor("playing", false), "chat");
  assert.equal(inputPurposeFor("waiting", true), "chat");
  assert.equal(inputPurposeFor("waiting", false), "chat");
  assert.equal(inputPurposeFor("game-end", true), "chat");
});

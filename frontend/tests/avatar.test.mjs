import assert from "node:assert/strict";
import test from "node:test";

import { getAvatarColor, getInitials } from "../src/lib/avatar.ts";

test("getInitials handles single and multiple words", () => {
  assert.equal(getInitials("Alice"), "AL");
  assert.equal(getInitials("Alice Wonder"), "AW");
  assert.equal(getInitials("speedy artist pro"), "SA");
  assert.equal(getInitials(""), "?");
});

test("getAvatarColor returns gray for guests and custom color for registered", () => {
  assert.equal(getAvatarColor(true, "#ff0000"), "#888888");
  assert.equal(getAvatarColor(false, "#ff0000"), "#ff0000");
  assert.equal(getAvatarColor(false, null), "#3b82f6");
});

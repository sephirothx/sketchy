import assert from "node:assert/strict";
import test from "node:test";

import { initialsFromName } from "../src/lib/avatar.ts";
import { suggestUsername } from "../src/lib/username.ts";

test("initialsFromName uses the first letter", () => {
  assert.equal(initialsFromName("Ada"), "A");
  assert.equal(initialsFromName("Ada Lovelace"), "A");
  assert.equal(initialsFromName("  "), "?");
});

test("suggestUsername sanitizes guest nicknames", () => {
  assert.equal(suggestUsername("Cool Cat"), "Cool_Cat");
  assert.equal(suggestUsername("ab"), "");
});

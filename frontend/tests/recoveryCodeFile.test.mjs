import assert from "node:assert/strict";
import test from "node:test";

import {
  recoveryCodeFileBody,
  recoveryCodeFileName,
} from "../src/lib/recoveryCodeFile.ts";

const WHEN = new Date("2026-09-08T10:00:00Z");
const CODES = ["ABCDEFGHJK", "MNPQRSTVWX"];

test("the file is named for the account and the day it was made", () => {
  assert.equal(
    recoveryCodeFileName("Marmalade", WHEN),
    "sketchy-recovery-codes-marmalade-2026-09-08.txt",
  );
});

test("a name that is all punctuation still produces a usable filename", () => {
  assert.equal(
    recoveryCodeFileName("!!!", WHEN),
    "sketchy-recovery-codes-account-2026-09-08.txt",
  );
});

test("the file says what the codes are for and what holding them means", () => {
  const body = recoveryCodeFileBody("Marmalade", CODES, WHEN);
  assert.match(body, /signs you in once/);
  assert.match(body, /Anyone holding these/);
  assert.equal(body.includes("Marmalade"), true);
});

test("every code is in the file, one per line", () => {
  const body = recoveryCodeFileBody("Marmalade", CODES, WHEN);
  for (const code of CODES) {
    assert.equal(body.split("\n").some((line) => line.trim() === code), true);
  }
});

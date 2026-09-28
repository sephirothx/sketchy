import assert from "node:assert/strict";
import test from "node:test";

import { serverFullText } from "../src/lib/serverFullNotice.ts";
import { setCatalogue } from "../src/content/ui/index.ts";

test("the sentence says which ceiling turned the socket away (#1232)", () => {
  setCatalogue("en");
  assert.equal(serverFullText({ limit: "server" }), "Sketchy is full right now. Try again in a few minutes.");
  assert.equal(serverFullText({ limit: "account" }), "Sketchy is open in too many tabs. Close one to continue.");
});

test("an older server's notice, or a newer server's ceiling, reads as full", () => {
  setCatalogue("en");
  assert.equal(serverFullText(undefined), "Sketchy is full right now. Try again in a few minutes.");
  assert.equal(serverFullText({ reason: "Sketchy is full" }), "Sketchy is full right now. Try again in a few minutes.");
  assert.equal(serverFullText({ limit: "planet" }), "Sketchy is full right now. Try again in a few minutes.");
});

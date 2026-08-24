import assert from "node:assert/strict";
import test from "node:test";

import {
  canAdminister,
  canModerate,
  operatorEntries,
} from "../src/lib/operatorAccess.ts";

test("a moderator reviews reports; an administrator also runs the server", () => {
  assert.deepEqual(
    operatorEntries("moderator").map((entry) => entry.path),
    ["/moderation"],
  );
  assert.deepEqual(
    operatorEntries("admin").map((entry) => entry.path),
    ["/moderation", "/admin/operations"],
  );
});

test("an ordinary player is offered nothing", () => {
  assert.deepEqual(operatorEntries("user"), []);
  assert.equal(canModerate("user"), false);
  assert.equal(canAdminister("moderator"), false);
});

test("an unknown or missing role hides rather than reveals", () => {
  // The safe direction: a payload from an older server, or one that failed to
  // load, should not advertise a surface.
  assert.deepEqual(operatorEntries(undefined), []);
  assert.deepEqual(operatorEntries(null), []);
  assert.deepEqual(operatorEntries("superuser"), []);
});

test("a guest is never staff, whatever the payload claims", () => {
  assert.deepEqual(operatorEntries("admin", { isAnonymous: true }), []);
});

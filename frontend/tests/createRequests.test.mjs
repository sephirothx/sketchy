import assert from "node:assert/strict";
import test from "node:test";

import {
  CREATE_REQUEST_REUSE_MS,
  createRequestIds,
  mintRequestId,
} from "../src/lib/createRequests.ts";

function counter() {
  let n = 0;
  return () => `id-${(n += 1)}`;
}

test("a press retried with the same settings keeps its id (#879)", () => {
  const ids = createRequestIds(counter());
  assert.equal(ids.idFor("settings", 0), "id-1");
  assert.equal(ids.idFor("settings", 5000), "id-1");
});

test("different settings, a success, or a minute later is a new request", () => {
  const ids = createRequestIds(counter());
  ids.idFor("a", 0);
  assert.equal(ids.idFor("b", 1), "id-2", "the settings changed");
  ids.succeeded();
  assert.equal(ids.idFor("b", 2), "id-3", "the last one got in");
  assert.equal(ids.idFor("b", 3 + CREATE_REQUEST_REUSE_MS), "id-4", "the server has forgotten it");
});

test("a minted id is 128 random bits of hex", () => {
  const a = mintRequestId();
  assert.match(a, /^[0-9a-f]{32}$/);
  assert.notEqual(a, mintRequestId());
});

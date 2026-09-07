import assert from "node:assert/strict";
import test from "node:test";

import {
  isUpdateRequired,
  markUpdateRequired,
  onUpdateRequired,
  resetUpdateRequiredForTests,
} from "../src/lib/updateRequired.ts";

test("the flag is raised once and reaches late subscribers", () => {
  resetUpdateRequiredForTests();
  let calls = 0;
  const off = onUpdateRequired(() => { calls += 1; });
  assert.equal(isUpdateRequired(), false);
  markUpdateRequired();
  markUpdateRequired();
  assert.equal(calls, 1);
  assert.equal(isUpdateRequired(), true);
  off();
  let late = 0;
  onUpdateRequired(() => { late += 1; });
  assert.equal(late, 1);
});

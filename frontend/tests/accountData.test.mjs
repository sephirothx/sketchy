import assert from "node:assert/strict";
import test from "node:test";

import { exportFailureNote, exportLabel, pollDelayMs } from "../src/lib/accountData.ts";

test("a live or ready job reads as its state", () => {
  assert.equal(exportLabel({ status: "pending", failureCode: null }), "Queued");
  assert.equal(exportLabel({ status: "processing", failureCode: null }), "Preparing…");
  assert.equal(exportLabel({ status: "ready", failureCode: null }), "Ready");
  assert.equal(exportFailureNote({ status: "ready", failureCode: null }), null);
});

test("a document past the server's ceiling is named as such, not as a fault", () => {
  const job = { status: "failed", failureCode: "too_large" };
  assert.equal(exportLabel(job), "Too large to prepare here");
  assert.match(exportFailureNote(job), /larger than this server/);
  assert.match(exportFailureNote(job), /operator/);
});

test("any other failure keeps the generic label and invites another request", () => {
  const job = { status: "failed", failureCode: "generation_failed" };
  assert.equal(exportLabel(job), "Could not prepare");
  assert.match(exportFailureNote(job), /request another/);
  assert.equal(exportLabel({ status: "failed", failureCode: null }), "Could not prepare");
});

test("polling is brisk for the first ten seconds and settles after", () => {
  assert.equal(pollDelayMs(0), 1_000);
  assert.equal(pollDelayMs(9_999), 1_000);
  assert.equal(pollDelayMs(10_000), 5_000);
  assert.equal(pollDelayMs(120_000), 5_000);
});

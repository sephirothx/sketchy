import assert from "node:assert/strict";
import test from "node:test";

import { parseShutdownNotice } from "../src/lib/shutdownNotice.ts";

const notice = {
  contractVersion: 1,
  reason: "deployment",
  drainSeconds: 30,
  startedAt: "2026-08-23T12:00:00+00:00",
};

test("the current deployment notice is accepted as sent", () => {
  assert.deepEqual(parseShutdownNotice(notice), notice);
});

test("a zero-second window is a real window, not a missing one", () => {
  assert.deepEqual(parseShutdownNotice({ ...notice, drainSeconds: 0 }), {
    ...notice,
    drainSeconds: 0,
  });
});

test("a later contract version is ignored rather than half-rendered", () => {
  assert.equal(parseShutdownNotice({ ...notice, contractVersion: 2 }), null);
});

test("only a deployment is announced as a deployment", () => {
  assert.equal(parseShutdownNotice({ ...notice, reason: "maintenance" }), null);
});

test("a malformed or absent payload never opens the banner", () => {
  for (const payload of [
    null,
    undefined,
    "server_shutdown",
    {},
    { ...notice, drainSeconds: "30" },
    { ...notice, drainSeconds: Number.NaN },
    { ...notice, drainSeconds: -1 },
    { ...notice, startedAt: 1234 },
  ]) {
    assert.equal(parseShutdownNotice(payload), null);
  }
});

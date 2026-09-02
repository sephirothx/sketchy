import assert from "node:assert/strict";
import test from "node:test";

import {
  FIRST_RETRY_MS,
  MAX_RETRY_MS,
  resubscribeDelayMs,
} from "../src/lib/lobbyChannel.ts";

test("the first retry is soon and the rest back off", () => {
  assert.equal(resubscribeDelayMs(1), FIRST_RETRY_MS);
  assert.equal(resubscribeDelayMs(2), 2000);
  assert.equal(resubscribeDelayMs(3), 4000);
  assert.equal(resubscribeDelayMs(4), 8000);
});

test("the wait is capped, so a recovery is noticed promptly", () => {
  // A server refusing every subscription still hears from each open lobby, so
  // this cannot grow without bound - and it must not shrink to a retry loop
  // that is itself the outage.
  for (const attempt of [10, 50, 1000]) {
    assert.equal(resubscribeDelayMs(attempt), MAX_RETRY_MS, String(attempt));
  }
});

test("a nonsense attempt still yields a usable wait", () => {
  for (const attempt of [0, -1, Number.NaN]) {
    assert.equal(resubscribeDelayMs(attempt), FIRST_RETRY_MS, String(attempt));
  }
});

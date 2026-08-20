import assert from "node:assert/strict";
import test from "node:test";

import { createCanvasSyncRequester } from "../src/lib/canvasSyncRequests.ts";

function createEnvironment() {
  const timers = new Map();
  let nextId = 1;
  const environment = {
    requests: 0,
    requestSync() {
      environment.requests += 1;
    },
    setTimeout(handler, delayMs) {
      const id = nextId++;
      timers.set(id, { handler, delayMs });
      return id;
    },
    clearTimeout(timeoutId) {
      timers.delete(timeoutId);
    },
    pending() {
      return timers.size;
    },
    /** Run every armed timer, as the browser would once the delay elapses. */
    elapse() {
      const armed = [...timers.entries()];
      timers.clear();
      for (const [, timer] of armed) timer.handler();
    },
  };
  return environment;
}

test("a second ask while one is outstanding is coalesced into one follow-up", () => {
  const environment = createEnvironment();
  const requester = createCanvasSyncRequester(environment);

  requester.request();
  requester.request();
  requester.request();
  assert.equal(environment.requests, 1);

  requester.arrived();
  requester.drainQueued();
  assert.equal(environment.requests, 2);

  // Only one follow-up, however many asks were coalesced into it.
  requester.arrived();
  requester.drainQueued();
  assert.equal(environment.requests, 2);
});

test("an unanswered request releases the latch instead of jamming it", () => {
  const environment = createEnvironment();
  const requester = createCanvasSyncRequester(environment);

  requester.request();
  assert.equal(environment.requests, 1);

  // The server answers request_sync_strokes only for a socket that already
  // resolves to a seat in a live game, and says nothing at all otherwise.
  environment.elapse();

  requester.request();
  assert.equal(environment.requests, 2, "the next ask must still get through");
});

test("an ask made during an unanswered request survives the timeout", () => {
  const environment = createEnvironment();
  const requester = createCanvasSyncRequester(environment);

  requester.request();
  requester.request();
  assert.equal(environment.requests, 1);

  environment.elapse();
  assert.equal(
    environment.requests,
    2,
    "the need for a sync outlived the request that went unanswered",
  );
});

test("an unanswered request that nobody repeated does not poll", () => {
  const environment = createEnvironment();
  const requester = createCanvasSyncRequester(environment);

  requester.request();
  environment.elapse();
  environment.elapse();

  assert.equal(environment.requests, 1);
  assert.equal(environment.pending(), 0, "no timer is left armed");
});

test("an arrived sync disarms the timeout", () => {
  const environment = createEnvironment();
  const requester = createCanvasSyncRequester(environment);

  requester.request();
  requester.arrived();
  assert.equal(environment.pending(), 0);

  // Nothing was queued, so the arrival alone must not ask again.
  requester.drainQueued();
  assert.equal(environment.requests, 1);
});

test("reset drops an outstanding request and anything queued behind it", () => {
  const environment = createEnvironment();
  const requester = createCanvasSyncRequester(environment);

  requester.request();
  requester.request();
  requester.reset();

  assert.equal(environment.pending(), 0);
  requester.drainQueued();
  assert.equal(environment.requests, 1, "the stale follow-up is dropped");

  // And the latch is open again for the new generation.
  requester.request();
  assert.equal(environment.requests, 2);
});

test("a fresh request after a timeout is itself protected by a timeout", () => {
  const environment = createEnvironment();
  const requester = createCanvasSyncRequester(environment);

  requester.request();
  environment.elapse();
  requester.request();
  assert.equal(environment.pending(), 1);

  environment.elapse();
  requester.request();
  assert.equal(environment.requests, 3, "the latch cannot re-jam");
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  CANVAS_SYNC_RETRIES_MS,
  CANVAS_SYNC_TIMEOUT_MS,
  createCanvasSyncRequester,
} from "../src/lib/canvasSyncRequests.ts";

function harness({ claim = null, answer = () => ({ ok: true }) } = {}) {
  const state = { now: 0, timers: [], sent: [], exhausted: 0, claim, answer };
  const env = {
    send: (requestId, claimed) => {
      state.sent.push({ requestId, claim: claimed, at: state.now });
      const reply = state.answer(requestId);
      return reply instanceof Error ? Promise.reject(reply) : Promise.resolve(reply);
    },
    claim: () => state.claim,
    exhausted: () => { state.exhausted += 1; },
    setTimeout: (handler, delayMs) => {
      const handle = { at: state.now + delayMs, handler };
      state.timers.push(handle);
      return handle;
    },
    clearTimeout: (handle) => {
      state.timers = state.timers.filter((timer) => timer !== handle);
    },
  };
  const advance = async (ms) => {
    const until = state.now + ms;
    for (;;) {
      await Promise.resolve();
      const due = state.timers.filter((t) => t.at <= until).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      state.now = due.at;
      state.timers = state.timers.filter((t) => t !== due);
      due.handler();
    }
    state.now = until;
    await Promise.resolve();
  };
  return { requester: createCanvasSyncRequester(env), state, advance };
}

const CLAIM = { generation: 4, actionCount: 3, historyHash: 99 };

test("a request carries an id and the claim captured at that moment", () => {
  const { requester, state } = harness({ claim: CLAIM });
  requester.request();
  assert.deepEqual(state.sent, [{ requestId: 1, claim: CLAIM, at: 0 }]);
  assert.equal(requester.outstanding, 1);
});

test("request a tail, draw locally, the tail arrives: it is the answer to that request", () => {
  const { requester } = harness({ claim: CLAIM });
  requester.request();
  // The drawer drew in between; the claim was captured before, so the tail
  // must be cut for the claimed prefix, whatever the history looks like now.
  assert.equal(requester.classify({ requestId: 1, generation: 4, baseActionCount: 3 }), "matches");
  assert.equal(requester.classify({ requestId: 1, generation: 4, baseActionCount: 5 }), "stale", "cut for a prefix that was not claimed");
  assert.equal(requester.classify({ requestId: 1, generation: 5, baseActionCount: 3 }), "stale", "another generation");
});

test("a reply to a request abandoned by a reset is stale; a server-pushed sync never is", () => {
  const { requester } = harness({ claim: CLAIM });
  requester.request();
  requester.reset();
  assert.equal(requester.classify({ requestId: 1, generation: 4 }), "stale");
  assert.equal(requester.classify({ requestId: 0, generation: 9 }), "unsolicited");
  requester.request();
  assert.equal(requester.classify({ requestId: 1, generation: 4 }), "stale", "an old id after a room switch");
  assert.equal(requester.classify({ requestId: 2, generation: 4 }), "matches");
});

test("a dropped request with no later drawing is retried with backoff, then handed over", async () => {
  const { requester, state, advance } = harness({ answer: () => ({ ok: true }) });
  requester.request();
  assert.equal(state.sent.length, 1);
  await advance(CANVAS_SYNC_TIMEOUT_MS);
  await advance(CANVAS_SYNC_RETRIES_MS[1]);
  assert.equal(state.sent.length, 2, "retried after the timeout and the backoff");
  await advance(CANVAS_SYNC_TIMEOUT_MS + CANVAS_SYNC_RETRIES_MS[2]);
  assert.equal(state.sent.length, 3);
  await advance(CANVAS_SYNC_TIMEOUT_MS);
  assert.equal(state.exhausted, 1, "the third loss hands the session over");
  assert.equal(requester.outstanding, null);
  await advance(60_000);
  assert.equal(state.sent.length, 3, "nothing more on its own");
});

test("a throttled request waits the server's retryAfterMs and asks again", async () => {
  let calls = 0;
  const { requester, state, advance } = harness({
    answer: () => (calls++ === 0 ? { ok: false, errorCode: "too_fast", retryAfterMs: 6_000 } : { ok: true }),
  });
  requester.request();
  await advance(CANVAS_SYNC_RETRIES_MS[1]);
  assert.equal(state.sent.length, 1, "not before the server said");
  await advance(6_000 - CANVAS_SYNC_RETRIES_MS[1]);
  assert.equal(state.sent.length, 2);
  assert.equal(state.sent[1].requestId, 2, "a retry is a new request");
});

test("a refusal with no canvas to send is retried after its delay, and a socket that never answers is a loss", async () => {
  let calls = 0;
  const { requester, state, advance } = harness({
    answer: () => (calls++ === 0 ? { ok: false, errorCode: "not_in_game", retryAfterMs: 2_000 } : new Error("disconnected")),
  });
  requester.request();
  await advance(2_000);
  assert.equal(state.sent.length, 1, "the backoff is a floor under the server's delay");
  await advance(CANVAS_SYNC_RETRIES_MS[1] - 2_000);
  assert.equal(state.sent.length, 2);
  await advance(CANVAS_SYNC_RETRIES_MS[2]);
  assert.equal(state.sent.length, 3);
});

test("triggers coalesced during a transaction are discharged by a converged reply and re-issued by one that did not", () => {
  const { requester, state } = harness();
  requester.request();
  requester.request();
  requester.request();
  assert.equal(state.sent.length, 1);
  requester.applied(true);
  assert.equal(state.sent.length, 1, "one reply satisfied all three");
  requester.request();
  requester.request();
  requester.applied(false);
  assert.equal(state.sent.length, 3, "a reply that did not converge asks once more");
});

test("a malformed tail is a non-converged reply: the follow-up is a full request", () => {
  const claims = [CLAIM, null];
  const { requester, state } = harness({ claim: claims[0] });
  requester.request();
  assert.equal(requester.classify({ requestId: 1, generation: 4, baseActionCount: 3 }), "matches");
  state.claim = null; // the client now holds pending work and can claim nothing
  requester.request();
  requester.applied(false);
  assert.equal(state.sent.length, 2);
  assert.equal(state.sent[1].claim, null);
});

test("an arrived reply disarms the loss timer", async () => {
  const { requester, state, advance } = harness();
  requester.request();
  requester.applied(true);
  await advance(CANVAS_SYNC_TIMEOUT_MS * 3);
  assert.equal(state.sent.length, 1);
  assert.equal(state.exhausted, 0);
});

test("reset drops an outstanding transaction, its retries and anything queued", async () => {
  const { requester, state, advance } = harness({ answer: () => ({ ok: false, errorCode: "too_fast", retryAfterMs: 1_000 }) });
  requester.request();
  requester.request();
  requester.reset();
  await advance(60_000);
  assert.equal(state.sent.length, 1);
  assert.equal(state.exhausted, 0);
});

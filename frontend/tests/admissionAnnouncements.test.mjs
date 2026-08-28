import assert from "node:assert/strict";
import test from "node:test";

import {
  announcementsAfter,
  NO_ANNOUNCEMENTS,
} from "../src/lib/admissionAnnouncements.ts";
import { mergeAdmission } from "../src/lib/adminControls.ts";

const fold = (...events) => events.reduce(announcementsAfter, NO_ANNOUNCEMENTS);

test("nothing is asserted before anything is announced", () => {
  assert.deepEqual(NO_ANNOUNCEMENTS, {
    draining: false,
    paused: null,
    connection: 0,
  });
});

test("a drain is remembered for the rest of its connection", () => {
  const state = fold({ type: "connect" }, { type: "draining" });
  assert.equal(state.draining, true);
});

test("losing the connection forgets what that process announced", () => {
  // The bug this exists for: a drain ends the process that announced it, so
  // carrying the announcement into the next connection is the old server's
  // last words about the new one. And because the merge ORs it, no fresh
  // snapshot could correct it - an operations page left open across a restart
  // stayed locked down until somebody reloaded it.
  const stuck = fold({ type: "connect" }, { type: "draining" });
  const reconnected = fold(
    { type: "connect" },
    { type: "draining" },
    { type: "disconnect" },
    { type: "connect" },
  );

  assert.equal(reconnected.draining, false);
  assert.equal(reconnected.paused, null);
  assert.equal(reconnected.connection, stuck.connection + 1);

  // What the page then computes, with a snapshot from the new server.
  const healthy = { paused: false, draining: false };
  assert.deepEqual(mergeAdmission(healthy, reconnected), healthy);
  assert.deepEqual(
    mergeAdmission(healthy, stuck),
    { paused: false, draining: true },
    "and would still be stuck, without the reset",
  );
});

test("a pause does not outlive the connection that announced it", () => {
  // State can change while a client is away: pause, drop, another operator
  // resumes, reconnect. An unpaused server sends no notice, so a cached
  // `true` would claim for ever that rooms are paused.
  const state = fold(
    { type: "connect" },
    { type: "paused", paused: true },
    { type: "disconnect" },
    { type: "connect" },
  );
  assert.equal(state.paused, null);
  assert.equal(mergeAdmission({ paused: false, draining: false }, state).paused, false);
});

test("the reset happens on disconnect, so handshake notices survive connect", () => {
  // Load-bearing ordering. A paused server says so from inside its connection
  // handler, and socket.io-client buffers that event and flushes it in
  // `onconnect` *before* emitting `connect` - so a reset on `connect` erases
  // the state the new server had just sent. Clearing when the old connection
  // ended leaves nothing to erase.
  const state = fold(
    { type: "connect" },
    { type: "disconnect" },
    { type: "paused", paused: true },
    { type: "connect" },
  );
  assert.equal(state.paused, true, "the new server's handshake notice stands");
});

test("a resume replaces a pause within one connection", () => {
  const state = fold(
    { type: "connect" },
    { type: "paused", paused: true },
    { type: "paused", paused: false },
  );
  assert.equal(state.paused, false);
});

test("each connection is counted, so a reader knows its snapshot is stale", () => {
  const state = fold({ type: "connect" }, { type: "connect" }, { type: "connect" });
  assert.equal(state.connection, 3);
});

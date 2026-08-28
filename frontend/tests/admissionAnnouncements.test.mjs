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

test("a reconnect forgets what the previous process announced", () => {
  // The bug this exists for: a drain ends the process that announced it, so
  // carrying the announcement across a reconnect is the old server's last
  // words about the new one. And because the merge ORs it, no fresh snapshot
  // could correct it - an operations page left open across a restart stayed
  // locked down until somebody reloaded it.
  const stuck = fold({ type: "connect" }, { type: "draining" });
  const reconnected = announcementsAfter(stuck, { type: "connect" });

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

test("a pause announced before a reconnect does not outlive it", () => {
  // State can change while a client is disconnected, so a cached pause stops
  // being authoritative the moment the connection does.
  const state = fold(
    { type: "connect" },
    { type: "paused", paused: true },
    { type: "connect" },
  );
  assert.equal(state.paused, null);
  assert.equal(mergeAdmission({ paused: false, draining: false }, state).paused, false);
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

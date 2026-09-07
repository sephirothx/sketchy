import assert from "node:assert/strict";
import test from "node:test";

import {
  HEARTBEAT_MS,
  MAX_GAP_MS,
  createHeartbeatSchedule,
  replyIsCurrent,
} from "../src/lib/heartbeatSchedule.ts";

const DRAWING = { phase: "drawing", round: 1 };

test("a probe goes on every tick when the seat has heard nothing authoritative", () => {
  const schedule = createHeartbeatSchedule();
  let now = 100_000;
  for (let tick = 0; tick < 4; tick += 1) {
    assert.equal(schedule.shouldProbe(now, DRAWING), true);
    schedule.noteProbe(now);
    now += HEARTBEAT_MS;
  }
  assert.equal(schedule.skipped(), 0);
});

test("an authoritative event that agrees with the seat stands in for the next probe", () => {
  const schedule = createHeartbeatSchedule();
  let now = 100_000;
  schedule.noteProbe(now);
  now += HEARTBEAT_MS;
  schedule.noteAuthoritative(DRAWING, now - 1000); // a turn_started a second ago
  assert.equal(schedule.shouldProbe(now, DRAWING), false);
  assert.equal(schedule.skipped(), 1);
  // Nothing more arrives: the tick after that probes again.
  now += HEARTBEAT_MS;
  assert.equal(schedule.shouldProbe(now, DRAWING), true);
});

test("an authoritative event that disagrees with the seat does not cover it", () => {
  // The server says results; the seat still thinks it is drawing. That is
  // exactly the drift a probe is for.
  const schedule = createHeartbeatSchedule();
  const now = 100_000;
  schedule.noteProbe(now - HEARTBEAT_MS);
  schedule.noteAuthoritative({ phase: "turn_results", round: 1 }, now - 500);
  assert.equal(schedule.shouldProbe(now, DRAWING), true);
  schedule.noteAuthoritative({ phase: "drawing", round: 2 }, now - 500);
  assert.equal(schedule.shouldProbe(now, DRAWING), true);
});

test("a probe is forced at the cap however much the seat was told", () => {
  const schedule = createHeartbeatSchedule();
  let now = 100_000;
  schedule.noteProbe(now);
  let probes = 0;
  for (let tick = 1; tick <= 6; tick += 1) {
    now += HEARTBEAT_MS;
    schedule.noteAuthoritative(DRAWING, now - 100); // a matching event every tick
    if (schedule.shouldProbe(now, DRAWING)) {
      probes += 1;
      schedule.noteProbe(now);
    }
  }
  // Ticks at 5 and 10 s are covered; 15 s is the cap; 20 and 25 covered; 30 the cap.
  assert.equal(probes, 2);
  assert.equal(MAX_GAP_MS, 15_000);
});

test("unrelated traffic is not an input at all", () => {
  // The schedule has no way to be told about a draw frame or a chat line:
  // only authoritative events and probes move it. A seat that saw nothing
  // else for ten seconds probes on both ticks.
  const schedule = createHeartbeatSchedule();
  let now = 100_000;
  schedule.noteProbe(now);
  now += HEARTBEAT_MS;
  assert.equal(schedule.shouldProbe(now, DRAWING), true);
  schedule.noteProbe(now);
  now += HEARTBEAT_MS;
  assert.equal(schedule.shouldProbe(now, DRAWING), true);
});

test("a reply is judged only from the socket, room and seat it was sent on, and before the seat moved", () => {
  const scope = { socketId: "s1", code: "ABC", playerId: "p1", sentAt: 1000 };
  const here = { socketId: "s1", code: "ABC", playerId: "p1", lastAuthoritativeAt: 900 };
  assert.equal(replyIsCurrent(scope, here), true);
  assert.equal(replyIsCurrent(scope, { ...here, socketId: "s2" }), false, "a reconnect happened");
  assert.equal(replyIsCurrent(scope, { ...here, code: "XYZ" }), false, "another room");
  assert.equal(replyIsCurrent(scope, { ...here, playerId: "p2" }), false, "another seat");
  assert.equal(replyIsCurrent(scope, { ...here, lastAuthoritativeAt: 1500 }), false, "the seat moved after the probe left");
  assert.equal(replyIsCurrent(scope, { ...here, lastAuthoritativeAt: null }), true);
});

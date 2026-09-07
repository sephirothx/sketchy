import assert from "node:assert/strict";
import test from "node:test";

import { lastSeenLabel } from "../src/lib/lastSeen.ts";

const now = new Date("2026-09-07T12:00:00Z");
const ago = (seconds) => new Date(now.getTime() - seconds * 1000).toISOString();

test("a player who is here is online, whatever the clock says", () => {
  assert.equal(lastSeenLabel({ isOnline: true, lastSeenAt: ago(86400) }, now), "online");
});

test("an account that never connected says nothing", () => {
  assert.equal(lastSeenLabel({ isOnline: false, lastSeenAt: null }, now), null);
});

test("an absence is rounded down to the largest unit that fits", () => {
  assert.equal(lastSeenLabel({ isOnline: false, lastSeenAt: ago(30) }, now), "last seen just now");
  assert.equal(lastSeenLabel({ isOnline: false, lastSeenAt: ago(60) }, now), "last seen 1 minute ago");
  assert.equal(lastSeenLabel({ isOnline: false, lastSeenAt: ago(59 * 60) }, now), "last seen 59 minutes ago");
  assert.equal(lastSeenLabel({ isOnline: false, lastSeenAt: ago(3 * 3600) }, now), "last seen 3 hours ago");
  assert.equal(lastSeenLabel({ isOnline: false, lastSeenAt: ago(40 * 86400) }, now), "last seen 40 days ago");
});

test("a clock that is ahead of the server reads as just now, not the future", () => {
  assert.equal(lastSeenLabel({ isOnline: false, lastSeenAt: ago(-120) }, now), "last seen just now");
});

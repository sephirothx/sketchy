import assert from "node:assert/strict";
import test from "node:test";

import {
  FIRST_CONNECT_GRACE_MS,
  RECONNECT_GRACE_MS,
  connectionBannerDelayMs,
  resolveConnectionStatus,
} from "../src/lib/connectionStatus.ts";

const connected = { online: true, socketConnected: true, binding: "ready" };

test("a connected socket with a bound room session needs no banner", () => {
  assert.equal(resolveConnectionStatus(connected), "connected");
});

test("being offline outranks every other signal", () => {
  assert.equal(
    resolveConnectionStatus({ online: false, socketConnected: true, binding: "failed" }),
    "offline",
  );
  assert.equal(
    resolveConnectionStatus({ online: false, socketConnected: false, binding: "ready" }),
    "offline",
  );
});

test("a missing socket reads as reconnecting", () => {
  assert.equal(resolveConnectionStatus({ ...connected, socketConnected: false }), "reconnecting");
});

test("room binding state surfaces while the socket is up", () => {
  assert.equal(resolveConnectionStatus({ ...connected, binding: "rejoining" }), "reconnecting");
  assert.equal(resolveConnectionStatus({ ...connected, binding: "failed" }), "failed");
});

test("statuses other than reconnecting show immediately", () => {
  for (const status of ["connected", "offline", "failed"]) {
    assert.equal(connectionBannerDelayMs(status, true), 0);
    assert.equal(connectionBannerDelayMs(status, false), 0);
  }
});

test("the first connection gets a longer grace than a reconnect", () => {
  assert.equal(connectionBannerDelayMs("reconnecting", false), FIRST_CONNECT_GRACE_MS);
  assert.equal(connectionBannerDelayMs("reconnecting", true), RECONNECT_GRACE_MS);
  assert.ok(FIRST_CONNECT_GRACE_MS > RECONNECT_GRACE_MS);
});

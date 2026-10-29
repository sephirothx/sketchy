import assert from "node:assert/strict";
import test from "node:test";

import { roomCodeFromScan } from "../src/lib/scannedRoomCode.ts";

const ORIGIN = "https://sketchy.example";

test("the invite QR's own link reads as its room code", () => {
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/BQ7F2K`, ORIGIN), "BQ7F2K");
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/bq7f2k/`, ORIGIN), "BQ7F2K");
  // A query or fragment a camera app might have kept does not change the room.
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/BQ7F2K?from=qr#x`, ORIGIN), "BQ7F2K");
});

test("a bare code reads as itself", () => {
  assert.equal(roomCodeFromScan("bq7f2k", ORIGIN), "BQ7F2K");
  assert.equal(roomCodeFromScan("  BQ7F2K \n", ORIGIN), "BQ7F2K");
});

test("anything that is not this site's room is refused, never followed", () => {
  // Another host, even with the same path: a lookalike's room.
  assert.equal(roomCodeFromScan("https://evil.example/room/BQ7F2K", ORIGIN), null);
  assert.equal(roomCodeFromScan("http://sketchy.example/room/BQ7F2K", ORIGIN), null);
  // This host, but not a room.
  assert.equal(roomCodeFromScan(`${ORIGIN}/rules`, ORIGIN), null);
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/BQ7F2K/extra`, ORIGIN), null);
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/BQ7F`, ORIGIN), null);
  // Whatever else QR codes carry.
  assert.equal(roomCodeFromScan("WIFI:S:Cafe;T:WPA;P:secret;;", ORIGIN), null);
  assert.equal(roomCodeFromScan("javascript:alert(1)", ORIGIN), null);
  assert.equal(roomCodeFromScan("BQ7F2K9", ORIGIN), null);
  assert.equal(roomCodeFromScan("", ORIGIN), null);
});

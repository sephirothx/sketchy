import assert from "node:assert/strict";
import test from "node:test";

import { roomCodeFromScan } from "../src/lib/scannedRoomCode.ts";

const ORIGIN = "https://sketchy.example";

test("the invite QR's own link reads as its room code", () => {
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/BQ7F2K`), "BQ7F2K");
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/bq7f2k/`), "BQ7F2K");
  // A query or fragment a camera app might have kept does not change the room.
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/BQ7F2K?from=qr#x`), "BQ7F2K");
});

test("a bare code reads as itself", () => {
  assert.equal(roomCodeFromScan("bq7f2k"), "BQ7F2K");
  assert.equal(roomCodeFromScan("  BQ7F2K \n"), "BQ7F2K");
});

test("a room link from another address reads as its code", () => {
  // The same server reached another way - localhost and a tunnel, a LAN
  // address - draws its invite with the address it was opened on.
  assert.equal(roomCodeFromScan("http://localhost:8000/room/BQ7F2K"), "BQ7F2K");
  assert.equal(roomCodeFromScan("http://192.168.1.20:8000/room/bq7f2k"), "BQ7F2K");
});

test("anything that is not a room is refused, never followed", () => {
  // A room's path under a scheme that is not the web's.
  assert.equal(roomCodeFromScan("ftp://sketchy.example/room/BQ7F2K"), null);
  // A room link, but not a room.
  assert.equal(roomCodeFromScan(`${ORIGIN}/rules`), null);
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/BQ7F2K/extra`), null);
  assert.equal(roomCodeFromScan(`${ORIGIN}/room/BQ7F`), null);
  // Whatever else QR codes carry.
  assert.equal(roomCodeFromScan("WIFI:S:Cafe;T:WPA;P:secret;;"), null);
  assert.equal(roomCodeFromScan("javascript:alert(1)"), null);
  assert.equal(roomCodeFromScan("BQ7F2K9"), null);
  assert.equal(roomCodeFromScan(""), null);
});

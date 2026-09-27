import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

// Every command that can make a seat has to say which language it plays in
// (#1182): a mixed-language room plays each seat in its own, and a seat made
// without one plays in English. The server cannot tell a forgotten field from
// a player who chose English, and the wire-contract test only asks whether
// the name appears somewhere in the client - so a call moved to a new file
// without it (#1187's invitation hook) would fail silently.

function sources(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

const SEAT_MAKING = /\bemit(?:Entry|WithAck)\s*<[^>]*>\s*\(\s*"(create_room|join_room|join_friend_room)"\s*,\s*(\{[\s\S]*?\})\s*\)/g;

test("every command that can make a seat sends its language", () => {
  const calls = [];
  for (const path of sources(new URL("../src", import.meta.url).pathname)) {
    const text = readFileSync(path, "utf8");
    for (const match of text.matchAll(SEAT_MAKING)) {
      const [, command, payload] = match;
      // Asking whether a seat is already held makes none.
      if (payload.includes("reconnectOnly: true")) continue;
      calls.push({ path, command, payload });
    }
  }
  assert.ok(calls.some((call) => call.command === "join_friend_room"), "found no invitation join");
  assert.ok(calls.some((call) => call.command === "create_room"), "found no create");
  for (const call of calls) {
    assert.ok(
      /\bseatLanguage\b/.test(call.payload) || /\.\.\.settings\b/.test(call.payload),
      `${call.command} in ${call.path} sends no seatLanguage`,
    );
  }
});

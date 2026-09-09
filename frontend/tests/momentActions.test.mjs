import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";

/** R-CONN-06, read off the tree: an action that only makes sense in the
moment must never be sent with a buffering emit.

`socket.emit` queues while the transport is down and delivers on reconnect.
For a guess, a vote, leaving, or toggling AFK that is exactly wrong — the
packet arrives into whatever the room has since become. The AFK answer is the
sharpest case, because the thing it undoes may be the AFK status the missed
deadline just set, or the one the player set on themselves while disconnected.

Convention alone did not hold this: every call site used `emitTransient`
because each author happened to know, and the first one that did not (#677's
AFK answer) compiled, linted and passed every other test. So it is read off
the source, the way `backend/tests/test_wire_contract.py` reads both trees for
names neither compiler checks.

Deliberately not a ban on `socket.emit` outright. An action that expects an
answer — creating a room, joining, starting, voting to restart — is handed to
`emitWithAck`, which waits for the connection on purpose. Only these four are
moment-scoped. */

const SRC = path.join(import.meta.dirname, "..", "src");

/** The commands R-CONN-06 names, by the wire names they are sent under. */
const MOMENT_ACTIONS = ["guess", "vote_player", "leave_room", "toggle_afk"];

function sourceFiles(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) return sourceFiles(full);
    return /\.tsx?$/.test(entry) ? [full] : [];
  });
}

test("no moment-scoped action is sent with a buffering emit", () => {
  const offenders = [];
  for (const file of sourceFiles(SRC)) {
    const text = readFileSync(file, "utf8");
    for (const action of MOMENT_ACTIONS) {
      // `socket.emit("guess"` and friends — but not `emitTransient("guess"`,
      // and not `target.emitTransient(`, which is the seam the guess sender
      // is tested through.
      const buffering = new RegExp(
        String.raw`(?<!Transient)\bemit\(\s*["']${action}["']`,
      );
      if (buffering.test(text)) {
        offenders.push(`${path.relative(SRC, file)} → ${action}`);
      }
    }
  }
  assert.deepEqual(
    offenders,
    [],
    "R-CONN-06: these must use emitTransient, or they replay into a room that moved on",
  );
});

test("the guard would catch a buffering emit if one were written", () => {
  // The regex is the whole test, so it gets a test of its own: a guard that
  // silently matches nothing is worse than no guard, because it reads as
  // coverage.
  const buffering = new RegExp(String.raw`(?<!Transient)\bemit\(\s*["']toggle_afk["']`);
  assert.equal(buffering.test('socket.emit("toggle_afk", { afk: false })'), true);
  assert.equal(buffering.test("socket.emit('toggle_afk')"), true);
  assert.equal(buffering.test('emitTransient("toggle_afk", { afk: false })'), false);
  assert.equal(buffering.test('emitWithAck("start_game", {})'), false);
});

test("every action R-CONN-06 names is actually looked for", () => {
  // A typo in a wire name here would quietly stop guarding that command.
  const text = sourceFiles(SRC)
    .map((file) => readFileSync(file, "utf8"))
    .join("\n");
  for (const action of MOMENT_ACTIONS) {
    assert.ok(
      text.includes(`"${action}"`) || text.includes(`'${action}'`),
      `${action} appears in no source file — renamed on the wire?`,
    );
  }
});

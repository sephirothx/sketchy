import assert from "node:assert/strict";
import { test } from "node:test";

import {
  EMPTY_LOBBY_CHAT,
  MAX_HELD_LINES,
  applyChatBacklog,
  applyChatLine,
  applyLineVisibility,
  chatResumeRequest,
  chatTimeLabel,
  parseLine,
  reportableLine,
} from "../src/lib/lobbyChat.ts";

// Whole seconds since the epoch, as the server sends it (#885).
const SAID_AT = Date.parse("2026-09-02T12:00:00+00:00") / 1000;

function line(seq, overrides = {}) {
  return {
    seq,
    userId: "user-ada",
    displayName: "Ada",
    nameColor: "#4f9",
    isAnonymous: false,
    text: `line ${seq}`,
    sentAt: SAID_AT,
    ...overrides,
  };
}

test("a line this build cannot read is dropped rather than shown blank", () => {
  assert.equal(parseLine(null), null);
  assert.equal(parseLine("hello"), null);
  assert.equal(parseLine(line(1, { seq: "1" })), null);
  assert.equal(parseLine(line(0)), null);
  assert.equal(parseLine(line(1, { userId: "" })), null);
  assert.equal(parseLine(line(1, { text: undefined })), null);
  assert.equal(parseLine(line(1, { sentAt: undefined })), null);
  assert.equal(parseLine(line(1, { sentAt: "2026-09-02T12:00:00+00:00" })), null);
  assert.equal(parseLine(line(1, { sentAt: Number.NaN })), null);
});

test("the instant is parsed once and the retained id survives only when present", () => {
  const parsed = parseLine(line(3, { retainedMessageId: "0192-abc" }));
  assert.equal(parsed.sentAt, SAID_AT * 1000);
  assert.equal(parsed.retainedMessageId, "0192-abc");
  assert.equal("retainedMessageId" in parseLine(line(3)), false);
  assert.equal(parseLine(line(3, { nameColor: null })).nameColor, null);
});

test("a line numbered at or below what is held is one we have", () => {
  const first = applyChatLine(EMPTY_LOBBY_CHAT, line(1));
  assert.equal(first.lastSeq, 1);
  const again = applyChatLine(first, line(1, { text: "a duplicate" }));
  assert.equal(again, first, "a duplicate should return the identical state");
  assert.equal(applyChatLine(first, "nonsense"), first);
});

test("a gap in the numbering is appended without complaint", () => {
  // A blocked line was said in between; the blocker is never sent it.
  const held = applyChatLine(applyChatLine(EMPTY_LOBBY_CHAT, line(1)), line(4));
  assert.deepEqual(
    held.lines.map((item) => item.seq),
    [1, 4],
  );
  assert.equal(held.lastSeq, 4);
});

test("the client keeps the newest lines and no more", () => {
  let state = EMPTY_LOBBY_CHAT;
  for (let seq = 1; seq <= MAX_HELD_LINES + 5; seq += 1) state = applyChatLine(state, line(seq));
  assert.equal(state.lines.length, MAX_HELD_LINES);
  assert.equal(state.lines[0].seq, 6);
  assert.equal(state.lastSeq, MAX_HELD_LINES + 5);
});

test("a backlog from another process, or for another account, replaces what was held", () => {
  const held = applyChatBacklog(
    EMPTY_LOBBY_CHAT,
    { chat: [line(90, { text: "from before" })], chatSeq: 90, chatEpoch: "old" },
    "user-ada",
  );
  const replaced = applyChatBacklog(
    held,
    { chat: [line(2), line(1)], chatSeq: 3, chatEpoch: "new" },
    "user-ada",
  );
  assert.deepEqual(
    replaced.lines.map((item) => item.seq),
    [1, 2],
    "the backlog is what there is, in the order it was said",
  );
  // The last line said was one this watcher is not shown (a blocked
  // author); its number is still the one the next line must follow.
  assert.equal(replaced.lastSeq, 3);
  assert.equal(replaced.epoch, "new");

  // Same process, but filtered for somebody else's blocks.
  const otherAccount = applyChatBacklog(
    held,
    { chat: [line(91)], chatSeq: 91, chatEpoch: "old" },
    "user-bob",
  );
  assert.deepEqual(otherAccount.lines.map((item) => item.seq), [91]);
  assert.equal(otherAccount.owner, "user-bob");
});

test("a backlog continuing what is held merges rather than cutting the history back", () => {
  let held = applyChatBacklog(EMPTY_LOBBY_CHAT, { chat: [], chatSeq: 0, chatEpoch: "e" }, "u");
  for (let seq = 1; seq <= 4; seq += 1) held = applyChatLine(held, line(seq));
  const merged = applyChatBacklog(
    held,
    { chat: [line(3), line(4), line(6)], chatSeq: 7, chatEpoch: "e" },
    "u",
  );
  assert.deepEqual(
    merged.lines.map((item) => item.seq),
    [1, 2, 3, 4, 6],
  );
  assert.equal(merged.lastSeq, 7);
  const unchanged = applyChatBacklog(merged, { chat: [line(6)], chatSeq: 7, chatEpoch: "e" }, "u");
  assert.equal(unchanged, merged, "nothing new should return the identical state");
});

test("only lines from a known process and the same account are resumed (#885)", () => {
  assert.deepEqual(chatResumeRequest(EMPTY_LOBBY_CHAT, "u"), {});
  const held = applyChatBacklog(
    EMPTY_LOBBY_CHAT,
    { chat: [line(1), line(2)], chatSeq: 5, chatEpoch: "e" },
    "u",
  );
  assert.deepEqual(chatResumeRequest(held, "u"), { chatSince: 5, chatEpoch: "e", chatVisibility: 0 });
  assert.deepEqual(chatResumeRequest(held, "someone-else"), {});
  assert.deepEqual(chatResumeRequest(held, null), {});
});

test("the label says how fresh a line is, and no more than that", () => {
  const noon = new Date(2026, 8, 2, 12, 0, 0).getTime();
  const minute = 60_000;
  assert.equal(chatTimeLabel(noon, noon), "now");
  assert.equal(chatTimeLabel(noon - 59_000, noon), "now");
  assert.equal(chatTimeLabel(noon - minute, noon), "1m");
  assert.equal(chatTimeLabel(noon - 59 * minute, noon), "59m");
  assert.match(chatTimeLabel(noon - 60 * minute, noon), /\d{1,2}:\d{2}/);
  // The clock beside a line follows the player's time format (#577).
  assert.equal(chatTimeLabel(noon - 60 * minute, noon, "24h"), "11:00");
  assert.match(chatTimeLabel(noon - 60 * minute, noon, "12h"), /^11:00\s?AM$/i);
  assert.match(chatTimeLabel(new Date(2026, 8, 2, 0, 30).getTime(), noon), /\d{1,2}:\d{2}/);
  assert.equal(chatTimeLabel(new Date(2026, 8, 1, 23, 30).getTime(), noon), "yesterday");
  assert.equal(chatTimeLabel(new Date(2026, 8, 1, 0, 5).getTime(), noon), "yesterday");
  assert.equal(chatTimeLabel(new Date(2026, 7, 31, 12, 0).getTime(), noon), "2d");
  assert.equal(chatTimeLabel(new Date(2026, 7, 3, 12, 0).getTime(), noon), "30d");
  // A clock behind the server's is a fresh line, not one from the future.
  assert.equal(chatTimeLabel(noon + 5 * minute, noon), "now");
});

test("a line is reportable only by a registered viewer, only when retained, and never by its author", () => {
  const retained = { ...line(1), sentAt: Date.parse(SAID_AT), retainedMessageId: "row-1" };
  const withheld = { ...line(2), sentAt: Date.parse(SAID_AT) };
  const registered = { id: "user-bob", isAnonymous: false };

  assert.equal(reportableLine(retained, registered), true);
  // Nothing to cite: the row was never written, so the REST route would
  // refuse it as unavailable. No action rather than a dead end.
  assert.equal(reportableLine(withheld, registered), false);
  // Your own line, and a guest viewer: the room's two rules.
  assert.equal(reportableLine(retained, { id: "user-ada", isAnonymous: false }), false);
  assert.equal(reportableLine(retained, { id: "user-bob", isAnonymous: true }), false);
  // A socket with no account yet reads the lobby, and reports nothing.
  assert.equal(reportableLine(retained, null), false);
  assert.equal(reportableLine(retained, undefined), false);
});


test("a line a moderator hid is held without its words, and shown again in place", () => {
  // #1435: matched by the id that names it everywhere, replaced where it
  // stands; an unknown or malformed change leaves the state as it was.
  let held = applyChatLine(EMPTY_LOBBY_CHAT, line(1, { retainedMessageId: "msg-1" }));
  held = applyChatLine(held, line(2, { retainedMessageId: "msg-2" }));

  const hidden = applyLineVisibility(held, { retainedMessageId: "msg-1", hidden: true, visibility: 1 });
  assert.deepEqual(hidden.lines.map((l) => [l.seq, l.hidden ?? false, l.text]), [[1, true, ""], [2, false, "line 2"]]);
  assert.equal(applyLineVisibility(hidden, { retainedMessageId: "msg-1", hidden: true, visibility: 1 }), hidden, "already so");
  assert.equal(applyLineVisibility(hidden, { retainedMessageId: "nope", hidden: true, visibility: 1 }), hidden);

  const shown = applyLineVisibility(hidden, { retainedMessageId: "msg-1", hidden: false, text: "line 1", visibility: 2 });
  assert.deepEqual(shown.lines[0], { ...held.lines[0], visibility: 2 }, "as it was before it was hidden");

  // From the wire: a hidden line arrives with no words, and cannot be reported.
  const parsed = parseLine({ ...line(3, { retainedMessageId: "msg-3" }), text: "", hidden: true, visibility: 7 });
  assert.equal(parsed.hidden, true);
  assert.equal(parsed.visibility, 7);
  assert.equal(reportableLine(parsed, { id: "user-bob", isAnonymous: false }), false);
});

test("a late change to a line cannot undo a newer one, and the muted get only the count", () => {
  // #1435: the server's block lookup can send a later change first. Per line,
  // the newer revision stands; a late change to another line still lands.
  let held = applyChatLine(EMPTY_LOBBY_CHAT, line(1, { retainedMessageId: "m1" }));
  held = applyChatLine(held, line(2, { retainedMessageId: "m2" }));
  const restored = applyLineVisibility(held, { retainedMessageId: "m1", hidden: false, text: "line 1", visibility: 2 });
  const late = applyLineVisibility(restored, { retainedMessageId: "m1", hidden: true, visibility: 1 });
  assert.equal(late.lines[0], restored.lines[0], "the older hide arrives second and leaves the line");
  assert.deepEqual([late.visibility, late.visibilityAhead], [2, []], "but it closes the gap below change 2");
  const other = applyLineVisibility(late, { retainedMessageId: "m2", hidden: true, visibility: 1 });
  assert.equal(other.lines[1].hidden, true, "an older count, but news for this line");

  // Shown again to somebody who muted its author: no words, only the count.
  const muted = applyLineVisibility(other, { retainedMessageId: "m9", hidden: false, visibility: 9 });
  assert.deepEqual([muted.visibility, muted.visibilityAhead], [2, [9]], "counted, past a gap");
  assert.equal(muted.lines, other.lines);
});

test("a change received early does not hide that an earlier one never came", () => {
  // The review's case (#1435): line A is restored as change 2, but the block
  // lookup holds that broadcast; hiding B goes out at once as change 3; the
  // tab disconnects before change 2 arrives. Counting the highest received
  // resumed as caught up, and A stayed a placeholder for good.
  const owner = "user-carol";
  let held = applyChatBacklog(EMPTY_LOBBY_CHAT, {
    chat: [
      { ...line(1, { retainedMessageId: "A" }), text: "", hidden: true, visibility: 1 },
      line(2, { retainedMessageId: "B" }),
    ],
    chatSeq: 2, chatEpoch: "e1", chatVisibility: 1,
  }, owner);
  held = applyLineVisibility(held, { retainedMessageId: "B", hidden: true, visibility: 3 });
  assert.equal(held.lines[1].hidden, true);
  assert.deepEqual([held.visibility, held.visibilityAhead], [1, [3]]);
  assert.equal(chatResumeRequest(held, owner).chatVisibility, 1, "resumes from below the gap");

  // Had change 2 arrived after all, the count would have closed up to 3.
  const closed = applyLineVisibility(held, { retainedMessageId: "A", hidden: false, text: "line 1", visibility: 2 });
  assert.deepEqual([closed.visibility, closed.visibilityAhead], [3, []]);
  assert.equal(closed.lines[0].text, "line 1");
});

test("a lobby that missed a hide replaces what it holds with the backlog it is handed", () => {
  // #1435: the count rides the resume request; behind, the server marks the
  // backlog `chatReplace`, and lines held older than it go too - nothing
  // vouches for them now.
  const owner = "user-carol";
  let held = applyChatBacklog(EMPTY_LOBBY_CHAT, {
    chat: [line(1, { retainedMessageId: "m1" }), line(2, { retainedMessageId: "m2" })],
    chatSeq: 2, chatEpoch: "e1", chatVisibility: 3,
  }, owner);
  assert.deepEqual(chatResumeRequest(held, owner), { chatSince: 2, chatEpoch: "e1", chatVisibility: 3 });

  // A change this tab did see moves its count, held line or not.
  held = applyLineVisibility(held, { retainedMessageId: "elsewhere", hidden: true, visibility: 4 });
  assert.equal(held.visibility, 4);

  const replaced = applyChatBacklog(held, {
    chat: [{ ...line(2, { retainedMessageId: "m2" }), text: "", hidden: true }],
    chatSeq: 2, chatEpoch: "e1", chatVisibility: 6, chatReplace: true,
  }, owner);
  assert.deepEqual(replaced.lines.map((l) => [l.seq, l.hidden ?? false]), [[2, true]]);
  assert.equal(replaced.visibility, 6);

  // A change this tab already applied is newer than the replacing backlog's
  // copy of that line: it stands (the answer was read before it).
  const ahead = applyLineVisibility(replaced, { retainedMessageId: "m2", hidden: false, text: "line 2", visibility: 9 });
  const older = applyChatBacklog(ahead, {
    chat: [{ ...line(2, { retainedMessageId: "m2" }), text: "", hidden: true, visibility: 6 }],
    chatSeq: 2, chatEpoch: "e1", chatVisibility: 8, chatReplace: true,
  }, owner);
  assert.deepEqual([older.lines[0].hidden ?? false, older.lines[0].text], [false, "line 2"]);

  // Level, a resumed backlog still merges.
  const merged = applyChatBacklog(replaced, {
    chat: [line(3)], chatSeq: 3, chatEpoch: "e1", chatVisibility: 6,
  }, owner);
  assert.deepEqual(merged.lines.map((l) => l.seq), [2, 3]);
});

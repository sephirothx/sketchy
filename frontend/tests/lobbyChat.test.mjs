import assert from "node:assert/strict";
import { test } from "node:test";

import {
  EMPTY_LOBBY_CHAT,
  MAX_HELD_LINES,
  applyChatBacklog,
  applyChatLine,
  chatTimeLabel,
  parseLine,
} from "../src/lib/lobbyChat.ts";

const SAID_AT = "2026-09-02T12:00:00+00:00";

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
  assert.equal(parseLine(line(1, { sentAt: "yesterday-ish" })), null);
});

test("the instant is parsed once and the retained id survives only when present", () => {
  const parsed = parseLine(line(3, { retainedMessageId: "0192-abc" }));
  assert.equal(parsed.sentAt, Date.parse(SAID_AT));
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

test("a new socket's backlog replaces what was held", () => {
  const held = applyChatLine(EMPTY_LOBBY_CHAT, line(90, { text: "from before" }));
  const replaced = applyChatBacklog(held, { chat: [line(2), line(1)], chatSeq: 3 }, true);
  assert.deepEqual(
    replaced.lines.map((item) => item.seq),
    [1, 2],
    "the backlog is what there is, in the order it was said",
  );
  // The last line said was one this watcher is not shown (a blocked
  // author); its number is still the one the next line must follow.
  assert.equal(replaced.lastSeq, 3);
  assert.deepEqual(applyChatBacklog(held, { chat: [], chatSeq: 0 }, true), EMPTY_LOBBY_CHAT);
  assert.deepEqual(applyChatBacklog(held, undefined, true), EMPTY_LOBBY_CHAT);
});

test("a resync on a live socket merges the backlog rather than cutting the history back", () => {
  let held = EMPTY_LOBBY_CHAT;
  for (let seq = 1; seq <= 4; seq += 1) held = applyChatLine(held, line(seq));
  const merged = applyChatBacklog(held, { chat: [line(3), line(4), line(6)], chatSeq: 7 }, false);
  assert.deepEqual(
    merged.lines.map((item) => item.seq),
    [1, 2, 3, 4, 6],
  );
  assert.equal(merged.lastSeq, 7);
  const unchanged = applyChatBacklog(merged, { chat: [line(6)], chatSeq: 7 }, false);
  assert.equal(unchanged, merged, "nothing new should return the identical state");
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

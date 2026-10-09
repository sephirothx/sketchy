import assert from "node:assert/strict";
import test from "node:test";

import { invitationExpired, invitationStillOpen, parseInboxPage, readThrough, withMore } from "../src/lib/inbox.ts";

const NOW = "2026-10-09T10:00:00+00:00";

test("an inbox read keeps the entries it understands and drops the rest", () => {
  const page = parseInboxPage({
    entries: [
      { id: "1", kind: "reports_reviewed", createdAt: NOW, read: false, count: 3 },
      {
        id: "2", kind: "drawing_shared", createdAt: NOW, read: true,
        drawing: { turnId: "t", prompt: "kite", inGallery: true, sharedBy: { displayName: "Cid", nameColor: null, isAnonymous: false } },
      },
      { id: "3", kind: "friend_request", createdAt: NOW, read: false, person: { userId: "u", displayName: "Dan", nameColor: "#123456" }, state: "pending" },
      // A kind this build does not know, and one missing what its kind needs.
      { id: "4", kind: "telegram", createdAt: NOW },
      { id: "5", kind: "game_invite", createdAt: NOW },
      { id: "6", kind: "drawing_shared", createdAt: NOW, drawing: { prompt: "no turn" } },
    ],
    unreadCount: 2,
    next: "3",
    mustAcknowledge: null,
    pendingRole: null,
  });
  assert.deepEqual(page.entries.map((entry) => entry.id), ["1", "2", "3"]);
  assert.equal(page.entries[0].count, 3);
  assert.equal(page.entries[1].drawing.sharedBy.displayName, "Cid");
  assert.equal(page.entries[2].state, "pending");
  assert.equal(page.unreadCount, 2);
  assert.equal(page.next, "3");
});

test("a share that no longer names anybody is still read, naming nobody", () => {
  const [entry] = parseInboxPage({
    entries: [{ id: "1", kind: "drawing_shared", createdAt: NOW, drawing: { turnId: "t", prompt: "kite", inGallery: false, sharedBy: null } }],
  }).entries;
  assert.equal(entry.drawing.sharedBy, null);
  assert.equal(entry.drawing.inGallery, false);
});

test("the warning that must be answered rides the read", () => {
  const page = parseInboxPage({
    entries: [],
    unreadCount: 0,
    mustAcknowledge: { id: "w", kind: "avatar_removal", reason: "", category: null, messages: [], drawings: [], uploadAgainAt: NOW },
  });
  assert.equal(page.mustAcknowledge.kind, "avatar_removal");
  assert.equal(page.mustAcknowledge.uploadAgainAt, NOW);
  assert.equal(parseInboxPage({ mustAcknowledge: { id: 1 } }).mustAcknowledge, null);
  assert.deepEqual(parseInboxPage(null).entries, []);
});

test("a later page adds what is new and repeats nothing", () => {
  const shown = [{ id: "1" }, { id: "2" }];
  assert.deepEqual(withMore(shown, [{ id: "2" }, { id: "3" }]).map((e) => e.id), ["1", "2", "3"]);
});

test("an invitation can be answered only while the card's own invitation from that friend stands", () => {
  const now = new Date("2026-10-09T10:00:00Z");
  const later = "2026-10-09T10:01:00+00:00";
  const earlier = "2026-10-09T09:59:00+00:00";
  assert.equal(invitationStillOpen(later, "eve", { fromUserId: "eve" }, now), true);
  assert.equal(invitationStillOpen(earlier, "eve", { fromUserId: "eve" }, now), false, "run out");
  assert.equal(invitationStillOpen(later, "eve", { fromUserId: "bob" }, now), false, "somebody else's card");
  assert.equal(invitationStillOpen(later, "eve", null, now), false, "no card: the token is gone");
});

test("a push reads afresh every page the reader had loaded, and no further", async () => {
  // Three pages of two on the server; another tab has read them all.
  const server = [
    { id: "f", read: true }, { id: "e", read: true },
    { id: "d", read: true }, { id: "c", read: true },
    { id: "b", read: true }, { id: "a", read: true },
  ];
  const asked = [];
  const read = async (before) => {
    asked.push(before ?? null);
    const start = before ? server.findIndex((e) => e.id === before) + 1 : 0;
    const entries = server.slice(start, start + 2);
    const more = start + 2 < server.length;
    return { entries, unreadCount: 0, next: more ? entries[1].id : null, mustAcknowledge: null, pendingRole: null };
  };
  const deep = await readThrough(read, 4);
  assert.deepEqual(deep.entries.map((e) => [e.id, e.read]), [["f", true], ["e", true], ["d", true], ["c", true]]);
  assert.equal(deep.next, "c", "the third page is still there to show");
  assert.deepEqual(asked, [null, "e"]);

  asked.length = 0;
  assert.equal((await readThrough(read, 2)).entries.length, 2);
  assert.deepEqual(asked, [null], "page one only, for a reader who never went further");
});

test("an invitation is expired only once its own time has passed", () => {
  const now = new Date("2026-10-09T10:00:00Z");
  assert.equal(invitationExpired("2026-10-09T10:01:00+00:00", now), false);
  assert.equal(invitationExpired("2026-10-09T09:59:00+00:00", now), true);
  assert.equal(invitationExpired(null, now), true);
});

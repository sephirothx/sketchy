import assert from "node:assert/strict";
import test from "node:test";

import {
  canAdminister,
  canModerate,
  operatorEntries,
  roleNoticeFromPayload,
  roleNoticeText,
} from "../src/lib/operatorAccess.ts";

test("a moderator reviews reports; an administrator also runs the server", () => {
  assert.deepEqual(
    operatorEntries("moderator").map((entry) => entry.path),
    ["/moderation"],
  );
  assert.deepEqual(
    operatorEntries("admin").map((entry) => entry.path),
    ["/moderation", "/admin/operations", "/admin/bug-reports"],
  );
});

test("bug triage is an administrator surface, not a moderation one", () => {
  // A moderator staffs the safety queue. Bug reports carry build and
  // diagnostic data and are somebody else's job, so they are not offered.
  assert.ok(
    !operatorEntries("moderator").some((entry) => entry.path === "/admin/bug-reports"),
  );
});

test("an ordinary player is offered nothing", () => {
  assert.deepEqual(operatorEntries("user"), []);
  assert.equal(canModerate("user"), false);
  assert.equal(canAdminister("moderator"), false);
});

test("an unknown or missing role hides rather than reveals", () => {
  // The safe direction: a payload from an older server, or one that failed to
  // load, should not advertise a surface.
  assert.deepEqual(operatorEntries(undefined), []);
  assert.deepEqual(operatorEntries(null), []);
  assert.deepEqual(operatorEntries("superuser"), []);
});

test("a guest is never staff, whatever the payload claims", () => {
  assert.deepEqual(operatorEntries("admin", { isAnonymous: true }), []);
});

test("a pushed role notice is read out of the payload the server sends", () => {
  const notice = roleNoticeFromPayload({
    notice: { id: "n-1", role: "moderator", createdAt: "2026-08-29T00:00:00+00:00" },
  });
  assert.deepEqual(notice, {
    id: "n-1",
    role: "moderator",
    createdAt: "2026-08-29T00:00:00+00:00",
  });
  assert.equal(roleNoticeFromPayload({ notice: { id: "n-2", role: "user" } }).role, "user");
});

test("a malformed notice is dropped rather than shown to a player", () => {
  // The alternative is a pop-up reading "undefined", in front of somebody who
  // did nothing but be online at the wrong moment.
  for (const payload of [null, undefined, {}, "moderator", { notice: null }, { notice: {} }]) {
    assert.equal(roleNoticeFromPayload(payload), null);
  }
  assert.equal(roleNoticeFromPayload({ notice: { id: 42, role: "moderator" } }), null);
  assert.equal(roleNoticeFromPayload({ notice: { id: "n-3", role: "wizard" } }), null);
});

test("a notice cannot announce an administrator", () => {
  // `admin` is never granted over the network, so a push claiming it is a
  // payload that should not exist - and the menu must not act on one.
  assert.equal(roleNoticeFromPayload({ notice: { id: "n-4", role: "admin" } }), null);
});

test("the two halves of a promotion agree: told, then offered Moderation", () => {
  const notice = roleNoticeFromPayload({ notice: { id: "n-5", role: "moderator" } });
  assert.deepEqual(
    operatorEntries(notice.role).map((entry) => entry.path),
    ["/moderation"],
  );
  assert.deepEqual(operatorEntries(roleNoticeFromPayload({ notice: { id: "n-6", role: "user" } }).role), []);
});

test("the notice explains the change without quoting the ledger", () => {
  // The reason an administrator recorded was written for other administrators
  // and can name a report or a second account; it never reaches this text.
  const promoted = roleNoticeText("moderator");
  const removed = roleNoticeText("user");
  assert.match(promoted.title, /now a moderator/);
  assert.match(promoted.body, /Moderation/);
  assert.match(removed.title, /no longer a moderator/);
  assert.ok(!/reason/i.test(promoted.body + removed.body));
});

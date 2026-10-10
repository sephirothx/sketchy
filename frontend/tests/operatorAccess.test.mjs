import assert from "node:assert/strict";
import test from "node:test";

import { parseInboxEntry } from "../src/lib/inbox.ts";
import {
  canAdminister,
  canModerate,
  operatorEntries,
  pendingRoleFromPayload,
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

test("an offered role is read as an offer, and says so in its own words", () => {
  // The difference is the whole point: one reports, the other asks. A role
  // that is waiting on a second factor has not happened yet.
  const offered = parseInboxEntry({
    id: "n-6", kind: "role", createdAt: "2026-10-09T00:00:00+00:00", role: "moderator", change: "offered", offerOpen: true,
  });
  assert.equal(offered.change, "offered");
  const { title, body } = roleNoticeText("moderator", { pending: true });
  assert.match(title, /waiting for you/);
  assert.match(body, /two-factor/);
  // And the granted wording is untouched by it.
  assert.match(roleNoticeText("moderator").title, /You are now a moderator/);
});

test("the push says what is outstanding, even when it says nothing else", () => {
  // Withdrawing an offer settles the notice and ends the offer together, so
  // the payload that reaches a connected browser carries no notice at all -
  // and the one thing it has to convey is that nothing is waiting now.
  assert.equal(pendingRoleFromPayload({ notice: null, pendingRole: "moderator" }), "moderator");
  assert.equal(pendingRoleFromPayload({ notice: null, pendingRole: null }), null);
  for (const payload of [null, undefined, {}, "moderator", { pendingRole: "wizard" }]) {
    assert.equal(pendingRoleFromPayload(payload), null);
  }
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

test("a role entry is read out of the inbox, and anything else is dropped", () => {
  // The alternative is a row reading "undefined", in front of somebody who
  // did nothing but be online at the wrong moment (#1436).
  const granted = parseInboxEntry({
    id: "n-1", kind: "role", createdAt: "2026-10-09T00:00:00+00:00", role: "moderator", change: "granted",
  });
  assert.deepEqual(granted, {
    id: "n-1", createdAt: "2026-10-09T00:00:00+00:00", read: false,
    kind: "role", role: "moderator", change: "granted", offerOpen: false,
  });
  assert.deepEqual(operatorEntries(granted.role).map((entry) => entry.path), ["/moderation"]);
  // `admin` is never granted over the network, so an entry claiming it is a
  // payload that should not exist.
  for (const bad of [
    { id: "n-2", kind: "role", createdAt: "", role: "admin", change: "granted" },
    { id: "n-3", kind: "role", createdAt: "", role: "moderator", change: "promoted" },
    { id: 42, kind: "role", createdAt: "", role: "moderator", change: "granted" },
    null,
  ]) {
    assert.equal(parseInboxEntry(bad), null);
  }
});
